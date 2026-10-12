"""v7R6 research: strict 60-minute forewarning attainable-set upper bound.

No model fitting or hindsight-chosen warnings. Same frozen historical 5m
first-touch outcomes from v7R6 labels and 4 predefined historical weeks.
At every fixed decision point, hypothetically assume PERFECT direction and
compute how many historical UP_FIRST/DOWN_FIRST outcomes could possibly
have >=60m public-delivery lead for given publication delays.

Five-minute OHLC lacks intrabar hit time. Report BOTH best-case (hit at
candle END) and guaranteed worst-case (hit at candle OPEN). This is a
physical deadline ceiling, not directional skill or an actual forecast.
"""
from __future__ import annotations
import argparse,datetime as dt,gzip,hashlib,json,pathlib
from btc_skill_rebuild.research_execution_drift_v7r6 import STEP
from btc_skill_rebuild.research_competing_barriers_v7r6 import HORIZONS,labels
from btc_skill_rebuild.research_walkforward_barriers_v7r6 import FOLDS,UTC

DELIVERY_DELAY_MIN=(0,3,8,13)
MINIMUM_WARNING_LEAD_MIN=60

def clock_feasibility(slot_ms,touch_bar_start_ms,public_delay_minutes,window_ms):
    if public_delay_minutes<0 or window_ms<=0 or touch_bar_start_ms<slot_ms:
        raise ValueError('invalid future first-touch timing')
    if touch_bar_start_ms>=slot_ms+window_ms:
        raise ValueError('touch outside registered outcome horizon')
    public=slot_ms+public_delay_minutes*60000
    earliest_touch=touch_bar_start_ms
    latest_touch=touch_bar_start_ms+STEP
    minimum=MINIMUM_WARNING_LEAD_MIN*60000
    return {
      'possible_ge_60m_even_perfect_direction':(latest_touch-public)>=minimum,
      'guaranteed_ge_60m_any_intrabar_touch':(earliest_touch-public)>=minimum,
      'possible_positive_lead':latest_touch>public,
      'guaranteed_positive_lead':earliest_touch>public,
      'best_possible_lead_minutes':(latest_touch-public)/60000,
      'worst_possible_lead_minutes':(earliest_touch-public)/60000,
    }

def evaluate(rows):
    assert len(rows)>=10000
    end_ms=int(rows[-1][0])+STEP
    results={}
    for h,(n,barrier) in HORIZONS.items():
        sub={}
        for sample_type in ('every_15min_due','predeclared_nonoverlapping_due'):
            count=0;actual_wins=0;ambiguous=0;none=0
            by_delay={str(lag):{'possible_60m_warnings_even_oracle_direction':0,
                               'guaranteed_60m_warnings_even_oracle_direction':0,
                               'positive_lead_possible':0,
                               'positive_lead_guaranteed':0} for lag in DELIVERY_DELAY_MIN}
            for start in FOLDS:
                day0=int(start.timestamp()*1000);end=day0+7*86400000
                for i in range(300,len(rows)-n):
                    slot=int(rows[i][0])+STEP
                    if not day0<=slot<end or slot%(15*60000):continue
                    if sample_type=='predeclared_nonoverlapping_due' and slot%(n*STEP):continue
                    due=int(rows[i+n][0])+STEP
                    if due>end_ms:continue
                    count+=1
                    side,first_hit=labels(rows,i,n,barrier)
                    if side==2:none+=1;continue
                    if side==3:ambiguous+=1;continue
                    actual_wins+=1
                    hit=int(rows[first_hit][0])
                    for lag in DELIVERY_DELAY_MIN:
                        calc=clock_feasibility(slot,hit,lag,n*STEP)
                        v=by_delay[str(lag)]
                        v['possible_60m_warnings_even_oracle_direction']+=int(calc['possible_ge_60m_even_perfect_direction'])
                        v['guaranteed_60m_warnings_even_oracle_direction']+=int(calc['guaranteed_ge_60m_any_intrabar_touch'])
                        v['positive_lead_possible']+=int(calc['possible_positive_lead'])
                        v['positive_lead_guaranteed']+=int(calc['guaranteed_positive_lead'])
            for lag,v in by_delay.items():
                v['resolved_first_touch_outcomes']=actual_wins
                v['earliest_possible_oracle_recall_60m_upper_bound']=(
                  v['possible_60m_warnings_even_oracle_direction']/actual_wins if actual_wins else None)
                v['unavoidably_earlier_than_60m_deadline_count']=(
                  actual_wins-v['possible_60m_warnings_even_oracle_direction'])
            sub[sample_type]={'predefined_due_count':count,
                'resolved_directional_outcomes':actual_wins,
                'neither_outcomes':none,'ambiguous_same_5m_candle':ambiguous,
                'by_assumed_public_delivery_lag_minutes':by_delay}
            assert count==actual_wins+none+ambiguous
            print('PHYSICAL_LEAD_CEILING',h,sample_type,'due',count,'directional',actual_wins,
                  'lag_3_upper',by_delay['3']['possible_60m_warnings_even_oracle_direction'],
                  'lag_8_upper',by_delay['8']['possible_60m_warnings_even_oracle_direction'],flush=True)
        results[h]=sub
    return {'schema':'btc-v7r6-physical-publication-lead-ceiling-v1',
        'historical_labels_already_seen':True,
        'perfect_direction_assumed_for_UPPER_BOUND_ONLY':True,
        'not_a_model_skill_estimate':True,
        'touch_within_5m_earliest_open_latest_close':True,
        'assumed_public_delivery_latency_minutes':DELIVERY_DELAY_MIN,
        'fixed_UTC_historical_blocks':[x.isoformat() for x in FOLDS],
        'required_early_warning_minutes':MINIMUM_WARNING_LEAD_MIN,
        'trading_authority':False,'horizons':results}

def run(path,out):
    with gzip.open(path,'rt') as fh:r=json.load(fh)
    res=evaluate(r)
    res['source_gzip_sha256']=hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()
    pathlib.Path(out).write_text(json.dumps(res,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+'\n')
    return res
if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('--raw',required=True);a.add_argument('--out',required=True)
    p=a.parse_args();run(p.raw,p.out)
