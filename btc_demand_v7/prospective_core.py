"""v7R2 fixed prospective grid, future-only outcomes and conservative admission.

The mathematical model remains BASELINE_ONLY. Integrity of execution is not
a claim of predictive skill. No retroactive forecasts, mutable due windows
or missing-outcome omission from denominators. All times UTC-aware.
"""
from __future__ import annotations
from datetime import datetime,timedelta,timezone
import hashlib,json,math
UTC=timezone.utc
SCHEMA="btc-v7r2-prospective-grid-v1"
HORIZONS=("1h","4h","24h","morning_08msk")
CADENCE=timedelta(minutes=15)
MAX_FORECAST_DELAY=timedelta(minutes=10)
OUTCOME_GRACE=timedelta(minutes=30)
MIN_EVAL_SLOT_COUNT=96
MIN_INDEPENDENT_DAYS=20
MIN_DISTINCT_UP_EVENTS=20
MIN_DISTINCT_DOWN_EVENTS=20

def when(v):
    t=datetime.fromisoformat(v.replace("Z","+00:00")) if isinstance(v,str) else v
    if not isinstance(t,datetime) or t.tzinfo is None:
        raise ValueError("UTC-aware time required")
    return t.astimezone(UTC)

def canonical(x):
    return (json.dumps(x,sort_keys=True,separators=(",",":"),allow_nan=False)+"\n").encode()

def sha256(obj):
    return hashlib.sha256(canonical(obj)).hexdigest()

def next_morning(t):
    t=when(t); morning=t.replace(hour=5,minute=0,second=0,microsecond=0)
    return morning if morning>t else morning+timedelta(days=1)

def target(slot,head):
    t=when(slot)
    if head=="1h":return t+timedelta(hours=1)
    if head=="4h":return t+timedelta(hours=4)
    if head=="24h":return t+timedelta(hours=24)
    if head=="morning_08msk":return next_morning(t)
    raise ValueError("unknown horizon "+head)

def due_slot_id(slot):
    return when(slot).strftime("%Y%m%dT%H%MZ")

def registered_grid(start,*,days=7,source_sha,created_at,source_ref):
    t=when(start);created=when(created_at)
    if t.minute%15 or t.second or t.microsecond:
        raise ValueError("registration start not aligned")
    if t-created<timedelta(hours=2):
        raise ValueError("prospective start must be >=2 hours after signed registration")
    if not(1<=days<=21) or len(source_sha)!=40 or not all(c in "0123456789abcdef" for c in source_sha):
        raise ValueError("bad source freeze or days")
    entries=[]
    for n in range(96*days):
        slot=t+n*CADENCE
        entries.append({"id":due_slot_id(slot),"slot_utc":slot.isoformat(),
                        "forecast_deadline_utc":(slot+MAX_FORECAST_DELAY).isoformat(),
                        "heads":{h:{"target_utc":target(slot,h).isoformat(),
                                    "outcome_deadline_utc":(target(slot,h)+OUTCOME_GRACE).isoformat()}
                                 for h in HORIZONS}})
    return {"schema":SCHEMA,"registered_at_utc":created.isoformat(),
            "model_source_sha":source_sha,"model_source_ref":source_ref,
            "start_utc":t.isoformat(),"days":days,"cadence_minutes":15,
            "forecast_deadline_minutes":10,"outcome_grace_minutes":30,
            "model_skill_status":"BASELINE_ONLY_UNVALIDATED",
            "trading_authority":False,
            "source":"Binance BTCUSDT closed 1m+5m; OKX optional book/funding/OI",
            "no_backfill":True,
            "pre_registered_event_semantics":{
                "30m":{"barrier_fraction":0.0045,"window_minutes":30},
                "1h":{"barrier_fraction":0.007,"window_minutes":60},
                "4h":{"barrier_fraction":0.012,"window_minutes":240},
                "competition":"upper-first / lower-first / neither / AMBIGUOUS_SAME_MINUTE",
                "episode_cluster_gap_minutes":240,
                "minimum_actionable_lead_minutes":60,
                "maximum_alerts_per_utc_day":1,
                "overlapping_grid_rows_are_not_independent_events":True
            },
            "no_auto_trade":True,"slots":entries}

