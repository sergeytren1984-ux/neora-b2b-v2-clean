"""Generalized first-passage research for the user's fixed-price operational questions.

The model is parameterized by lower/upper distance and horizon. That allows a
future frozen head to answer exact 82,500/87,000 or 81,500/88,000 questions
without pretending that a volatility-normalized probability is the same event.

Historical results are diagnostic only: the available Jul-Sep 2026 period has
already been inspected in prior research and is not called untouched.
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
    read_klines,build_hourly_features,target_percent,calibrate,full_proba,metrics,block_ci
)

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"research_vnext4/operational_barrier_result.json"
SEED=20261004
# Predeclared grid; not fitted to any one known episode.
LOWER=(.015,.025,.030,.040)
UPPER=(.015,.025,.030,.040)
HORIZONS=(24,72,168)
FOLDS=(
    ("2025Q3","2025-04-01","2025-04-01","2025-07-01","2025-07-08","2025-10-01"),
    ("2025Q4","2025-07-01","2025-07-01","2025-10-01","2025-10-08","2026-01-01"),
    ("2026H1","2025-10-01","2025-10-01","2026-01-01","2026-01-08","2026-07-01"),
)


def make_dataset(dates,X,vol,ix,c,hi,lo):
    # One anchor per 6h to lower dependence in research fitting.
    choose=np.arange(len(ix))[::6]
    aix=ix[choose];adates=dates[choose];aX=X[choose];avol=vol[choose];ac=c[aix]
    qs=[];ys=[];whens=[];features=[];out_dates=[];scenario_ids=[];horizons=[]
    scenario=0
    for h in HORIZONS:
        for dl in LOWER:
            for du in UPPER:
                y,when=target_percent(aix,c,hi,lo,1-dl,1+du,h)
                # Query geometry available at anchor only.
                q=np.column_stack([
                    np.full(len(aix),dl),
                    np.full(len(aix),du),
                    np.full(len(aix),np.log(h)),
                    np.full(len(aix),du-dl),
                    dl/np.maximum(avol,1e-9),
                    du/np.maximum(avol,1e-9),
                ])
                features.append(np.column_stack([aX,q]))
                ys.append(y);whens.append(when);out_dates.append(adates)
                scenario_ids.append(np.full(len(aix),scenario,dtype=np.int16))
                horizons.append(np.full(len(aix),h,dtype=np.int16))
                qs.append({"scenario_id":scenario,"lower_distance":dl,"upper_distance":du,"horizon_hours":h})
                scenario+=1
    return {
        "X":np.concatenate(features),"y":np.concatenate(ys),
        "dates":np.concatenate(out_dates),"scenario":np.concatenate(scenario_ids),
        "horizon":np.concatenate(horizons),"query_specs":qs,
        "base_feature_count":X.shape[1],
    }


def split(dates,horizon,bounds):
    train_end,cal_start,cal_end,test_start,test_end=map(np.datetime64,bounds)
    due=dates+horizon.astype("timedelta64[h]")
    tr=due<train_end
    ca=(dates>=cal_start)&(due<cal_end)
    te=(dates>=test_start)&(due<test_end)
    return tr,ca,te


def baseline_predictions(y,scenario,vol,train,test):
    # Volatility terciles are frozen from train only.
    q=np.quantile(vol[train],[1/3,2/3])
    vb=np.digitize(vol,q,right=True)
    global_counts=np.bincount(y[train],minlength=4).astype(float)+.5
    gp=global_counts/global_counts.sum()
    test_idx=np.flatnonzero(test);p=np.zeros((len(test_idx),4))
    for pos,i in enumerate(test_idx):
        key=train&(scenario==scenario[i])&(vb==vb[i])
        if np.sum(key)<40:
            key=train&(scenario==scenario[i])
        if np.sum(key)<40:
            p[pos]=gp;continue
        cnt=np.bincount(y[key],minlength=4).astype(float)+.5
        p[pos]=cnt/cnt.sum()
    return p


def fit_models(X,y,tr,ca,te):
    out={}
    logistic=make_pipeline(StandardScaler(),LogisticRegression(C=.025,max_iter=500))
    logistic.fit(X[tr],y[tr])
    out["logistic"]=calibrate(full_proba(logistic,X[ca]),full_proba(logistic,X[te]),y[ca])

    tree=HistGradientBoostingClassifier(max_iter=130,max_leaf_nodes=19,min_samples_leaf=120,
                                        learning_rate=.035,l2_regularization=15,random_state=SEED)
    tree.fit(X[tr],y[tr])
    out["gbdt"]=calibrate(full_proba(tree,X[ca]),full_proba(tree,X[te]),y[ca])
    return out


def scenario_metrics(p,y,scenario,test_idx,specs):
    out={}
    st=scenario[test_idx]
    for spec in specs:
        sid=spec["scenario_id"];m=st==sid
        if np.sum(m)<50:continue
        key=f"{int(spec['horizon_hours'])}h_L{spec['lower_distance']:.3f}_U{spec['upper_distance']:.3f}"
        out[key]={"n":int(np.sum(m)),**metrics(p[m],y[test_idx][m])}
    return out


def main():
    path=ROOT/"btc_1h_2024_to_sep24_2026.json"
    t,o,hi,lo,c,v,tr,tk,sha=read_klines(path,3600000)
    ix,dates,X,names,reg,vol,atr=build_hourly_features(t,hi,lo,c,v,tr,tk,168)
    data=make_dataset(dates,X,vol,ix,c,hi,lo)
    AX=data["X"];y=data["y"];d=data["dates"];sid=data["scenario"];h=data["horizon"]

    # Repeat anchor 24h volatility measure over the scenario grid.
    chosen_vol=vol[::6]
    aug_vol=np.tile(chosen_vol,len(data["query_specs"]))

    result={
      "schema":"btc-predictive-vnext4-generalized-operational-first-passage-v1",
      "research_only":True,"trading_authority":False,
      "historical_status":"INSPECTED_DIAGNOSTIC_NOT_UNTOUCHED",
      "source_sha256":sha,
      "anchor_stride_hours":6,
      "query_grid":{"lower":LOWER,"upper":UPPER,"horizons_hours":HORIZONS},
      "feature_note":"existing frozen hourly features + lower distance + upper distance + log horizon + asymmetry + both distances / prior 24h volatility",
      "folds":{}
    }
    for fold,*bounds in FOLDS:
        trm,cam,tem=split(d,h,bounds)
        baseline=baseline_predictions(y,sid,aug_vol,trm,tem)
        pred=fit_models(AX,y,trm,cam,tem)
        yt=y[tem];dt=d[tem]
        row={"n":int(np.sum(tem)),"baseline":metrics(baseline,yt),"models":{}}
        for name,p in pred.items():
            sc=metrics(p,yt)
            sc["brier_gain_vs_conditional_baseline_ci"]=block_ci(baseline,p,yt,dt,n_boot=500)
            sc["scenario_metrics"]=scenario_metrics(p,y,sid,np.flatnonzero(tem),data["query_specs"])
            row["models"][name]=sc
        result["folds"][fold]=row

    # Summary on query geometries nearest the current operational corridors.
    # These do not claim exact-price probabilities; they test comparable distance/horizon shapes.
    focus=["72h_L0.025_U0.030","168h_L0.040_U0.040"]
    summary={}
    for focus_key in focus:
        summary[focus_key]={}
        for model in ("logistic","gbdt"):
            brier=[];logloss=[]
            for fold,row in result["folds"].items():
                s=row["models"][model]["scenario_metrics"].get(focus_key)
                if s:
                    brier.append(s["brier"]);logloss.append(s["log_loss"])
            summary[focus_key][model]={
                "fold_brier":brier,"fold_log_loss":logloss,
                "mean_brier":None if not brier else float(np.mean(brier)),
                "mean_log_loss":None if not logloss else float(np.mean(logloss))
            }
    result["operational_geometry_diagnostic"]=summary
    result["promotion_status"]="RESEARCH_ONLY_NO_PROBABILITY_PUBLICATION"
    result["next_valid_step"]="If diagnostic lift is promising, freeze a separate future prospective head that accepts exact lower/upper distances; do not retrofit vNext4."

    OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2,sort_keys=True)+"\n")
    print(json.dumps({
      "folds":{k:{m:{"brier":v["models"][m]["brier"],
                      "log_loss":v["models"][m]["log_loss"],
                      "ci":v["models"][m]["brier_gain_vs_conditional_baseline_ci"]}
                  for m in ("logistic","gbdt")}|{"baseline_brier":v["baseline"]["brier"]}
                for k,v in result["folds"].items()},
      "focus":summary
    },ensure_ascii=False,indent=2))


if __name__=="__main__":main()
