"""BTC v7R6: causal price/range uncertainty research, NOT a new live model.

The existing price head collapsed to persistence. Evaluate a volatility-aware
probability of ANY symmetric first passage independently of the unsupported
direction. The status quo point price remains persistence unless a genuine
out-of-sample improvement is demonstrated; no retroactive October 11 fitting.
Raw source is historical Binance closed 5m OHLCV (not signed as-of OI/book).
"""
from __future__ import annotations
import argparse,datetime as dt,gzip,hashlib,json,math,pathlib,statistics
UTC=dt.timezone.utc
STEP=300000
TRAIN_CUTOFF=dt.datetime(2026,9,28,tzinfo=UTC)
VALIDATION_CUTOFF=dt.datetime(2026,10,5,tzinfo=UTC)
HORIZONS={'1h':(12,0.007),'4h':(48,0.012),'24h':(288,0.020)}
VOL_SCALES=(0.6,0.8,1.0,1.2,1.5,1.8)
TREND_SHRINK=(-0.25,-0.1,0.,0.1,0.25)
BUDGET=147600.0

def walk_to_barrier_probability(var_over_horizon,logbarrier):
    """Probability of touching +b OR -b by T for zero-drift Brownian log BTC.

    Analytical absorbing-boundary solution (no Monte Carlo seed):
      S=4/pi sum (-1)^k/(2k+1) exp(-(2k+1)^2 pi^2 V/(8b^2)).
    For low V use the numerically stable reflection approximation; the
    omitted alternating-image overlap is negligible in the used tail.
    """
    if not (math.isfinite(var_over_horizon) and var_over_horizon>=0 and logbarrier>0):
        raise ValueError('invalid instantaneous future risk')
    if var_over_horizon==0:return 0.
    u=var_over_horizon/(logbarrier*logbarrier)
    if u<.12:
        return min(1.,2*math.erfc(1/math.sqrt(2*u)))
    series=sum(((-1)**k)/(2*k+1)*math.exp(-((2*k+1)**2)*math.pi**2*u/8) for k in range(28))
    return min(1.,max(0.,1-4*series/math.pi))

def cumulative_var(logclose):
    out=[0.]
    for i in range(1,len(logclose)):
        v=logclose[i]-logclose[i-1]
        out.append(out[-1]+v*v)
    return out

def historic_daily_gain_ci(block_gains):
    # Descriptive conservative normal interval; 7 days cannot establish skill.
    n=len(block_gains)
    if n<2:return None
    mean=statistics.mean(block_gains)
    se=statistics.stdev(block_gains)/math.sqrt(n)
    return [mean-1.96*se,mean+1.96*se]

