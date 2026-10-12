"""v7R6 OTC execution-time sensitivity, research only.

Evaluate uncertainty of future hypothetical spot execution windows at t+60
and t+120, with operator markup +300..+400. The future candles are LABELS
only, never ex-ante features. One fixed 15:00 UTC issue per day. Four
weekly blocks. No historical signed OTC quotes or actual fills available.
"""
from __future__ import annotations
import argparse,datetime as dt,gzip,hashlib,json,math,pathlib,statistics
from btc_skill_rebuild.research_execution_drift_v7r6 import examples,STEP
from btc_skill_rebuild.research_walkforward_barriers_v7r6 import FOLDS,UTC

USDT=147600.
MARKUP_MIN=300.
MARKUP_MAX=400.
OFFSETS=(0,5,10,15,30)

def bounded_btc_difference(now_min,now_max,wait_min,wait_max):
    if not all(math.isfinite(z) and z>0 for z in (now_min,now_max,wait_min,wait_max)):
        raise ValueError('invalid future quote envelope')
    if now_min>now_max or wait_min>wait_max:raise ValueError('broken quote envelope')
    # The minimax outcomes for WAIT minus NOW in BTC units; negative lower
    # means WAIT may hurt under some admissible execution times/markups.
    lower=USDT/(wait_max+MARKUP_MAX)-USDT/(now_min+MARKUP_MIN)
    upper=USDT/(wait_min+MARKUP_MIN)-USDT/(now_max+MARKUP_MAX)
    assert lower<=upper+1e-12
    return lower,upper

def interval_prices(rows,base_i,target_minutes,tolerance_minutes,price_mode):
    if target_minutes%5 or tolerance_minutes%5:raise ValueError('5m window only')
    bars=range(base_i+(target_minutes-tolerance_minutes)//5,
               base_i+(target_minutes+tolerance_minutes)//5+1)
    if min(bars)<0 or max(bars)>=len(rows):
        raise ValueError('not enough fully matured 5m closes')
    if price_mode=='closed_5m':
        a=[float(rows[i][4]) for i in bars]
        return min(a),max(a)
    if price_mode=='intrabar_5m':
        return min(float(rows[i][3]) for i in bars),max(float(rows[i][2]) for i in bars)
    raise ValueError('unregistered future price mode')

def classify(lower,upper):
    return ('WAIT_ROBUST' if lower>0 else
            'NOW_ROBUST' if upper<0 else 'NOT_IDENTIFIABLE')

def evaluate(raw_rows):
    candles=raw_rows
    if any(int(b[0])-int(a[0])!=STEP for a,b in zip(candles,candles[1:])):
        raise ValueError('historical spot has gaps')
    days=[]
    begin=FOLDS[0].date();end=(FOLDS[-1]+dt.timedelta(days=7)).date()
    for i in range(len(candles)-31):
        issue_ms=int(candles[i][0])+STEP
        when=dt.datetime.fromtimestamp(issue_ms/1000,UTC)
        if when.hour!=15 or when.minute!=0 or not begin<=when.date()<end:
            continue
        # All future 5m closes and intrabar highs/lows remain OUTCOME labels.
        row={'date_utc':when.date().isoformat(),'issue_utc':when.isoformat(),
             'historical_spot_proxy_not_operator_quote':True,'sensitivity':{}}
        for offset in OFFSETS:
            for mode in ('closed_5m','intrabar_5m'):
                a,b=interval_prices(candles,i,60,offset,mode)
                c,d=interval_prices(candles,i,120,offset,mode)
                lb,ub=bounded_btc_difference(a,b,c,d)
                row['sensitivity'][f'{mode}_plusminus_{offset}min']={
                    'now_price_range_usdt':[a,b],
                    'wait_price_range_usdt':[c,d],
                    'worst_wait_minus_now_btc':lb,
                    'best_wait_minus_now_btc':ub,
                    'classification':classify(lb,ub)}
        days.append(row)
    expected=(end-begin).days
    if len(days)!=expected or len({x['date_utc'] for x in days})!=expected:
        raise ValueError(f'incomplete 28-day fixed grid: {len(days)} vs {expected}')
    aggregated={}
    for key in days[0]['sensitivity']:
        entries=[x['sensitivity'][key] for x in days]
        robust_wait=sum(y['classification']=='WAIT_ROBUST' for y in entries)
        robust_now=sum(y['classification']=='NOW_ROBUST' for y in entries)
        uncertain=sum(y['classification']=='NOT_IDENTIFIABLE' for y in entries)
        assert robust_wait+robust_now+uncertain==expected
        aggregated[key]={
            'due_days':expected,'robust_WAIT_days':robust_wait,
            'robust_NOW_days':robust_now,'NOT_IDENTIFIABLE_days':uncertain,
            'worst_spread_average_WaitMinusNow_BTC':statistics.mean(
                a['worst_wait_minus_now_btc'] for a in entries),
            'best_spread_average_WaitMinusNow_BTC':statistics.mean(
                a['best_wait_minus_now_btc'] for a in entries)}
    return {'schema':'btc-v7r6-otc-future-timing-sensitivity-research-v1',
        'all_outcomes_historic_already_seen':True,
        'not_a_predictive_feature_or_actionable_quote':True,
        'no_ex_ante_edge_demonstrated':True,'trading_authority':False,
        'budget_usdt':USDT,'markups_usdt_per_btc':[MARKUP_MIN,MARKUP_MAX],
        'clock':'one UTC 15:00 anchor daily',
        'operator_fixed_delay_assumption_tested_minutes':[60,120],
        'future_time_error_pm_minutes':OFFSETS,'summary':aggregated,'days':days}

def run(raw,out):
    with gzip.open(raw,'rt') as f:rows=json.load(f)
    r=evaluate(rows)
    r['raw_gzip_sha256']=hashlib.sha256(pathlib.Path(raw).read_bytes()).hexdigest()
    pathlib.Path(out).write_text(json.dumps(r,ensure_ascii=False,indent=2,sort_keys=True,allow_nan=False)+'\n')
    for name,a in r['summary'].items():
        print('OTC_FUTURE_TIME_STRESS',name,'wait',a['robust_WAIT_days'],
              'now',a['robust_NOW_days'],'unidentifiable',a['NOT_IDENTIFIABLE_days'],flush=True)
    return r
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--raw',required=True);ap.add_argument('--out',required=True)
    args=ap.parse_args();run(args.raw,args.out)
