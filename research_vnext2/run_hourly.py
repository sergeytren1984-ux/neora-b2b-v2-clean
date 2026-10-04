"""Run the vNext hourly benchmark with hourly anchors, adaptive baselines,
regime-dependent competing risks, and normalized first-passage targets."""
from __future__ import annotations

import json
import math
from pathlib import Path
import numpy as np

from core import (read_klines, build_hourly_features, target_percent, target_distance,
                  masks, evaluate_fold, shift_report)

ROOT=Path(__file__).resolve().parents[1]
HISTORY=ROOT/"btc_1h_2024_to_sep24_2026.json"
OUT=ROOT/"research_vnext2/hourly_result.json"
REFERENCE=84672.01
FOLDS=(
    ("2025Q3","2025-04-01","2025-04-01","2025-07-01","2025-07-08","2025-10-01"),
    ("2025Q4","2025-07-01","2025-07-01","2025-10-01","2025-10-08","2026-01-01"),
    ("2026H1","2025-10-01","2025-10-01","2026-01-01","2026-01-08","2026-07-01"),
)
CANDIDATES=("logistic","gbdt","competing_risks","regime_competing_risks")


def target_specs(ix,c,hi,lo,atr_abs,vol_measure):
    specs={}
    # Stable benchmark.
    specs["pm1pct_24h"]={
        "horizon_hours":24,
        "label":target_percent(ix,c,hi,lo,.99,1.01,24)
    }
    # Current operational distances mapped proportionally to every historical anchor.
    specs["entry_82500_before_87000_72h_scaled"]={
        "horizon_hours":72,
        "label":target_percent(ix,c,hi,lo,82500/REFERENCE,87000/REFERENCE,72)
    }
    specs["entry_81500_before_88000_7d_scaled"]={
        "horizon_hours":168,
        "label":target_percent(ix,c,hi,lo,81500/REFERENCE,88000/REFERENCE,168)
    }
    # ATR-normalized barrier: same volatility-relative distance at every anchor.
    specs["atr1_5_72h"]={
        "horizon_hours":72,
        "label":target_distance(ix,c,hi,lo,1.5*atr_abs,72)
    }
    # Realized-volatility normalized barrier. Past 24h sigma only, horizon-scaled.
    rv_distance=c[ix]*vol_measure*np.sqrt(72.0)
    specs["rv24_sqrth_72h"]={
        "horizon_hours":72,
        "label":target_distance(ix,c,hi,lo,rv_distance,72)
    }
    return specs


def run():
    t,o,hi,lo,c,v,trades,taker,sha=read_klines(HISTORY,3600000)
    ix,dates,X,names,regime,vol_measure,atr_abs=build_hourly_features(
        t,hi,lo,c,v,trades,taker,max_horizon=168)
    specs=target_specs(ix,c,hi,lo,atr_abs,vol_measure)
    out={
        "schema":"btc-predictive-vnext2-hourly",
        "research_only":True,
        "trading_authority":False,
        "anchor_cadence":"1h",
        "history_sha256":sha,
        "features":names,
        "regimes":["LOW_VOL_COMPRESSION","TREND_OTHER","BREAKOUT_POST_BREAKOUT","REVERSAL_LIQUIDATION"],
        "adaptive_baselines":["rolling30d","rolling60d","rolling90d","ewma30d","regime90d","vol90d"],
        "targets":{},
        "candidate_selection":{}
    }
    aggregate={m:[] for m in CANDIDATES}
    operational_y=None
    for target_name,spec in specs.items():
        horizon=spec["horizon_hours"]
        y,when=spec["label"]
        due_delta=np.timedelta64(horizon,"h")
        hstep=1 if horizon<=24 else 6 if horizon<=72 else 12
        target_out={"horizon_hours":horizon,"folds":{}}
        for fold,*bounds in FOLDS:
            tr,ca,te=masks(dates,due_delta,*bounds)
            fold_result=evaluate_fold(X,regime,vol_measure,dates,y,when,tr,ca,te,
                                      due_delta,horizon,hstep)
            target_out["folds"][fold]=fold_result
            strongest=fold_result["strongest_baseline"]
            base=fold_result["models"][strongest]
            for m in CANDIDATES:
                s=fold_result["models"][m]
                gain=base["brier"]-s["brier"]
                log_gain=base["log_loss"]-s["log_loss"]
                ci=s["brier_gain_vs_strongest_baseline_ci"]
                aggregate[m].append({"target":target_name,"fold":fold,
                                     "brier_gain":gain,"log_loss_gain":log_gain,
                                     "ci_low":ci[0],"ci_high":ci[1]})
        out["targets"][target_name]=target_out
        if target_name=="entry_82500_before_87000_72h_scaled":
            operational_y=y
    # Explicitly diagnose the Q3 -> Q4 regime shift on the main 72h entry question.
    out["q3_vs_q4_shift"]=shift_report(
        X,names,dates,regime,operational_y,
        ("2025-07-08","2025-10-01"),("2025-10-08","2026-01-01"))
    ranking=[]
    for m,rows in aggregate.items():
        gains=np.asarray([r["brier_gain"] for r in rows],dtype=float)
        logs=np.asarray([r["log_loss_gain"] for r in rows],dtype=float)
        lows=np.asarray([r["ci_low"] for r in rows],dtype=float)
        robust=float(np.mean(gains)+min(0.0,float(np.min(gains)))+0.25*np.mean(logs))
        ranking.append({
            "model":m,
            "mean_brier_gain_vs_strongest_adaptive_baseline":float(np.mean(gains)),
            "worst_brier_gain":float(np.min(gains)),
            "mean_log_loss_gain":float(np.mean(logs)),
            "positive_ci_count":int(np.sum(lows>0)),
            "comparisons":len(rows),
            "robust_score":robust
        })
    ranking.sort(key=lambda x:x["robust_score"],reverse=True)
    out["candidate_selection"]={
        "selection_is_diagnostic_not_validation":True,
        "ranked":ranking,
        "shadow_candidates":[x["model"] for x in ranking[:2]],
        "predictive_accept":False,
        "reason":"No candidate may be promoted from inspected history; top candidates are eligible only for frozen prospective shadow collection."
    }
    OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2,sort_keys=True)+"\n")
    print(json.dumps({"out":str(OUT),"shadow_candidates":out["candidate_selection"]["shadow_candidates"],
                      "ranking":ranking},ensure_ascii=False,indent=2))


if __name__=="__main__":
    run()
