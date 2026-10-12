"""Independent phase event scoring and DAY-block paired MAE confidence limits.

Pre-registered TRAIN priors; no oracle prevalence from test. Price rows with
overlapping horizons are not independent observations. No promotion by
a nominal number of five-minute/quarter-hour rows.
"""
from __future__ import annotations
import math,random
from collections import defaultdict
from datetime import datetime,timezone
from btc_demand_v7.prospective_core import when,HORIZONS
from btc_demand_v7.event_semantics import BARRIERS,clustered_episodes,warning_lead_minutes

SEED=60112
DRAWS=500
MIN_DAYS=20

def fixed_phase(slot,head):
    s=when(slot)
    n={"1h":1,"4h":4,"24h":24,
       "morning_08msk":24,"30m":0.5}.get(head)
    if n is None:raise ValueError("unknown independent phase")
    if head=="morning_08msk":return s.hour==0 and s.minute==0
    if n==0.5:return s.minute%30==0
    return s.minute==0 and s.hour%int(n)==0

def day_block_ci(rows):
    """Paired daily bootstrap of absolute-error gain, deterministic seed."""
    grouped=defaultdict(list)
    for r in rows:
        day=when(r["slot_utc"]).strftime("%Y-%m-%d")
        grouped[day].append(float(r["baseline_abs_error"])-float(r["model_abs_error"]))
    if len(grouped)<MIN_DAYS:return None
    days=sorted(grouped)
    rng=random.Random(SEED)
    means=[]
    for _ in range(DRAWS):
        resampled=[rng.choice(days) for __ in days]
        values=[x for day in resampled for x in grouped[day]]
        means.append(sum(values)/len(values))
    means.sort()
    return {"n_day_blocks":len(days),
            "lower_95_mae_gain_usdt":means[int(.025*(DRAWS-1))],
            "upper_95_mae_gain_usdt":means[int(.975*(DRAWS-1))],
            "model_beats_persistence_at_95pct":means[int(.025*(DRAWS-1))]>0}

def prospective_skill(grid,forecasts,prices,barriers,frozen_priors):
    by_slot={f["slot_id"]:f for f in forecasts if f.get("kind")=="FORECAST_ISSUED"}
    price_metrics={}
    for head in HORIZONS:
        samples=[]
        for v in prices:
            if v.get("horizon")!=head or v.get("kind")!="OUTCOME_RECORDED":continue
            f=by_slot.get(v["slot_id"])
            if f is None or not fixed_phase(f["slot_utc"],head):continue
            samples.append({"slot_utc":f["slot_utc"],
                            "model_abs_error":v["absolute_error_usdt"],
                            "baseline_abs_error":v["persistence_absolute_error_usdt"]})
        avg=sum(float(r["baseline_abs_error"])-float(r["model_abs_error"]) for r in samples)/len(samples) if samples else None
        price_metrics[head]={"n_fixed_phase_windows":len(samples),
                             "mean_mae_gain_usdt":avg,
                             "paired_day_bootstrap":day_block_ci(samples)}
    events={}
    for head in BARRIERS:
        stats={"UP_FIRST":0,"DOWN_FIRST":0,"NEITHER":0,
               "AMBIGUOUS_SAME_MINUTE":0}
        usable=[];candidates=[]
        for event in barriers:
            if event.get("period")!=head or event.get("kind")!="BARRIER_OUTCOME_RECORDED":continue
            f=by_slot.get(event["slot_id"])
            if f is None or not fixed_phase(f["slot_utc"],head):continue
            direction=event["result"]["direction"]
            if direction not in stats:raise ValueError("invalid future event label")
            stats[direction]+=1
            usable.append(event["result"])
            c=f.get("demand_position_change",{}).get("state","UNAVAILABLE")
            candidates.append((f,event,c))
        n=sum(stats.values())-stats["AMBIGUOUS_SAME_MINUTE"]
        prior=frozen_priors["event_priors"][head]
        # Train-only prior Brier against actual held-out first-passage outcome.
        states=("UP_FIRST","DOWN_FIRST","NEITHER")
        pp=[float(prior["p_up_first_train"]),float(prior["p_down_first_train"]),float(prior["p_neither_train"])]
        brier=(sum(sum((float(label==state)-p)**2 for label,p in zip(states,pp))
                   for label in [x["direction"] for x in usable if x["direction"] in states])/n) if n else None
        proposed=[]
        effective=[]
        for f,event,state in candidates:
            if state not in ("UNCALIBRATED_UP_SHIFT","UNCALIBRATED_DOWN_SHIFT"):continue
            side="UP_FIRST" if state=="UNCALIBRATED_UP_SHIFT" else "DOWN_FIRST"
            proposed.append(f)
            if event["result"]["direction"]==side:
                hit=event["result"]["first_barrier_touch_utc"]
                lead=warning_lead_minutes(hit,f["recorded_utc"]) if hit else None
                if lead is not None and lead>=60:effective.append(f)
        events[head]={"n_fixed_phase_independent_windows":len(usable),
            "first_passage_counts":stats,
            "frozen_train_first_passage_prior":dict(zip(states,pp)),
            "train_prior_multiclass_brier":brier,
            "prospective_change_point_candidates":len(proposed),
            "correct_candidates_with_60m_execution_lead":len(effective),
            "event_level_lead_not_validated":True,
            "alert_precision":len(effective)/len(proposed) if proposed else None,
            "independent_event_clusters":len(clustered_episodes(usable))}
    return {"schema":"btc-v7r2-independent-phase-skill-v1",
            "source_training_prior_sha256":grid["frozen_train_priors_sha256"],
            "price":price_metrics,"first_passage":events,
            "never_use_heldout_prevalence_as_prior":True,
            "minimum_day_blocks_before_admission":MIN_DAYS,
            "evidence_insufficient_for_trading":True,
            "trading_authority":False}
