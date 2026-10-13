"""Conservative dependence audit for BTC v7R6 directional first-touch events.

Historical research only. UP and DOWN touches in the same minute or within
a single forecast horizon are NOT independent market episodes. Existing
side-specific grouping counts them separately. This is not a new predictor,
does not change frozen outcomes, and cannot authorize trading.
"""
from __future__ import annotations

def market_episodes(events, horizon_ms):
    """Transitive side-agnostic clustering of first touches in milliseconds."""
    if not isinstance(horizon_ms,int) or isinstance(horizon_ms,bool) or horizon_ms<=0:
        raise ValueError('invalid forecast horizon')
    distinct=set()
    for event in events:
        if not isinstance(event,(tuple,list)) or len(event)!=2:
            raise ValueError('invalid first-touch pair')
        t,side=event
        if (not isinstance(t,int) or isinstance(t,bool) or t<0 or
            type(side) is not int or side not in (0,1)):
            raise ValueError('invalid first-touch timestamp or side')
        distinct.add((t,side))
    episodes=[]
    for t,side in sorted(distinct):
        if episodes and t-episodes[-1]['last_touch_ms']<=horizon_ms:
            e=episodes[-1]
            e['last_touch_ms']=t
            e['distinct_touch_timestamp_directions']+=1
            e['directions'].add(side)
        else:
            episodes.append({'first_touch_ms':t,'last_touch_ms':t,
                             'distinct_touch_timestamp_directions':1,
                             'directions':{side}})
    return [{**e,'directions':sorted(e['directions']),
             'mixed_up_down':len(e['directions'])>1,
             'span_ms':e['last_touch_ms']-e['first_touch_ms']}
            for e in episodes]

def compare_episode_independence(weekly_events,horizon_ms):
    """Report both old directional count and stricter market independence."""
    from btc_skill_rebuild.research_global_event_dedup_v7r6 import grouped_episodes
    weeks=[list(week) for week in weekly_events]
    events=set(e for week in weeks for e in week)
    directional=grouped_episodes(events,horizon_ms)
    market=market_episodes(events,horizon_ms)
    if len(market)>len(directional):
        raise AssertionError('market episodes cannot exceed side-specific episodes')
    return {
        'distinct_first_touch_timestamp_direction_pairs':len(events),
        'existing_side_specific_directional_episode_count':len(directional),
        'conservative_cross_side_market_episode_count':len(market),
        'directional_episode_count_overstatement':len(directional)-len(market),
        'cross_side_mixed_episodes':sum(e['mixed_up_down'] for e in market),
        'cross_side_mixed_event_tuples':sum(e['distinct_touch_timestamp_directions']
                                             for e in market if e['mixed_up_down']),
        'max_market_episode_span_ms':max((e['span_ms'] for e in market),default=0),
        'boundary_dedup_global':True,
        'known_historical_research_only':True,
        'raw_5m_archive_recomputed':False,
        'trading_authority':False,
    }
