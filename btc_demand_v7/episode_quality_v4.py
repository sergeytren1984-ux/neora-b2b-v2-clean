"""One-detector prospective episode scorer, never retrospective training.

Only independently VERIFIED signed R4 first-touch outcomes enter this module.
Duplicate overlapping 15m forecasts cannot become independent observations.
Events with missing outcome windows cannot support recall or trading admission.
"""
from __future__ import annotations
from datetime import timedelta
from btc_demand_v7.prospective_core import when

GAP_MINUTES=240
LEAD_THRESHOLDS=(10,30,60)

def episodes_from_verified_barriers(verified_events, *,gap_minutes=GAP_MINUTES):
    """Return directionally clustered verified first-passage episodes.

    Minute-open is the EARLIEST possible touch and thus the conservative
    warning lead. Every source row must be signed and independently rederived.
    """
    if not isinstance(gap_minutes,int) or gap_minutes<=0:
        raise ValueError("cluster gap must be positive whole minutes")
    inputs=[]
    seen_slots=set()
    for e in verified_events:
        sid=e["slot_id"]
        if sid in seen_slots:
            raise ValueError("duplicate verified slot, even when first touch absent")
        seen_slots.add(sid)
        side=e["direction"]
        if side in ("NEITHER","AMBIGUOUS_SAME_MINUTE"):
            if e.get("touch_open_utc") is not None:
                raise ValueError("no valid first-touch time for neither/ambiguous outcome")
            continue
        if side not in ("UP_FIRST","DOWN_FIRST"):
            raise ValueError("unknown verified barrier direction")
        if not e.get("touch_open_utc"):
            raise ValueError("touch timestamp absent")
        touch=when(e["touch_open_utc"])
        inputs.append((touch,side,e["slot_id"]))
    inputs.sort()
    items=[]
    for touch,side,sid in inputs:
        last=next((x for x in reversed(items) if x["side"]==side),None)
        if last is not None and touch-when(last["last_member_touch_utc"])<timedelta(minutes=gap_minutes):
            last["member_windows"]+=1
            last["last_member_touch_utc"]=touch.isoformat()
            last["members"].append({"slot_id":sid,"touch_open_utc":touch.isoformat()})
            continue
        items.append({"side":side,"first_touch_utc":touch.isoformat(),
                      "last_member_touch_utc":touch.isoformat(),
                      "member_windows":1,
                      "members":[{"slot_id":sid,"touch_open_utc":touch.isoformat()}]})
    return sorted(items,key=lambda x:x["first_touch_utc"])

def report(horizon, verified_outcomes, verified_alerts, *,full_due_count,
           missing_or_late_count):
    if horizon not in ("1h","4h"):raise ValueError("invalid horizon")
    minutes={"1h":60,"4h":240}[horizon]
    if (not isinstance(full_due_count,int) or not isinstance(missing_or_late_count,int)
        or full_due_count<0 or not 0<=missing_or_late_count<=full_due_count
        or len(verified_outcomes)+missing_or_late_count!=full_due_count):
        raise ValueError("full mature grid mismatch: every resolved NEITHER also counts")
    episodes=episodes_from_verified_barriers(verified_outcomes)
    outcome_index={e["slot_id"]:e for e in verified_outcomes}
    unique_alerts={}
    for a in verified_alerts:
        sid=a["slot_id"]
        if sid in unique_alerts:raise ValueError("duplicate verified public alert")
        if a["side"] not in ("UP_FIRST","DOWN_FIRST"):raise ValueError("invalid alarm direction")
        unique_alerts[sid]=a
    alerts=list(unique_alerts.values())
    by_lead={}
    for cutoff in LEAD_THRESHOLDS:
        # An event is a cluster of overlapping forecasts, but an alert may
        # ONLY match the verified first touch of its OWN frozen slot. A nearby
        # same-side event with a different price barrier is not evidence.
        matched_slots=set()
        for alert in alerts:
            if alert.get("eligible") is not True:
                continue
            result=outcome_index.get(alert["slot_id"])
            if result is None or result["direction"]!=alert["side"]:
                continue
            if result["direction"] not in ("UP_FIRST","DOWN_FIRST"):
                continue
            issued=when(alert["public_delivery_utc"])
            lead=(when(result["touch_open_utc"])-issued).total_seconds()/60
            if cutoff<=lead<=minutes:
                matched_slots.add(alert["slot_id"])
        matched_alerts=len(matched_slots)
        matched_episodes=sum(any(m["slot_id"] in matched_slots
                                 for m in ep["members"]) for ep in episodes)
        by_lead[str(cutoff)]={
            "verified_distinct_episodes_matched":matched_episodes,
            "verified_alerts_matched":matched_alerts,
            "verified_alerts_without_matching_episode":len(alerts)-matched_alerts,
            "observed_episode_recall":(matched_episodes/len(episodes) if episodes else None),
            "observed_alert_precision":(matched_alerts/len(alerts) if alerts else None),
        }
    return {"schema":"btc-v7r4-verified-independent-episode-score-v1",
            "horizon":horizon,
            "n_verified_nonoverlapping_episodes":len(episodes),
            "n_verified_public_alerts":len(alerts),
            "n_verified_resolved_including_neither":len(verified_outcomes),
            "n_dedicated_unmatched_due":missing_or_late_count,
            "alert_matching":"exact_forecast_slot_id_only_no_cross_window_credit",
            "otc_60min_lead_unattainable_within_1h_event_horizon":horizon=="1h",
            "n_frozen_grid_due":int(full_due_count),
            "n_missing_or_late":int(missing_or_late_count),
            "partial_coverage":bool(missing_or_late_count),
            "minute_open_lower_bound_used":True,
            "cluster_gap_minutes":GAP_MINUTES,
            "unique_verified_episodes":episodes,
            "conservative_lead_minutes":by_lead,
            "prospective_skill_proven":False,
            "trading_authority":False}

[executed on device: MacBook-Air-Sergey.local (ec25f5e8-4047-48da-b895-a85c27d563ae)]