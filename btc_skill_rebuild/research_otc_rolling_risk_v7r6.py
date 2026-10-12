"""BTC v7R6 math: daily causal OTC direct-BTC utility plus 20-day risk veto.

Everything here is a RETROSPECTIVE replay using known Binance OHLCV;
virtual publication timestamps are assumptions, NOT GitHub evidence.
This script does NOT trade, and is not the frozen v7R6 live worker.
"""
from __future__ import annotations
import argparse,datetime as dt,gzip,hashlib,json,math,pathlib,statistics
from btc_skill_rebuild.research_execution_drift_v7r6 import examples,fit_ridge,predict,STEP
from btc_skill_rebuild.research_otc_direct_btc_target_v7r6 import (
    btc_opportunity_gain,SHRINK_CHOICES,decide_from_expected_btc_gain)
from btc_skill_rebuild.research_otc_confidence_v7r6 import (
    MaturedDay,worst_case_wait_advantage_btc,bound_wait_utility)
from btc_skill_rebuild.research_walkforward_barriers_v7r6 import UTC,FOLDS

FIRST=FOLDS[0]
END=FOLDS[-1]+dt.timedelta(days=7)
MAX_HORIZON_BARS=24

def calculate(rows):
    all_rows=[]
    for i,when,x,cl,logs in examples(rows):
        if i+MAX_HORIZON_BARS>=len(rows) or when%(15*60000):continue
        future1=cl[i+12];future2=cl[i+24]
        label=btc_opportunity_gain(future1,future2)
        label_due=int(rows[i+24][0])+STEP
        all_rows.append((when,label_due,x,label,cl[i],future1,future2))
    if not all_rows:raise ValueError('no historical research spot')
    issued_at={(when):r for r in all_rows for when in [r[0]]}
    completed=[];research_predictions=[]
    for day_i in range((END-FIRST).days):
        forecast_date=FIRST+dt.timedelta(days=day_i,hours=15)
        forecast_t=int(forecast_date.timestamp()*1000)
        if forecast_t not in issued_at:raise ValueError('missing fixed 15 UTC forecast anchor')
        current=issued_at[forecast_t]
        # Every past TRAIN label must have matured BEFORE the seven-day
        # chronological validation period. We do not use a 15m feature
        # from after the 15UTC forecast anchor.
        validation_start=forecast_t-7*86400000
        past_train=[(at,x,y) for at,due,x,y,spot,f1,f2 in all_rows
                    if due<validation_start]
        previous_seven=[]
        for j in range(7,0,-1):
            val_t=forecast_t-j*86400000
            if val_t not in issued_at:raise ValueError('missing validation daily due slot')
            s=issued_at[val_t]
            if s[1]>=forecast_t:raise ValueError('validation label not matured by forecast')
            previous_seven.append((s[0],s[2],s[3],s[4],s[5],s[6]))
        model=fit_ridge(past_train)
        def gain_for_alpha(alpha):
            gain=0.
            for at,x,y,spot,p60,p120 in previous_seven:
                raw_pred=alpha*predict(model,x)
                if decide_from_expected_btc_gain(raw_pred,spot)=='WAIT_60':gain+=y
            return gain
        alpha=max(SHRINK_CHOICES,key=gain_for_alpha)
        predicted_btc_gain=alpha*predict(model,current[2])
        old=completed[-20:]
        if day_i<20:
            decision='INSUFFICIENT_MATURED_CALIBRATION'
            bound=None
        else:
            bound=bound_wait_utility(forecast_date,predicted_btc_gain,old,
                                    required_days=20,alpha=.10)
            decision=bound['decision']
        exact_wait=(decision=='WAIT_CANDIDATE_RESEARCH_ONLY')
        outcome=predicted_btc_gain
        observed=current[3]
        worst=worst_case_wait_advantage_btc(current[5],current[6])
        # Historical as-if published t+8m solely for validating arithmetic.
        # This is NOT a source-signed prospective forecast or OTC record.
        completed.append(MaturedDay(forecast_date,
            forecast_date+dt.timedelta(minutes=8),
            forecast_date+dt.timedelta(minutes=125),
            predicted_btc_gain,worst,'historical_spot_proxy'))
        research_predictions.append({
            'date_utc':str(forecast_date.date()),
            'training_before_validation_n':len(past_train),
            'seven_previous_calendar_days_used_for_validation':len(previous_seven),
            'validation_selected_shrink':alpha,
            'nominal_ex_ante_predicted_wait_gain_btc':predicted_btc_gain,
            'risk_veto':decision,
            'risk_bound_btc':bound['forecast_lower_bound_btc'] if bound else None,
            'research_WAIT':exact_wait,
            'realized_nominal_wait_gain_btc':observed,
            'worst_markup_wait_gain_btc':worst,
            'strategy_gain_btc_against_buy_now':observed if exact_wait else 0.,
            'strategy_worst_markup_gain_if_wait_btc':worst if exact_wait else 0.,
            'signing_and_OTC_operators_NOT_present':True})
        print('BTC_OTC_CAUSAL_DAILY_REPLAY',forecast_date.date(),
              'val_shrink',alpha,
              'pred_gain',round(predicted_btc_gain,7),
              'risk_veto',decision,
              'future_spot_proxy_nominal_gain',round(observed,7),flush=True)
    after=research_predictions[20:]
    vals=[x['strategy_gain_btc_against_buy_now'] for x in after]
    result={'schema':'btc-v7r6-20day-OTC-gain-lower-tail-causal-replay-v1',
        'historical_data_known_before_replay':True,
        'virtual_publication_timestamps_not_real_evidence':True,
        'actual_quoted_and_filled_OTC_orders':0,
        'prospective_forecast_skill_proven':False,'trading_authority':False,
        'issue_time_utc_clock':'15:00 each day',
        'decision_minutes_to_now_execution':60,
        'decision_minutes_to_wait_execution':120,
        'rows':research_predictions,
        'all_due_days':len(research_predictions),
        'complete_daily_due_grid':len(research_predictions)==28,
        'first20_training_calibration_days':20,
        'next8_evaluated_outcomes':len(after),
        'post_calibration_WAIT_decisions':sum(x['research_WAIT'] for x in after),
        'post_calibration_regret_vs_buy_now_btc':sum(vals),
        'post_calibration_worst_markup_gain_if_WAIT_btc':sum(
               x['strategy_worst_markup_gain_if_wait_btc'] for x in after),
        'post_calibration_always_wait_spot_proxy_mean_BTC':statistics.mean(
               x['realized_nominal_wait_gain_btc'] for x in after)}
    return result

def run(source,out):
    with gzip.open(source,'rt') as f:rows=json.load(f)
    result=calculate(rows)
    result['source_sha256']=hashlib.sha256(pathlib.Path(source).read_bytes()).hexdigest()
    pathlib.Path(out).write_text(json.dumps(result,indent=2,sort_keys=True,allow_nan=False)+'\n')
    print('BTC_OTC_CAUSAL_20DAY_REPLAY_SUMMARY','due',result['all_due_days'],
          'eligible',result['next8_evaluated_outcomes'],
          'WAIT',result['post_calibration_WAIT_decisions'],
          'proxy_gain_btc',result['post_calibration_regret_vs_buy_now_btc'],flush=True)
    return result
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--raw',required=True);p.add_argument('--out',required=True)
    a=p.parse_args();run(a.raw,a.out)
