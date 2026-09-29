from __future__ import annotations
import math
from datetime import datetime, timezone

UTC=timezone.utc
NAMES=(
"dxy_return_vs_prev_close_pct",
"nasdaq_return_vs_prev_close_pct",
"us10y_change_bp",
"funding_rate_bps",
"oi_change_1h_pct",
"etf_last_complete_flow_usd_m",
"tier1_event_inside_horizon",
"tier2_event_inside_horizon",
"minutes_to_next_tier1",
)

def _factor(snapshot,name):
    x=snapshot["factors"][name]
    if x.get("status")!="VALID": raise ValueError(name+" unavailable")
    return x

def _value_oi(x):
    if "value_btc" in x: return float(x["value_btc"])
    return float(x["value"])

def _ts(s):
    return datetime.fromisoformat(s.replace("Z","+00:00")).astimezone(UTC)

def vector(snapshot,previous_1h_snapshot,anchor_utc,horizon_hours):
    anchor=_ts(anchor_utc) if isinstance(anchor_utc,str) else anchor_utc.astimezone(UTC)
    dxy=_factor(snapshot,"dxy")
    nq=_factor(snapshot,"nasdaq_futures")
    y10=_factor(snapshot,"us10y")
    funding=_factor(snapshot,"funding")
    oi=_factor(snapshot,"open_interest")
    etf=_factor(snapshot,"etf_flows")
    poi=_factor(previous_1h_snapshot,"open_interest")
    if not dxy.get("previous_close") or not nq.get("previous_close") or y10.get("previous_close") is None:
        raise ValueError("missing external previous close")
    events=snapshot.get("calendar",{}).get("events",[])
    due=anchor.replace()+__import__("datetime").timedelta(hours=horizon_hours)
    tier1=[];tier2=[]
    for e in events:
        t=_ts(e["scheduled_utc"])
        if anchor<t<=due:
            if e.get("importance")=="TIER1": tier1.append((t,e))
            elif e.get("importance")=="TIER2": tier2.append((t,e))
    mins=horizon_hours*60.0
    next1=min(((t-anchor).total_seconds()/60.0 for t,_ in tier1),default=mins)
    vals=[
      100.0*(float(dxy["value"])/float(dxy["previous_close"])-1.0),
      100.0*(float(nq["value"])/float(nq["previous_close"])-1.0),
      100.0*(float(y10["value"])-float(y10["previous_close"])),
      10000.0*float(funding["value"]),
      100.0*(_value_oi(oi)/_value_oi(poi)-1.0),
      float(etf["numeric_value"]),
      1.0 if tier1 else 0.0,
      1.0 if tier2 else 0.0,
      max(0.0,min(mins,next1))/mins,
    ]
    if any(not math.isfinite(v) for v in vals): raise ValueError("non-finite exogenous feature")
    return dict(zip(NAMES,vals))
