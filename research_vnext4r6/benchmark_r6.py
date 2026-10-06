"""R6 structural research benchmark.

Research-only. No trading authority. No prospective evidence writes.

Predeclared questions:
1) Replace the fixed ±1% 4h endpoint with volatility-scaled 1h/4h/24h heads.
2) Test whether a deterministic regime selector can beat the strong adaptive vol90d
   baseline without choosing a rule after seeing the test fold.
3) Preserve the vNext4 feature implementation for parity while changing only target/
   selection architecture in this structural phase.

Macro/exogenous features are intentionally NOT included here; they are evaluated by
a separate ablation so they cannot contaminate this structural comparison.
"""
from __future__ import annotations

import json
from pathlib import Path
import numpy as np

from predictive_vnext4.core import (
    read_klines, build_hourly_features, build_15m_features,
    target_distance, masks, fit_candidates, adaptive_baselines,
    metrics, block_ci,
)

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"research_vnext4r6"
CONTENDERS=("logistic","gbdt","competing_risks")
SELECTORS=("selector_regime","selector_regime_or_highvol")


def fit_fold(X,regime,vol,dates,y,when,train,cal,test,due_delta,horizon_steps,hazard_step):
    pred=fit_candidates(X,regime,y,when,train,cal,test,horizon_steps,hazard_step)
    base=adaptive_baselines(dates,y,regime,vol,train,test,due_delta)
    pred.update(base)

    test_idx=np.flatnonzero(test)
    q=np.quantile(vol[train],[1/3,2/3])
    highvol=vol[test_idx]>q[1]
    event_regime=np.isin(regime[test_idx],[2,3])

    # Fixed before test inspection. No learned router and no test-derived threshold.
    p_primary=pred["vol90d"]
    p_gbdt=pred["gbdt"]
    pred["selector_regime"]=np.where(event_regime[:,None],p_gbdt,p_primary)
    pred["selector_regime_or_highvol"]=np.where((event_regime|highvol)[:,None],p_gbdt,p_primary)

    yt=y[test]
    dt=dates[test]
    report={}
    for name,p in pred.items():
        m=metrics(p,yt)
        m["brier_gain_vs_vol90d_ci95"]=block_ci(p_primary,p,yt,dt)
        m["brier_gain_vs_vol90d_mean"]=float(
            np.mean(np.sum((p_primary-np.eye(4)[yt])**2,axis=1) -
                    np.sum((p-np.eye(4)[yt])**2,axis=1))
        )
        report[name]=m
    counts=np.bincount(yt,minlength=4)
    return report, {
        "test_n":int(np.sum(test)),
        "test_class_counts":counts.tolist(),
        "test_class_frequency":(counts/max(int(counts.sum()),1)).tolist(),
        "test_regime_event_fraction":float(np.mean(event_regime)) if len(event_regime) else None,
        "test_highvol_fraction":float(np.mean(highvol)) if len(highvol) else None,
        "training_vol_quantiles":[float(q[0]),float(q[1])],
    }


def make_folds(end_limit):
    folds=[
      ("2025Q3","2025-04-01","2025-04-01","2025-07-01","2025-07-08","2025-10-01"),
      ("2025Q4","2025-07-01","2025-07-01","2025-10-01","2025-10-08","2026-01-01"),
      ("2026H1","2025-10-01","2025-10-01","2026-01-01","2026-01-08","2026-07-01"),
    ]
    if end_limit >= np.datetime64("2026-09-24"):
        folds.append(("2026Q3","2026-01-01","2026-01-01","2026-07-01","2026-07-08","2026-09-24"))
    return folds


def evaluate_head(name,X,regime,vol,dates,y,when,due_delta,horizon_steps,hazard_step):
    out={"head":name,"folds":{}}
    for label,*b in make_folds(dates.max()):
        # Skip folds beyond the available source.
        if np.datetime64(b[-1])>dates.max()+np.timedelta64(1,"D"):
            continue
        tr,ca,te=masks(dates,due_delta,*b)
        if np.sum(tr)<500 or np.sum(ca)<100 or np.sum(te)<100:
            continue
        scores,meta=fit_fold(
            X,regime,vol,dates,y,when,tr,ca,te,due_delta,horizon_steps,hazard_step)
        out["folds"][label]={"meta":meta,"models":scores}
    return out


