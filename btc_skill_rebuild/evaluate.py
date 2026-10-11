"""Research-only, causal BTC directional/price skill audit. NO trading authority.

Targets are independent:
  1h/4h: endpoint price returns and large up/down first-passage events.
  next 08:00 MSK: endpoint price return at 05:00 UTC.
Feature universe: Binance closed 5m spot OHLCV, taker-buy base-volume, number of
trades. NEVER claim that macro, ETF, OI, liquidation or order-book are numeric
inputs. Historical snapshots of these must be proven before a second version.
Evaluation: fixed chronological train/validation/test with 24h label embargo,
persistence and simple momentum baselines, no retrospective tuning on test.
"""
from __future__ import annotations
import argparse
import datetime as dt
import gzip
import hashlib
import json
import math
import os
import pathlib
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
import numpy as np

UTC=dt.timezone.utc
STEP=300_000
END=dt.datetime(2026,10,11,18,55,tzinfo=UTC)
LOOKBACK_DAYS=65
TEST_START=dt.datetime(2026,10,5,0,0,tzinfo=UTC)
VAL_START=dt.datetime(2026,9,28,0,0,tzinfo=UTC)
EMBARGO_BARS=288
SEED=60111
SOURCE="https://data-api.binance.vision/api/v3/klines"
EVENTS={"1h":(12,0.007),"4h":(48,0.012)}
PRICE_HEADS={"1h":12,"4h":48,"morning_08msk":None}

def iso(ms:int)->str:
    return dt.datetime.fromtimestamp(ms/1000,UTC).isoformat()

def fetch_closed_5m(end=END,lookback_days=LOOKBACK_DAYS)->list:
    last_closed=int(end.timestamp()*1000)
    first=last_closed-lookback_days*86_400_000
    by={}
    cursor=last_closed-1
    calls=0
    while cursor>=first:
        params={"symbol":"BTCUSDT","interval":"5m","limit":1000,"endTime":cursor}
        url=SOURCE+"?"+urllib.parse.urlencode(params)
        error=None
        for attempt in range(4):
            try:
                req=urllib.request.Request(url,headers={"User-Agent":"btc-vnext6-research-closed-only"})
                with urllib.request.urlopen(req,timeout=25) as resp:
                    if resp.status!=200: raise ValueError("unexpected HTTP "+str(resp.status))
                    rows=json.load(resp)
                break
            except (TimeoutError,urllib.error.URLError,ValueError) as exc:
                error=exc; time.sleep((attempt+1)*1.5)
        else:
            raise RuntimeError("failed historical collection") from error
        if not rows: raise RuntimeError("empty Binance historical klines")
        for row in rows:
            t=int(row[0])
            if first<=t and int(row[6])+1<=last_closed:
                if t in by and by[t]!=row: raise ValueError("duplicate changed candle")
                by[t]=row
        cursor=int(rows[0][0])-1
        calls+=1
        if calls>50:raise ValueError("pagination exceeded bound")
        time.sleep(0.12)
    ordered=[by[k] for k in sorted(by)]
    if len(ordered)<12000: raise ValueError("historical dataset unexpectedly small")
    times=np.asarray([int(r[0]) for r in ordered],dtype=np.int64)
    if np.any(np.diff(times)!=STEP): raise ValueError("historical 5m grid has gaps")
    for r in ordered:
        if int(r[6])+1!=int(r[0])+STEP:raise ValueError("unclosed/misaligned candle")
        hi,lo,c,o,v,taker=map(float,[r[2],r[3],r[4],r[1],r[5],r[9]])
        if not (0<lo<=min(o,c)<=max(o,c)<=hi and v>=0 and 0<=taker<=v):
            raise ValueError("invalid market OHLC/taker volume")
    return ordered

def build_arrays(rows:list):
    arr=np.asarray([[float(r[j]) for j in (1,2,3,4,5,8,9)] for r in rows],dtype=float)
    return (np.asarray([int(r[0]) for r in rows],dtype=np.int64),arr)

