"""Pre-registered symmetric event semantics for BTC prospectively collected 1m.

For each endpoint independent symmetrical +/- barriers. Same-minute double
touch is AMBIGUOUS; not a fabricated order. Event-level clusters separated
by >=4h; overlapping 15m predictions NEVER count as independent episodes.
"""
from __future__ import annotations
from datetime import datetime,timedelta,timezone
import math
from btc_demand_v7.prospective_core import when

BARRIERS={"30m":(30,0.0045),"1h":(60,0.007),"4h":(240,0.012)}
CLUSTER_GAP_MINUTES=240
MIN_ACTIONABLE_WARNING_LEAD_MINUTES=60

def first_passage(anchor,spot,rows,horizon):
    if horizon not in BARRIERS:raise ValueError("unknown event horizon")
    if not(math.isfinite(float(spot)) and float(spot)>0):
        raise ValueError("invalid reference spot")
    minutes,threshold=BARRIERS[horizon]
    first=when(anchor)
    if len(rows)!=minutes:raise ValueError("incomplete forward raw minute grid")
    upper=spot*(1+threshold);lower=spot*(1-threshold)
    winner="NEITHER";hit_at=None
    for n,row in enumerate(rows,1):
        expect=first+timedelta(minutes=n)
        close=datetime.fromtimestamp((int(row[6])+1)/1000,timezone.utc)
        if close!=expect or int(row[0])+60000!=int(row[6])+1:
            raise ValueError("future candles have gap/future timestamp")
        h=float(row[2]);l=float(row[3]);o=float(row[1]);c=float(row[4])
        if not all(math.isfinite(x) for x in (h,l,o,c)) or not (0<l<=min(o,c)<=max(o,c)<=h):
            raise ValueError("invalid outcome OHLC")
        touched_up=h>=upper;touched_down=l<=lower
        if winner=="NEITHER" and (touched_up or touched_down):
            if touched_up and touched_down:
                winner="AMBIGUOUS_SAME_MINUTE"
            elif touched_up:
                winner="UP_FIRST"
            else:
                winner="DOWN_FIRST"
            hit_at=close.isoformat()
    return {"schema":"btc-v7r2-symmetric-first-passage-v1",
            "anchor_utc":first.isoformat(),"horizon":horizon,
            "target_utc":(first+timedelta(minutes=minutes)).isoformat(),
            "reference_spot":float(spot),"upper":upper,"lower":lower,
            "direction":winner,"first_barrier_touch_utc":hit_at,
            "resolution_seconds":60,"independent_event_counted":False}

def clustered_episodes(records,*,minimum_gap_minutes=CLUSTER_GAP_MINUTES):
    # Actual future events, not overlapping windows; cluster by first-touch time.
    events=[]
    for r in records:
        if r["direction"] not in ("UP_FIRST","DOWN_FIRST"):continue
        touch=when(r["first_barrier_touch_utc"])
        events.append((touch,r))
    events.sort(key=lambda x:x[0])
    clusters=[];last=None
    for touch,item in events:
        if last is None or touch-last>=timedelta(minutes=minimum_gap_minutes):
            clusters.append({"episode_first_touch_utc":touch.isoformat(),
                             "direction":item["direction"],
                             "episode_member_count":1})
            last=touch
        else:
            clusters[-1]["episode_member_count"]+=1
    return clusters

def warning_lead_minutes(event_touch,alert_issued):
    touched=when(event_touch);alert=when(alert_issued)
    if alert>=touched:return None
    return (touched-alert).total_seconds()/60

def validate_alert_budget(alerts,*,max_per_day=1):
    """Deduplicated alert budget per UTC day; include all rejected/false alerts."""
    unique=set();day_counts={}
    for x in alerts:
        when_issued=when(x["issued_utc"])
        key=x["alert_id"]
        if key in unique:raise ValueError("duplicate alert id")
        unique.add(key)
        day=when_issued.date().isoformat()
        day_counts[day]=day_counts.get(day,0)+1
    return {"per_day":day_counts,
            "max_pre_registered_alerts_per_day":max_per_day,
            "within_budget":all(v<=max_per_day for v in day_counts.values())}
