"""Controlled spot-only versus spot+as-of futures comparison (RESEARCH ONLY).

Uses identical rows, 24-hour embargo, fixed model hyperparameters and the same
validation Platt calibration. Futures OI is lagged at least 5m after the vendor
observation timestamp, preventing synchronous point-in-time leakage.
"""
import datetime as dt,urllib.request,urllib.parse,urllib.error,time,json,gzip,hashlib,pathlib,math,argparse,bisect
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from btc_skill_rebuild.evaluate import (
    UTC, STEP, END, build_arrays,features,build_targets,classification_metrics,
    SEED, VAL_START, TEST_START
)
START=dt.datetime(2026,9,14,0,0,tzinfo=UTC)
END_MS=int(END.timestamp()*1000)
START_MS=int(START.timestamp()*1000)
BASE_FAPI="https://fapi.binance.com"
BASE_DAPI="https://dapi.binance.com"

def get_json(base,path,params):
    url=base+path+"?"+urllib.parse.urlencode(params)
    for attempt in range(4):
        try:
            req=urllib.request.Request(url,headers={"User-Agent":"btc-vnext6-causal-oi-audit"})
            with urllib.request.urlopen(req,timeout=30) as r:
                if r.status!=200:raise ValueError("HTTP "+str(r.status))
                return json.load(r)
        except (TimeoutError,urllib.error.URLError,ValueError) as e:
            if attempt==3:raise
            time.sleep(2+attempt*2)

def get_oi(base,path,other):
    result={}
    cursor=START_MS
    while cursor<END_MS:
        top=min(cursor+499*STEP,END_MS)
        params={**other,"period":"5m","limit":500,"startTime":cursor,"endTime":top}
        rows=get_json(base,path,params)
        if not isinstance(rows,list):raise ValueError("invalid OI rows")
        if not rows:raise ValueError("empty OI period "+str(cursor))
        for row in rows:
            t=int(row["timestamp"])
            if START_MS<=t<=END_MS:
                val=float(row["sumOpenInterestValue"])
                if not (math.isfinite(val) and val>0):raise ValueError("invalid OI")
                if t in result and abs(val-result[t])>1e-8:raise ValueError("changed OI value")
                result[t]=val
        cursor=top+STEP
        time.sleep(.14)
    if len(result)<6500:raise ValueError("short futures OI history "+str(len(result)))
    return result

def get_funding():
    rows=get_json(BASE_FAPI,"/fapi/v1/fundingRate",
                  {"symbol":"BTCUSDT","limit":1000,"startTime":START_MS-86_400_000,"endTime":END_MS})
    if not isinstance(rows,list) or len(rows)<65:raise ValueError("incomplete funding history")
    out={}
    for r in rows:
        t=int(r["fundingTime"]);v=float(r["fundingRate"])
        if math.isfinite(v):out[t]=v
    return out

def aligned_derivatives(times,idx,um,cm,funding):
    """USDT-M required; COIN-M optional with <=15m causal as-of lag and age flag."""
    results=[];mask=[]
    fund_ts=sorted(funding);cm_ts=sorted(cm)
    for j,i in enumerate(idx):
        # Market input must have existed at least 5 minutes before this decision.
        observed=int(times[i]) # candle closes at observed + STEP
        lookback=(observed,observed-3*STEP,observed-12*STEP)
        if not all(t in um for t in lookback):continue
        pos=bisect.bisect_right(fund_ts,observed)-1
        if pos<0 or observed-fund_ts[pos]>9*3600*1000:continue
        def oi_features(vals):
            a,b,c=vals
            return [math.log(a/b),math.log(a/c),math.log(a)]
        # Missing OPTIONAL COIN-M observations must not exclude a fast impulse.
        cm_values=[];stale=[]
        for t in lookback:
            k=bisect.bisect_right(cm_ts,t)-1
            if k<0 or t-cm_ts[k]>3*STEP:
                cm_values=[];stale=[];break
            cm_values.append(cm[cm_ts[k]])
            stale.append(t-cm_ts[k])
        if len(cm_values)==3:
            cmfeat=oi_features(cm_values)
            age=float(stale[0]/(3*STEP));missing=0.0
        else:
            cmfeat=[0.0,0.0,0.0]
            age=1.0;missing=1.0
        x=oi_features([um[t] for t in lookback])+cmfeat+[funding[fund_ts[pos]],age,missing]
        if not np.all(np.isfinite(x)):raise ValueError("non-finite derivatives")
        mask.append(j);results.append(x)
    return np.asarray(mask,dtype=int),np.asarray(results,dtype=float)

def fit_eval(x,y,tr,va,te):
    tr=tr[np.isfinite(y[tr])];va=va[np.isfinite(y[va])];te=te[np.isfinite(y[te])]
    if np.sum(y[tr])<30 or len(np.unique(y[va]))!=2:return {"status":"INSUFFICIENT_EVENTS"}
    model=HistGradientBoostingClassifier(
        learning_rate=0.035,max_iter=130,max_leaf_nodes=10,
        min_samples_leaf=120,l2_regularization=10,random_state=SEED)
    model.fit(x[tr],y[tr])
    pv=np.clip(model.predict_proba(x[va])[:,1],1e-5,1-1e-5)
    pt=np.clip(model.predict_proba(x[te])[:,1],1e-5,1-1e-5)
    cal=LogisticRegression(C=.25,random_state=SEED)
    cal.fit(np.log(pv/(1-pv)).reshape(-1,1),y[va])
    prob=cal.predict_proba(np.log(pt/(1-pt)).reshape(-1,1))[:,1]
    stats=classification_metrics(y[te],prob)
    return {"stats":stats,"model":model,"cal":cal}

