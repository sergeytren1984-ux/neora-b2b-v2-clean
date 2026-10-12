"""Research-only event-count sensitivity; never alters frozen forecasts.

Global single-linkage can chain first-touches farther than a full horizon.
A fixed-first-touch-span count is a second PREDECLARED diagnostic, not a
new tuned episode threshold. Neither count proves event independence.
"""
from btc_skill_rebuild.research_global_event_dedup_v7r6 import grouped_episodes

def fixed_span_episodes(events,horizon_ms):
    if type(horizon_ms) is not int or horizon_ms<=0:
        raise ValueError("invalid horizon")
    unique=set()
    for item in events:
        if not isinstance(item,tuple) or len(item)!=2:
            raise ValueError("invalid event tuple")
        t,side=item
        if type(t) is not int or t<0 or type(side) is not int or side not in (0,1):
            raise ValueError("invalid first-touch")
        unique.add(item)
    clusters=[]
    for t,side in sorted(unique):
        old=next((c for c in reversed(clusters) if c["side"]==side),None)
        if old is not None and 0<=t-old["first_touch_ms"]<=horizon_ms:
            old["last_touch_ms"]=t
            old["distinct_touches"]+=1
        else:
            clusters.append({"side":side,"first_touch_ms":t,
                             "last_touch_ms":t,"distinct_touches":1})
    return clusters

def compare_partition_counts(events,horizon_ms):
    unique=set(events)
    linked=grouped_episodes(unique,horizon_ms)
    fixed=fixed_span_episodes(unique,horizon_ms)
    if len(linked)>len(fixed):
        raise AssertionError("fixed span cannot merge more than single linkage")
    return {"unique_first_touches":len(unique),
            "single_linkage_episodes":len(linked),
            "fixed_span_episodes":len(fixed),
            "max_single_linkage_span_minutes":max(
                ((c["last_touch_ms"]-c["first_touch_ms"])/60000
                 for c in linked),default=0),
            "max_fixed_span_minutes":max(
                ((c["last_touch_ms"]-c["first_touch_ms"])/60000
                 for c in fixed),default=0),
            "not_proof_of_independent_events":True,
            "not_forecast_skill_or_trade_admission":True,
            "trading_authority":False}