def find_slot(grid,slot):
    i=due_slot_id(slot)
    matches=[s for s in grid["slots"] if s["id"]==i]
    if len(matches)!=1:raise ValueError("not a preregistered due slot")
    if when(matches[0]["slot_utc"])!=when(slot):raise ValueError("slot id mismatch")
    return matches[0]

def acceptance_at(grid,slot,issued):
    item=find_slot(grid,slot);t=when(issued);start=when(item["slot_utc"])
    if t<start:return "FORECAST_EARLY"
    if t>when(item["forecast_deadline_utc"]):return "SLOT_MISSED"
    return "FORECAST_ISSUED"

def forecast_receipt(grid,slot,issued,live,*,snapshot_sha,live_sha):
    item=find_slot(grid,slot)
    state=acceptance_at(grid,slot,issued)
    if state!="FORECAST_ISSUED":
        return {"schema":"btc-v7r2-slot-event-v1","kind":state,
                "slot_id":item["id"],"slot_utc":item["slot_utc"],
                "recorded_utc":when(issued).isoformat(),
                "frozen_grid_sha256":sha256(grid),"trading_authority":False}
    if when(live.get("reference_anchor_utc"))!=when(slot):
        raise ValueError("forecast was not computed from EXACT registered anchor")
    if when(live.get("computed_at_utc"))>when(issued):
        raise ValueError("future-dated computation")
    if live.get("model_skill_status")!="NOT_PROVEN_BASELINE_ONLY":
        raise ValueError("cannot silently promote frozen baseline model")
    binding=live.get("evidence_binding")
    if not binding or binding["snapshot_sha256"]!=snapshot_sha:
        raise ValueError("snapshot provenance hash mismatch")
    prices=live["price_point_forecasts"]
    raw_spot=float(live["spot"])
    if not(math.isfinite(raw_spot) and raw_spot>0):
        raise ValueError("invalid reference spot")
    heads={}
    for h in HORIZONS:
        if h=="morning_08msk":p=float(prices["morning"])
        elif h=="24h":p=raw_spot  # EXPLICIT persistence-only, no trained head.
        else:p=float(prices[h])
        if not math.isfinite(p) or p<=0:raise ValueError("invalid point forecast")
        heads[h]={"target_utc":item["heads"][h]["target_utc"],
                  "forecast_spot":p,"persistence_spot":raw_spot,
                  "method":"PERSISTENCE_BASELINE_ONLY" if h=="24h" else "FROZEN_UNVALIDATED_V7"}
    return {"schema":"btc-v7r2-slot-event-v1","kind":state,
            "slot_id":item["id"],"slot_utc":item["slot_utc"],
            "recorded_utc":when(issued).isoformat(),
            "frozen_grid_sha256":sha256(grid),
            "snapshot_sha256":snapshot_sha,"full_forecast_sha256":live_sha,
            "source_commit_sha":grid["model_source_sha"],
            "training_model_sha256":binding["model_sha256"],
            "spot_reference":raw_spot,"heads":heads,
            "event_head_diagnostics":{name:{
                "estimate":float(value["estimate"]),
                "status":value["status"],"watch":bool(value["watch"])
             } for name,value in live.get("large_move_probabilities",{}).items()
             if "estimate" in value},
            "trading_authority":False,"skill_verified":False,
            "otc_status":live["otc_comparison"]["status"],
            "otc_calculation_is_executable":False}