def features(times, a):
    """No future indexes used. Each example is built ONLY from closed bars <= i."""
    opens,high,low,close,volume,trades,taker=[a[:,j] for j in range(7)]
    z=np.log(close)
    out=[]; idx=[]
    first=576 # 48h of pre-anchor closed data
    for i in range(first,len(times)-EMBARGO_BARS):
        f=[]
        for bars in (1,3,6,12,48,144):
            f.append(float(z[i]-z[i-bars]))
        for bars in (3,12,48):
            f.append(float((z[i]-z[i-bars])-(z[i-bars]-z[i-2*bars])))
        vol5=max(volume[i],1e-8)
        for bars in (1,3,12):
            v0=sum(volume[i-bars+1:i+1])
            f.append(float(sum(taker[i-bars+1:i+1])/max(v0,1e-8)))
        f.append(f[11]-float(sum(taker[i-23:i-11])/max(sum(volume[i-23:i-11]),1e-8)))
        f.append(float(np.log((volume[i]+1)/(np.mean(volume[i-12:i])+1))))
        f.append(float(np.log((trades[i]+1)/(np.mean(trades[i-12:i])+1))))
        f.append(float((high[i]-low[i])/close[i]))
        f.append(float((close[i]-np.max(high[i-12:i]))/close[i]))
        f.append(float((close[i]-np.min(low[i-12:i]))/close[i]))
        f.append(float(np.std(np.diff(z[i-12:i+1]))))
        f.append(float(np.std(np.diff(z[i-48:i+1]))))
        for bars in (3,12,48):
            w=np.diff(z[i-bars:i+1])
            f.append(float(abs(np.sum(w))/max(np.sum(np.abs(w)),1e-9)))
        tm=dt.datetime.fromtimestamp((int(times[i])+STEP)/1000,UTC)
        mins=tm.hour*60+tm.minute
        f.extend([math.sin(2*math.pi*mins/1440),math.cos(2*math.pi*mins/1440)])
        f.append(1.0 if tm.weekday()>=5 else 0.0)
        # Time until NEXT 08:00 Moscow, equivalently 05:00 UTC year round.
        next_morning=tm.replace(hour=5,minute=0,second=0,microsecond=0)
        if next_morning<=tm:next_morning+=dt.timedelta(days=1)
        morning_bars=int((next_morning-tm).total_seconds()/300)
        f.append(morning_bars/288)
        out.append(f);idx.append(i)
    return np.asarray(idx,dtype=int),np.asarray(out,dtype=np.float64)

def future_morning_bars(t):
    tm=dt.datetime.fromtimestamp((int(t)+STEP)/1000,UTC)
    morning=tm.replace(hour=5,minute=0,second=0,microsecond=0)
    if morning<=tm:morning+=dt.timedelta(days=1)
    return int((morning-tm).total_seconds()/300)

def build_targets(times,a,idx):
    high=a[:,1];low=a[:,2];close=a[:,3]
    result={}
    for name,h in PRICE_HEADS.items():
        steps=np.asarray([future_morning_bars(times[i]) for i in idx],dtype=int) if h is None else np.full(len(idx),h,dtype=int)
        result["price_"+name]=np.log(close[idx+steps]/close[idx])
    for name,(h,move) in EVENTS.items():
        peak=np.asarray([np.max(high[i+1:i+h+1])/close[i]-1 for i in idx])
        trough=np.asarray([np.min(low[i+1:i+h+1])/close[i]-1 for i in idx])
        result["large_up_"+name]=(peak>=move).astype(int)
        result["large_down_"+name]=(trough<=-move).astype(int)
    return result

def splits(times,idx):
    anchors=times[idx]+STEP
    va=int(VAL_START.timestamp()*1000);te=int(TEST_START.timestamp()*1000)
    # End-of-label embargo: no training label may extend into validation;
    # and no validation label may extend into test.
    train=np.where(anchors+24*3600*1000<va)[0]
    valid=np.where((anchors>=va)&(anchors+24*3600*1000<te))[0]
    test=np.where(anchors>=te)[0]
    if len(train)<3000 or len(valid)<1000 or len(test)<1000:raise ValueError("insufficient chronological split")
    return train,valid,test

def regression_metrics(actual_price,pred_price,persist_price):
    err=np.abs(pred_price-actual_price)
    base=np.abs(persist_price-actual_price)
    return {"n":len(err),"model_mae_usdt":float(np.mean(err)),
            "persistence_mae_usdt":float(np.mean(base)),
            "model_mae_gain_usdt":float(np.mean(base-err)),
            "model_rmse_usdt":float(np.sqrt(np.mean((pred_price-actual_price)**2))),
            "persistence_rmse_usdt":float(np.sqrt(np.mean((persist_price-actual_price)**2)))}

