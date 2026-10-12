"""Count directional first-touch episodes across week boundaries; research only."""

def grouped_episodes(events, horizon_ms):
    if not isinstance(horizon_ms, int) or horizon_ms <= 0:
        raise ValueError("invalid horizon")
    clusters=[]
    for touch, side in sorted(set(events), key=lambda e:(e[0],e[1])):
        if not isinstance(touch,int) or touch<0 or side not in (0,1):
            raise ValueError("invalid event")
        matches=[c for c in clusters if c["side"]==side
                 and 0<=touch-c["last_touch_ms"]<=horizon_ms]
        if matches:
            c=matches[-1]
            c["last_touch_ms"]=touch
            c["distinct_touches"]+=1
        else:
            clusters.append({"side":side,"first_touch_ms":touch,
                             "last_touch_ms":touch,"distinct_touches":1})
    return clusters

def global_event_summary(weekly_events, horizon_ms):
    weeks=[list(week) for week in weekly_events]
    unique=set(event for week in weeks for event in week)
    global_clusters=grouped_episodes(unique,horizon_ms)
    weekly_unique=sum(len(set(week)) for week in weeks)
    weekly_clusters=sum(len(grouped_episodes(week,horizon_ms)) for week in weeks)
    return {
        "globally_unique_first_touch_timestamp_directions":len(unique),
        "duplicate_first_touches_across_weeks":weekly_unique-len(unique),
        "globally_horizon_clustered_directional_episodes":len(global_clusters),
        "excess_weekly_episodes_due_to_boundary_splits":weekly_clusters-len(global_clusters),
        "global_up_episodes":sum(c["side"]==0 for c in global_clusters),
        "global_down_episodes":sum(c["side"]==1 for c in global_clusters),
        "trading_authority":False,
    }