def scan(rows):
    if len(rows)<10000:raise ValueError('too little raw spot history')
    ts=[int(r[0]) for r in rows]
    if any(b-a!=STEP for a,b in zip(ts,ts[1:])):raise ValueError('missing 5-minute historical candles')
    closes=[];hi=[];lo=[]
    for r in rows:
        if int(r[6])+1!=int(r[0])+STEP:raise ValueError('unclosed or shifted candle')
        o,h,l,c=map(float,(r[1],r[2],r[3],r[4]))
        if not(all(math.isfinite(v) for v in (o,h,l,c)) and 0<l<=min(o,c)<=max(o,c)<=h):
            raise ValueError('historical spot OHLC rejected')
        closes.append(c);hi.append(h);lo.append(l)
    logs=list(map(math.log,closes));cs=cumulative_var(logs)
    times=[dt.datetime.fromtimestamp((t+STEP)/1000,UTC) for t in ts]
    cut1=int(TRAIN_CUTOFF.timestamp()*1000);cut2=int(VALIDATION_CUTOFF.timestamp()*1000)
    levels={};result={'schema':'btc-v7r6-existing-head-volatility-conditional-research-v1',
       'historical_period_already_known_to_developers':True,
       'not_prospective_outcome_evidence':True,'trading_authority':False,
       'price_edge_proven':False,'directional_edge_proven':False,
       'no_oibook_historical_asof_claim':True,
       'data_start_utc':times[0].isoformat(),'data_end_utc':times[-1].isoformat(),
       'train_end_exclusive_utc':TRAIN_CUTOFF.isoformat(),
       'validation_end_exclusive_utc':VALIDATION_CUTOFF.isoformat(),
       'event_target':'future max(high)/min(low) touched either symmetric barrier over exact forward bars',
       'conditional_forecast_is_two_sided_risk_not_directional_prediction':True,
       'horizons':levels}
    for h,(n,barrier) in HORIZONS.items():
        examples={'train':[],'validation':[],'test':[]}
        for i in range(289,len(rows)-n):
            issued=ts[i]+STEP
            end=ts[i+n]+STEP
            # 24-hour strict label embargo at each chronological split
            if end<cut1:split='train'
            elif cut1<=issued and end<cut2:split='validation'
            elif cut2<=issued:split='test'
            else:continue
            current=closes[i]
            upper=current*(1+barrier);lower=current*(1-barrier)
            u=any(v>=upper for v in hi[i+1:i+n+1])
            d=any(v<=lower for v in lo[i+1:i+n+1])
            any_touch=int(u or d)
            # Last 1h / 4h / 24h purely as-of variance per closed 5m bar.
            v12=(cs[i]-cs[i-12])/12
            v48=(cs[i]-cs[i-48])/48
            v288=(cs[i]-cs[i-288])/288
            # Fixed mixture before any evaluation; not selected on test data.
            future_var=n*(0.25*v12+0.35*v48+0.40*v288)
            ex=(issued,any_touch,future_var,current,closes[i+n],
                logs[i]-logs[i-n] if i>=n else 0.)
            examples[split].append(ex)
        tr=examples['train'];va=examples['validation'];te=examples['test']
        if not (len(tr)>5000 and len(va)>1000 and len(te)>1000):
            raise ValueError('insufficient split counts for '+h)
        baseline=sum(x[1] for x in tr)/len(tr)
        logbarrier=(math.log1p(barrier)-math.log1p(-barrier))/2
        def pfun(ex,mult):return walk_to_barrier_probability(ex[2]*mult**2,logbarrier)
        def brier(sample,p):return sum((p(x)-x[1])**2 for x in sample)/len(sample)
        selected=min(VOL_SCALES,key=lambda mult:brier(tr,lambda e:pfun(e,mult)))
        # Trend shrinks train-selected by absolute point-price error; zero is
        # an explicit competitor. The model cannot pass merely by vol skill.
        def point_price(e,a):return e[3]*math.exp(a*e[5])
        chosen_trend=min(TREND_SHRINK,
            key=lambda alpha:sum(abs(point_price(e,alpha)-e[4]) for e in tr)/len(tr))
        def stats(sample):
            n0=len(sample);pred=[pfun(x,selected) for x in sample]
            gains=[(baseline-x[1])**2-(p-x[1])**2 for x,p in zip(sample,pred)]
            day={}
            for ex,g in zip(sample,gains):day.setdefault(dt.datetime.fromtimestamp(ex[0]/1000,UTC).date().isoformat(),[]).append(g)
            block_gains=[statistics.mean(v) for k,v in sorted(day.items())]
            pred_mae=statistics.mean(abs(point_price(x,chosen_trend)-x[4]) for x in sample)
            base_mae=statistics.mean(abs(x[3]-x[4]) for x in sample)
            return {'n_overlapping_5m_windows':n0,'n_distinct_UTC_days':len(day),
                    'observed_any_touch_rate':statistics.mean(x[1] for x in sample),
                    'mean_forecast_any_touch_probability':statistics.mean(pred),
                    'conditional_brier':statistics.mean((p-x[1])**2 for x,p in zip(sample,pred)),
                    'frozen_train_constant_brier':statistics.mean((baseline-x[1])**2 for x in sample),
                    'brier_gain_positive_is_better':statistics.mean(gains),
                    'days_with_positive_brier_gain':sum(z>0 for z in block_gains),
                    'daily_gain_ci95_descriptive_not_prospective':historic_daily_gain_ci(block_gains),
                    'selected_trend_point_mae_usdt':pred_mae,
                    'persistence_point_mae_usdt':base_mae,
                    'point_mae_gain_usdt':base_mae-pred_mae}
        levels[h]={'barrier_pct':100*barrier,'horizon_5m_bars':n,
           'frozen_zero_drift_direction_p_up_given_touch':.5,
           'train_selected_vol_scale':selected,'train_selected_point_trend_shrink':chosen_trend,
           'train_any_touch_prevalence':baseline,
           'train':stats(tr),'validation':stats(va),'historic_test_already_seen':stats(te)}
    # Execution-aligned *historical spot proxy*, not a real OTC order/quote.
    # Publication is the closed 5m boundary i+1, when the current history
    # was knowable; BUY_NOW execution is +1h, WAIT_1H executes +2h.
    # The action label is therefore p(t+2h)-p(t+1h), NOT tomorrow morning
    # or a 1h endpoint mistakenly treated as an immediate purchase.
    markups=(300.,350.,400.)
    rules=('BUY_NOW_ALWAYS','WAIT_1H_ALWAYS','WAIT_ON_1H_UP_15BP',
           'WAIT_ON_1H_DOWN_15BP')
    action_samples={'train':[],'validation':[],'test':[]}
    for i in range(289,len(rows)-24):
        issued=ts[i]+STEP
        if issued%(3600*1000)!=0:continue # independent hourly decision grid
        end=ts[i+24]+STEP
        if end<cut1:part='train'
        elif cut1<=issued and end<cut2:part='validation'
        elif cut2<=issued:part='test'
        else:continue
        lag=logs[i]-logs[i-12]
        future_now=closes[i+12]
        future_wait=closes[i+24]
        action_samples[part].append((issued,lag,future_now,future_wait))
    def decide(rule,lag):
        return (rule=='WAIT_1H_ALWAYS' or
                rule=='WAIT_ON_1H_UP_15BP' and lag>=.0015 or
                rule=='WAIT_ON_1H_DOWN_15BP' and lag<=-.0015)
    def gain_rows(part,rule,premium=350.):
        for when_ms,lag,p_buy,p_wait in action_samples[part]:
            b_now=BUDGET/(p_buy+premium)
            b_action=BUDGET/(p_wait+premium) if decide(rule,lag) else b_now
            yield (when_ms, b_action-b_now)
    def block_stats(rows_of_delta):
        if not rows_of_delta:raise ValueError('empty economic sample')
        d={}
        for timestamp_ms,value in rows_of_delta:
            day=dt.datetime.fromtimestamp(timestamp_ms/1000,UTC).date().isoformat()
            d.setdefault(day,[]).append(value)
        day_means=[statistics.mean(v) for k,v in sorted(d.items())]
        return {'hourly_opportunity_windows':len(rows_of_delta),
            'calendar_day_blocks':len(day_means),
            'mean_incremental_btc':statistics.mean(x[1] for x in rows_of_delta),
            'daily_paired_gain_ci95_not_economic_proof':historic_daily_gain_ci(day_means),
            'share_days_wait_rule_improved_BTC':sum(v>0 for v in day_means)/len(day_means)}
    train_scores={r:block_stats(list(gain_rows('train',r))) for r in rules}
    # One explicitly locked conservative decision: only consider a WAIT
    # rule if its TRAIN lower day-level confidence bound is positive AND
    # beats always-wait on the same daily samples. Otherwise abstain / BUY.
    wait_base=train_scores['WAIT_1H_ALWAYS']['mean_incremental_btc']
    candidates=[]
    for rule in rules[1:]:
        lo95=train_scores[rule]['daily_paired_gain_ci95_not_economic_proof'][0]
        if lo95>0 and train_scores[rule]['mean_incremental_btc']>=wait_base:
            candidates.append(rule)
    selected=max(candidates,key=lambda r:train_scores[r]['mean_incremental_btc']) if candidates else 'BUY_NOW_ALWAYS'
    result['execution_aligned_spot_proxy']={
        'budget_usdt':BUDGET,'typical_premium_usdt_per_btc':350.,
        'markup_sensitivity_usdt_per_btc':markups,
        'buy_now_operator_delay_minutes':60,'wait_1h_operator_delay_minutes':60,
        'price_future_buy_target_minutes_after_publication':60,
        'price_future_wait_target_minutes_after_publication':120,
        'no_actual_operator_fills_or_acceptance_observed':True,
        'no_actual_quote_or_execution_forecast':True,
        'no_risk_adjusted_OTC_advantage_proven':True,
        'selected_by_training_day_ci_only':selected,
        'train':train_scores,
        'validation':{r:block_stats(list(gain_rows('validation',r))) for r in rules},
        'historic_test_already_seen':{r:block_stats(list(gain_rows('test',r))) for r in rules},
        'premium_sensitivity_train_btc_gain':{
            str(m):block_stats(list(gain_rows('train',selected,m)))['mean_incremental_btc'] for m in markups},
        'trading_authority':False}
    return result