def classification_metrics(y,p):
    from sklearn.metrics import roc_auc_score,average_precision_score,brier_score_loss,log_loss
    y=np.asarray(y);p=np.clip(np.asarray(p,dtype=float),1e-6,1-1e-6)
    prior=float(np.mean(y))
    d={"n":int(len(y)),"positive":int(np.sum(y)),"prevalence":prior,
       "brier":float(brier_score_loss(y,p)),"baseline_brier":float(brier_score_loss(y,np.full(len(y),prior))),
       "logloss":float(log_loss(y,p,labels=[0,1])),
       "baseline_logloss":float(log_loss(y,np.full(len(y),prior),labels=[0,1]))}
    if 0<prior<1:
        d["roc_auc"]=float(roc_auc_score(y,p))
        d["pr_auc"]=float(average_precision_score(y,p))
        d["baseline_pr_auc"]=prior
    return d

def audit(rows,outdir:pathlib.Path):
    from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
    from sklearn.metrics import average_precision_score
    from sklearn.linear_model import LogisticRegression
    from joblib import dump
    outdir.mkdir(parents=True,exist_ok=True)
    times,a=build_arrays(rows)
    idx,x=features(times,a)
    labels=build_targets(times,a,idx)
    tr,va,te=splits(times,idx)
    c=a[idx,3]
    report={
        "schema":"btc-skill-rnd-v1","status":"RESEARCH_ONLY_NO_TRADING_AUTHORITY",
        "data_source":SOURCE,"symbol":"BTCUSDT","interval":"5m",
        "features":["closed spot OHLCV","trade count","taker buy volume"],
        "not_in_numeric_model":["OI","funding","ETF","macro","liquidations","orderbook"],
        "data_start_utc":iso(times[0]),"data_last_closed_utc":iso(times[-1]+STEP),
        "training_before_utc":VAL_START.isoformat(),"validation_start_utc":VAL_START.isoformat(),
        "test_start_utc":TEST_START.isoformat(),"test_cutoff_utc":END.isoformat(),
        "embargo_hours":24,"train_n":len(tr),"validation_n":len(va),"test_n":len(te),
        "thresholds":{"large_up_1h":0.007,"large_down_1h":-0.007,"large_up_4h":0.012,"large_down_4h":-0.012},
        "decision_use":"FORBIDDEN_UNTIL_PROSPECTIVE_VALIDATED",
        "prices":{},"events":{},"episode_2026_10_11":{},
    }
    models={}
    for target in PRICE_HEADS:
        name="price_"+target
        y=labels[name]
        model=HistGradientBoostingRegressor(
            loss="squared_error",learning_rate=0.035,max_iter=135,
            max_leaf_nodes=12,min_samples_leaf=105,l2_regularization=7.0,
            random_state=SEED)
        model.fit(x[tr],y[tr])
        # Validation-only shrinkage to prevent overfit; choose from a fixed 5-point grid.
        vpred=model.predict(x[va]);v_actual=c[va]*np.exp(y[va])
        shrink=min((0,0.25,0.5,0.75,1),key=lambda g:float(np.mean(np.abs(c[va]*np.exp(g*vpred)-v_actual))))
        tp=model.predict(x[te])*shrink
        actual=c[te]*np.exp(y[te]);pred=c[te]*np.exp(tp)
        metrics=regression_metrics(actual,pred,c[te])
        metrics["validation_selected_shrinkage"]=shrink
        metrics["beats_persistence"]=metrics["model_mae_gain_usdt"]>0
        report["prices"][target]=metrics
        models[target]=model
    for target in ("1h","4h"):
        for side in ("up","down"):
            name=f"large_{side}_{target}"
            y=labels[name]
            if np.sum(y[tr])<30 or np.sum(y[tr])==len(tr):
                report["events"][name]={"status":"INSUFFICIENT_TRAINING_EVENTS","train_positives":int(np.sum(y[tr]))}
                continue
            model=HistGradientBoostingClassifier(
                learning_rate=0.035,max_iter=130,max_leaf_nodes=10,
                min_samples_leaf=120,l2_regularization=10.0,
                random_state=SEED)
            model.fit(x[tr],y[tr])
            raw_va=np.clip(model.predict_proba(x[va])[:,1],1e-5,1-1e-5)
            raw_te=np.clip(model.predict_proba(x[te])[:,1],1e-5,1-1e-5)
            # Calibration uses validation labels only; fixed regularization and no test tuning.
            calibration=LogisticRegression(C=0.25,random_state=SEED)
            calibration.fit(np.log(raw_va/(1-raw_va)).reshape(-1,1),y[va])
            pv=calibration.predict_proba(np.log(raw_va/(1-raw_va)).reshape(-1,1))[:,1]
            pt=calibration.predict_proba(np.log(raw_te/(1-raw_te)).reshape(-1,1))[:,1]
            d=classification_metrics(y[te],pt)
            # Rank top <= 2 hourly-sampled alerts/day on validation, no test tuning.
            val_hour=(times[idx[va]]%(3600*1000))==(55*60*1000) # close at UTC hour (bar begins :55)
            test_hour=(times[idx[te]]%(3600*1000))==(55*60*1000)
            vh=pv[val_hour]; th=pt[test_hour]; yh=y[te][test_hour]
            limit=float(np.quantile(vh,1-2/24)) if len(vh)>0 else 1.0
            alarm=th>=limit
            d.update({"validation_alert_threshold":limit,
                      "test_alerts_per_day":float(np.sum(alarm)/(len(yh)/24)) if len(yh) else None,
                      "test_alert_precision":float(np.mean(yh[alarm])) if np.any(alarm) else None,
                      "test_alert_recall":float(np.sum(yh[alarm])/np.sum(yh)) if np.any(yh) else None,
                      "beats_constant_brier":d["brier"]<d["baseline_brier"],
                      "beats_constant_pr_auc":d.get("pr_auc",0)>d["prevalence"]})
            report["events"][name]=d
            models[name]=(model,calibration)
    # Holdout episode: both 18:30 & 18:45 Moscow 11 Oct 2026
    for hhmm in ("15:30","15:45","16:00"):
        ts=dt.datetime.fromisoformat("2026-10-11T"+hhmm+":00+00:00")
        matches=np.where(times[idx]+STEP==int(ts.timestamp()*1000))[0]
        if len(matches)!=1:continue
        j=int(matches[0]); event={"anchor_utc":ts.isoformat(),"btc_close":float(c[j])}
        for target in PRICE_HEADS:
            m=models[target];shr=report["prices"][target]["validation_selected_shrinkage"]
            event["price_"+target]=float(c[j]*np.exp(shr*m.predict(x[j:j+1])[0]))
        for target in ("1h","4h"):
            for side in ("up","down"):
                name=f"large_{side}_{target}"
                if name not in models:continue
                m,cal=models[name]
                p=float(np.clip(m.predict_proba(x[j:j+1])[0,1],1e-5,1-1e-5))
                event[name+"_prob"]=float(cal.predict_proba([[math.log(p/(1-p))]])[0,1])
                event[name+"_observed"]=int(labels[name][j])
                event[name+"_alert_threshold"]=report["events"][name]["validation_alert_threshold"]
        report["episode_2026_10_11"][hhmm]=event
    raw=json.dumps(rows,separators=(",",":")).encode()
    compressed=gzip.compress(raw,mtime=0)
    (outdir/"raw_5m_closed_klines.json.gz").write_bytes(compressed)
    report["raw_sha256"]=hashlib.sha256(raw).hexdigest()
    report["raw_compressed_sha256"]=hashlib.sha256(compressed).hexdigest()
    report["result_sha256_before_signing"]=None
    with (outdir/"research_result.json").open("w") as f:
        json.dump(report,f,sort_keys=True,indent=2,ensure_ascii=False);f.write("\n")
    dump(models,outdir/"research_models.joblib",compress=3)
    summary={"price_mae_gains":{k:round(v["model_mae_gain_usdt"],2) for k,v in report["prices"].items()},
             "classification_skill":{k:{"brier_better":v.get("beats_constant_brier"),"pr_auc_better":v.get("beats_constant_pr_auc"),
                                         "n":v.get("n"),"prevalence":v.get("prevalence")}
                                     for k,v in report["events"].items()},
             "episode":report["episode_2026_10_11"],
             "status":report["status"]}
    print("BTC_VNEXT6_RESEARCH_SUMMARY",json.dumps(summary,sort_keys=True,ensure_ascii=False),flush=True)
    return report

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--out",default="btc-skill-audit")
    p.add_argument("--existing-raw",default="")
    args=p.parse_args()
    if args.existing_raw:
        with gzip.open(args.existing_raw,"rb") as f:rows=json.load(f)
    else:
        rows=fetch_closed_5m()
    audit(rows,pathlib.Path(args.out))
if __name__=="__main__":main()
