"""One deterministic analog-conditional BTC price challenger; RESEARCH ONLY.

Purpose: check whether similar as-of 5m spot conditions predict 1h, 4h,
24h and the next 08:00 MSK endpoints BETTER than constant-price and fixed
momentum, without relying on a zero-valued gradient booster. Not a trading
model. The Oct5-11 holdout has already been examined by earlier experiments,
so any success here is only a diagnostic and does NOT count as unseen proof.

Feature and k-NN parameters below are fixed PRIOR to seeing this run's scores.
Use only closed 5m, training split/validation split with label embargo.
"""
from __future__ import annotations
import argparse,datetime as dt,gzip,hashlib,json,math,pathlib
import numpy as np
from sklearn.neighbors import NearestNeighbors
from btc_skill_rebuild.evaluate import (
    STEP,UTC,VAL_START,TEST_START,features,build_arrays,
    build_targets,splits as chronological_splits,
    future_morning_bars
)

K=192
SHRINKS=(0.,.20,.40,.60,.80,1.)
SEED=60113
# Causal, physically motivated trend/flow/participation/volatility/time state
FEATURE_IDS=(0,1,3,4,9,11,12,13,15,16,17,18,19,23,24,26)
WEIGHTS=(1.,1.,1.2,.65,1.,1.,1.15,.8,.8,.65,.65,1.,.65,.4,.4,.65)
HORIZONS=("1h","4h","24h","morning_08msk")

def label_log_return(times,a,idx,h):
    close=a[:,3]
    if h=="morning_08msk":
        offset=np.asarray([future_morning_bars(times[i]) for i in idx],dtype=int)
    else:
        offset=np.full(len(idx),{"1h":12,"4h":48,"24h":288}[h],dtype=int)
    ret=np.full(len(idx),np.nan)
    good=(idx+offset<len(close))
    ret[good]=np.log(close[idx[good]+offset[good]]/close[idx[good]])
    return ret

def normalize(train, other):
    ref=np.median(train,axis=0)
    deviation=np.median(np.abs(train-ref),axis=0)*1.4826
    # Data-derived train-only scaling, strictly bounded against instability.
    std=np.maximum(deviation,1e-4)
    return [np.clip((v-ref)/std,-5,5)*np.asarray(WEIGHTS)
            for v in (train,other)]

def analog_median(x_train,y_train,x_query):
    """Only observed TRAIN labels can be nearest-neighbor targets."""
    keep=np.isfinite(y_train)
    x_train=x_train[keep];y_train=y_train[keep]
    if len(x_train)<K*8:raise RuntimeError("train horizon has insufficient analogs")
    train,query=normalize(x_train,x_query)
    engine=NearestNeighbors(n_neighbors=K,algorithm="auto",metric="euclidean",n_jobs=1)
    engine.fit(train)
    distance,neighbors=engine.kneighbors(query)
    # Median protects rare tail labels; stable tie-handling by numpy.
    return np.median(y_train[neighbors],axis=1)

def test_score(actual,pred,reference,anchors):
    err=np.abs(pred-actual);persist=np.abs(reference-actual)
    valid=np.isfinite(actual)&np.isfinite(pred)&np.isfinite(reference)
    if not np.all(valid):raise RuntimeError("test used unknown actual or model price")
    gain=persist-err
    daykeys=np.array([dt.datetime.fromtimestamp(int(t)/1000,UTC).strftime("%Y-%m-%d")
                      for t in anchors])
    day_gain=[float(np.mean(gain[daykeys==day])) for day in sorted(set(daykeys))]
    # This CI is descriptive; one week can never satisfy the fixed
    # 20+ independent days required for prospective acceptance.
    return {"n_overlapping_5m_windows":len(err),
            "n_distinct_days":len(day_gain),
            "model_mae_usdt":float(np.mean(err)),
            "persistence_mae_usdt":float(np.mean(persist)),
            "mae_gain_usdt":float(np.mean(gain)),
            "model_signed_bias_usdt":float(np.mean(pred-actual)),
            "daily_mean_gains_usdt":day_gain,
            "independent_prospective_skill_proven":False}

