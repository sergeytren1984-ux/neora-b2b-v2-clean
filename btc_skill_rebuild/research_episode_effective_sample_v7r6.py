"""Estimate effective independent event count behind overlapping barrier labels.

No training or prediction, just mathematical guardrails. A first touch can
appear as 4/16 separate correct 15m window labels for 1h/4h, respectively.
Inspect events by TRUE first touch UTC, not by time forecast was issued.
Optional episode merging by horizon makes conservative clustered denominator.
"""
from __future__ import annotations
import datetime as dt,gzip,json,pathlib,statistics,hashlib,argparse
from btc_skill_rebuild.research_execution_drift_v7r6 import STEP
from btc_skill_rebuild.research_competing_barriers_v7r6 import labels,HORIZONS
from btc_skill_rebuild.research_walkforward_barriers_v7r6 import FOLDS,UTC


def grouped_episodes(events,range_ms):
    """Group directional first-touches causally by side and consecutive spacing.

    Different sides are different episodes regardless of overlapping times.
    Return only summary: no future input in any of the model's features.
    """
    clusters=[]
    sorted_events=sorted(set(events),key=lambda e:(e[0],e[1]))
    for touch,side in sorted_events:
        matches=[c for c in clusters if c['side']==side
                 and 0<=touch-c['last_touch_ms']<=range_ms]
        if matches:
            c=matches[-1];c['last_touch_ms']=touch;c['distinct_touches']+=1
        else:clusters.append({'side':side,'first_touch_ms':touch,'last_touch_ms':touch,
                              'distinct_touches':1})
    return clusters


def tally(rows):
    first=int(rows[0][0]);last=int(rows[-1][0])+STEP
    for a,b in zip(rows,rows[1:]):
        if int(b[0])-int(a[0])!=STEP:raise ValueError('historical 5m grid has gaps')
    result={}
    for h,(n,barrier) in HORIZONS.items():
        slices=[]
        for start in FOLDS:
            begin=int(start.timestamp()*1000);end=begin+7*86400000
            lasttouch=[];predictive_slots=0;none=ambiguous=directional_windows=0
            for i in range(289,len(rows)-n):
                at=int(rows[i][0])+STEP
                if at%(15*60000) or at<begin or at>=end:continue
                label,idx=labels(rows,i,n,barrier)
                predictive_slots+=1
                if label in (0,1):
                    directional_windows+=1
                    lasttouch.append((int(rows[idx][0]),label))
                elif label==2:none+=1
                else:ambiguous+=1
            touchset=set(lasttouch)
            episodes=grouped_episodes(touchset,n*STEP)
            slices.append({'test_week_utc':start.date().isoformat(),
                'full_due_15m_slots':predictive_slots,
                'directionally_resolved_slot_labels':directional_windows,
                'distinct_exact_minute_directional_first_touches':len(touchset),
                'conservative_nonoverlapping_directional_episodes':len(episodes),
                'no_barrier_labels':none,'ambiguous_same_5m_bar_labels':ambiguous,
                'unique_UP_episodes':sum(c['side']==0 for c in episodes),
                'unique_DOWN_episodes':sum(c['side']==1 for c in episodes),
                'window_count_overstates_episode_count_ratio':directional_windows/max(1,len(episodes))})
        result[h]={'weekly':slices,
             'n_independent_calendar_day_blocks':28,
             'total_15m_windows':sum(x['full_due_15m_slots'] for x in slices),
             'total_directional_window_labels':sum(x['directionally_resolved_slot_labels'] for x in slices),
             'total_unique_first_touch_timestamp_directions':sum(x['distinct_exact_minute_directional_first_touches'] for x in slices),
             'sum_weekly_conservative_event_episodes':sum(x['conservative_nonoverlapping_directional_episodes'] for x in slices)}
    return {'schema':'btc-v7r6-event-episode-effective-sample-v1',
            'not_a_predictive_model_or_live_signal':True,
            'first_touch_5m_candle_ambiguity_preserved':True,
            'forecast_windows_are_not_independent_events':True,
            'only_historical_already_seen':True,'trading_authority':False,'horizons':result}


def run(raw,out):
    with gzip.open(raw,'rt') as f:rows=json.load(f)
    result=tally(rows)
    result['raw_gzip_sha256']=hashlib.sha256(pathlib.Path(raw).read_bytes()).hexdigest()
    pathlib.Path(out).write_text(json.dumps(result,indent=2,sort_keys=True,allow_nan=False)+'\n')
    for h,v in result['horizons'].items():
        print('EFFECTIVE_EVENT_SAMPLE',h,'windows',v['total_15m_windows'],
             'directional_labels',v['total_directional_window_labels'],
             'unique_first_touch_timestamps',v['total_unique_first_touch_timestamp_directions'],
             'conservative_episodes',v['sum_weekly_conservative_event_episodes'],flush=True)
    return result
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--raw',required=True);p.add_argument('--out',required=True)
    x=p.parse_args();run(x.raw,x.out)