def audit(spot_rows,output,futures_raw):
    times,a=build_arrays(spot_rows)
    idx,base=features(times,a)
    labels=build_targets(times,a,idx)
    with gzip.open(futures_raw,"rt") as f:external=json.load(f)
    if external.get("schema")!="btc-vnext6-historical-futures-mac-collector-v1":
        raise ValueError("unexpected historical futures raw provenance")
    um={int(k):float(v) for k,v in external["um"].items()}
    cm={int(k):float(v) for k,v in external["cm"].items()}
    funding={int(k):float(v) for k,v in external["funding"].items()}
    ix,deriv=aligned_derivatives(times,idx,um,cm,funding)
    anchor=times[idx[ix]]+STEP
    va_ms=int(VAL_START.timestamp()*1000)
    te_ms=int(TEST_START.timestamp()*1000)
    # 24h embargo preserved at each train/validation border.
    tr=np.where((anchor+86_400_000<va_ms))[0]
    va=np.where((anchor>=va_ms)&(anchor+86_400_000<te_ms))[0]
    te=np.where(anchor>=te_ms)[0]
    if min(len(tr),len(va),len(te))<450:raise ValueError("insufficient as-of historical overlap")
    x0=base[ix]; x1=np.hstack([x0,deriv])
    report={"schema":"btc-vnext6-derivatives-incremental-v1",
            "status":"RESEARCH_ONLY_NO_TRADING_AUTHORITY",
            "source_spot":"Binance 5m OHLCV",
            "source_um":"Binance USD-M 5m OI sumOpenInterestValue",
            "source_cm":"Binance COIN-M perpetual 5m OI sumOpenInterestValue",
            "source_funding":"Binance USD-M fundingRate settlement history",
            "collection_provenance":external["collector"],
            "point_in_time_publication_proven":False,
            "minimum_feature_lag_seconds":300,
            "optional_coinm_max_age_minutes":15,
            "missing_coinm_never_eliminates_required_usdtm_row":True,
            "sample_counts":{"training":len(tr),"validation":len(va),"test":len(te)},
            "metrics":{},"episode":{}}
    trained={}
    for h in ("1h","4h"):
        for side in ("up","down"):
            name=f"large_{side}_{h}"
            y=labels[name][ix]
            a0=fit_eval(x0,y,tr,va,te);a1=fit_eval(x1,y,tr,va,te)
            m0=a0.get("stats");m1=a1.get("stats")
            report["metrics"][name]={"spot_only":m0,"with_derivatives":m1,
                "delta_brier_spot_minus_derivatives":m0["brier"]-m1["brier"] if m0 and m1 else None,
                "delta_pr_auc":m1["pr_auc"]-m0["pr_auc"] if m0 and m1 else None}
            if "model" in a0 and "model" in a1:trained[name]=(a0,a1)
    for hhmm in ("15:30","15:45","16:00"):
        t=int(dt.datetime.fromisoformat("2026-10-11T"+hhmm+":00+00:00").timestamp()*1000)
        where=np.where(anchor==t)[0]
        if not len(where):continue
        j=int(where[0]);one={"anchor_utc":dt.datetime.fromtimestamp(t/1000,UTC).isoformat()}
        for name,(a0,a1) in trained.items():
            def pred(obj,vec):
                raw=float(np.clip(obj["model"].predict_proba(vec.reshape(1,-1))[0,1],1e-5,1-1e-5))
                return float(obj["cal"].predict_proba([[math.log(raw/(1-raw))]])[0,1])
            one[name]={"spot_only":pred(a0,x0[j]),
                       "with_derivatives":pred(a1,x1[j]),
                       "observed":int(labels[name][ix[j]]) if np.isfinite(labels[name][ix[j]]) else None}
        one["oi_usdtm_15m_change_pct"]=100*(math.exp(deriv[j,0])-1)
        one["oi_coinm_15m_change_pct"]=100*(math.exp(deriv[j,3])-1)
        one["funding"]=float(deriv[j,6])
        one["coinm_staleness_ratio"]=float(deriv[j,7])
        one["coinm_missing_flag"]=bool(deriv[j,8])
        report["episode"][hhmm]=one
    output.mkdir(parents=True,exist_ok=True)
    evidence={"um":um,"cm":cm,"funding":funding}
    raw=json.dumps(evidence,sort_keys=True,separators=(",",":")).encode()
    report["raw_derivatives_sha256"]=hashlib.sha256(raw).hexdigest()
    with (output/"raw_derivatives.json.gz").open("wb") as f:
        with gzip.GzipFile(fileobj=f,mode="wb",mtime=0) as z:z.write(raw)
    (output/"incremental_report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True)+"\n")
    print("BTC_VNEXT6_INCREMENTAL_OI_REPORT",json.dumps(report,ensure_ascii=False,sort_keys=True),flush=True)
    return report

def main():
    p=argparse.ArgumentParser();p.add_argument("--spot-raw",required=True);p.add_argument("--out",required=True);p.add_argument("--futures-raw",required=True)
    a=p.parse_args()
    with gzip.open(a.spot_raw,"rt") as f:rows=json.load(f)
    audit(rows,pathlib.Path(a.out),a.futures_raw)
if __name__=="__main__":main()
