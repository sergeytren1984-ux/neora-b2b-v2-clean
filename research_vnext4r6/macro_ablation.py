"""R6 exogenous macro-market ablation for the 24h head.

No macro feature is eligible merely because it is economically plausible.
All exogenous observations use conservative availability times. Test folds are
chronological and never used to choose feature values or availability lags.
"""
from __future__ import annotations
import json
from datetime import datetime,timezone,timedelta
from pathlib import Path
import numpy as np

from predictive_vnext4.core import (
  read_klines,build_hourly_features,target_distance,masks,fit_candidates,
  adaptive_baselines,metrics,block_ci
)

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/"research_vnext4r6"
UTC=timezone.utc


def ms(dt):
    return int(dt.timestamp()*1000)


def market_features(anchors_ms,doc):
    cols=[]
    valid=np.ones(len(anchors_ms),dtype=bool)
    meta={}
    for key in ("dxy","nasdaq_futures","us10y"):
        pts=doc["series"][key]["points"]
        t=np.asarray([ms(datetime.fromisoformat(x["timestamp_utc"]))+24*3600000 for x in pts],dtype=np.int64)
        v=np.asarray([float(x["close"]) for x in pts],dtype=float)
        idx=np.searchsorted(t,anchors_ms,side="right")-1
        ok=idx>=5
        safe=np.maximum(idx,5)
        age=anchors_ms-t[safe]
        ok &= age>=0
        ok &= age<=5*24*3600000  # weekends/holidays allowed, long stale gaps rejected
        valid &= ok
        if key=="us10y":
            f1=v[safe]-v[safe-1]
            f5=v[safe]-v[safe-5]
            lev=v[safe]
        else:
            f1=np.log(v[safe]/v[safe-1])
            f5=np.log(v[safe]/v[safe-5])
            lev=np.log(v[safe])
        cols.extend([lev,f1,f5])
        meta[key+"_raw_sha256"]=doc["series"][key]["raw_sha256"]
    return np.column_stack(cols),valid,meta


def etf_features(anchors_ms,doc):
    rows=doc["series"]["etf_flows"]["rows"]
    if len(rows)<100:
        return np.zeros((len(anchors_ms),2)),np.zeros(len(anchors_ms),dtype=bool),{
          "status":"INSUFFICIENT_HISTORY","rows":len(rows),
          "raw_sha256":doc["series"]["etf_flows"]["raw_sha256"]}
    at=[];vals=[]
    for r in rows:
        d=datetime.fromisoformat(r["date"]+"T12:00:00+00:00")+timedelta(days=1)
        at.append(ms(d));vals.append(float(r["total_usd_millions"]))
    at=np.asarray(at,dtype=np.int64);vals=np.asarray(vals)
    idx=np.searchsorted(at,anchors_ms,side="right")-1
    ok=idx>=2
    safe=np.maximum(idx,2)
    age=anchors_ms-at[safe]
    ok &= (age>=0)&(age<=7*24*3600000)
    f=np.column_stack((vals[safe],vals[safe]+vals[safe-1]+vals[safe-2]))
    return f,ok,{"status":"OK","rows":len(rows),"raw_sha256":doc["series"]["etf_flows"]["raw_sha256"]}


def fold_scores(X,regime,vol,dates,y,when,train,cal,test):
    due=np.timedelta64(24,"h")
    pred=fit_candidates(X,regime,y,when,train,cal,test,24,3)
    base=adaptive_baselines(dates,y,regime,vol,train,test,due)
    pred.update(base)
    yt=y[test];dt=dates[test];primary=pred["vol90d"]
    out={}
    one=np.eye(4)[yt]
    for name,p in pred.items():
        m=metrics(p,yt)
        m["brier_gain_vs_vol90d_ci95"]=block_ci(primary,p,yt,dt)
        m["brier_gain_vs_vol90d_mean"]=float(np.mean(
          np.sum((primary-one)**2,axis=1)-np.sum((p-one)**2,axis=1)))
        out[name]=m
    return out


def main():
    macro=json.loads((DATA/"macro_history.json").read_text())
    hist=ROOT/"btc_1h_2024_to_sep24_2026.json"
    t,o,hi,lo,c,v,trades,taker,source=read_klines(hist,3600000)
    ix,dates,spot,names,regime,vol,atr=build_hourly_features(t,hi,lo,c,v,trades,taker,24)
    anchors=t[ix]+3600000
    xm,vm,prov=market_features(anchors,macro)
    xe,ve,eprov=etf_features(anchors,macro)
    distance=c[ix]*vol*np.sqrt(24.0)
    y,when=target_distance(ix,c,hi,lo,distance,24)

    folds=[
      ("2025Q3","2025-04-01","2025-04-01","2025-07-01","2025-07-08","2025-10-01"),
      ("2025Q4","2025-07-01","2025-07-01","2025-10-01","2025-10-08","2026-01-01"),
      ("2026H1","2025-10-01","2025-10-01","2026-01-01","2026-01-08","2026-07-01"),
      ("2026Q3","2026-01-01","2026-01-01","2026-07-01","2026-07-08","2026-09-24"),
    ]
    report={"schema":"btc-predictive-vnext4r6-macro-ablation-v1",
            "status":"RESEARCH_ONLY","trading_authority":False,
            "history_sha256":source,"availability_policy":macro["availability_policy"],
            "market_provenance":prov,"etf_provenance":eprov,"folds":{}}
    for label,*b in folds:
        tr,ca,te=masks(dates,np.timedelta64(24,"h"),*b)
        common=vm
        # Same anchors within each market-macro comparison.
        trm=tr&common;cam=ca&common;tem=te&common
        if min(np.sum(trm),np.sum(cam),np.sum(tem))<100:continue
        fam={
          "spot":spot,
          "spot_plus_macro_markets":np.column_stack((spot,xm)),
        }
        if eprov["status"]=="OK":
            ce=vm&ve
            if np.sum(te&ce)>=100:
                fam["spot_plus_macro_markets_etf"]=np.column_stack((spot,xm,xe))
        fr={"n_market_test":int(np.sum(tem)),"families":{}}
        for name,X in fam.items():
            vv=common if name!="spot_plus_macro_markets_etf" else (vm&ve)
            trf=tr&vv;caf=ca&vv;tef=te&vv
            fr["families"][name]=fold_scores(
              X,regime,vol,dates,y,when,trf,caf,tef)
            fr["families"][name]["_n_test"]=int(np.sum(tef))
        report["folds"][label]=fr

    # Structural acceptance summary for the GBDT macro challenger only.
    gains=[]
    for f in report["folds"].values():
        if "spot_plus_macro_markets" in f["families"]:
            gains.append(f["families"]["spot_plus_macro_markets"]["gbdt"]["brier_gain_vs_vol90d_mean"])
    report["macro_market_gbdt_summary"]={
      "folds":len(gains),"wins_vs_vol90d":sum(g>0 for g in gains),
      "mean_brier_gain_vs_vol90d":None if not gains else float(np.mean(gains)),
      "research_gate_pass":bool(len(gains)>=3 and sum(g>0 for g in gains)>=2 and np.mean(gains)>0),
    }
    p=DATA/"macro_ablation_result.json"
    p.write_text(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True)+"\n")
    print(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True))


if __name__=="__main__":
    main()
