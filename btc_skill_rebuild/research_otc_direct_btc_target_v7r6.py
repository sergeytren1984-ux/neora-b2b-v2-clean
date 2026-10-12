"""Existing BTC v7R6 OTC head: TRAIN against EXECUTABLE BTC difference.

Historical SPOT PROXY only, not actual OTC quotes or a trade-capable model.
For a decision at t, NOW asks operator at t and can fill at t+60m;
WAIT_60 asks at t+60m and fills at t+120m. Direct target is BTC received,
not point price MAE and not first touch of an unrelated 4h barrier.

TRAIN+validation labels mature before subsequent fold; one pre-fixed
daily decision at 15:00 UTC prevents 24 overlapping hypothetical
whole-portfolio purchases being treated as independent trades.
"""
from __future__ import annotations
import argparse,datetime as dt,gzip,json,pathlib,hashlib,math,statistics
from btc_skill_rebuild.research_execution_drift_v7r6 import examples,fit_ridge,predict,STEP
from btc_skill_rebuild.research_walkforward_barriers_v7r6 import FOLDS,UTC
from btc_skill_rebuild.research_otc_execution_utility_v7r6 import (
    CAPITAL_USDT,markup_robust_direction)

MARKUP_USDT_PER_BTC=350.
UNKNOWN_MARKUP_BAND_USDT=100.
SHRINK_CHOICES=(0.,.25,.5,.75,1.)
HORIZON_NOW_BARS=12
HORIZON_WAIT_BARS=24

def btc_opportunity_gain(price_at_60,price_at_120,capital=CAPITAL_USDT,
                         markup=MARKUP_USDT_PER_BTC):
    values=(price_at_60,price_at_120,capital,markup)
    if any(not math.isfinite(x) for x in values) or min(price_at_60,price_at_120,capital)<=0 or markup<0:
        raise ValueError("invalid OTC-execution proxy input")
    return capital/(price_at_120+markup)-capital/(price_at_60+markup)

def forecast_markup_uncertainty_margin(known_price_at_issue):
    # Worst-case $100/BTC differential between otherwise equal OTC asks.
    # Computed ONLY from price known at forecast issue t; future unknown
    # price at t+60 or t+120 is never allowed to determine signal size.
    if not math.isfinite(known_price_at_issue) or known_price_at_issue<=0:
        raise ValueError("bad current price")
    ask=known_price_at_issue+MARKUP_USDT_PER_BTC
    return CAPITAL_USDT*UNKNOWN_MARKUP_BAND_USDT/(ask*ask)

def decide_from_expected_btc_gain(gain,known_price):
    if not math.isfinite(gain):
        raise ValueError("invalid forecast")
    return "WAIT_60" if gain>forecast_markup_uncertainty_margin(known_price) else "BUY_NOW"

def daily_score(observations,model,shrink):
    # Never treat correlated hourly or 15m counterfactual whole-budget
    # purchases as independent decisions. There is exactly ONE issue/day.
    dates=[dt.datetime.fromtimestamp(t/1000,UTC).date().isoformat()
           for t,x,y,known,spot60,spot120 in observations]
    if not dates or len(dates)!=len(set(dates)):
        raise ValueError("one prospective full-capital opportunity per UTC day")
    gains=[];all_wait=[];n_wait=0;robust_correct=0;robust_wrong=0
    for t,x,y,known,spot60,spot120 in observations:
        ex_ante=shrink*predict(model,x)
        decision=decide_from_expected_btc_gain(ex_ante,known)
        actual_gain=y if decision=="WAIT_60" else 0.
        all_wait.append(y);gains.append(actual_gain)
        if decision=="WAIT_60":
            n_wait+=1
            rule=markup_robust_direction(spot60,spot120)
            robust_correct+=(rule=="WAIT_60_ROBUSTLY_CHEAPER")
            robust_wrong+=(rule=="BUY_NOW_ROBUSTLY_CHEAPER")
    n=len(observations)
    return {
        "n_predeclared_daily_decisions":n,
        "historical_wait_decisions":n_wait,
        "full_budget_spot_proxy_mean_incremental_btc_vs_buy_now":statistics.mean(gains),
        "full_budget_spot_proxy_total_incremental_btc_not_realized":sum(gains),
        "always_buy_now_btc_gain":0.,
        "always_wait_mean_btc_gain":statistics.mean(all_wait),
        "robust_wait_signals_correct":robust_correct,
        "robust_wait_signals_wrong":robust_wrong,
        "not_multiple_actual_OTC_positions":True,
        "economic_execution_proof":False}

