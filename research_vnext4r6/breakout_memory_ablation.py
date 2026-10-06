"""R6 failed-breakout memory ablation.

Tests explicit causal rejection/breakout-memory features against the exact same GBDT
without those features. Research only; no production or trading authority.
"""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np

from predictive_vnext4.core import (
  read_klines,build_15m_features,build_hourly_features,target_distance,masks,
  fit_candidates,metrics,block_ci
)

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"research_vnext4r6"


def memory_features(o,hi,lo,c,ix,lookback,scan):
    rows=[]
    for i in ix:
        fu=fd=su=sd=0
        start=max(lookback,i-scan+1)
        for j in range(start,i+1):
            ph=float(np.max(hi[j-lookback:j]));pl=float(np.min(lo[j-lookback:j]))
            if hi[j]>ph:
                if c[j]<=ph:fu+=1
                else:su+=1
            if lo[j]<pl:
                if c[j]>=pl:fd+=1
                else:sd+=1
        wstart=max(0,i-scan+1)
        hh=hi[wstart:i+1];ll=lo[wstart:i+1]
        ih=int(np.argmax(hh));il=int(np.argmin(ll))
        rng=max(float(hi[i]-lo[i]),1e-12)
        rows.append([
          fu/scan,fd/scan,su/scan,sd/scan,
          (c[i]-float(np.max(hh)))/c[i],
          (c[i]-float(np.min(ll)))/c[i],
          (len(hh)-1-ih)/scan,(len(ll)-1-il)/scan,
          (hi[i]-max(o[i],c[i]))/rng,
          (min(o[i],c[i])-lo[i])/rng,
        ])
    X=np.asarray(rows,dtype=float)
    if not np.all(np.isfinite(X)):raise ValueError("nonfinite memory feature")
    return X


def one_fold(X0,X1,regime,dates,y,when,tr,ca,te,horizon,step):
    p0=fit_candidates(X0,regime,y,when,tr,ca,te,horizon,step)["gbdt"]
    p1=fit_candidates(X1,regime,y,when,tr,ca,te,horizon,step)["gbdt"]
    yt=y[te];dt=dates[te];one=np.eye(4)[yt]
    gain=np.sum((p0-one)**2,axis=1)-np.sum((p1-one)**2,axis=1)
    return {
      "n":int(np.sum(te)),
      "base_gbdt":metrics(p0,yt),
      "memory_gbdt":metrics(p1,yt),
      "brier_gain_memory_vs_base_mean":float(np.mean(gain)),
      "brier_gain_memory_vs_base_ci95":block_ci(p0,p1,yt,dt),
    }


def folds(maxdate):
    x=[
      ("2025Q3","2025-04-01","2025-04-01","2025-07-01","2025-07-08","2025-10-01"),
      ("2025Q4","2025-07-01","2025-07-01","2025-10-01","2025-10-08","2026-01-01"),
      ("2026H1","2025-10-01","2025-10-01","2026-01-01","2026-01-08","2026-07-01"),
    ]
    if maxdate>=np.datetime64("2026-09-24"):
        x.append(("2026Q3","2026-01-01","2026-01-01","2026-07-01","2026-07-08","2026-09-24"))
    return x


def eval_head(name,X0,X1,regime,dates,y,when,due,horizon,step):
    out={"folds":{}}
    for label,*b in folds(dates.max()):
        if np.datetime64(b[-1])>dates.max()+np.timedelta64(1,"D"):continue
        tr,ca,te=masks(dates,due,*b)
        if min(np.sum(tr),np.sum(ca),np.sum(te))<100:continue
        out["folds"][label]=one_fold(X0,X1,regime,dates,y,when,tr,ca,te,horizon,step)
    gains=[x["brier_gain_memory_vs_base_mean"] for x in out["folds"].values()]
    cis=[x["brier_gain_memory_vs_base_ci95"] for x in out["folds"].values()]
    out["summary"]={
      "folds":len(gains),"wins":sum(g>0 for g in gains),
      "mean_brier_gain":None if not gains else float(np.mean(gains)),
      "positive_ci_folds":sum(ci[0]>0 for ci in cis if ci and ci[0] is not None),
      "research_gate_pass":bool(
          len(gains)>=3 and sum(g>0 for g in gains)>=2 and np.mean(gains)>0 and
          sum(ci[0]>0 for ci in cis if ci and ci[0] is not None)>=2
      ),
    }
    return out


def build_15m():
    t,o,hi,lo,c,v,trades,taker,sha=read_klines(
      ROOT/"research_vnext/data/BTCUSDT_15m_2024-01_2026-06.json.gz",900000)
    ix,dates,X,names,regime,vol=build_15m_features(t,hi,lo,c,v,trades,taker,16)
    mem=memory_features(o,hi,lo,c,ix,16,16)
    X1=np.column_stack((X,mem))
    out={}
    for name,bars in (("1h",4),("4h",16)):
        d=c[ix]*vol*np.sqrt(float(bars));y,when=target_distance(ix,c,hi,lo,d,bars)
        out[name]=eval_head(name,X,X1,regime,dates,y,when,np.timedelta64(bars*15,"m"),bars,1)
        out[name]["source_sha256"]=sha
    return out


def build_24h():
    t,o,hi,lo,c,v,trades,taker,sha=read_klines(ROOT/"btc_1h_2024_to_sep24_2026.json",3600000)
    ix,dates,X,names,regime,vol,atr=build_hourly_features(t,hi,lo,c,v,trades,taker,24)
    mem=memory_features(o,hi,lo,c,ix,24,24)
    X1=np.column_stack((X,mem))
    d=c[ix]*vol*np.sqrt(24.0);y,when=target_distance(ix,c,hi,lo,d,24)
    z=eval_head("24h",X,X1,regime,dates,y,when,np.timedelta64(24,"h"),24,3)
    z["source_sha256"]=sha
    return z


def main():
    report={"schema":"btc-predictive-vnext4r6-breakout-memory-ablation-v1",
            "research_iteration_note":"gate hardened after first diagnostic to require >=2 positive block-CI folds; prior diagnostic is tuning evidence only",
            "status":"RESEARCH_ONLY","trading_authority":False,
            "feature_contract":[
              "failed_up_break_count","failed_down_break_count",
              "successful_up_break_count","successful_down_break_count",
              "distance_from_recent_high","distance_from_recent_low",
              "bars_since_recent_high","bars_since_recent_low",
              "upper_wick_ratio","lower_wick_ratio"],
            "heads":build_15m()}
    report["heads"]["24h"]=build_24h()
    p=OUT/"breakout_memory_result.json"
    p.write_text(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True)+"\n")
    print(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True))

if __name__=="__main__":
    main()