def run(source,output):
    with gzip.open(source,'rt') as f:rows=json.load(f)
    r=scan(rows)
    r['source_gzip_sha256']=hashlib.sha256(pathlib.Path(source).read_bytes()).hexdigest()
    pathlib.Path(output).parent.mkdir(parents=True,exist_ok=True)
    pathlib.Path(output).write_text(json.dumps(r,sort_keys=True,indent=2,ensure_ascii=False,allow_nan=False)+'\n')
    print('OTC_EXECUTION_ALIGNED_PROXY',r['execution_aligned_spot_proxy']['selected_by_training_day_ci_only'],
          'known_historic_test',r['execution_aligned_spot_proxy']['historic_test_already_seen'][r['execution_aligned_spot_proxy']['selected_by_training_day_ci_only']],flush=True)
    print('BTC_V7R6_MATH_HISTORIC_RESEARCH_NO_LIVE_EDGE',json.dumps({
      h:{'train_vol_scale':v['train_selected_vol_scale'],
         'trend_alpha':v['train_selected_point_trend_shrink'],
         'validation_brier_gain':round(v['validation']['brier_gain_positive_is_better'],7),
         'historic_test_brier_gain':round(v['historic_test_already_seen']['brier_gain_positive_is_better'],7),
         'historic_test_point_mae_gain':round(v['historic_test_already_seen']['point_mae_gain_usdt'],2)}
      for h,v in r['horizons'].items()},sort_keys=True),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--raw',required=True);p.add_argument('--out',required=True)
    a=p.parse_args();run(a.raw,a.out)