def summarize(head):
    names=["vol90d",*CONTENDERS,*SELECTORS]
    summary={}
    for name in names:
        rows=[]
        for fold in head["folds"].values():
            m=fold["models"].get(name)
            if m: rows.append(m)
        if not rows: continue
        gains=[r["brier_gain_vs_vol90d_mean"] for r in rows]
        ci=[r["brier_gain_vs_vol90d_ci95"] for r in rows]
        summary[name]={
            "folds":len(rows),
            "wins_vs_vol90d":sum(g>0 for g in gains),
            "mean_brier_gain_vs_vol90d":float(np.mean(gains)),
            "all_fold_brier_better":all(g>0 for g in gains),
            "positive_ci_folds":sum(x[0]>0 for x in ci if x and x[0] is not None),
            "mean_brier":float(np.mean([r["brier"] for r in rows])),
            "mean_log_loss":float(np.mean([r["log_loss"] for r in rows])),
        }
    # Research gate only. Never authorizes trading or production.
    for s in SELECTORS:
        z=summary.get(s)
        if z:
            z["research_gate_pass"]=bool(
                z["folds"]>=3 and z["wins_vs_vol90d"]>=2 and
                z["mean_brier_gain_vs_vol90d"]>0
            )
    return summary


def build_15m_heads():
    hist=ROOT/"research_vnext/data/BTCUSDT_15m_2024-01_2026-06.json.gz"
    t,o,hi,lo,c,v,trades,taker,source_sha=read_klines(hist,900000)
    ix,dates,X,names,regime,vol=build_15m_features(t,hi,lo,c,v,trades,taker,16)
    heads={}
    for label,bars in (("1h",4),("4h",16)):
        distance=c[ix]*vol*np.sqrt(float(bars))
        y,when=target_distance(ix,c,hi,lo,distance,bars)
        due=np.timedelta64(bars*15,"m")
        heads[label]=evaluate_head(
            label,X,regime,vol,dates,y,when,due,bars,1)
        ratio=distance/c[ix]
        heads[label]["target"]={
            "type":"realized_vol_scaled_first_passage",
            "distance_ratio_quantiles":[float(x) for x in np.quantile(ratio,[.01,.1,.5,.9,.99])],
            "source_interval":"15m","vol_window":"4h",
            "distance_formula":f"reference * std(15m_log_returns,4h) * sqrt({bars})",
            "horizon_minutes":bars*15,
        }
        heads[label]["historical_source_sha256"]=source_sha
        heads[label]["feature_names"]=names
        heads[label]["summary"]=summarize(heads[label])
    return heads


def build_24h_head():
    hist=ROOT/"btc_1h_2024_to_sep24_2026.json"
    t,o,hi,lo,c,v,trades,taker,source_sha=read_klines(hist,3600000)
    ix,dates,X,names,regime,vol,atr=build_hourly_features(t,hi,lo,c,v,trades,taker,24)
    bars=24
    distance=c[ix]*vol*np.sqrt(float(bars))
    y,when=target_distance(ix,c,hi,lo,distance,bars)
    head=evaluate_head("24h",X,regime,vol,dates,y,when,np.timedelta64(24,"h"),24,3)
    ratio=distance/c[ix]
    head["target"]={
        "type":"realized_vol_scaled_first_passage",
        "distance_ratio_quantiles":[float(x) for x in np.quantile(ratio,[.01,.1,.5,.9,.99])],
        "source_interval":"1h","vol_window":"24h",
        "distance_formula":"reference * std(1h_log_returns,24h) * sqrt(24)",
        "horizon_hours":24,
    }
    head["historical_source_sha256"]=source_sha
    head["feature_names"]=names
    head["summary"]=summarize(head)
    return head


def main():
    heads=build_15m_heads()
    heads["24h"]=build_24h_head()
    report={
      "schema":"btc-predictive-vnext4r6-structural-research-v1",
      "status":"RESEARCH_ONLY",
      "trading_authority":False,
      "production_freeze_authorized":False,
      "predeclared_selector_rules":{
        "selector_regime":"GBDT only in BREAKOUT_POST_BREAKOUT or REVERSAL_LIQUIDATION; vol90d otherwise",
        "selector_regime_or_highvol":"GBDT in event regime OR top training volatility tercile; vol90d otherwise",
      },
      "heads":heads,
      "decision_rule":"No selector/model enters R6 production unless independent review accepts its multi-fold evidence.",
    }
    OUT.mkdir(exist_ok=True)
    p=OUT/"structural_result.json"
    p.write_text(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True)+"\n")
    print(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True))


if __name__=="__main__":
    main()
