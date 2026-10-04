"""15-minute early-warning contour for 4h BTC moves.

Every closed 15m bar is an anchor. This is deliberately separate from the hourly
first-passage model so that short-lived microstructure information is not diluted
by a four-hour anchor stride.
"""
from __future__ import annotations

import json
from pathlib import Path
import numpy as np

from core import (read_klines, build_15m_features, target_percent, masks,
                  evaluate_fold)

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/"research_vnext/data/BTCUSDT_15m_2024-01_2026-06.json.gz"
OUT=ROOT/"research_vnext2/early15m_result.json"
FOLDS=(
    ("2025Q3","2025-04-01","2025-04-01","2025-07-01","2025-07-03","2025-10-01"),
    ("2025Q4","2025-07-01","2025-07-01","2025-10-01","2025-10-03","2026-01-01"),
    ("2026H1","2025-10-01","2025-10-01","2026-01-01","2026-01-03","2026-07-01"),
)
CANDIDATES=("logistic","gbdt","competing_risks","regime_competing_risks")


def run():
    t,o,hi,lo,c,v,trades,taker,sha=read_klines(DATA,900000)
    ix,dates,X,names,regime,vol_measure=build_15m_features(
        t,hi,lo,c,v,trades,taker,max_forward_bars=16)
    y,when=target_percent(ix,c,hi,lo,.99,1.01,16)
    due=np.timedelta64(240,"m")
    out={
        "schema":"btc-predictive-vnext2-early15m",
        "research_only":True,
        "trading_authority":False,
        "anchor_cadence":"15m",
        "target":"first passage ±1% within 4h",
        "history_sha256":sha,
        "features":names,
        "regimes":["LOW_VOL_COMPRESSION","TREND_OTHER","BREAKOUT_POST_BREAKOUT","REVERSAL_LIQUIDATION"],
        "folds":{}
    }
    aggregate={m:[] for m in CANDIDATES}
    for fold,*bounds in FOLDS:
        tr,ca,te=masks(dates,due,*bounds)
        result=evaluate_fold(X,regime,vol_measure,dates,y,when,tr,ca,te,
                             due,16,1)
        out["folds"][fold]=result
        strongest=result["strongest_baseline"]
        base=result["models"][strongest]
        for m in CANDIDATES:
            s=result["models"][m]
            aggregate[m].append({
                "fold":fold,
                "brier_gain":base["brier"]-s["brier"],
                "log_loss_gain":base["log_loss"]-s["log_loss"],
                "ci_low":s["brier_gain_vs_strongest_baseline_ci"][0]
            })
    ranking=[]
    for m,rows in aggregate.items():
        gains=np.asarray([r["brier_gain"] for r in rows])
        logs=np.asarray([r["log_loss_gain"] for r in rows])
        robust=float(np.mean(gains)+min(0.0,float(np.min(gains)))+0.25*np.mean(logs))
        ranking.append({
            "model":m,
            "mean_brier_gain_vs_strongest_adaptive_baseline":float(np.mean(gains)),
            "worst_brier_gain":float(np.min(gains)),
            "mean_log_loss_gain":float(np.mean(logs)),
            "positive_ci_count":int(sum(r["ci_low"]>0 for r in rows)),
            "robust_score":robust
        })
    ranking.sort(key=lambda x:x["robust_score"],reverse=True)
    out["candidate_selection"]={
        "selection_is_diagnostic_not_validation":True,
        "ranked":ranking,
        "shadow_candidate":ranking[0]["model"],
        "predictive_accept":False
    }
    OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2,sort_keys=True)+"\n")
    print(json.dumps({"out":str(OUT),"candidate":ranking[0]["model"],"ranking":ranking},
                     ensure_ascii=False,indent=2))


if __name__=="__main__":
    run()
