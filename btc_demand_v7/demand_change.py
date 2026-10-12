"""Single preregistered *untrained* demand-positioning change-point challenger.

Uses ONLY signed prior/now 15m snapshots, robust median/MAD background,
and directional CUSUM. Does not claim probability or trading edge.
Missing book/OI or >20m gaps -> UNAVAILABLE, never fill with zero.
"""
from __future__ import annotations
from datetime import timedelta
from statistics import median
import math
from btc_demand_v7.prospective_core import when

MIN_BACKGROUND=32
MIN_EVENT_LEAD_MINUTES=60
MAX_GAP_MINUTES=20
CUSUM_DRIFT=1.0
CUSUM_THRESHOLD=8.0
Z_CLIP=5.0

def vector(snapshot):
    ob=snapshot["observation"]
    oi=ob.get("oi");book=ob.get("book")
    if not (isinstance(oi,dict) and isinstance(book,dict)):
        return None
    names=("15m_price_change_pct","15m_taker_buy_fraction",
           "15m_volume_vs_previous_1h_quarter")
    try:
        p,flow,ratio=(float(ob[name]) for name in names)
        oi_delta=float(oi["oi_change_15m_pct"])
        imbalance=float(book["top10_size_imbalance"])
        spread=float(book["spread_bps"])
    except (KeyError,TypeError,ValueError):return None
    if not all(math.isfinite(v) for v in (p,flow,ratio,oi_delta,imbalance,spread)):
        return None
    if not(0<=flow<=1 and ratio>0 and -1<=imbalance<=1 and spread>=0):
        return None
    return (p,2*flow-1,math.log(ratio),oi_delta,imbalance)

def robust_z(history,value):
    med=median(history)
    deviation=median([abs(x-med) for x in history])
    scale=max(1.4826*deviation,0.001)
    return max(-Z_CLIP,min(Z_CLIP,(value-med)/scale))

def estimate(snapshots,*,prior_up=0.,prior_down=0.):
    if len(snapshots)<MIN_BACKGROUND+1:
        return {"schema":"btc-v7r2-change-point-v1","state":"INSUFFICIENT_ASOF_HISTORY",
                "sample_count":len(snapshots),"calibrated_probability":False,
                "trading_authority":False}
    ordered=sorted(snapshots,key=lambda x:when(x["anchor_utc"]))
    last=ordered[-(MIN_BACKGROUND+1):]
    v=[vector(s) for s in last]
    if any(x is None for x in v):
        return {"schema":"btc-v7r2-change-point-v1",
                "state":"POSITIONING_OR_BOOK_UNAVAILABLE",
                "calibrated_probability":False,"trading_authority":False}
    gaps=[(when(last[i+1]["anchor_utc"])-when(last[i]["anchor_utc"])).total_seconds()/60
          for i in range(len(last)-1)]
    if any(g<5 or g>MAX_GAP_MINUTES for g in gaps):
        return {"schema":"btc-v7r2-change-point-v1",
                "state":"ASOF_HISTORY_GAP",
                "calibrated_probability":False,"trading_authority":False}
    history=v[:-1];now=v[-1]
    zs=[robust_z([h[i] for h in history],now[i]) for i in range(5)]
    # Signed market pressure is mirrored for UP and DOWN. Increased OI or
    # volume means participation, not mechanically bullish. OI is an
    # intensity term and cannot decide direction independently.
    participation=.4*max(0,zs[2])+.3*max(0,zs[3])
    up=max(0,float(prior_up)-CUSUM_DRIFT+max(0,zs[0])+max(0,zs[1])
           +.5*max(0,zs[4])+participation)
    down=max(0,float(prior_down)-CUSUM_DRIFT+max(0,-zs[0])+max(0,-zs[1])
             +.5*max(0,-zs[4])+participation)
    if up>CUSUM_THRESHOLD and down>CUSUM_THRESHOLD:
        status="AMBIGUOUS_BIDIRECTIONAL_PRESSURE"
    elif up>CUSUM_THRESHOLD:status="UNCALIBRATED_UP_SHIFT"
    elif down>CUSUM_THRESHOLD:status="UNCALIBRATED_DOWN_SHIFT"
    else:status="NO_UNCALIBRATED_SHIFT"
    return {"schema":"btc-v7r2-change-point-v1",
            "state":status,"anchor_utc":last[-1]["anchor_utc"],
            "z_price":zs[0],"z_taker_imbalance":zs[1],
            "z_volume":zs[2],"z_oi_change":zs[3],"z_book_imbalance":zs[4],
            "cusum_up":up,"cusum_down":down,
            "background_n":MIN_BACKGROUND,"minimum_actionable_lead_minutes":60,
            "warning_not_a_calibrated_probability":True,
            "trading_authority":False,"calibrated_probability":False}
