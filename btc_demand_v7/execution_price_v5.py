"""ONE research-only causal BTC price challenger with OTC execution-time horizons.

Input is separately verified, previously signed 65d Binance closed 5m spot.
Historical OI/book are NOT verified as-of inputs and are NOT in this model.
Oct 5-11 2026 has already been examined; it is exploratory, NOT untouched.
There is NO trading authority, actual OTC quote or fill.
"""
from __future__ import annotations
import argparse,datetime as dt,gzip,hashlib,json,math,pathlib
import numpy as np
from sklearn.linear_model import Ridge
from btc_skill_rebuild.evaluate import (
    STEP,UTC,VAL_START,TEST_START,features,build_arrays,future_morning_bars
)

ALPHA=90.0
EMBARGO_MS=30*3600*1000
SHRINKS=(0.,.2,.4,.6,.8,1.)
HORIZONS={"1h":12,"2h_wait1h_exec":24,"4h":48,"5h_wait4h_exec":60,
          "24h":288,"morning_08msk":None,"morning_plus1h_exec":None}
CASH=147600.
MARKUP=350.

def strict_spot(rows):
    if len(rows)<12000:raise ValueError("insufficient signed raw")
    previous=None
    for r in rows:
        start=int(r[0]);end=int(r[6])+1
        if end!=start+STEP or (previous is not None and start-previous!=STEP):
            raise ValueError("spot gap/future/unclosed")
        previous=start
        n=[float(r[k]) for k in (1,2,3,4,5,7,8,9,10)]
        if not all(math.isfinite(x) for x in n):raise ValueError("nonfinite raw")
        op,hi,lo,cl,vol,quote,trades,taker,takerquote=n
        if (not(0<lo<=min(op,cl)<=max(op,cl)<=hi)
            or not(0<=taker<=vol and 0<=takerquote<=quote)
            or not(trades>=0 and trades.is_integer())):
            raise ValueError("invalid raw market mechanics")

def make_target(times,array,indices,h):
    if HORIZONS[h] is not None:
        offset=np.full(len(indices),HORIZONS[h],dtype=int)
    else:
        extra=12 if h=="morning_plus1h_exec" else 0
        offset=np.asarray([future_morning_bars(times[i])+extra for i in indices])
    y=np.full(len(indices),np.nan)
    valid=indices+offset<len(array)
    y[valid]=np.log(array[indices[valid]+offset[valid],3]/array[indices[valid],3])
    return y,offset

def split(anchors,offset):
    valid_start=int(VAL_START.timestamp()*1000)
    test_start=int(TEST_START.timestamp()*1000)
    label_end=anchors+offset*STEP
    train=np.flatnonzero(label_end+EMBARGO_MS<valid_start)
    valid=np.flatnonzero((anchors>=valid_start)&(label_end+EMBARGO_MS<test_start))
    test=np.flatnonzero(anchors>=test_start)
    if min(len(train),len(valid),len(test))<250:raise ValueError("empty chronological split")
    return train,valid,test

def transform(train,other):
    median=np.median(train,axis=0)
    scale=np.maximum(1e-5,1.4826*np.median(np.abs(train-median),axis=0))
    return np.clip((train-median)/scale,-6,6),np.clip((other-median)/scale,-6,6),median,scale

def report_metrics(anchor,actual,pred,spot,momentum):
    err=np.abs(pred-actual);base=np.abs(spot-actual)
    keys=np.array([dt.datetime.fromtimestamp(int(t)/1000,UTC).strftime("%Y-%m-%d") for t in anchor])
    daily={day:float(np.mean((base-err)[keys==day])) for day in sorted(set(keys))}
    return {"overlapping_15m_windows":len(anchor),"distinct_days":len(daily),
            "model_mae_usdt":float(np.mean(err)),
            "persistence_mae_usdt":float(np.mean(base)),
            "momentum_mae_usdt":float(np.mean(np.abs(momentum-actual))),
            "gain_vs_persistence_usdt":float(np.mean(base-err)),
            "gain_vs_momentum_usdt":float(np.mean(np.abs(momentum-actual)-err)),
            "model_rmse_usdt":float(np.sqrt(np.mean((pred-actual)**2))),
            "model_signed_bias_usdt":float(np.mean(pred-actual)),
            "winning_days":sum(x>0 for x in daily.values()),
            "daily_gains_usdt":daily,
            "independent_20day_interval_available":len(daily)>=20,
            "historical_test_previously_examined":True,
            "prospective_skill_proven":False}

