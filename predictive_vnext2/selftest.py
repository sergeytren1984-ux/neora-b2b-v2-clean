"""Production-parity selftest for frozen vNext2 shadow heads."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))

from research_vnext2.core import build_hourly_features, build_15m_features
from predictive_vnext2.live_features import (
    HOURLY_NAMES, EARLY15M_NAMES, hourly_feature, early15m_feature,
)
from predictive_vnext2.predict import load_artifact, predict_competing_risks, control_prediction

HERE=ROOT/"predictive_vnext2"


def synthetic(n,period_ms,drift):
    t=np.arange(n,dtype=np.int64)*period_ms
    base=100.0+np.arange(n)*drift+0.12*np.sin(np.arange(n)/11.0)
    hi=base+0.08+0.01*np.cos(np.arange(n)/5.0)
    lo=base-0.08-0.01*np.sin(np.arange(n)/7.0)
    v=20.0+2.0*np.sin(np.arange(n)/13.0)
    trades=200.0+20.0*np.cos(np.arange(n)/17.0)
    taker=v*(0.48+0.05*np.sin(np.arange(n)/19.0))
    return t,hi,lo,base,v,trades,taker


def assert_dist(d):
    vals=np.asarray([d["lower_first"],d["upper_first"],d["neither"],d["ambiguous_same_bar"]],dtype=float)
    assert np.all(np.isfinite(vals))
    assert np.all(vals>=0)
    assert abs(float(vals.sum())-1.0)<1e-9


def hourly_parity():
    t,hi,lo,c,v,trades,taker=synthetic(520,3600000,.015)
    ix,dates,X,names,regime,vol,atr=build_hourly_features(t,hi,lo,c,v,trades,taker,max_horizon=1)
    i=320;row=int(np.flatnonzero(ix==i)[0])
    live,meta=hourly_feature(hi[:i+1],lo[:i+1],c[:i+1],v[:i+1],trades[:i+1],taker[:i+1])
    np.testing.assert_allclose(live,X[row],rtol=0,atol=1e-12)
    assert names==HOURLY_NAMES
    assert abs(meta["rv24"]-float(vol[row]))<1e-12
    assert abs(meta["atr14_abs"]-float(atr[row]))<1e-12


def early_parity():
    t,hi,lo,c,v,trades,taker=synthetic(900,900000,.003)
    ix,dates,X,names,regime,vol=build_15m_features(t,hi,lo,c,v,trades,taker,max_forward_bars=1)
    i=520;row=int(np.flatnonzero(ix==i)[0])
    live,meta=early15m_feature(hi[:i+1],lo[:i+1],c[:i+1],v[:i+1],trades[:i+1],taker[:i+1])
    np.testing.assert_allclose(live,X[row],rtol=0,atol=1e-12)
    assert names==EARLY15M_NAMES
    assert abs(meta["rv4h"]-float(vol[row]))<1e-12


def artifact_check(protocol_name,artifact_name,feature_kind):
    proto=json.loads((HERE/protocol_name).read_text())
    art=load_artifact(HERE/artifact_name,proto["artifact_sha256"])
    assert art["schema"]=="btc-predictive-vnext2-artifact-v1"
    if feature_kind=="hourly":
        _,hi,lo,c,v,trades,taker=synthetic(520,3600000,.015)
        x,meta=hourly_feature(hi,lo,c,v,trades,taker)
        vol=meta["rv24"]
    else:
        _,hi,lo,c,v,trades,taker=synthetic(900,900000,.003)
        x,meta=early15m_feature(hi,lo,c,v,trades,taker)
        vol=meta["rv4h"]
    candidate=predict_competing_risks(art,x)
    assert_dist(candidate)
    control=control_prediction(art,vol)
    assert_dist(control["training_frequency"])
    assert_dist(control["volatility_bin_frequency"])
    assert control["volatility_bin"] in (0,1,2)


def main():
    hourly_parity()
    early_parity()
    artifact_check("protocol_hourly.json","hourly_rv72_competing_risks.joblib","hourly")
    artifact_check("protocol_early15m.json","early15m_pm1_4h_competing_risks.joblib","early15m")
    metadata=json.loads((HERE/"freeze_metadata.json").read_text())
    assert metadata["predictive_accept"] is False
    assert metadata["no_trade_authority"] is True
    print("vNext2 production parity selftest: OK")


if __name__=="__main__":
    main()
