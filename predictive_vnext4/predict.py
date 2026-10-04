"""Frozen vNext4 contender prediction and exact preregistered controls."""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import joblib
import numpy as np

UTC=timezone.utc


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def full_proba(model,X):
    p=np.zeros((len(X),4),dtype=float)
    p[:,model.classes_.astype(int)]=model.predict_proba(X)
    return p


def _calibrate(calibrator,raw):
    return full_proba(calibrator,np.log(np.clip(raw,1e-8,1)))


def _dist(values):
    vals=np.asarray(values,dtype=float)
    if not np.all(np.isfinite(vals)) or abs(float(vals.sum())-1.0)>1e-8:
        raise ValueError("invalid probability distribution")
    return {
        "lower_first":float(vals[0]),
        "upper_first":float(vals[1]),
        "neither":float(vals[2]),
        "ambiguous_same_bar":float(vals[3]),
    }


def load_artifact(path, expected_sha256):
    path=Path(path)
    if digest(path)!=expected_sha256:
        raise ValueError("artifact SHA256 mismatch")
    artifact=joblib.load(path)
    if artifact.get("schema")!="btc-predictive-vnext4-bundle-v1":
        raise ValueError("unexpected vNext4 artifact schema")
    if artifact.get("contenders")!=["logistic","gbdt","competing_risks"]:
        raise ValueError("contender set drift")
    return artifact


def predict_contenders(artifact,x):
    X=np.asarray(x,dtype=float).reshape(1,-1)
    if X.shape[1]!=len(artifact["feature_names"]):
        raise ValueError("feature count mismatch")
    out={}
    for name in artifact["contenders"]:
        spec=artifact["models"][name]
        if name in ("logistic","gbdt"):
            raw=full_proba(spec["model"],X)
        elif name=="competing_risks":
            horizon=int(spec["horizon_steps"]);step=int(spec["hazard_step"])
            raw=np.zeros((1,4),dtype=float);survive=np.ones(1,dtype=float)
            for elapsed in range(step,horizon+1,step):
                h=full_proba(spec["model"],np.column_stack((X,np.full(1,elapsed/horizon))))
                raw[:,0]+=survive*h[:,0]
                raw[:,1]+=survive*h[:,1]
                raw[:,3]+=survive*h[:,3]
                survive*=h[:,2]
            raw[:,2]=survive
            raw/=np.maximum(raw.sum(axis=1,keepdims=True),1e-12)
        else:
            raise ValueError("unknown contender")
        p=_calibrate(spec["calibrator"],raw)[0]
        dist=_dist(p)
        th=artifact["alert_thresholds"][name]
        out[name]={
            "class_distribution":dist,
            "alerts_at_calibration_fpr20":{
                "lower_first":bool(p[0]>=float(th["lower_first_fpr20"])),
                "upper_first":bool(p[1]>=float(th["upper_first_fpr20"])),
                "lower_threshold":float(th["lower_first_fpr20"]),
                "upper_threshold":float(th["upper_first_fpr20"]),
            }
        }
    return out


def _parse_utc(s):
    x=s[:-1]+"+00:00" if s.endswith("Z") else s
    dt=datetime.fromisoformat(x)
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def control_prediction(artifact, vol_value, anchor_utc, resolved_records=()):
    ctrl=artifact["control"]
    q0,q1=map(float,ctrl["vol_quantiles"])
    vol_bin=0 if float(vol_value)<=q0 else 1 if float(vol_value)<=q1 else 2
    anchor=_parse_utc(anchor_utc)
    start=anchor-timedelta(days=int(ctrl["vol90d_window_days"]))
    eligible=[]
    for r in list(artifact.get("baseline_seed",()))+list(resolved_records):
        try:
            a=_parse_utc(r["anchor_utc"]);due=_parse_utc(r["due_utc"])
            cls=int(r["class_id"]);b=int(r["vol_bin"])
        except Exception as ex:
            raise ValueError("malformed control history record") from ex
        if start<=a<anchor and due<anchor and b==vol_bin and 0<=cls<=3:
            eligible.append(cls)
    train=np.asarray(ctrl["training_frequency"],dtype=float)
    if len(eligible)>=int(ctrl["vol90d_min_same_bin"]):
        counts=np.bincount(np.asarray(eligible,dtype=int),minlength=4).astype(float)+.5
        primary=counts/counts.sum()
        source="vol90d_same_bin"
    else:
        primary=train
        source="training_frequency_fallback"
    return {
        "primary_name":"vol90d_same_frozen_volatility_bin",
        "primary_distribution":_dist(primary),
        "primary_source":source,
        "primary_eligible_records":len(eligible),
        "volatility_bin":vol_bin,
        "secondary_name":"frozen_training_frequency",
        "secondary_distribution":_dist(train),
    }
