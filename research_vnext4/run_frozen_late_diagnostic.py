"""Late-period diagnostic of the exact frozen vNext4 artifacts.

The production artifacts are not re-fit. Jul-Sep 2026 is treated as inspected
diagnostic history, not confirmatory evidence. Baselines are reconstructed causally:
only outcomes whose due time precedes each anchor may enter vol90d.
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from pathlib import Path
import joblib
import numpy as np

from predictive_vnext4.core import (
    read_klines,build_hourly_features,build_15m_features,
    target_distance,target_percent,metrics,full_proba
)

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"research_vnext4/frozen_late_diagnostic.json"


def fetch_range(interval,duration_ms,start_iso,end_iso):
    start=int(np.datetime64(start_iso,"ms").astype(np.int64))
    end=int(np.datetime64(end_iso,"ms").astype(np.int64))-1
    rows=[];cursor=start
    while cursor<=end:
        q=urllib.parse.urlencode({"symbol":"BTCUSDT","interval":interval,
                                  "startTime":cursor,"endTime":end,"limit":1000})
        req=urllib.request.Request("https://data-api.binance.vision/api/v3/klines?"+q,
                                   headers={"User-Agent":"vnext4-late-diagnostic"})
        with urllib.request.urlopen(req,timeout=30) as resp:
            batch=json.loads(resp.read())
        if not batch:break
        rows.extend(batch)
        nxt=int(batch[-1][0])+duration_ms
        if nxt<=cursor:raise RuntimeError("cursor stalled")
        cursor=nxt
        if len(batch)<1000:break
    uniq={int(r[0]):r for r in rows}
    rows=[uniq[k] for k in sorted(uniq)]
    if any(int(b[0])-int(a[0])!=duration_ms for a,b in zip(rows,rows[1:])):
        raise ValueError("gap in fetched diagnostic range")
    return rows


def arrays(rows):
    t=np.asarray([int(r[0]) for r in rows],dtype=np.int64)
    o=np.asarray([float(r[1]) for r in rows]);hi=np.asarray([float(r[2]) for r in rows])
    lo=np.asarray([float(r[3]) for r in rows]);c=np.asarray([float(r[4]) for r in rows])
    v=np.asarray([float(r[5]) for r in rows]);tr=np.asarray([float(r[8]) for r in rows])
    tk=np.asarray([float(r[9]) for r in rows])
    return t,o,hi,lo,c,v,tr,tk


def calibrate_with(model_spec,raw):
    cal=model_spec["calibrator"]
    return full_proba(cal,np.log(np.clip(raw,1e-8,1)))


def batch_predictions(artifact,X):
    out={}
    for name in artifact["contenders"]:
        spec=artifact["models"][name]
        if name in ("logistic","gbdt"):
            raw=full_proba(spec["model"],X)
        else:
            horizon=int(spec["horizon_steps"]);step=int(spec["hazard_step"])
            raw=np.zeros((len(X),4));survive=np.ones(len(X))
            for elapsed in range(step,horizon+1,step):
                h=full_proba(spec["model"],np.column_stack((X,np.full(len(X),elapsed/horizon))))
                raw[:,0]+=survive*h[:,0];raw[:,1]+=survive*h[:,1];raw[:,3]+=survive*h[:,3]
                survive*=h[:,2]
            raw[:,2]=survive;raw/=np.maximum(raw.sum(axis=1,keepdims=True),1e-12)
        out[name]=calibrate_with(spec,raw)
    return out


def causal_control(artifact,dates,y,vol,due_delta,test_mask):
    ctrl=artifact["control"];q=np.asarray(ctrl["vol_quantiles"])
    vb=np.digitize(vol,q,right=True);train=np.asarray(ctrl["training_frequency"])
    due=dates+due_delta
    ids=np.flatnonzero(test_mask);p=np.zeros((len(ids),4))
    sources=[]
    for pos,i in enumerate(ids):
        start=dates[i]-np.timedelta64(int(ctrl["vol90d_window_days"]),"D")
        elig=(dates>=start)&(dates<dates[i])&(due<dates[i])&(vb==vb[i])
        if np.sum(elig)>=int(ctrl["vol90d_min_same_bin"]):
            cnt=np.bincount(y[elig],minlength=4).astype(float)+.5
            p[pos]=cnt/cnt.sum();sources.append("vol90d")
        else:
            p[pos]=train;sources.append("training_fallback")
    return p,vb[ids],sources



def paired_block_ci(reference,p,y,dates,block_days,n_boot=1200):
    one=np.eye(4)[y];eps=1e-12
    bg=np.sum((reference-one)**2,axis=1)-np.sum((p-one)**2,axis=1)
    lg=-np.log(np.clip(reference[np.arange(len(y)),y],eps,1))+np.log(np.clip(p[np.arange(len(y)),y],eps,1))
    ds=np.asarray(dates,dtype="datetime64[s]")
    origin=ds.min().astype("datetime64[D]")
    bid=((ds.astype("datetime64[D]")-origin)/np.timedelta64(block_days,"D")).astype(int)
    groups=[np.flatnonzero(bid==x) for x in np.unique(bid)]
    if len(groups)<3:
        return {"brier_gain_ci95":None,"logloss_gain_ci95":None,"block_count":len(groups)}
    rng=np.random.default_rng(20261004+block_days);bb=[];ll=[]
    for _ in range(n_boot):
        ids=np.concatenate([groups[j] for j in rng.integers(len(groups),size=len(groups))])
        bb.append(float(np.mean(bg[ids])));ll.append(float(np.mean(lg[ids])))
    return {
        "brier_gain_ci95":[float(x) for x in np.quantile(bb,[.025,.975])],
        "logloss_gain_ci95":[float(x) for x in np.quantile(ll,[.025,.975])],
        "block_count":len(groups)
    }

def fixed_nonoverlap(dates,horizon_steps):
    ids=np.arange(len(dates))
    return ids%horizon_steps==0


def alert_stats(p,y,artifact,model):
    result={}
    th=artifact["alert_thresholds"][model]
    for cls,name in ((0,"lower"),(1,"upper")):
        alert=p[:,cls]>=float(th[name+"_first_fpr20"])
        actual=y==cls
        tp=int(np.sum(alert&actual));fp=int(np.sum(alert&~actual))
        fn=int(np.sum(~alert&actual));tn=int(np.sum(~alert&~actual))
        result[name]={
            "tp":tp,"fp":fp,"fn":fn,"tn":tn,
            "recall":None if tp+fn==0 else tp/(tp+fn),
            "miss_rate":None if tp+fn==0 else fn/(tp+fn),
            "fpr":None if fp+tn==0 else fp/(fp+tn),
            "precision":None if tp+fp==0 else tp/(tp+fp),
            "false_alert_share":None if tp+fp==0 else fp/(tp+fp),
            "alerts_per_100_anchors":100*float(np.mean(alert)),
        }
    return result


def evaluate(artifact,X,dates,y,vol,due_delta,test_mask,nonstep):
    ids=np.flatnonzero(test_mask);Xt=X[ids];yt=y[ids];dt=dates[ids]
    baseline,bins,sources=causal_control(artifact,dates,y,vol,due_delta,test_mask)
    preds=batch_predictions(artifact,Xt)
    non=fixed_nonoverlap(dt,nonstep)
    out={
      "n_overlapping":len(ids),"n_nonoverlap":int(np.sum(non)),
      "baseline_overlapping":metrics(baseline,yt),
      "baseline_nonoverlap":metrics(baseline[non],yt[non]),
      "baseline_source_counts":{s:sources.count(s) for s in sorted(set(sources))},
      "models":{}
    }
    for name,p in preds.items():
        out["models"][name]={
          "overlapping":metrics(p,yt),
          "nonoverlap":metrics(p[non],yt[non]),
          "paired_uncertainty_nonoverlap":{
              "14d":paired_block_ci(baseline[non],p[non],yt[non],dt[non],14),
              "28d":paired_block_ci(baseline[non],p[non],yt[non],dt[non],28)
          },
          "early_warning_overlapping":alert_stats(p,yt,artifact,name),
          "early_warning_nonoverlap":alert_stats(p[non],yt[non],artifact,name),
        }
    return out


def main():
    hourly_art=joblib.load(ROOT/"predictive_vnext4/hourly_contenders.joblib")
    t,o,hi,lo,c,v,tr,tk,hsha=read_klines(ROOT/"btc_1h_2024_to_sep24_2026.json",3600000)
    ix,dates,X,names,reg,vol,atr=build_hourly_features(t,hi,lo,c,v,tr,tk,168)
    dist=c[ix]*vol*np.sqrt(72.0)
    y,when=target_distance(ix,c,hi,lo,dist,72)
    htest=(dates>=np.datetime64("2026-07-02"))&(dates<np.datetime64("2026-09-21"))
    hourly=evaluate(hourly_art,X,dates,y,vol,np.timedelta64(72,"h"),htest,72)

    # Fetch enough 15m history for causal 90d baseline and late-period labels.
    rows=fetch_range("15m",900000,"2026-03-15T00:00:00","2026-10-01T00:00:00")
    t,o,hi,lo,c,v,tr,tk=arrays(rows)
    ix,dates,X,names,reg,vol=build_15m_features(t,hi,lo,c,v,tr,tk,16)
    y,when=target_percent(ix,c,hi,lo,.99,1.01,16)
    early_art=joblib.load(ROOT/"predictive_vnext4/early15m_contenders.joblib")
    etest=(dates>=np.datetime64("2026-07-02"))&(dates<np.datetime64("2026-09-30T20:00"))
    early=evaluate(early_art,X,dates,y,vol,np.timedelta64(240,"m"),etest,16)

    result={
      "schema":"btc-predictive-vnext4-frozen-late-diagnostic-v1",
      "research_only":True,"trading_authority":False,
      "historical_status":"INSPECTED_DIAGNOSTIC_NOT_CONFIRMATORY",
      "important":"Exact frozen production artifacts are evaluated without refitting. Results cannot be used to call vNext4 prospectively validated.",
      "hourly":hourly,"early15m":early
    }
    OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2,sort_keys=True)+"\n")
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=="__main__":main()
