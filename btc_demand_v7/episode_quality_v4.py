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
    for e in verified_events:
        side=e["direction"]
        if side in ("NEITHER","AMBIGUOUS_SAME_MINUTE"):
            continue
        if side not in ("UP_FIRST","DOWN_FIRST"):
            raise ValueError("unknown verified barrier direction")
        if not e.get("touch_open_utc"):
            raise ValueError("touch timestamp absent")
        touch=when(e["touch_open_utc"])
        inputs.append((touch,side,e["slot_id"]))
    inputs.sort()
    items=[]
    seen=set()
    for touch,side,sid in inputs:
        if sid in seen:raise ValueError("duplicate signed slot, including conflicting directions")
        seen.add(sid)
        last=next((x for x in reversed(items) if x["side"]==side),None)
        if last is not None and touch-when(last["last_member_touch_utc"])<timedelta(minutes=gap_minutes):
            last["member_windows"]+=1
            last["last_member_touch_utc"]=touch.isoformat()
            continue
        items.append({"side":side,"first_touch_utc":touch.isoformat(),
                      "last_member_touch_utc":touch.isoformat(),
                      "member_windows":1})
    return sorted(items,key=lambda x:x["first_touch_utc"])

def report(horizon, verified_outcomes, verified_alerts, *,full_due_count,
           missing_or_late_count):
    if horizon not in ("1h","4h"):raise ValueError("invalid horizon")
    minutes={"1h":60,"4h":240}[horizon]
    if (not isinstance(full_due_count,int) or not isinstance(missing_or_late_count,int)
        or full_due_count<0 or not 0<=missing_or_late_count<=full_due_count
        or len(verified_outcomes)>full_due_count):
        raise ValueError("invalid fixed-grid denominators")
    episodes=episodes_from_verified_barriers(verified_outcomes)
    unique_alerts={}
    for a in verified_alerts:
        sid=a["slot_id"]
        if sid in unique_alerts:raise ValueError("duplicate verified public alert")
        if a["side"] not in ("UP_FIRST","DOWN_FIRST"):raise ValueError("invalid alarm direction")
        unique_alerts[sid]=a
    alerts=list(unique_alerts.values())
    by_lead={}
    for cutoff in LEAD_THRESHOLDS:
        matched_episodes=0
        for event in episodes:
            time=when(event["first_touch_utc"])
            candidates=[a for a in alerts
                if a.get("eligible") is True
                and a["side"]==event["side"]
                and cutoff<=(time-when(a["public_delivery_utc"])).total_seconds()/60<=minutes]
            if candidates:matched_episodes+=1
        matched_alerts=0
        for alert in alerts:
            issued=when(alert["public_delivery_utc"])
            if alert.get("eligible") is not True:continue
            if any(e["side"]==alert["side"] and
                   cutoff<=(when(e["first_touch_utc"])-issued).total_seconds()/60<=minutes
                   for e in episodes):
                matched_alerts+=1
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
            "n_frozen_grid_due":int(full_due_count),
            "n_missing_or_late":int(missing_or_late_count),
            "partial_coverage":bool(missing_or_late_count),
            "minute_open_lower_bound_used":True,
            "cluster_gap_minutes":GAP_MINUTES,
            "unique_verified_episodes":episodes,
            "conservative_lead_minutes":by_lead,
            "prospective_skill_proven":False,
            "trading_authority":False}