def price_outcome(grid,forecast,head,now,spot_close,*,raw_sha):
    if forecast.get("kind")!="FORECAST_ISSUED":
        raise ValueError("no legitimate forecast available")
    slot=find_slot(grid,forecast["slot_utc"])
    if forecast["slot_id"]!=slot["id"]:
        raise ValueError("wrong slot in forecast")
    if forecast.get("frozen_grid_sha256")!=sha256(grid):
        raise ValueError("mixed prospective schedule")
    if head not in HORIZONS:raise ValueError("invalid horizon")
    due=when(slot["heads"][head]["target_utc"]);recorded=when(now)
    if recorded<due:raise ValueError("future outcome before maturity")
    value=float(spot_close)
    if not(math.isfinite(value) and value>0):raise ValueError("invalid outcome")
    pred=float(forecast["heads"][head]["forecast_spot"])
    base=float(forecast["heads"][head]["persistence_spot"])
    return {"schema":"btc-v7r2-price-outcome-v1",
            "kind":"OUTCOME_RECORDED" if recorded<=due+OUTCOME_GRACE else "OUTCOME_LATE",
            "slot_id":slot["id"],"horizon":head,
            "target_utc":due.isoformat(),"recorded_utc":recorded.isoformat(),
            "source_commit_sha":grid["model_source_sha"],
            "frozen_grid_sha256":sha256(grid),
            "forecast_sha256":sha256(forecast),
            "market_raw_sha256":raw_sha,
            "reference_symbol":"BTCUSDT","actual_spot":value,
            "pred_spot":pred,"persistence_spot":base,
            "absolute_error_usdt":abs(pred-value),
            "persistence_absolute_error_usdt":abs(base-value),
            "signed_error_usdt":pred-value,
            "trading_authority":False}

