"""Exact daily-block inference on frozen research-only prospective scores.

Never convert missing HH00 forecasts into retrospective predictions.
Never treat 15-minute overlapping windows as independent.
"""
from datetime import datetime, timedelta, timezone
from itertools import product
from math import comb, isfinite

UTC=timezone.utc
START=datetime(2026,10,13,tzinfo=UTC)

def as_utc(value):
    if isinstance(value,str):
        value=datetime.fromisoformat(value.replace("Z","+00:00"))
    if value.tzinfo is None:
        raise ValueError("naive timestamp")
    return value.astimezone(UTC)

def due_grid(asof,horizon=0):
    t=as_utc(asof)
    if horizon not in (0,1,4,24):
        raise ValueError("unknown horizon")
    n=max(0,int(((t-timedelta(hours=horizon))-START).total_seconds()//3600)+1)
    return tuple(START+timedelta(hours=i) for i in range(n))

def sign_flip_one_sided_p(day_means):
    if not 1<=len(day_means)<=20 or not all(isfinite(x) for x in day_means):
        raise ValueError("unsupported or invalid independent day sample")
    target=sum(day_means)
    return sum(sum(s*x for s,x in zip(signs,day_means))>=target-1e-13
               for signs in product((-1,1),repeat=len(day_means)))/2**len(day_means)

def exact_sign_one_sided_p(day_means):
    n=len(day_means)
    if not n or not all(isfinite(x) for x in day_means):
        raise ValueError("invalid independent day sample")
    positives=sum(x>0 for x in day_means)
    return sum(comb(n,k) for k in range(positives,n+1))/2**n

def audit(asof,published,scored):
    grid=set(due_grid(asof))
    published=tuple(as_utc(x) for x in published)
    if len(published)!=len(set(published)) or not set(published)<=grid:
        raise ValueError("duplicate or invalid published slot")
    counted=set()
    by_day={}
    horizons=(1,4,24)
    for stamp,horizon,gain in scored:
        stamp=as_utc(stamp)
        if (stamp,horizon) in counted or horizon not in horizons:
            raise ValueError("duplicate/unknown score")
        counted.add((stamp,horizon))
        if stamp not in published or stamp not in due_grid(asof,horizon):
            raise ValueError("late or unregistered score")
        if not isfinite(gain) or not -1<=gain<=1:
            raise ValueError("invalid normalized Brier improvement")
        if horizon==1:
            by_day.setdefault(stamp.date().isoformat(),[]).append(gain)
    means=[sum(v)/len(v) for _,v in sorted(by_day.items())]
    return {
        "due_HH00":len(grid),
        "published_HH00":len(published),
        "missing_HH00":len(grid)-len(published),
        "matured_due":{str(h):len(due_grid(asof,h)) for h in horizons},
        "matured_published_scored":{str(h):sum(y==h for _,y in counted) for h in horizons},
        "independent_1h_day_blocks":len(means),
        "equal_day_1h_Brier_gain":sum(means)/len(means) if means else None,
        "one_sided_exact_sign_p":exact_sign_one_sided_p(means) if means else None,
        "one_sided_exact_sign_flip_p_conditional_on_symmetry":sign_flip_one_sided_p(means) if means else None,
        "minimum_20_independent_day_blocks_met":len(means)>=20,
        "trading_authority":False,
    }
