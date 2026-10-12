"""v7R3 separate future-only pre-registration for stateful demand shadow.

This is not the v7R2 frozen price model. Never edit the v7R2 evidence branch.
The objective is to measure the earliest *actually published* warning relative
to future BTC moves, with missing slots and factor coverage fully visible.
"""
from __future__ import annotations
from datetime import datetime,timedelta,timezone
import hashlib,json,math
from btc_demand_v7.prospective_core import when

UTC=timezone.utc
SOURCE_R2_SHA="39f61562803f3120bcda872b56f76a392989ed4e"
SOURCE_R2_GRID_SHA="6c65642c24d2b093cdeaf707dfe0da5d5339f5988e8643dabbde497a5cc51c28"
BRANCH="btc-v7r3-demand-stateful-challenger-20261012"
EVIDENCE="btc-v7r3-signed-pressure-evidence-20261013"
R2_EVIDENCE="btc-v7r2-prospective-evidence-20261013"
CYCLE=timedelta(minutes=15)
TICK_MIN=8
TICK_MAX=13
EPISODE_GAP_MINUTES=240
HORIZONS={"1h":60,"4h":240}
MIN_LEAD_LEVELS=(10,30,60)

def canonical(item):
    return (json.dumps(item,sort_keys=True,separators=(",",":"),allow_nan=False)+"\n").encode()

def digest(item):
    return hashlib.sha256(canonical(item)).hexdigest()

def slot_id(slot):
    return when(slot).strftime("%Y%m%dT%H%MZ")

def grid(start,created,model_sha,days=7):
    start=when(start);created=when(created)
    if not(1<=days<=14) or len(model_sha)!=40:
        raise ValueError("invalid preregistration")
    if start.minute%15 or start.second or start.microsecond:
        raise ValueError("15m grid alignment error")
    if start-created<timedelta(hours=2):
        raise ValueError("retroactive registration forbidden")
    slots=[]
    for i in range(days*96):
        origin=start+i*CYCLE
        slots.append({"slot_id":slot_id(origin),"anchor_utc":origin.isoformat(),
                      "decision_window_open_utc":(origin+timedelta(minutes=TICK_MIN)).isoformat(),
                      "decision_window_close_utc":(origin+timedelta(minutes=TICK_MAX)).isoformat()})
    return {
        "schema":"btc-v7r3-pressure-future-registration-v1",
        "registered_at_utc":created.isoformat(),
        "start_utc":start.isoformat(),
        "end_utc":(start+timedelta(days=days)).isoformat(),
        "model_source_sha":model_sha,"model_source_ref":"refs/heads/"+BRANCH,
        "r2_registered_source_sha":SOURCE_R2_SHA,
        "r2_grid_sha256":SOURCE_R2_GRID_SHA,
        "due_slots":slots,"days":days,"cadence_minutes":15,
        "min_issue_minutes_after_anchor":TICK_MIN,
        "max_issue_minutes_after_anchor":TICK_MAX,
        "source_required":["signed R2 forecast receipt","signed R2 raw spot 1m+5m",
                           "signed R2 current OKX OI","signed R2 current OKX top 10 book"],
        "forecast_warning_definition":"actual model-publication-time (NOT candle-open)",
        "price_reference_definition":"last completed 1m Binance spot as of actual publication",
        "outcomes":"UP_FIRST,DOWN_FIRST,NEITHER,AMBIGUOUS_SAME_MINUTE",
        "full_minute_after_publication_not_including_prior_part_of_minute":True,
        "threshold_up_down":{"1h":0.007,"4h":0.012},
        "minimum_lead_minutes_levels":MIN_LEAD_LEVELS,
        "max_raw_alerts_per_utc_day":1,
        "model_has_price_skill":False,
        "trading_authority":False,"no_retroactive_alert":True,
        "no_automatic_otc_order":True,
    }

def accept_slot(reg,slot,issued):
    expected={x["slot_id"]:x for x in reg["due_slots"]}
    key=slot_id(slot)
    if key not in expected:
        raise ValueError("not a preregistered slot")
    obj=expected[key]
    if when(obj["anchor_utc"])!=when(slot):
        raise ValueError("slot id alias")
    at=when(issued)
    if at<when(obj["decision_window_open_utc"]):
        return "NOT_YET_DUE"
    if at>when(obj["decision_window_close_utc"]):
        return "MISSED_DEADLINE"
    return "ON_TIME"

def future_anchor(issued):
    """First FULL minute after publication (no minute that started before it)."""
    at=when(issued)
    floor=at.replace(second=0,microsecond=0)
    return floor if floor==at else floor+timedelta(minutes=1)

def future_due(issued,horizon):
    if horizon not in HORIZONS:raise ValueError("unsupported event horizon")
    return future_anchor(issued)+timedelta(minutes=HORIZONS[horizon])

def status_grid(reg,event_items,as_of):
    now=when(as_of)
    observed={}
    for item in event_items:
        key=item["slot_id"]
        if key in observed:raise ValueError("duplicate signed state")
        observed[key]=item
    scheduled={i["slot_id"]:i for i in reg["due_slots"]}
    if not set(observed).issubset(scheduled):
        raise ValueError("unregistered extra evidence")
    due=0;correct=0;missed=0;no_source=0;warming=0;invalid=0;alert=0
    for item in reg["due_slots"]:
        if now<when(item["decision_window_close_utc"]):continue
        due+=1
        row=observed.get(item["slot_id"])
        if row is None or row.get("status")=="MISSED_DEADLINE":missed+=1;continue
        if row.get("status")=="MISSING_R2_SIGNED_INPUT":
            no_source+=1;continue
        if row.get("status") in ("INSUFFICIENT_ASOF_HISTORY","NO_OPTIONAL_OI_BOOK",
                                 "STATEFUL_CHAIN_DISCONTINUITY"):
            warming+=1;continue
        if row.get("status")=="SIGNED_STATE_PUBLISHED":
            correct+=1
            if row.get("diagnostic",{}).get("alert"):alert+=1
        else:invalid+=1
    return {"schema":"btc-v7r3-registered-slot-coverage-v1",
            "as_of_utc":now.isoformat(),"grid_sha256":digest(reg),
            "due":due,"on_time_signed_model_state":correct,
            "missing_slots":missed,"missing_r2_source":no_source,
            "warming_or_missing_factors":warming,"invalid":invalid,
            "signed_pre_move_alerts":alert,
            "admission_ready":False,"trading_authority":False}

def early_lead_report(warnings_with_outcomes):
    levels={k:{"correct_earlier":0,"false_alert":0} for k in MIN_LEAD_LEVELS}
    for r in warnings_with_outcomes:
        if not r.get("alert"):continue
        actual=r.get("first_touch_utc")
        side=r.get("warning_side")
        intended=r.get("actual_side")
        lead=(when(actual)-when(r["issued_utc"])).total_seconds()/60 if actual else None
        for k,obj in levels.items():
            if lead is not None and lead>=k and side==intended:
                obj["correct_earlier"]+=1
            else:
                obj["false_alert"]+=1
    return {"lead_levels_minutes":levels,
            "does_not_claim_early_detection_without_signed_future_outcomes":True,
            "admission_ready":False}
