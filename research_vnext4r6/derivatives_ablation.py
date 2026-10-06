"""R6 funding/open-interest paired ablation on the 24h volatility-scaled head.

Research only. Derivatives observations are used with a conservative 1h lag because
Binance metric create_time is not proven publication time. Missing/stale observations
are rejected, never interpolated.
"""
from __future__ import annotations
import gzip,hashlib,json
from pathlib import Path
import numpy as np

from predictive_vnext4.core import (
    read_klines,build_hourly_features,target_distance,masks,
    fit_candidates,metrics,block_ci
)

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/"research_vnext/data"
OUT=ROOT/"research_vnext4r6"


def derivative_features(anchors_ms,spot,names):
    oip=DATA/"BTCUSDT_oi_2024-01_2026-06.json.gz"
    fundp=DATA/"BTCUSDT_funding_2024-01_2026-06.json.gz"
    oi=sorted(json.load(gzip.open(oip,"rt")),key=lambda r:r["create_time"])
    ft=sorted(json.load(gzip.open(fundp,"rt")),key=lambda r:int(r["calc_time"]))
    ot=np.asarray([np.datetime64(r["create_time"].replace(" ","T"),"ms").astype("int64") for r in oi])
    ov=np.asarray([float(r["sum_open_interest"]) for r in oi])
    fv=np.asarray([float(r["last_funding_rate"]) for r in ft])
    ftime=np.asarray([int(r["calc_time"]) for r in ft])
    if np.any(np.diff(ot)<=0) or np.any(np.diff(ftime)<=0):
        raise ValueError("duplicate/unsorted derivatives timestamps")

    lag=3600000
    oidx=[np.searchsorted(ot,anchors_ms-k*lag,side="right")-1 for k in (1,2,5,25)]
    valid=np.ones(len(anchors_ms),dtype=bool)
    for idx,k in zip(oidx,(1,2,5,25)):
        safe=np.maximum(idx,0)
        valid &= idx>=0
        valid &= (anchors_ms-k*lag-ot[safe] <= 600000)
        valid &= ov[safe]>0
    fi=np.searchsorted(ftime,anchors_ms-lag,side="right")-1
    sfi=np.maximum(fi,0);sfi1=np.maximum(fi-1,0)
    valid &= fi>=1
    valid &= (anchors_ms-lag-ftime[sfi] <= 9*lag)
    valid &= (anchors_ms-lag-ftime[sfi1] <= 17*lag)

    ids=[np.maximum(x,0) for x in oidx]
    pos={n:i for i,n in enumerate(names)}
    safe=lambda idx:np.maximum(ov[idx],1e-12)
    d1=np.log(safe(ids[0])/safe(ids[1]))
    d4=np.log(safe(ids[0])/safe(ids[2]))
    d24=np.log(safe(ids[0])/safe(ids[3]))
    funding=fv[sfi];fund_change=funding-fv[sfi1]
    ret1=spot[:,pos["ret_1h"]];ret4=spot[:,pos["ret_4h"]];ret24=spot[:,pos["ret_24h"]]
    X=np.column_stack((
      d1,d4,d24,d1-d4/4.0,
      funding,fund_change,
      ret1*d1,ret4*d4,ret24*d24,
      funding*d4
    ))
    return X,valid,{
      "oi_sha256":hashlib.sha256(oip.read_bytes()).hexdigest(),
      "funding_sha256":hashlib.sha256(fundp.read_bytes()).hexdigest(),
      "timestamp_lag_hours":1,
      "publication_time_verified":False,
    }


def paired_fold(X0,X1,regime,vol,dates,y,when,tr,ca,te):
    p0=fit_candidates(X0,regime,y,when,tr,ca,te,24,3)["gbdt"]
    p1=fit_candidates(X1,regime,y,when,tr,ca,te,24,3)["gbdt"]
    yt=y[te];dt=dates[te];one=np.eye(4)[yt]
    gain=np.sum((p0-one)**2,axis=1)-np.sum((p1-one)**2,axis=1)
    return {
      "n":int(np.sum(te)),
      "spot_gbdt":metrics(p0,yt),
      "derivatives_gbdt":metrics(p1,yt),
      "brier_gain_derivatives_vs_spot_mean":float(np.mean(gain)),
      "brier_gain_derivatives_vs_spot_ci95":block_ci(p0,p1,yt,dt),
    }


def main():
    t,o,hi,lo,c,v,trades,taker,source=read_klines(ROOT/"btc_1h_2024_to_sep24_2026.json",3600000)
    ix,dates,X,names,regime,vol,atr=build_hourly_features(t,hi,lo,c,v,trades,taker,24)
    anchors=t[ix]+3600000
    xd,valid,prov=derivative_features(anchors,X,names)
    d=c[ix]*vol*np.sqrt(24.0)
    y,when=target_distance(ix,c,hi,lo,d,24)
    X1=np.column_stack((X,xd))
    folds=[
      ("2025Q3","2025-04-01","2025-04-01","2025-07-01","2025-07-08","2025-10-01"),
      ("2025Q4","2025-07-01","2025-07-01","2025-10-01","2025-10-08","2026-01-01"),
      ("2026H1","2025-10-01","2025-10-01","2026-01-01","2026-01-08","2026-07-01"),
    ]
    report={"schema":"btc-predictive-vnext4r6-derivatives-ablation-v1",
            "status":"RESEARCH_ONLY","trading_authority":False,
            "history_sha256":source,"provenance":prov,
            "anchors_dropped_for_missing_or_stale_derivatives":int(np.sum(~valid)),
            "folds":{}}
    for label,*b in folds:
        tr,ca,te=masks(dates,np.timedelta64(24,"h"),*b)
        tr&=valid;ca&=valid;te&=valid
        if min(np.sum(tr),np.sum(ca),np.sum(te))<100:
            continue
        report["folds"][label]=paired_fold(X,X1,regime,vol,dates,y,when,tr,ca,te)
    gains=[z["brier_gain_derivatives_vs_spot_mean"] for z in report["folds"].values()]
    cis=[z["brier_gain_derivatives_vs_spot_ci95"] for z in report["folds"].values()]
    report["summary"]={
      "folds":len(gains),"wins_vs_spot_gbdt":sum(g>0 for g in gains),
      "mean_brier_gain_vs_spot_gbdt":None if not gains else float(np.mean(gains)),
      "positive_ci_folds":sum(ci[0]>0 for ci in cis if ci and ci[0] is not None),
      "research_gate_pass":bool(len(gains)>=3 and sum(g>0 for g in gains)>=2 and np.mean(gains)>0),
    }
    OUT.mkdir(exist_ok=True)
    (OUT/"derivatives_ablation_result.json").write_text(
      json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True)+"\n")
    print(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True))


if __name__=="__main__":
    main()
