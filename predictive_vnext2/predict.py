"""Frozen vNext2 artifact loading and prediction."""
from __future__ import annotations

import hashlib
from pathlib import Path

import joblib
import numpy as np

ROOT=Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def full_proba(model,X):
    p=np.zeros((len(X),4),dtype=float)
    p[:,model.classes_.astype(int)]=model.predict_proba(X)
    return p


def load_artifact(path, expected_sha256):
    path=Path(path)
    if digest(path)!=expected_sha256:
        raise ValueError("artifact SHA256 mismatch")
    artifact=joblib.load(path)
    if artifact.get("model_family")!="competing_risks":
        raise ValueError("unsupported frozen model family")
    return artifact


def predict_competing_risks(artifact,x):
    X=np.asarray(x,dtype=float).reshape(1,-1)
    if X.shape[1]!=len(artifact["feature_names"]):
        raise ValueError("feature count mismatch")
    hazard=artifact["hazard"]
    if artifact["head"]=="hourly_rv_first_passage_72h":
        horizon=72;step=6
    elif artifact["head"]=="early15m_pm1pct_4h":
        horizon=16;step=1
    else:
        raise ValueError("unknown artifact head")
    out=np.zeros((1,4),dtype=float);survive=np.ones(1,dtype=float)
    for elapsed in range(step,horizon+1,step):
        h=full_proba(hazard,np.column_stack((X,np.full(1,elapsed/horizon))))
        out[:,0]+=survive*h[:,0]
        out[:,1]+=survive*h[:,1]
        out[:,3]+=survive*h[:,3]
        survive*=h[:,2]
    out[:,2]=survive
    out/=np.maximum(out.sum(axis=1,keepdims=True),1e-12)
    cal=artifact["calibrator"]
    result=full_proba(cal,np.log(np.clip(out,1e-8,1)))[0]
    if not np.all(np.isfinite(result)) or abs(float(result.sum())-1)>1e-9:
        raise ValueError("invalid predictive output")
    return {
        "lower_first":float(result[0]),
        "upper_first":float(result[1]),
        "neither":float(result[2]),
        "ambiguous_same_bar":float(result[3])
    }