def score_fixed_grid(grid,forecast_events,outcome_events,now,barrier_events=()):
    now=when(now)
    slotted={x["slot_id"]:x for x in forecast_events}
    outcomes={(x["slot_id"],x["horizon"]):x for x in outcome_events}
    barriers={(x["slot_id"],x["period"]):x for x in barrier_events}
    if len(barriers)!=len(barrier_events):
        raise ValueError("duplicate barrier outcome")
    known_ids=set(x["id"] for x in grid["slots"])
    if not set(slotted).issubset(known_ids):
        raise ValueError("unknown forecast id")
    if len(slotted)!=len(forecast_events):
        raise ValueError("duplicate forecast: cannot score")
    if len(outcomes)!=len(outcome_events):
        raise ValueError("duplicate outcome: cannot score")
    missed=early=correct=late=0
    expected=settled=unsettled=missing=late_outcomes=0
    head_scores={h:{"n":0,"sum_absolute_error":0.0,
                    "sum_baseline_absolute_error":0.0,"due_count":0,
                    "missing":0} for h in HORIZONS}
    days=set()
    for slot in grid["slots"]:
        deadline=when(slot["forecast_deadline_utc"])
        if now<deadline:continue
        expected+=1
        f=slotted.get(slot["id"])
        if f is None or f["kind"]=="SLOT_MISSED":missed+=1;continue
        if f["kind"]=="FORECAST_EARLY":early+=1;continue
        if f["kind"]!="FORECAST_ISSUED":
            raise ValueError("unknown event kind")
        actual_at=when(f["recorded_utc"])
        if actual_at>deadline or actual_at<when(slot["slot_utc"]):
            late+=1;continue
        correct+=1;days.add(slot["id"][:8])
        for h in HORIZONS:
            due=when(slot["heads"][h]["target_utc"])
            if now<due+OUTCOME_GRACE:
                unsettled+=1;continue
            v=head_scores[h];v["due_count"]+=1
            o=outcomes.get((slot["id"],h))
            if o is None:
                missing+=1;v["missing"]+=1;continue
            if o.get("forecast_sha256")!=sha256(f) or o.get("frozen_grid_sha256")!=sha256(grid):
                raise ValueError("orphan or forged outcome")
            if when(o["recorded_utc"])<due:raise ValueError("premature outcome")
            if o["kind"]!="OUTCOME_RECORDED":
                late_outcomes+=1;continue
            settled+=1;v["n"]+=1
            v["sum_absolute_error"]+=float(o["absolute_error_usdt"])
            v["sum_baseline_absolute_error"]+=float(o["persistence_absolute_error_usdt"])
    # Symmetric first-passage outcomes on a separate 1m causal grid.
    # They are NOT interchangeable with old independent touch classifiers.
    from btc_demand_v7.event_semantics import BARRIERS,clustered_episodes,warning_lead_minutes,validate_alert_budget
    barrier_summary={h:{"due":0,"recorded":0,"missing":0,"late":0,"ambiguous":0,
                        "up_first":0,"down_first":0,"neither":0,
                        "actionable_warnings_ge_60m":0,"not_validated_warnings":0}
                     for h in BARRIERS}
    observed_events=[];alerts=[]
    for slot in grid["slots"]:
        f=slotted.get(slot["id"])
        if f is None or f.get("kind")!="FORECAST_ISSUED":continue
        for h,(minutes,threshold) in BARRIERS.items():
            due=when(slot["slot_utc"])+timedelta(minutes=minutes)
            if now<due+OUTCOME_GRACE:continue
            v=barrier_summary[h];v["due"]+=1
            outcome=barriers.get((slot["id"],h))
            if outcome is None:
                v["missing"]+=1;continue
            if outcome["forecast_sha256"]!=sha256(f) or outcome["frozen_grid_sha256"]!=sha256(grid):
                raise ValueError("forged barrier outcome provenance")
            if outcome.get("kind")!="BARRIER_OUTCOME_RECORDED":
                v["late"]+=1;continue
            result=outcome["result"]
            v["recorded"]+=1
            direction=result["direction"]
            key={"UP_FIRST":"up_first","DOWN_FIRST":"down_first",
                 "NEITHER":"neither","AMBIGUOUS_SAME_MINUTE":"ambiguous"}.get(direction)
            if key is None:raise ValueError("unknown first-passage outcome")
            v[key]+=1;observed_events.append(result)
            for side,event_direction in (("up","UP_FIRST"),("down","DOWN_FIRST")):
                model_key=side+"_"+h
                head=f.get("event_head_diagnostics",{}).get(model_key,{})
                if head.get("watch") is True:
                    alerts.append({"alert_id":slot["id"]+model_key,
                                   "issued_utc":f["recorded_utc"]})
                    if head.get("status")!="EXPERIMENTAL_NOT_CALIBRATED_FOR_TRADING":
                        v["not_validated_warnings"]+=1;continue
                    if direction==event_direction and result["first_barrier_touch_utc"]:
                        lead=warning_lead_minutes(result["first_barrier_touch_utc"],f["recorded_utc"])
                        if lead is not None and lead>=60:
                            v["actionable_warnings_ge_60m"]+=1
    budget=validate_alert_budget(alerts,max_per_day=1)
    episodes=clustered_episodes(observed_events)
    metrics={}
    for h,v in head_scores.items():
        n=v["n"]
        metrics[h]={"due_count":v["due_count"],"settled":n,
                    "missing_outcomes":v["missing"],
                    "model_mae_usdt":v["sum_absolute_error"]/n if n else None,
                    "baseline_mae_usdt":v["sum_baseline_absolute_error"]/n if n else None,
                    "mae_gain_usdt":(v["sum_baseline_absolute_error"]-v["sum_absolute_error"])/n if n else None}
    return {"schema":"btc-v7r2-full-due-grid-score-v1",
            "count_scope":"only due deadlines reached; missing forecast counts in denominator",
            "as_of_utc":now.isoformat(),"frozen_grid_sha256":sha256(grid),
            "due_forecast_slots":expected,"issued_on_time":correct,
            "missing_forecasts":missed,"early_forecasts":early,"late_forecasts":late,
            "outcome_due_count":sum(x["due_count"] for x in metrics.values()),
            "outcomes_on_time":settled,"outcomes_missing":missing,
            "outcomes_late":late_outcomes,"outcomes_not_due":unsettled,
            "distinct_issuance_days":len(days),
            "heads":metrics,
            "first_passage":barrier_summary,
            "distinct_clustered_barrier_episodes":len(episodes),
            "alert_budget":budget,
            "missing_slots_block_admission":bool(missed or late or early or missing or late_outcomes
                or any(v["missing"] or v["late"] for v in barrier_summary.values())
                or not budget["within_budget"]),
            "admission_ready":False,
            "why_no_admission":"No proven directional/price/OTC edge; insufficient independent future events; baseline-only prices",
            "trading_authority":False}