def run(raw,out):
    with gzip.open(raw,"rt") as f:rows=json.load(f)
    data=[]
    for i,issued,x,cl,lg in examples(rows):
        if i+HORIZON_WAIT_BARS>=len(rows):continue
        p0=cl[i];p60=cl[i+HORIZON_NOW_BARS];p120=cl[i+HORIZON_WAIT_BARS]
        y=btc_opportunity_gain(p60,p120)
        due=int(rows[i+HORIZON_WAIT_BARS][0])+STEP
        # Train on 15m as-of observations; evaluation uses ONE fixed daily
        # decision. Correlated TRAIN points do not become independent trials.
        if issued%(15*60000):continue
        data.append((issued,due,x,y,p0,p60,p120))
    trials=[]
    for fold in FOLDS:
        start=int(fold.timestamp()*1000);end=start+7*86400000
        val_start=start-8*86400000;val_end=start-86400000
        train=[(t,x,y) for t,due,x,y,p0,p60,p120 in data if due<val_start]
        valid=[(t,x,y,p0,p60,p120) for t,due,x,y,p0,p60,p120 in data
               if val_start<=t and due<val_end and
                  dt.datetime.fromtimestamp(t/1000,UTC).hour==15 and
                  dt.datetime.fromtimestamp(t/1000,UTC).minute==0]
        future=[(t,x,y,p0,p60,p120) for t,due,x,y,p0,p60,p120 in data
                if start<=t<end and
                   dt.datetime.fromtimestamp(t/1000,UTC).hour==15 and
                   dt.datetime.fromtimestamp(t/1000,UTC).minute==0]
        if len(train)<1000 or len(valid)<5 or len(future)<5:
            raise ValueError("incomplete prospective-like daily validation grid")
        model=fit_ridge(train)
        # Select only on previous validation; if nothing beats BUY_NOW
        # choose zero-shrink, explicitly abstaining from WAIT.
        chosen=max(SHRINK_CHOICES,key=lambda a:
                   daily_score(valid,model,a)["full_budget_spot_proxy_mean_incremental_btc_vs_buy_now"])
        scores=daily_score(future,model,chosen)
        trials.append({"historical_week_start":fold.isoformat(),
                       "train_overlapping_15m":len(train),
                       "validation_daily":len(valid),"selected_shrink":chosen,
                       "validation":daily_score(valid,model,chosen),
                       "historical_forward":scores,
                       "expected_calendar_days":7,
                       "missing_daily_forward_outcomes":7-len(future),
                       "complete_day_grid":len(future)==7})
        print("OTC_DIRECT_BTC_TARGET",str(fold.date()),"shrink",chosen,
              "days",scores["n_predeclared_daily_decisions"],
              "wait",scores["historical_wait_decisions"],
              "mean_proxy_btc_gain",round(scores["full_budget_spot_proxy_mean_incremental_btc_vs_buy_now"],8),
              flush=True)
    output={
       "schema":"btc-v7r6-direct-OTC-BTC-gain-supervised-research-v1",
       "target":"C/(spot_t120+350) - C/(spot_t60+350) BTC",
       "price_at_t60_is_a_future_LABEL_not_a_predictor":True,
       "one_daily_opportunity_not_daily_repeated_capital_trades":True,
       "historical_spot_prices_are_NOT_executable_OTC_quotes":True,
       "operator_rejections_unknown":True,"future_model_not_publicly_issued":True,
       "trading_authority":False,
       "source_sha256":hashlib.sha256(pathlib.Path(raw).read_bytes()).hexdigest(),
       "folds":trials,
       "number_of_positive_weekly_proxy_gains":sum(
         t["historical_forward"]["full_budget_spot_proxy_mean_incremental_btc_vs_buy_now"]>0
         for t in trials)}
    pathlib.Path(out).write_text(json.dumps(output,indent=2,sort_keys=True,allow_nan=False)+"\n")
    return output

if __name__=="__main__":
    a=argparse.ArgumentParser();a.add_argument("--raw",required=True);a.add_argument("--out",required=True)
    r=a.parse_args();run(r.raw,r.out)
