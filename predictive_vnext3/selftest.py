"""Selftests for frozen vNext3 contender bundles and production parity."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))

from research_vnext2.core import build_hourly_features,build_15m_features
from predictive_vnext3.live_features import (
    HOURLY_NAMES,EARLY15M_NAMES,hourly_feature,early15m_feature,
)
from predictive_vnext3.predict import (
    load_artifact,predict_contenders,control_prediction,
)

HERE=ROOT/"predictive_vnext3"


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


def artifact_check(protocol_name,artifact_name,kind):
    proto=json.loads((HERE/protocol_name).read_text())
    art=load_artifact(HERE/artifact_name,proto["artifact_sha256"])
    assert art["contenders"]==["logistic","gbdt","competing_risks"]
    if kind=="hourly":
        _,hi,lo,c,v,tr,tk=synthetic(520,3600000,.015)
        x,meta=hourly_feature(hi,lo,c,v,tr,tk);vol=meta["rv24"]
    else:
        _,hi,lo,c,v,tr,tk=synthetic(900,900000,.003)
        x,meta=early15m_feature(hi,lo,c,v,tr,tk);vol=meta["rv4h"]
    pred=predict_contenders(art,x)
    assert set(pred)=={"logistic","gbdt","competing_risks"}
    for name in pred:
        assert_dist(pred[name]["class_distribution"])
        a=pred[name]["alerts_at_calibration_fpr20"]
        assert isinstance(a["lower_first"],bool) and isinstance(a["upper_first"],bool)
    anchor="2026-10-05T00:00:00+00:00"
    ctrl=control_prediction(art,vol,anchor,[])
    assert ctrl["primary_name"]=="vol90d_same_frozen_volatility_bin"
    assert_dist(ctrl["primary_distribution"]);assert_dist(ctrl["secondary_distribution"])

    # A future/not-yet-due record must not change the adaptive control.
    future={"anchor_utc":"2026-10-04T23:00:00+00:00",
            "due_utc":"2026-10-06T00:00:00+00:00","class_id":0,
            "vol_bin":ctrl["volatility_bin"]}
    ctrl2=control_prediction(art,vol,anchor,[future])
    assert ctrl2["primary_distribution"]==ctrl["primary_distribution"]


def main():
    parity()
    artifact_check("protocol_hourly.json","hourly_contenders.joblib","hourly")
    artifact_check("protocol_early15m.json","early15m_contenders.joblib","early15m")
    meta=json.loads((HERE/"freeze_metadata.json").read_text())
    assert meta["predictive_accept"] is False and meta["trading_authority"] is False
    assert meta["contenders"]==["logistic","gbdt","competing_risks"]
    assert meta["primary_baseline"]=="vol90d_same_frozen_volatility_bin"
    print("vNext3 selftest: OK")


if __name__=="__main__":main()
