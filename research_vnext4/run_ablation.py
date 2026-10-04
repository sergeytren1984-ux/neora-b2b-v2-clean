"""Research-only feature-family ablation requested by independent audit.

No result from this file can alter the frozen vNext4 prospective epoch.
Each family is removed from the exact existing feature matrix and re-fit on the
same chronological folds. This is diagnostic evidence for a future challenger.
"""
from __future__ import annotations

import json
from pathlib import Path
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from predictive_vnext4.core import (
    read_klines, build_hourly_features, build_15m_features,
    target_distance, target_percent, masks, adaptive_baselines,
    calibrate, full_proba, metrics,
)

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"research_vnext4/ablation_result.json"
FOLDS_H=(
    ("2025Q3","2025-04-01","2025-04-01","2025-07-01","2025-07-08","2025-10-01"),
    ("2025Q4","2025-07-01","2025-07-01","2025-10-01","2025-10-08","2026-01-01"),
    ("2026H1","2025-10-01","2025-10-01","2026-01-01","2026-01-08","2026-07-01"),
)
FOLDS_15=(
    ("2025Q3","2025-04-01","2025-04-01","2025-07-01","2025-07-03","2025-10-01"),
    ("2025Q4","2025-07-01","2025-07-01","2025-10-01","2025-10-03","2026-01-01"),
    ("2026H1","2025-10-01","2025-10-01","2026-01-01","2026-01-03","2026-07-01"),
)
SEED=20261004


def groups(names):
    g={
      "returns_trend":[],
      "volatility_range":[],
      "activity":[],
      "taker_flow":[],
      "structure_efficiency":[],
    }
    for i,n in enumerate(names):
        if n.startswith("ret_") or n.startswith("ret_accel"):
            g["returns_trend"].append(i)
        elif n.startswith(("mean_abs_","std_","range_","vol_ratio_","atr14")):
            g["volatility_range"].append(i)
        elif n.startswith(("volume_ratio_","trades_ratio_")):
            g["activity"].append(i)
        elif n.startswith("taker_"):
            g["taker_flow"].append(i)
        elif n.startswith(("efficiency_","dist_prev")):
            g["structure_efficiency"].append(i)
        else:
            raise ValueError("unassigned feature: "+n)
    return g


def fit_predict(kind,X,y,tr,ca,te):
    if kind=="logistic":
        m=make_pipeline(StandardScaler(),LogisticRegression(C=.03,max_iter=450))
    elif kind=="gbdt":
        m=HistGradientBoostingClassifier(max_iter=110,max_leaf_nodes=15,min_samples_leaf=80,
                                          learning_rate=.04,l2_regularization=12,random_state=SEED)
    else: raise ValueError(kind)
    m.fit(X[tr],y[tr])
    return calibrate(full_proba(m,X[ca]),full_proba(m,X[te]),y[ca])


def run_head(head,dates,X,names,regime,vol,y,due_delta,folds):
    fam=groups(names)
    masks_by_variant={"full":np.arange(X.shape[1])}
    for name,idx in fam.items():
        keep=np.asarray([i for i in range(X.shape[1]) if i not in set(idx)],dtype=int)
        masks_by_variant["drop_"+name]=keep
    out={"feature_groups":{k:[names[i] for i in v] for k,v in fam.items()},"folds":{}}
    for fold,*bounds in folds:
        tr,ca,te=masks(dates,due_delta,*bounds)
        baseline=adaptive_baselines(dates,y,regime,vol,tr,te,due_delta)
        bscore={k:metrics(v,y[te]) for k,v in baseline.items()}
        strongest=min(bscore,key=lambda n:bscore[n]["brier"])
        row={"strongest_adaptive_baseline":strongest,"baseline":bscore[strongest],"models":{}}
        for model in ("logistic","gbdt"):
            row["models"][model]={}
            for variant,cols in masks_by_variant.items():
                p=fit_predict(model,X[:,cols],y,tr,ca,te)
                row["models"][model][variant]=metrics(p,y[te])
        out["folds"][fold]=row
    # Summarize removal effect relative to same-model full feature set.
    summary={}
    for model in ("logistic","gbdt"):
        summary[model]={}
        for family in fam:
            db=[];dl=[]
            for fold in out["folds"].values():
                full=fold["models"][model]["full"]
                drop=fold["models"][model]["drop_"+family]
                db.append(full["brier"]-drop["brier"]) # positive => removal helps
                dl.append(full["log_loss"]-drop["log_loss"])
            summary[model][family]={
                "brier_gain_from_removal_by_fold":db,
                "logloss_gain_from_removal_by_fold":dl,
                "mean_brier_gain_from_removal":float(np.mean(db)),
                "mean_logloss_gain_from_removal":float(np.mean(dl)),
                "removal_improves_both_metrics_fold_count":int(sum((a>0 and b>0) for a,b in zip(db,dl))),
                "diagnostic_remove_signal":bool(
                    np.median(db)>0 and np.median(dl)>0 and min(db)>-.01 and
                    sum((a>0 and b>0) for a,b in zip(db,dl))>=2
                )
            }
    out["summary"]=summary
    return out


def main():
    # Hourly volatility-normalized 72h target.
    hp=ROOT/"btc_1h_2024_to_sep24_2026.json"
    t,o,hi,lo,c,v,tr,tk,hsha=read_klines(hp,3600000)
    ix,dates,X,names,reg,vol,atr=build_hourly_features(t,hi,lo,c,v,tr,tk,168)
    distance=c[ix]*vol*np.sqrt(72.0)
    y,when=target_distance(ix,c,hi,lo,distance,72)
    hourly=run_head("hourly",dates,X,names,reg,vol,y,np.timedelta64(72,"h"),FOLDS_H)

    # 15m ±1% / 4h early-warning target.
    ep=ROOT/"research_vnext/data/BTCUSDT_15m_2024-01_2026-06.json.gz"
    t,o,hi,lo,c,v,tr,tk,esha=read_klines(ep,900000)
    ix,dates,X,names,reg,vol=build_15m_features(t,hi,lo,c,v,tr,tk,16)
    y,when=target_percent(ix,c,hi,lo,.99,1.01,16)
    early=run_head("early15m",dates,X,names,reg,vol,y,np.timedelta64(240,"m"),FOLDS_15)

    result={
      "schema":"btc-predictive-vnext4-feature-ablation-v1",
      "research_only":True,"trading_authority":False,
      "historical_status":"INSPECTED_DIAGNOSTIC_NOT_UNTOUCHED",
      "promotion_rule":"No feature-family change may enter vNext4. Any future challenger must be frozen before new prospective observations.",
      "hourly_source_sha256":hsha,"early15m_source_sha256":esha,
      "hourly":hourly,"early15m":early
    }
    OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2,sort_keys=True)+"\n")
    compact={}
    for head,x in (("hourly",hourly),("early15m",early)):
        compact[head]={m:{g:v["diagnostic_remove_signal"] for g,v in s.items()} for m,s in x["summary"].items()}
    print(json.dumps(compact,ensure_ascii=False,indent=2))


if __name__=="__main__":main()