def run(path,output):
    with gzip.open(path,"rt") as f:rows=json.load(f)
    times,a=build_arrays(rows)
    if not np.all(np.diff(times)==STEP):
        raise ValueError("closed 5m observations have missing timestamps")
    if any(int(r[6])+1!=int(r[0])+STEP for r in rows):
        raise ValueError("unclosed spot data")
    idx,fx=features(times,a)
    anchors=times[idx]+STEP
    x=fx[:,FEATURE_IDS]
    tr,va,te=chronological_splits(times,idx)
    close=a[idx,3]
    out={"schema":"btc-v7r3-causal-analog-price-research-v1",
         "training_only_factor_source":"signed Binance 5m closed OHLCV and taker buy",
         "numerical_oi_book_in_price_head":False,
         "price_analogue_k":K,"train_only_robust_scaling":True,
         "fixed_feature_ids":FEATURE_IDS,"fixed_weights":WEIGHTS,
         "pre_registered_calibration_grid":SHRINKS,
         "trained_before_validation":VAL_START.isoformat(),
         "test_start":TEST_START.isoformat(),
         "tested_historical_period_already_seen_in_prior_v7_experiments":True,
         "trading_authority":False,"prospective_skill_proven":False,
         "price_horizons":{}}
    for h in HORIZONS:
        y=label_log_return(times,a,idx,h)
        tr_h=tr[np.isfinite(y[tr])]
        va_h=va[np.isfinite(y[va])]
        te_h=te[np.isfinite(y[te])]
        if not len(va_h)>500 or not len(te_h)>500:raise ValueError("insufficient horizon labels")
        raw_va=analog_median(x[tr_h],y[tr_h],x[va_h])
        true_va=close[va_h]*np.exp(y[va_h])
        shrink=min(SHRINKS,key=lambda s:float(np.mean(np.abs(close[va_h]*np.exp(s*raw_va)-true_va))))
        raw_test=analog_median(x[tr_h],y[tr_h],x[te_h])
        prediction=close[te_h]*np.exp(shrink*raw_test)
        truth=close[te_h]*np.exp(y[te_h])
        stats=test_score(truth,prediction,close[te_h],anchors[te_h])
        stats["validation_selected_shrink"]=shrink
        stats["validation_analog_abs_usdt"]=float(np.mean(np.abs(close[va_h]*np.exp(raw_va)-true_va)))
        stats["validation_persistence_abs_usdt"]=float(np.mean(np.abs(close[va_h]-true_va)))
        out["price_horizons"][h]=stats
    incident=int(dt.datetime(2026,10,11,15,45,tzinfo=UTC).timestamp()*1000)
    where=np.where(anchors==incident)[0]
    out["incident_oct11_preknown"]=None
    if len(where):
        j=int(where[0]);profile={"anchor_utc":dt.datetime.fromtimestamp(incident/1000,UTC).isoformat(),
                                  "spot":float(close[j]),"forecasts":{}}
        for h in HORIZONS:
            yr=label_log_return(times,a,idx,h)
            tr_h=tr[np.isfinite(yr[tr])]
            # Same preselected validation shrink reported above; do not tune at incident.
            val=va[np.isfinite(yr[va])]
            raw_val=analog_median(x[tr_h],yr[tr_h],x[val])
            actual_val=close[val]*np.exp(yr[val])
            shrink=min(SHRINKS,key=lambda s:np.mean(np.abs(close[val]*np.exp(s*raw_val)-actual_val)))
            pred=analog_median(x[tr_h],yr[tr_h],x[j:j+1])
            profile["forecasts"][h]=float(close[j]*np.exp(shrink*pred[0]))
        out["incident_oct11_preknown"]=profile
    output=pathlib.Path(output);output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(out,sort_keys=True,indent=2,ensure_ascii=False,allow_nan=False)+"\n")
    print("BTC_V7R3_ANALOG_PRICE_DIAGNOSTIC",
          json.dumps({"status":"RESEARCH_ONLY_NOT_PROSPECTIVE",
                      "metrics":{h:{k:v for k,v in d.items()
                             if k in ("n_distinct_days","model_mae_usdt","persistence_mae_usdt",
                                      "mae_gain_usdt","validation_selected_shrink")}
                             for h,d in out["price_horizons"].items()},
                      "incident":out["incident_oct11_preknown"]},sort_keys=True),flush=True)

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--signed-spot-raw",required=True)
    parser.add_argument("--out",required=True)
    args=parser.parse_args()
    run(args.signed_spot_raw,args.out)