def evaluate(input_gz,outpath):
    packed=pathlib.Path(input_gz).read_bytes()
    with gzip.open(input_gz,"rt") as stream:raw=json.load(stream)
    strict_spot(raw)
    times,a=build_arrays(raw);indices,x=features(times,a)
    anchors=times[indices]+STEP
    current=a[indices,3]
    output={
      "schema":"btc-v7r5-single-causal-execution-price-research-v1",
      "signed_source_gzip_sha256":hashlib.sha256(packed).hexdigest(),
      "source_requires_independent_cosign_and_rekor_verification":True,
      "source_factors":["closed BTCUSDT 5m spot","past taker buy base volume","trades"],
      "OI_book_funding_in_numerical_price_head":False,
      "model":"Ridge fixed alpha, train-only robust scale and winsorization",
      "alpha":ALPHA,"embargo_hours":30,"validation_shrinks":SHRINKS,
      "methodological_limit":"Oct 5-11 seen by prior experiments, never clean future holdout",
      "price_heads":{},"execution_proxy":{},
      "prospective_skill_proven":False,"trading_authority":False,
      "model_release_authorized":False}
    by_h={}
    for h in HORIZONS:
        y,offset=make_target(times,a,indices,h)
        tr,va,te=split(anchors,offset)
        tr=tr[np.isfinite(y[tr])]
        va=va[np.isfinite(y[va])]
        te=te[np.isfinite(y[te])]
        if min(map(len,(tr,va,te)))<250:raise ValueError("insufficient mature labels "+h)
        x_train,x_both,center,scale=transform(x[tr],np.vstack((x[va],x[te])))
        bounds=np.quantile(y[tr],[.005,.995])
        model=Ridge(alpha=ALPHA,solver="cholesky")
        model.fit(x_train,np.clip(y[tr],*bounds))
        fitted=model.predict(x_both)
        valpred=fitted[:len(va)];testpred=fitted[len(va):]
        validation_truth=current[va]*np.exp(y[va])
        choose=lambda sh:np.mean(np.abs(current[va]*np.exp(sh*valpred)-validation_truth))
        attenuation=min(SHRINKS,key=lambda sh:(choose(sh),sh))
        keep=anchors[te]%900000==0
        ids=te[keep]
        actual=current[ids]*np.exp(y[ids])
        predicted=current[ids]*np.exp(attenuation*testpred[keep])
        offsettest=offset[ids]
        previous=a[np.maximum(indices[ids]-12,0),3]
        lagret=np.clip(np.log(current[ids]/previous),-.012,.012)
        momentum=current[ids]*np.exp(lagret*np.minimum(offsettest/12,6))
        metric=report_metrics(anchors[ids],actual,predicted,current[ids],momentum)
        output["price_heads"][h]={
          "attenuation_from_validation":attenuation,
          "validation_mae_usdt":float(choose(attenuation)),
          "validation_persistence_mae_usdt":float(choose(0)),
          "train_n":len(tr),"validation_n":len(va),"test_n":len(ids),
          "train_only_target_bounds":bounds.tolist(),
          "coef":model.coef_.tolist(),"intercept":float(model.intercept_),
          "training_feature_center":center.tolist(),"training_feature_scale":scale.tolist(),
          "metrics":metric}
        by_h[h]={int(t):(float(q),float(p),float(act))
                 for t,q,p,act in zip(anchors[ids],current[ids],predicted,actual)}
    candidates=("1h","2h_wait1h_exec","5h_wait4h_exec","morning_plus1h_exec")
    common=sorted(set.intersection(*(set(by_h[h]) for h in candidates)))
    if len(common)<100:raise ValueError("insufficient paired chronological OTC windows")
    for waited in candidates[1:]:
        pred_now=np.array([by_h["1h"][t][1] for t in common])
        pred_wait=np.array([by_h[waited][t][1] for t in common])
        actual_now=np.array([by_h["1h"][t][2] for t in common])
        actual_wait=np.array([by_h[waited][t][2] for t in common])
        simulated_wait=pred_wait<pred_now
        units_buy=CASH/(actual_now+MARKUP)
        units_wait=CASH/(actual_wait+MARKUP)
        units_policy=np.where(simulated_wait,units_wait,units_buy)
        difference=units_policy-units_buy
        output["execution_proxy"][waited]={
          "paired_15m_samples":len(common),
          "wait_choice_count":int(sum(simulated_wait)),
          "assumed_markup_usdt":MARKUP,"assumed_budget_usdt":CASH,
          "hypothetical_mean_gain_btc":float(np.mean(difference)),
          "p05_gain_btc":float(np.quantile(difference,.05)),
          "p95_gain_btc":float(np.quantile(difference,.95)),
          "operator_quote_or_fill_recorded":False,
          "operator_rejection_partial_execution_modeled":False,
          "economic_advantage_proven":False}
    primary=("1h","4h","morning_08msk")
    output["diagnostic_passed"] = all(
      output["price_heads"][h]["metrics"]["gain_vs_persistence_usdt"]>0
      and output["price_heads"][h]["metrics"]["winning_days"]>=5 for h in primary)
    output["model_release_authorized"]=False  # never authorize on seen test
    path=pathlib.Path(outpath);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(output,sort_keys=True,indent=2,allow_nan=False)+"\n")
    summary={h:{"validation_shrink":output["price_heads"][h]["attenuation_from_validation"],
                "days":output["price_heads"][h]["metrics"]["distinct_days"],
                "model_mae":output["price_heads"][h]["metrics"]["model_mae_usdt"],
                "baseline_mae":output["price_heads"][h]["metrics"]["persistence_mae_usdt"],
                "gain_usdt":output["price_heads"][h]["metrics"]["gain_vs_persistence_usdt"]}
             for h in primary}
    print("BTC_V7R5_ONE_CANDIDATE_PRICE_DIAGNOSTIC",
          json.dumps({"source":"verified-signed-spot-only",
                      "release_authorized":False,
                      "diagnostic_passed":output["diagnostic_passed"],
                      "heads":summary},sort_keys=True))

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--signed-spot-raw",required=True)
    p.add_argument("--out",required=True)
    args=p.parse_args()
    evaluate(args.signed_spot_raw,args.out)
if __name__=="__main__":main()
