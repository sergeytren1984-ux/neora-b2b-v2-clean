"""Third controlled skill comparison: 1-minute spot flow vs 5-minute baseline.

NO trading authority. Research-only 1m history is retrieved directly inside
GitHub; frozen 5m+futures data is verified before training.
"""
import argparse,datetime as dt,gzip,hashlib,json,math,pathlib,time,urllib.parse,urllib.request
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier,HistGradientBoostingRegressor
from sklearn.linear_model import LogisticRegression
from btc_skill_rebuild.evaluate import (
 UTC,STEP,END,features,build_arrays,build_targets,
 classification_metrics,regression_metrics,SEED,VAL_START,TEST_START
)
from btc_skill_rebuild.evaluate_derivatives import aligned_derivatives

MIN=60000
ONE_MIN_START=dt.datetime(2026,9,14,tzinfo=UTC)
def fetch_1m():
    last=int(END.timestamp()*1000); first=int(ONE_MIN_START.timestamp()*1000)
    values={};cursor=last-1;calls=0
    while cursor>=first:
        q=urllib.parse.urlencode({"symbol":"BTCUSDT","interval":"1m","limit":1000,"endTime":cursor})
        url="https://data-api.binance.vision/api/v3/klines?"+q
        err=None
        for retry in range(4):
            try:
                request=urllib.request.Request(url,headers={"User-Agent":"btc-vnext6-minute-research"})
                with urllib.request.urlopen(request,timeout=30) as r:rows=json.load(r)
                break
            except Exception as e:
                err=e;time.sleep((retry+1)*1.5)
        else:raise RuntimeError("missing 1m Binance data") from err
        if not rows:raise ValueError("empty 1m page")
        for row in rows:
            t=int(row[0])
            if first<=t and int(row[6])+1<=last:
                if t in values and values[t]!=row:raise ValueError("changed 1m candle")
                values[t]=row
        cursor=int(rows[0][0])-1
        calls+=1
        if calls>55:raise ValueError("1m pagination limit")
        time.sleep(.09)
    ordered=[values[t] for t in sorted(values)]
    if len(ordered)<37000:raise ValueError("insufficient 1m history "+str(len(ordered)))
    ts=np.asarray([int(x[0]) for x in ordered],dtype=np.int64)
    if np.any(np.diff(ts)!=MIN):raise ValueError("1m data gaps")
    for r in ordered:
        if int(r[6])+1!=int(r[0])+MIN:raise ValueError("unclosed 1m candle")
        h,l,c,o,v,taker=map(float,[r[2],r[3],r[4],r[1],r[5],r[9]])
        if not (0<l<=min(o,c)<=max(o,c)<=h and 0<=taker<=v):
            raise ValueError("invalid 1m candle")
    return ordered

def micro_features(minute_rows,times5,idx5):
    ts=np.asarray([int(x[0]) for x in minute_rows],dtype=np.int64)
    m=np.asarray([[float(x[j]) for j in (2,3,4,5,8,9)] for x in minute_rows])
    h,l,c,v,trades,taker=[m[:,k] for k in range(6)]
    indices=[];out=[]
    # The raw 1m candle used must close no later than the 5m forecast anchor.
    start_ms=int(ts[0]);end_ms=int(ts[-1]+MIN)
    for j,i in enumerate(idx5):
        anchor=int(times5[i]+STEP)
        if anchor<start_ms+61*MIN or anchor>end_ms:continue
        k=(anchor-start_ms)//MIN-1
        if k<60 or k>=len(ts) or int(ts[k])+MIN!=anchor:continue
        def frac(w):
            return float(np.sum(taker[k-w+1:k+1])/max(np.sum(v[k-w+1:k+1]),1e-9))
        def ret(w):
            return float(c[k]/c[k-w]-1)
        tv1,tv3,tv5,tv15=(frac(w) for w in (1,3,5,15))
        vx5=np.sum(v[k-4:k+1]);vx15prev=np.sum(v[k-19:k-4])
        tx5=np.sum(trades[k-4:k+1]);tx15prev=np.sum(trades[k-19:k-4])
        f=[
            ret(1),ret(3),ret(5),ret(15),ret(30),
            ret(5)-float(c[k-5]/c[k-10]-1),
            tv1,tv3,tv5,tv15,
            tv5-float(np.sum(taker[k-9:k-4])/max(np.sum(v[k-9:k-4]),1e-9)),
            math.log((vx5+1)/(vx15prev/3+1)),
            math.log((tx5+1)/(tx15prev/3+1)),
            float((c[k]-np.max(h[k-19:k-4]))/c[k]),
            float((c[k]-np.min(l[k-19:k-4]))/c[k]),
            float((np.max(h[k-4:k+1])-np.min(l[k-4:k+1]))/c[k]),
        ]
        if not np.all(np.isfinite(f)):raise ValueError("non-finite micro features")
        out.append(f);indices.append(j)
    return np.asarray(indices,dtype=int),np.asarray(out,dtype=float)

