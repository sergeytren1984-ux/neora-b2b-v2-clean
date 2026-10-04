"""Selftests for BTC Predictive vNext4.

Covers research/runtime parity and independently reconstructs the adaptive baseline
seed from the frozen raw seed candles.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import math
import sys
from pathlib import Path

import joblib
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))

from predictive_vnext4.core import (
    build_hourly_features,build_15m_features,target_distance,target_percent,
)
from predictive_vnext4.live_features import (
    HOURLY_NAMES,EARLY15M_NAMES,hourly_feature,early15m_feature,
)
from predictive_vnext4.predict import predict_contenders,control_prediction


def synthetic(n,period_ms,drift):
    t=np.arange(n,dtype=np.int64)*period_ms
    c=100+np.arange(n)*drift+.12*np.sin(np.arange(n)/11)
    hi=c+.08+.01*np.cos(np.arange(n)/5)
    lo=c-.08-.01*np.sin(np.arange(n)/7)
    v=20+2*np.sin(np.arange(n)/13)
    trades=200+20*np.cos(np.arange(n)/17)
    taker=v*(.48+.05*np.sin(np.arange(n)/19))
    return t,hi,lo,c,v,trades,taker


def assert_dist(d):
    vals=np.asarray([d["lower_first"],d["upper_first"],d["neither"],d["ambiguous_same_bar"]],dtype=float)
    assert np.all(np.isfinite(vals));assert np.all(vals>=0);assert abs(float(vals.sum())-1)<1e-9


def arrays(rows):
    t=np.asarray([int(r[0]) for r in rows],dtype=np.int64)
    o=np.asarray([float(r[1]) for r in rows])
    hi=np.asarray([float(r[2]) for r in rows])
    lo=np.asarray([float(r[3]) for r in rows])
    c=np.asarray([float(r[4]) for r in rows])
    v=np.asarray([float(r[5]) for r in rows])
    trades=np.asarray([float(r[8]) for r in rows])
    taker=np.asarray([float(r[9]) for r in rows])
    return t,o,hi,lo,c,v,trades,taker


def seed_records(dates,y,vol,control,due_delta,freeze_utc):
    q=np.asarray(control["vol_quantiles"],dtype=float)
    bins=np.digitize(vol,q,right=True)
    cutoff=np.datetime64(freeze_utc.replace(tzinfo=None))
    out=[]
    for dt,cls,b in zip(dates,y,bins):
        due=dt+due_delta
        if due>=cutoff:continue
        out.append({
            "anchor_utc":str(dt.astype("datetime64[s]"))+"Z",
            "due_utc":str(due.astype("datetime64[s]"))+"Z",
            "class_id":int(cls),"vol_bin":int(b),
        })
    lo=cutoff-np.timedelta64(100,"D")
    return [r for r in out if np.datetime64(r["anchor_utc"].replace("Z",""))>=lo]


def parity():
    t,hi,lo,c,v,tr,tk=synthetic(520,3600000,.015)
    ix,dates,X,names,reg,vol,atr=build_hourly_features(t,hi,lo,c,v,tr,tk,1)
    i=320;row=int(np.flatnonzero(ix==i)[0])
    live,meta=hourly_feature(hi[:i+1],lo[:i+1],c[:i+1],v[:i+1],tr[:i+1],tk[:i+1])
    np.testing.assert_allclose(live,X[row],rtol=0,atol=1e-12);assert names==HOURLY_NAMES
    assert abs(meta["rv24"]-float(vol[row]))<1e-12

    t,hi,lo,c,v,tr,tk=synthetic(900,900000,.003)
    ix,dates,X,names,reg,vol=build_15m_features(t,hi,lo,c,v,tr,tk,1)
    i=520;row=int(np.flatnonzero(ix==i)[0])
    live,meta=early15m_feature(hi[:i+1],lo[:i+1],c[:i+1],v[:i+1],tr[:i+1],tk[:i+1])
    np.testing.assert_allclose(live,X[row],rtol=0,atol=1e-12);assert names==EARLY15M_NAMES
    assert abs(meta["rv4h"]-float(vol[row]))<1e-12


def verify_seed(artifact_name,source_name,kind):
    art=joblib.load(ROOT/"predictive_vnext4"/artifact_name)
    source=ROOT/"predictive_vnext4"/source_name
    assert hashlib.sha256(source.read_bytes()).hexdigest()==art["baseline_seed_source_sha256"]
    rows=json.loads(gzip.decompress(source.read_bytes()))
    logical=json.dumps(rows,separators=(",",":"),ensure_ascii=False,sort_keys=False).encode()
    assert hashlib.sha256(logical).hexdigest()==art["baseline_seed_source_logical_sha256"]
    t,o,hi,lo,c,v,tr,tk=arrays(rows)
    from datetime import datetime
    freeze=datetime.fromisoformat(art["baseline_seed_freeze_utc"])
    if kind=="hourly":
        ix,dates,X,names,reg,vol,atr=build_hourly_features(t,hi,lo,c,v,tr,tk,168)
        d=c[ix]*vol*np.sqrt(72.0)
        y,when=target_distance(ix,c,hi,lo,d,72)
        rebuilt=seed_records(dates,y,vol,art["control"],np.timedelta64(72,"h"),freeze)
        live,meta=hourly_feature(hi,lo,c,v,tr,tk)
        vv=meta["rv24"]
    else:
        ix,dates,X,names,reg,vol=build_15m_features(t,hi,lo,c,v,tr,tk,16)
        y,when=target_percent(ix,c,hi,lo,.99,1.01,16)
        rebuilt=seed_records(dates,y,vol,art["control"],np.timedelta64(240,"m"),freeze)
        live,meta=early15m_feature(hi,lo,c,v,tr,tk)
        vv=meta["rv4h"]
    assert rebuilt==art["baseline_seed"],(len(rebuilt),len(art["baseline_seed"]))
    pred=predict_contenders(art,live)
    assert set(pred)=={"logistic","gbdt","competing_risks"}
    for p in pred.values():assert_dist(p["class_distribution"])
    ctrl=control_prediction(art,vv,freeze.isoformat(),[])
    assert_dist(ctrl["primary_distribution"]);assert_dist(ctrl["secondary_distribution"])


def main():
    parity()
    verify_seed("hourly_contenders.joblib","baseline_seed_hourly_source.json.gz","hourly")
    verify_seed("early15m_contenders.joblib","baseline_seed_early15m_source.json.gz","early15m")
    meta=json.loads((ROOT/"predictive_vnext4/freeze_metadata.json").read_text())
    assert meta["predictive_accept"] is False and meta["trading_authority"] is False
    print("vNext4 selftest: OK")


if __name__=="__main__":main()
