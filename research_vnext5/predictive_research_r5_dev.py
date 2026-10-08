"""vNext5R5 24h competing-risks development diagnostic.

The previous 24h zone classifier had strong Brier improvement but poor canonical
probability calibration. R5 changes model structure rather than post-hoc gates:
it models first-touch timing as a discrete-time competing-risks process.

IMPORTANT:
- all previous historical evaluation folds have already been observed;
- therefore this file is DEVELOPMENT_DIAGNOSTIC_ONLY;
- no historical result here may establish skill or authorize model selection;
- the eventual candidate must be frozen before a clean prospective epoch.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

from predictive_vnext4.core import (
    read_klines,
    build_hourly_features,
    first_touch_variable,
    _fit_hazard,
    _hazard_cumulative,
)
from research_vnext5 import predictive_research as r1
from research_vnext5 import predictive_research_r2 as r2

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"research_vnext5"
CANONICAL_PID=r1.ZONE_SIGMA_PAIRS.index((1.0,1.0))
HORIZON_STEPS=24
HAZARD_STEP=3


def zone_augmented_with_when(X,dates,regime,vol,ix,c,hi,lo):
    keep=np.arange(len(ix))%HORIZON_STEPS==0
    bix=ix[keep]; bx=X[keep]; bd=dates[keep]; bv=vol[keep]
    unit=c[bix]*bv*math.sqrt(float(HORIZON_STEPS))
    xs=[];ys=[];ws=[];ds=[];vs=[];pids=[]
    for pid,(lm,um) in enumerate(r1.ZONE_SIGMA_PAIRS):
        lower=c[bix]-lm*unit
        upper=c[bix]+um*unit
        y,w=first_touch_variable(bix,hi,lo,c,lower,upper,HORIZON_STEPS)
        extra=np.column_stack((
            np.full(len(bix),lm),
            np.full(len(bix),um),
            np.full(len(bix),lm-um),
            np.full(len(bix),math.log(lm/um)),
        ))
        xs.append(np.column_stack((bx,extra)))
        ys.append(y);ws.append(w);ds.append(bd);vs.append(bv)
        pids.append(np.full(len(bix),pid,dtype=np.int16))
    return (
        np.vstack(xs),np.concatenate(ys),np.concatenate(ws),
        np.concatenate(ds),np.concatenate(vs),np.concatenate(pids)
    )


def calibrated_hazard(X,y,when,train,cal,test):
    model=_fit_hazard(
        X,y,when,train,
        horizon_steps=HORIZON_STEPS,
        step=HAZARD_STEP,
    )
    pcal=_hazard_cumulative(
        model,X[cal],HORIZON_STEPS,HAZARD_STEP
    )
    ptest=_hazard_cumulative(
        model,X[test],HORIZON_STEPS,HAZARD_STEP
    )
    return r1.calibrate(pcal,ptest,y[cal])


def fold_metrics(p,base,y,dates,canon):
    row=r1.metrics(p,y,4)
    b=r1.metrics(base,y,4)
    row["baseline_ece10"]=b["ece10"]
    row["brier_gain_vs_baseline"]=float(b["brier"]-row["brier"])
    row["brier_gain_ci95"]=r1.block_ci_gain(base,p,y,dates,4)
    cp=p[canon]; cb=base[canon]; cy=y[canon]; cd=dates[canon]
    cm=r1.metrics(cp,cy,4); cbm=r1.metrics(cb,cy,4)
    cm["baseline_ece10"]=cbm["ece10"]
    cm["brier_gain_vs_baseline"]=float(cbm["brier"]-cm["brier"])
    cm["brier_gain_ci95"]=r1.block_ci_gain(cb,cp,cy,cd,4)
    cm["three_state_resolved"]=r1.zone_resolved_metrics(cp,cy)
    row["canonical_1sigma"]=cm
    return row


def summarize(rows):
    return {
        "folds":len(rows),
        "wins":sum(r["brier_gain_vs_baseline"]>0 for r in rows),
        "positive_ci_folds":sum(
            r["brier_gain_ci95"][0] is not None
            and r["brier_gain_ci95"][0]>0 for r in rows
        ),
        "mean_brier":float(np.mean([r["brier"] for r in rows])),
        "mean_brier_gain":float(np.mean([r["brier_gain_vs_baseline"] for r in rows])),
        "mean_log_loss":float(np.mean([r["log_loss"] for r in rows])),
        "mean_ece10":float(np.mean([r["ece10"] for r in rows])),
        "mean_baseline_ece10":float(np.mean([r["baseline_ece10"] for r in rows])),
    }


def main():
    path=ROOT/"btc_1h_2024_to_sep24_2026.json"
    t,o,hi,lo,c,v,trades,taker,sha=read_klines(path,3600000)
    ix,dates,X,names,regime,vol,atr=build_hourly_features(
        t,hi,lo,c,v,trades,taker,24
    )
    ZX,zy,zw,zd,zv,zpid=zone_augmented_with_when(
        X,dates,regime,vol,ix,c,hi,lo
    )
    due=np.timedelta64(24,"h")
    report={
        "schema":"btc-predictive-vnext5r5-competing-risks-dev-v1",
        "status":"DEVELOPMENT_DIAGNOSTIC_ONLY_HISTORICAL_FOLDS_ALREADY_SEEN",
        "source_sha256":sha,
        "hazard_step_hours":HAZARD_STEP,
        "folds":{},
        "no_historical_acceptance":True,
        "next_valid_selection_evidence":"CLEAN_PROSPECTIVE_EPOCH",
        "trading_authority":False,
    }

    for spec in r1.FOLD_SPECS:
        label=spec[0]
        tr,ca,te=r1.fold_masks(zd,due,spec)
        base=r2.rolling_pair_vol90d_baseline(
            zd,due,zy,zv,zpid,tr,te
        )
        classpred=r1.fit_classifier_candidates(ZX,zy,tr,ca,te,4)["ensemble_equal"]
        hazard=calibrated_hazard(ZX,zy,zw,tr,ca,te)
        blend=(classpred+hazard)/2.0
        blend/=np.maximum(blend.sum(axis=1,keepdims=True),1e-12)

        yt=zy[te]; dt=zd[te]; pid=zpid[te]
        canon=pid==CANONICAL_PID
        report["folds"][label]={
            "n":int(np.sum(te)),
            "canonical_n":int(np.sum(canon)),
            "models":{
                "r2_classifier_ensemble":fold_metrics(
                    classpred,base,yt,dt,canon
                ),
                "competing_risks_calibrated":fold_metrics(
                    hazard,base,yt,dt,canon
                ),
                "classifier_hazard_equal_blend":fold_metrics(
                    blend,base,yt,dt,canon
                ),
            },
        }

    models=sorted(next(iter(report["folds"].values()))["models"])
    report["summary"]={}
    report["canonical_summary"]={}
    for name in models:
        rows=[f["models"][name] for f in report["folds"].values()]
        report["summary"][name]=summarize(rows)
        report["canonical_summary"][name]=summarize(
            [r["canonical_1sigma"] for r in rows]
        )

    # Diagnostic ranking only; explicitly not a valid historical acceptance.
    report["diagnostic_rank"]=sorted(
        (
            report["canonical_summary"][n]["mean_ece10"],
            report["canonical_summary"][n]["mean_brier"],
            n,
        )
        for n in models
    )
    out=OUT/"predictive_research_r5_dev_result.json"
    out.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    print(json.dumps({
        "summary":report["summary"],
        "canonical_summary":report["canonical_summary"],
        "diagnostic_rank":report["diagnostic_rank"],
        "status":report["status"],
    },indent=2,sort_keys=True))


if __name__=="__main__":
    main()
