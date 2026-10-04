"""Freeze the two research-selected models for prospective shadow use.

Selection is based on inspected historical diagnostics, so these artifacts have no
trading authority. They are frozen solely to collect genuinely future outcomes.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import joblib
import numpy as np
import sklearn
from sklearn.linear_model import LogisticRegression

from core import (read_klines, build_hourly_features, build_15m_features,
                  target_distance, target_percent, masks, _fit_hazard,
                  _hazard_cumulative, full_proba)

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"predictive_vnext2"
OUT.mkdir(exist_ok=True)
# Compressed source provenance uses decompressed logical bytes; gzip mtimes are ignored.


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fit_calibrator(raw,y):
    model=LogisticRegression(C=.05,max_iter=450)
    model.fit(np.log(np.clip(raw,1e-8,1)),y)
    return model


def calibrated(calibrator,raw):
    return full_proba(calibrator,np.log(np.clip(raw,1e-8,1)))


def control_block(y,vol,train):
    counts=np.bincount(y[train],minlength=4).astype(float)+.5
    q=np.quantile(vol[train],[1/3,2/3])
    bins=np.digitize(vol,q,right=True)
    by_bin={}
    for b in range(3):
        ids=train&(bins==b)
        cnt=np.bincount(y[ids],minlength=4).astype(float)+.5
        by_bin[str(b)]=(cnt/cnt.sum()).tolist()
    return {
        "training_frequency":(counts/counts.sum()).tolist(),
        "vol_quantiles":[float(q[0]),float(q[1])],
        "vol_bin_training_frequency":by_bin,
        "smoothing":"Jeffreys-like +0.5 per class"
    }


def hourly_artifact():
    p=ROOT/"btc_1h_2024_to_sep24_2026.json"
    t,o,hi,lo,c,v,trades,taker,source_sha=read_klines(p,3600000)
    ix,dates,X,names,regime,vol,atr=build_hourly_features(t,hi,lo,c,v,trades,taker,168)
    distance=c[ix]*vol*np.sqrt(72.0)
    y,when=target_distance(ix,c,hi,lo,distance,72)
    train,cal,_=masks(dates,np.timedelta64(72,"h"),
                      "2026-04-01","2026-04-01","2026-07-01","2026-07-08","2026-09-01")
    hazard=_fit_hazard(X,y,when,train,72,6)
    raw_cal=_hazard_cumulative(hazard,X[cal],72,6)
    calibrator=fit_calibrator(raw_cal,y[cal])
    artifact={
        "schema":"btc-predictive-vnext2-artifact-v1",
        "head":"hourly_rv_first_passage_72h",
        "model_family":"competing_risks",
        "anchor_cadence":"1h",
        "target":{"type":"realized_vol_normalized","sigma_window_hours":24,
                  "distance":"reference_price * std(log_return_1h,24h) * sqrt(72)",
                  "horizon_hours":72,"classes":["LOWER_FIRST","UPPER_FIRST","NEITHER","AMBIGUOUS_SAME_BAR"]},
        "feature_names":names,
        "training":{"labels_due_before":"2026-04-01T00:00:00","calibration":"2026Q2 labels due before 2026-07-01",
                    "historical_source_sha256":source_sha},
        "control":control_block(y,vol,train),
        "control_vol_measure":"std(log_return_1h, last 24 closed hours)",
        "hazard_step_hours":6,
        "sklearn_version":sklearn.__version__,
        "numpy_version":np.__version__,
        "hazard":hazard,
        "calibrator":calibrator
    }
    path=OUT/"hourly_rv72_competing_risks.joblib"
    joblib.dump(artifact,path,compress=3)
    probe=calibrated(calibrator,_hazard_cumulative(hazard,X[-1:],72,6))[0]
    return path,artifact,{ "probe_probability_sum":float(probe.sum()),
                          "probe":probe.tolist(),"train_n":int(train.sum()),"cal_n":int(cal.sum()) }


def early_artifact():
    p=ROOT/"research_vnext/data/BTCUSDT_15m_2024-01_2026-06.json.gz"
    t,o,hi,lo,c,v,trades,taker,source_sha=read_klines(p,900000)
    ix,dates,X,names,regime,vol=build_15m_features(t,hi,lo,c,v,trades,taker,16)
    y,when=target_percent(ix,c,hi,lo,.99,1.01,16)
    train,cal,_=masks(dates,np.timedelta64(240,"m"),
                      "2026-04-01","2026-04-01","2026-07-01","2026-06-01","2026-07-01")
    hazard=_fit_hazard(X,y,when,train,16,1)
    raw_cal=_hazard_cumulative(hazard,X[cal],16,1)
    calibrator=fit_calibrator(raw_cal,y[cal])
    artifact={
        "schema":"btc-predictive-vnext2-artifact-v1",
        "head":"early15m_pm1pct_4h",
        "model_family":"competing_risks",
        "anchor_cadence":"15m",
        "target":{"type":"symmetric_percent_first_passage","lower_ratio":0.99,"upper_ratio":1.01,
                  "horizon_minutes":240,"classes":["LOWER_FIRST","UPPER_FIRST","NEITHER","AMBIGUOUS_SAME_BAR"]},
        "feature_names":names,
        "training":{"labels_due_before":"2026-04-01T00:00:00","calibration":"2026Q2 labels due before 2026-07-01",
                    "historical_source_sha256":source_sha},
        "control":control_block(y,vol,train),
        "control_vol_measure":"std(log_return_15m, last 4 closed hours)",
        "hazard_step_minutes":15,
        "sklearn_version":sklearn.__version__,
        "numpy_version":np.__version__,
        "hazard":hazard,
        "calibrator":calibrator
    }
    path=OUT/"early15m_pm1_4h_competing_risks.joblib"
    joblib.dump(artifact,path,compress=3)
    probe=calibrated(calibrator,_hazard_cumulative(hazard,X[-1:],16,1))[0]
    return path,artifact,{"probe_probability_sum":float(probe.sum()),
                          "probe":probe.tolist(),"train_n":int(train.sum()),"cal_n":int(cal.sum())}


def main():
    hp,ha,hs=hourly_artifact()
    ep,ea,es=early_artifact()
    research_hourly=ROOT/"research_vnext2/hourly_result.json"
    research_early=ROOT/"research_vnext2/early15m_result.json"
    meta={
        "schema":"btc-predictive-vnext2-freeze-metadata-v1",
        "predictive_accept":False,
        "purpose":"prospective shadow collection only",
        "selection_basis":{
            "hourly":"rv24_sqrth_72h: competing risks selected as normalized first-passage challenger; inspected history only",
            "early15m":"±1%/4h competing risks: best robust score across three inspected folds"
        },
        "artifacts":{
            "hourly":{"path":str(hp.relative_to(ROOT)),"sha256":sha(hp),"selfcheck":hs,
                      "source_sha256":ha["training"]["historical_source_sha256"]},
            "early15m":{"path":str(ep.relative_to(ROOT)),"sha256":sha(ep),"selfcheck":es,
                        "source_sha256":ea["training"]["historical_source_sha256"]}
        },
        "controls":{
            "hourly":"frozen training frequency plus frozen volatility-bin frequency",
            "early15m":"frozen training frequency plus frozen volatility-bin frequency"
        },
        "research_outputs":{
            "hourly_sha256":sha(research_hourly),
            "early15m_sha256":sha(research_early)
        },
        "no_trade_authority":True
    }
    (OUT/"freeze_metadata.json").write_text(json.dumps(meta,ensure_ascii=False,indent=2,sort_keys=True)+"\n")
    print(json.dumps(meta,ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
