"""Freeze the vNext4 contender set and reproducible adaptive-baseline seed.

Independent-audit remediation:
- no historical champion is selected;
- exact raw candles used to construct the pre-start adaptive baseline seed are
  frozen as deterministic gzip files and their SHA256 values are embedded into
  each artifact and freeze metadata;
- the same vendored vNext4 core is used for research/freeze and later runtime
  parity tests.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import joblib
import numpy as np
import sklearn
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline

from predictive_vnext4.core import (
    read_klines, build_hourly_features, build_15m_features,
    target_percent, target_distance, masks, _fit_hazard,
    _hazard_cumulative, full_proba,
)

UTC=timezone.utc
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"predictive_vnext4"
OUT.mkdir(exist_ok=True)
SEED=20261004
FREEZE_NOW=datetime.now(UTC)


def sha_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def canonical_json_bytes(obj) -> bytes:
    return json.dumps(obj,separators=(",",":"),ensure_ascii=False,sort_keys=False).encode()


def write_deterministic_gzip(path: Path, obj):
    raw=canonical_json_bytes(obj)
    blob=gzip.compress(raw,compresslevel=9,mtime=0)
    path.write_bytes(blob)
    return {"compressed_sha256":sha_bytes(blob),"logical_sha256":sha_bytes(raw),"rows":len(obj)}


def fit_calibrator(raw,y):
    model=LogisticRegression(C=.05,max_iter=450)
    model.fit(np.log(np.clip(raw,1e-8,1)),y)
    return model


def calibrated(calibrator,raw):
    return full_proba(calibrator,np.log(np.clip(raw,1e-8,1)))


def fixed_fpr_threshold(scores,y,cls,max_fpr=.20):
    neg=scores[y!=cls]
    if len(neg)==0:
        return 1.0
    return float(np.quantile(neg,1.0-max_fpr,method="higher"))


def contender_bundle(X,y,when,train,cal,horizon_steps,hazard_step):
    yy=y[train]
    models={}

    logistic=make_pipeline(StandardScaler(),LogisticRegression(C=.03,max_iter=450))
    logistic.fit(X[train],yy)
    lcal=full_proba(logistic,X[cal])
    lcalibrator=fit_calibrator(lcal,y[cal])
    lp=calibrated(lcalibrator,lcal)
    models["logistic"]={"model":logistic,"calibrator":lcalibrator}

    tree=HistGradientBoostingClassifier(
        max_iter=110,max_leaf_nodes=15,min_samples_leaf=80,
        learning_rate=.04,l2_regularization=12,random_state=SEED)
    tree.fit(X[train],yy)
    tcal=full_proba(tree,X[cal])
    tcalibrator=fit_calibrator(tcal,y[cal])
    tp=calibrated(tcalibrator,tcal)
    models["gbdt"]={"model":tree,"calibrator":tcalibrator}

    hazard=_fit_hazard(X,y,when,train,horizon_steps,hazard_step)
    hcal=_hazard_cumulative(hazard,X[cal],horizon_steps,hazard_step)
    hcalibrator=fit_calibrator(hcal,y[cal])
    hp=calibrated(hcalibrator,hcal)
    models["competing_risks"]={
        "model":hazard,"calibrator":hcalibrator,
        "horizon_steps":int(horizon_steps),"hazard_step":int(hazard_step)
    }

    preds={"logistic":lp,"gbdt":tp,"competing_risks":hp}
    thresholds={}
    for name,p in preds.items():
        thresholds[name]={
            "lower_first_fpr20":fixed_fpr_threshold(p[:,0],y[cal],0,.20),
            "upper_first_fpr20":fixed_fpr_threshold(p[:,1],y[cal],1,.20),
        }
    return models,thresholds


def control_block(y,vol,train):
    counts=np.bincount(y[train],minlength=4).astype(float)+.5
    q=np.quantile(vol[train],[1/3,2/3])
    return {
        "training_frequency":(counts/counts.sum()).tolist(),
        "vol_quantiles":[float(q[0]),float(q[1])],
        "vol90d_window_days":90,
        "vol90d_min_same_bin":30,
        "fallback":"training_frequency",
    }


def fetch_recent(interval,duration_ms,days):
    end=int(FREEZE_NOW.timestamp()*1000)-1
    start=int((FREEZE_NOW-timedelta(days=days)).timestamp()*1000)
    rows=[];cursor=start
    while cursor<=end:
        params=urllib.parse.urlencode({
            "symbol":"BTCUSDT","interval":interval,"startTime":cursor,
            "endTime":end,"limit":1000})
        req=urllib.request.Request(
            "https://data-api.binance.vision/api/v3/klines?"+params,
            headers={"User-Agent":"btc-predictive-vnext4-freeze"})
        with urllib.request.urlopen(req,timeout=30) as response:
            batch=json.loads(response.read())
        if not batch: break
        rows.extend(batch)
        nxt=int(batch[-1][0])+duration_ms
        if nxt<=cursor: raise RuntimeError("recent fetch cursor did not advance")
        cursor=nxt
        if len(batch)<1000: break
    uniq={int(r[0]):r for r in rows if int(r[6])<int(FREEZE_NOW.timestamp()*1000)}
    rows=[uniq[k] for k in sorted(uniq)]
    if len(rows)<500: raise RuntimeError("insufficient recent seed history")
    if any(int(b[0])-int(a[0])!=duration_ms for a,b in zip(rows,rows[1:])):
        raise ValueError("gap in recent seed history")
    if any(int(r[6])!=int(r[0])+duration_ms-1 for r in rows):
        raise ValueError("partial recent seed candle")
    return rows


def arrays(rows):
    t=np.asarray([int(r[0]) for r in rows],dtype=np.int64)
    o=np.asarray([float(r[1]) for r in rows])
    hi=np.asarray([float(r[2]) for r in rows])
    lo=np.asarray([float(r[3]) for r in rows])
    c=np.asarray([float(r[4]) for r in rows])
    v=np.asarray([float(r[5]) for r in rows])
    trades=np.asarray([float(r[8]) for r in rows])
    taker=np.asarray([float(r[9]) for r in rows])
    return t,o,hi,lo,c,v,trades,taker


def seed_records(dates,y,vol,control,due_delta,now):
    q=np.asarray(control["vol_quantiles"],dtype=float)
    bins=np.digitize(vol,q,right=True)
    cutoff=np.datetime64(now.replace(tzinfo=None))
    out=[]
    for dt,cls,b in zip(dates,y,bins):
        due=dt+due_delta
        if due>=cutoff: continue
        out.append({
            "anchor_utc":str(dt.astype("datetime64[s]"))+"Z",
            "due_utc":str(due.astype("datetime64[s]"))+"Z",
            "class_id":int(cls),"vol_bin":int(b),
        })
    lo=cutoff-np.timedelta64(100,"D")
    return [r for r in out if np.datetime64(r["anchor_utc"].replace("Z",""))>=lo]


def build_hourly():
    hist=ROOT/"btc_1h_2024_to_sep24_2026.json"
    t,o,hi,lo,c,v,trades,taker,source_sha=read_klines(hist,3600000)
    ix,dates,X,names,regime,vol,atr=build_hourly_features(t,hi,lo,c,v,trades,taker,168)
    distance=c[ix]*vol*np.sqrt(72.0)
    y,when=target_distance(ix,c,hi,lo,distance,72)
    train,cal,_=masks(dates,np.timedelta64(72,"h"),
                      "2026-04-01","2026-04-01","2026-07-01",
                      "2026-07-08","2026-09-01")
    models,thresholds=contender_bundle(X,y,when,train,cal,72,6)
    control=control_block(y,vol,train)

    recent=fetch_recent("1h",3600000,112)
    seed_path=OUT/"baseline_seed_hourly_source.json.gz"
    seed_source=write_deterministic_gzip(seed_path,recent)
    rt,ro,rhi,rlo,rc,rv,rtr,rtk=arrays(recent)
    rix,rdates,rX,rnames,rreg,rvol,ratr=build_hourly_features(rt,rhi,rlo,rc,rv,rtr,rtk,168)
    rdist=rc[rix]*rvol*np.sqrt(72.0)
    ry,rwhen=target_distance(rix,rc,rhi,rlo,rdist,72)
    seed=seed_records(rdates,ry,rvol,control,np.timedelta64(72,"h"),FREEZE_NOW)
    if rnames!=names: raise ValueError("hourly recent feature schema mismatch")
    artifact={
        "schema":"btc-predictive-vnext4-bundle-v1",
        "head":"hourly_rv_first_passage_72h",
        "contenders":["logistic","gbdt","competing_risks"],
        "models":models,"alert_thresholds":thresholds,
        "target":{"type":"realized_vol_normalized","sigma_window_hours":24,
                  "distance":"reference_price * std(log_return_1h,24h) * sqrt(72)",
                  "horizon_hours":72,
                  "classes":["LOWER_FIRST","UPPER_FIRST","NEITHER","AMBIGUOUS_SAME_BAR"]},
        "feature_names":names,"control":control,
        "control_vol_measure":"std(log_return_1h,last 24 closed hours)",
        "baseline_seed":seed,
        "baseline_seed_freeze_utc":FREEZE_NOW.isoformat(),
        "baseline_seed_source_path":str(seed_path.relative_to(ROOT)),
        "baseline_seed_source_sha256":seed_source["compressed_sha256"],
        "baseline_seed_source_logical_sha256":seed_source["logical_sha256"],
        "baseline_seed_not_used_for_model_fit_or_selection":True,
        "training":{"labels_due_before":"2026-04-01T00:00:00",
                    "calibration":"2026Q2 labels due before 2026-07-01",
                    "historical_source_sha256":source_sha,
                    "train_n":int(train.sum()),"cal_n":int(cal.sum())},
        "sklearn_version":sklearn.__version__,"numpy_version":np.__version__,
    }
    return artifact,seed_source


def build_early():
    hist=ROOT/"research_vnext/data/BTCUSDT_15m_2024-01_2026-06.json.gz"
    t,o,hi,lo,c,v,trades,taker,source_sha=read_klines(hist,900000)
    ix,dates,X,names,regime,vol=build_15m_features(t,hi,lo,c,v,trades,taker,16)
    y,when=target_percent(ix,c,hi,lo,.99,1.01,16)
    train,cal,_=masks(dates,np.timedelta64(240,"m"),
                      "2026-04-01","2026-04-01","2026-07-01",
                      "2026-06-01","2026-07-01")
    models,thresholds=contender_bundle(X,y,when,train,cal,16,1)
    control=control_block(y,vol,train)

    recent=fetch_recent("15m",900000,104)
    seed_path=OUT/"baseline_seed_early15m_source.json.gz"
    seed_source=write_deterministic_gzip(seed_path,recent)
    rt,ro,rhi,rlo,rc,rv,rtr,rtk=arrays(recent)
    rix,rdates,rX,rnames,rreg,rvol=build_15m_features(rt,rhi,rlo,rc,rv,rtr,rtk,16)
    ry,rwhen=target_percent(rix,rc,rhi,rlo,.99,1.01,16)
    seed=seed_records(rdates,ry,rvol,control,np.timedelta64(240,"m"),FREEZE_NOW)
    if rnames!=names: raise ValueError("15m recent feature schema mismatch")
    artifact={
        "schema":"btc-predictive-vnext4-bundle-v1",
        "head":"early15m_pm1pct_4h",
        "contenders":["logistic","gbdt","competing_risks"],
        "models":models,"alert_thresholds":thresholds,
        "target":{"type":"symmetric_percent_first_passage","lower_ratio":.99,"upper_ratio":1.01,
                  "horizon_minutes":240,
                  "classes":["LOWER_FIRST","UPPER_FIRST","NEITHER","AMBIGUOUS_SAME_BAR"]},
        "feature_names":names,"control":control,
        "control_vol_measure":"std(log_return_15m,last 4 closed hours)",
        "baseline_seed":seed,
        "baseline_seed_freeze_utc":FREEZE_NOW.isoformat(),
        "baseline_seed_source_path":str(seed_path.relative_to(ROOT)),
        "baseline_seed_source_sha256":seed_source["compressed_sha256"],
        "baseline_seed_source_logical_sha256":seed_source["logical_sha256"],
        "baseline_seed_not_used_for_model_fit_or_selection":True,
        "training":{"labels_due_before":"2026-04-01T00:00:00",
                    "calibration":"2026Q2 labels due before 2026-07-01",
                    "historical_source_sha256":source_sha,
                    "train_n":int(train.sum()),"cal_n":int(cal.sum())},
        "sklearn_version":sklearn.__version__,"numpy_version":np.__version__,
    }
    return artifact,seed_source


def dump_artifact(name,artifact):
    path=OUT/name
    joblib.dump(artifact,path,compress=3)
    return path


def main():
    hourly,hseed=build_hourly()
    early,eseed=build_early()
    hp=dump_artifact("hourly_contenders.joblib",hourly)
    ep=dump_artifact("early15m_contenders.joblib",early)
    summary={
        "schema":"btc-predictive-vnext4-freeze-metadata-v1",
        "freeze_utc":FREEZE_NOW.isoformat(),
        "historical_selection_status":"INSPECTED_HISTORY_DIAGNOSTIC_ONLY",
        "predictive_accept":False,"trading_authority":False,
        "contenders":["logistic","gbdt","competing_risks"],
        "primary_metric":["multiclass_brier","multiclass_log_loss"],
        "primary_baseline":"vol90d_same_frozen_volatility_bin",
        "secondary_baseline":"frozen_training_frequency",
        "artifacts":{
            "hourly":{"path":str(hp.relative_to(ROOT)),"sha256":sha_bytes(hp.read_bytes()),
                      "seed_records":len(hourly["baseline_seed"]),"seed_source":hseed},
            "early15m":{"path":str(ep.relative_to(ROOT)),"sha256":sha_bytes(ep.read_bytes()),
                        "seed_records":len(early["baseline_seed"]),"seed_source":eseed},
        },
        "fixed_fpr_alerts":{"target_fpr":.20,"threshold_source":"calibration period only"},
        "note":"No contender is champion before future prospective evaluation."
    }
    (OUT/"freeze_metadata.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2,sort_keys=True)+"\n")
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
