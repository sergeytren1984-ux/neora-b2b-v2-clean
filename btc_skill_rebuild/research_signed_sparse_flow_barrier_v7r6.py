"""First new-day signed R5 factor math against subsequent CLOSED 5m barriers.

No new deployed model. Contrasts three predeclared heuristic sign rules from
as-of signed R5 snapshots with separate later R5 fixed-candle first touches.
Quantifies missingness. Ex-post exploration, NOT prospective published alerts,
no true Cosign verification, no edge claims; one day only.
"""
from __future__ import annotations
import argparse,datetime as dt,json,math,pathlib,statistics
from btc_demand_v7.episode_quality_v4 import episodes_from_verified_barriers
UTC=dt.timezone.utc
HORIZONS={'1h':(60,.007),'4h':(240,.012)}
RULES=('two_binance_flows','microflow_okx_book','historic_flow_okx_book')
def parse(t):
    v=dt.datetime.fromisoformat(t.replace('Z','+00:00'))
    if v.utcoffset() is None:raise ValueError('naive date')
    return v.astimezone(UTC)
def sign(v):
    if v>0:return 'UP_FIRST'
    if v<0:return 'DOWN_FIRST'
    return None
def heuristic(ob):
    a=sign(ob['flow15']-.5);b=sign(ob['flow3']-.5);c=sign(ob['book'])
    return {'two_binance_flows':a if a==b else None,
            'microflow_okx_book':b if b==c else None,
            'historic_flow_okx_book':a if a==c else None}
def outcome(future_by_clock,issue,reference,horizon_minutes,threshold):
    if not math.isfinite(reference) or reference<=0:raise ValueError('invalid as-of price')
    when=[issue+dt.timedelta(minutes=5*i) for i in range(1,horizon_minutes//5+1)]
    if any(x not in future_by_clock for x in when):
        return {'mature':False,'side':None,'touch':None}
    upper=reference*(1+threshold);lower=reference*(1-threshold)
    for time in when:
        bar=future_by_clock[time]
        above=float(bar[2])>=upper
        below=float(bar[3])<=lower
        if above and below:
            return {'mature':True,'side':'AMBIGUOUS_SAME_5M','touch':time.isoformat()}
        if above:return {'mature':True,'side':'UP_FIRST','touch':time.isoformat()}
        if below:return {'mature':True,'side':'DOWN_FIRST','touch':time.isoformat()}
    return {'mature':True,'side':'NEITHER','touch':None}

def analyse(evidence,future):
    registered=evidence['predeclared_due_anchors'];observations=evidence['observed']
    if len(registered)!=len(set(registered)) or len(observations)!=len({e['slot'] for e in observations}):
        raise ValueError('duplicate anchor')
    valid=set(registered)
    if any(e['slot'] not in valid for e in observations):
        raise ValueError('off-grid sample')
    candles=future['bars']
    candle_end={dt.datetime.fromtimestamp((int(b[6])+1)/1000,UTC):b for b in candles}
    if len(candle_end)!=len(candles):raise ValueError('future duplicate bar')
    for bar in candles:
        start=int(bar[0]);end=int(bar[6])+1
        if end-start!=300000:raise ValueError('nonclosed bar')
    results={}
    for h,(window,threshold) in HORIZONS.items():
        rows=[]
        for obs in observations:
            issue=parse(obs['slot'])
            o=outcome(candle_end,issue,float(obs['price']),window,threshold)
            if not o['mature']:continue
            predicted=heuristic(obs)
            # Even a correct sign for an immediate touch is not an early warning.
            max_lead=(parse(o['touch'])-issue).total_seconds()/60 if o['touch'] else None
            rows.append({'slot_utc':obs['slot'],'source_blob':obs['blob'],
                         'independent_signed_evidence_cosign_unchecked':True,
                         'true_first_touch_or_neither':o['side'],
                         'touch_upper_bound_5m_close_utc':o['touch'],
                         'max_possible_60min_warning_after_hypothetical_8min_publication':bool(
                             max_lead is not None and max_lead-8>=60),
                         'raw_rule_directions_NOT_ACTUALLY_PUBLIC_FORECASTS':predicted})
        episode_rows=[]
        for row in rows:
            side=row['true_first_touch_or_neither']
            if side=='AMBIGUOUS_SAME_5M':side='AMBIGUOUS_SAME_MINUTE'
            close=row['touch_upper_bound_5m_close_utc']
            touch=(parse(close)-dt.timedelta(minutes=5)).isoformat() if close else None
            episode_rows.append({'slot_id':row['slot_utc'],'direction':side,
                                 'touch_open_utc':touch})
        episodes=episodes_from_verified_barriers(episode_rows)
        stats={}
        for key in RULES:
            candidate=[x for x in rows if x['raw_rule_directions_NOT_ACTUALLY_PUBLIC_FORECASTS'][key]]
            correct=[x for x in candidate if
                x['raw_rule_directions_NOT_ACTUALLY_PUBLIC_FORECASTS'][key]==x['true_first_touch_or_neither']]
            false=[x for x in candidate if x not in correct]
            matched_episode_count=sum(any(
                member['slot_id']==row['slot_utc']
                for row in correct for member in ep['members']) for ep in episodes)
            stats[key]={'matched_distinct_240m_first_touch_clusters_EX_POST':matched_episode_count,
                'historically_heuristic_directions_not_real_alerts':len(candidate),
                'same_direction_first_touch_rows':len(correct),
                'wrong_or_neither_or_ambiguous_rows':len(false),
                'same_direction_and_possible_60min_lead_assuming_8min_delivery':sum(
                    x['max_possible_60min_warning_after_hypothetical_8min_publication'] for x in correct),
                'independent_event_count_NOT_established':True,
                'precision_unknown_on_new_prospective_future':True}
        classes={x:sum(row['true_first_touch_or_neither']==x for row in rows)
                    for x in ('UP_FIRST','DOWN_FIRST','NEITHER','AMBIGUOUS_SAME_5M')}
        results[h]={'due_slots':len(registered),'asof_published_R5_samples':len(observations),
            'missing_R5_samples_full_due_denominator':len(registered)-len(observations),
            'fully_matured_before_last_signed_snapshot':len(rows),
            'outcome_counts':classes,
            'conservatively_clustered_240m_distinct_first_touch_episodes':len(episodes),
            'future_episode_clustering_EX_POST_not_public_forecast':True,
            'asof_rule_exploratory_score_not_prospective':stats,
            'matched_rows':rows}
        print('SIGNED_FIRST_NIGHT',h,'matured',len(rows),'missing',len(registered)-len(observations),
              'truth',classes)
        for k,v in stats.items():print(' ',k,v)
    return {'schema':'btc-v7r6-asof-factor-vs-closed-first-touch-sparse-night-research-v1',
       'outcome_R5_future_blob':future['source_snapshot_git_blob_sha'],
       'all_samples_later_known_NO_prospective_policy_publication':True,
       'R5_sample_blobs_not_cosign_verified':True,
       'due_slots_include_missing':True,'trading_authority':False,
       'horizons':results}
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--samples',required=True);p.add_argument('--future',required=True);p.add_argument('--out',required=True)
    a=p.parse_args()
    v=analyse(json.load(open(a.samples)),json.load(open(a.future)))
    pathlib.Path(a.out).write_text(json.dumps(v,sort_keys=True,indent=2,allow_nan=False)+'\n')