def eval_class(x,y,tr,va,te):
    tr=tr[np.isfinite(y[tr])];va=va[np.isfinite(y[va])];te=te[np.isfinite(y[te])]
    if np.sum(y[tr])<25 or np.unique(y[va]).size<2:return {"status":"INSUFFICIENT"}
    m=HistGradientBoostingClassifier(random_state=SEED,learning_rate=.035,
         max_iter=130,max_leaf_nodes=10,min_samples_leaf=120,l2_regularization=10.)
    m.fit(x[tr],y[tr])
    pv=np.clip(m.predict_proba(x[va])[:,1],1e-5,1-1e-5)
    pt=np.clip(m.predict_proba(x[te])[:,1],1e-5,1-1e-5)
    cal=LogisticRegression(C=.25,random_state=SEED)
    cal.fit(np.log(pv/(1-pv)).reshape(-1,1),y[va])
    pp=cal.predict_proba(np.log(pt/(1-pt)).reshape(-1,1))[:,1]
    return {"stats":classification_metrics(y[te],pp),"model":m,"cal":cal}

def eval_price(x,y,c,tr,va,te):
    tr=tr[np.isfinite(y[tr])];va=va[np.isfinite(y[va])];te=te[np.isfinite(y[te])]
    m=HistGradientBoostingRegressor(loss="squared_error",learning_rate=.035,max_iter=135,
        max_leaf_nodes=12,min_samples_leaf=105,l2_regularization=7,random_state=SEED)
    m.fit(x[tr],y[tr])
    pv=m.predict(x[va]);vactual=c[va]*np.exp(y[va])
    shrink=min((0,.25,.5,.75,1),key=lambda s:np.mean(np.abs(c[va]*np.exp(s*pv)-vactual)))
    p=c[te]*np.exp(shrink*m.predict(x[te]))
    metrics=regression_metrics(c[te]*np.exp(y[te]),p,c[te])
    metrics["validation_shrinkage"]=shrink
    return metrics

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--spot-raw",required=True);p.add_argument("--futures-raw",required=True)
    p.add_argument("--out",required=True);a=p.parse_args()
    with gzip.open(a.spot_raw,"rt") as f:spot=json.load(f)
    with gzip.open(a.futures_raw,"rt") as f:futures=json.load(f)
    if futures["schema"]!="btc-vnext6-historical-futures-mac-collector-v1":
        raise ValueError("noncanonical futures data")
    times,xraw=build_arrays(spot)
    idx,base=features(times,xraw)
    labels=build_targets(times,xraw,idx)
    minute=fetch_1m()
    m_ix,m_feat=micro_features(minute,times,idx)
    um={int(k):v for k,v in futures["um"].items()}
    cm={int(k):v for k,v in futures["cm"].items()}
    funding={int(k):v for k,v in futures["funding"].items()}
    d_ix,d_feat=aligned_derivatives(times,idx,um,cm,funding)
    # Explicit intersection, identical targets, identical chronology for candidates.
    avail={int(k):j for j,k in enumerate(d_ix)}
    micro_pairs=[(n,avail[int(j)]) for n,j in enumerate(m_ix) if int(j) in avail]
    ix=np.asarray([int(m_ix[i]) for i,_ in micro_pairs],dtype=int)
    m_ix2=np.asarray([i for i,_ in micro_pairs],dtype=int)
    d_ix2=np.asarray([j for _,j in micro_pairs],dtype=int)
    anchor=times[idx[ix]]+STEP
    split_v=int(VAL_START.timestamp()*1000);split_t=int(TEST_START.timestamp()*1000)
    tr=np.where(anchor+86_400_000<split_v)[0]
    va=np.where((anchor>=split_v)&(anchor+86_400_000<split_t))[0]
    te=np.where(anchor>=split_t)[0]
    if min(len(tr),len(va),len(te))<400:raise ValueError("too few matched samples")
    spot_x=base[ix];micro_x=np.hstack([spot_x,m_feat[m_ix2]])
    full_x=np.hstack([micro_x,d_feat[d_ix2]])
    x_set={"spot_only":spot_x,"with_1m_flow":micro_x,"with_1m_and_futures":full_x}
    report={"schema":"btc-vnext6-minute-microstructure-research-v1",
            "status":"RESEARCH_ONLY_NO_TRADING_AUTHORITY",
            "historical_coinm_point_in_time_publication_proven":False,
            "closed_spot_1m_candles":len(minute),
            "counts":{"train":len(tr),"validation":len(va),"test":len(te)},
            "events":{},"price":{},"episode":{}}
    models={}
    for h in ("1h","4h"):
        for side in ("up","down"):
            name=f"large_{side}_{h}";y=labels[name][ix]
            fit={k:eval_class(x,y,tr,va,te) for k,x in x_set.items()}
            report["events"][name]={k:v.get("stats",{"status":v.get("status")}) for k,v in fit.items()}
            models[name]=fit
    close=xraw[idx[ix],3]
    for h in ("1h","4h","morning_08msk"):
        y=labels["price_"+h][ix]
        report["price"][h]={k:eval_price(x,y,close,tr,va,te) for k,x in x_set.items()}
    for hhmm in ("15:30","15:45","16:00"):
        t=int(dt.datetime.fromisoformat("2026-10-11T"+hhmm+":00+00:00").timestamp()*1000)
        where=np.where(anchor==t)[0]
        if not len(where):continue
        j=int(where[0]);one={"anchor_utc":dt.datetime.fromtimestamp(t/1000,UTC).isoformat(),"close":float(close[j])}
        for name,fits in models.items():
            part={}
            for k,v in fits.items():
                if "model" not in v:continue
                raw=float(np.clip(v["model"].predict_proba(x_set[k][j:j+1])[0,1],1e-5,1-1e-5))
                part[k]=float(v["cal"].predict_proba([[math.log(raw/(1-raw))]])[0,1])
            part["observed"]=int(labels[name][ix[j]]) if np.isfinite(labels[name][ix[j]]) else None
            one[name]=part
        report["episode"][hhmm]=one
    out=pathlib.Path(a.out);out.mkdir(parents=True,exist_ok=True)
    raw=json.dumps(minute,separators=(",",":")).encode()
    report["raw_1m_sha256"]=hashlib.sha256(raw).hexdigest()
    with (out/"raw_minute_klines.json.gz").open("wb") as f:
        with gzip.GzipFile(fileobj=f,mode="wb",mtime=0) as z:z.write(raw)
    (out/"micro_audit.json").write_text(json.dumps(report,sort_keys=True,indent=2,ensure_ascii=False)+"\n")
    summary={"events":{k:{cand:{"brier":v["brier"],"pr_auc":v["pr_auc"],"n":v["n"]} if "brier" in v else v
                               for cand,v in table.items()} for k,table in report["events"].items()},
             "price_mae":{h:{cand:round(v["model_mae_usdt"],2) for cand,v in table.items()} for h,table in report["price"].items()},
             "episode":report["episode"]}
    print("BTC_VNEXT6_MICRO_AUDIT",json.dumps(summary,ensure_ascii=False,sort_keys=True),flush=True)

if __name__=="__main__":main()
