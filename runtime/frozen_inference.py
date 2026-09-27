"""Frozen v2.9.30 numeric inference, extracted without coefficient changes."""
from __future__ import annotations
import gzip, hashlib, json, math
from pathlib import Path
from datetime import datetime, timezone
from multi_horizon_features import compute, H4_FEATURES, H24_FEATURES
MODEL_SCHEMA_VERSION="numeric-bcde-v2"
SUPPORTED_MODEL_FAMILIES={"B_regularized_logistic","C_gradient_boosting","D_ensemble_B_C","E_hist_gradient_boosting"}
PINNED_BYTES_SHA="577017d19e6a2c607c8d7fb77b4ddce35dd8e3fc9be98db85e700d8862784a35"

def _softmax_vector(logits: list[float]) -> list[float]:
    if len(logits) != 3 or any(not math.isfinite(float(v)) for v in logits):
        raise ValueError("invalid three-class logits")
    mx=max(logits)
    e=[math.exp(float(v)-mx) for v in logits]
    total=sum(e)
    if not math.isfinite(total) or total <= 0:
        raise ValueError("invalid softmax normalization")
    return [v/total for v in e]

def _predict_B(payload: dict, z: list[float]) -> list[float]:
    if not isinstance(payload,dict) or set(payload) != {"bias","weights","classes"}:
        raise ValueError("B model contains missing or extra fields")
    bias=payload.get("bias"); weights=payload.get("weights"); classes=payload.get("classes")
    if classes != [0,1,2] or not isinstance(bias,list) or len(bias)!=3 or not isinstance(weights,list) or len(weights)!=3:
        raise ValueError("invalid B model schema")
    logits=[]
    for b,row in zip(bias,weights):
        if not isinstance(row,list) or len(row)!=len(z):
            raise ValueError("invalid B weight shape")
        values=[float(b), *map(float,row)]
        if any(not math.isfinite(v) for v in values):
            raise ValueError("non-finite B model parameter")
        logits.append(float(b)+sum(float(w)*v for w,v in zip(row,z)))
    return _softmax_vector(logits)

def _predict_C(payload: dict, z: list[float]) -> list[float]:
    if not isinstance(payload,dict) or set(payload) != {"base","lr","trees","classes"}:
        raise ValueError("C model contains missing or extra fields")
    base=payload.get("base"); lr=float(payload.get("lr", float("nan"))); trees=payload.get("trees"); classes=payload.get("classes")
    if classes != [0,1,2] or not isinstance(base,list) or len(base)!=3 or any(not math.isfinite(float(v)) for v in base):
        raise ValueError("invalid C base schema")
    if not math.isfinite(lr) or not 0 < lr <= 1 or not isinstance(trees,list) or not 1 <= len(trees) <= 1000:
        raise ValueError("invalid C learning-rate/tree schema")
    logits=[float(v) for v in base]
    for round_trees in trees:
        if not isinstance(round_trees,list) or len(round_trees)!=3:
            raise ValueError("invalid C round schema")
        for k,stump in enumerate(round_trees):
            if not isinstance(stump,dict) or set(stump) != {"feature","threshold","left","right"}:
                raise ValueError("invalid C stump schema or extra fields")
            feature=stump.get("feature")
            if not isinstance(feature,int) or isinstance(feature,bool) or not 0 <= feature < len(z):
                raise ValueError("invalid C stump feature")
            threshold=stump.get("threshold")
            threshold=math.inf if threshold is None else float(threshold)
            left=float(stump.get("left")); right=float(stump.get("right"))
            if (not math.isfinite(threshold) and threshold != math.inf) or any(not math.isfinite(v) for v in (left,right)):
                raise ValueError("invalid C stump parameter")
            logits[k]+=lr*(left if z[feature] <= threshold else right)
    return _softmax_vector(logits)

def _predict_E(payload: dict, z: list[float]) -> list[float]:
    """Evaluate a numeric export of sklearn HistGradientBoostingClassifier.

    Tree leaf values already include the fitted learning rate.  Only numeric
    thresholds/topology are serialized; no pickle or executable estimator is
    trusted at serving time.
    """
    if not isinstance(payload,dict) or set(payload) != {"baseline","trees","classes"}:
        raise ValueError("E model contains missing or extra fields")
    base=payload.get("baseline"); trees=payload.get("trees"); classes=payload.get("classes")
    if classes != [0,1,2] or not isinstance(base,list) or len(base)!=3 or any(not math.isfinite(float(v)) for v in base):
        raise ValueError("invalid E baseline schema")
    if not isinstance(trees,list) or not 1 <= len(trees) <= 1000:
        raise ValueError("invalid E tree schema")
    raw=[float(v) for v in base]
    for round_trees in trees:
        if not isinstance(round_trees,list) or len(round_trees)!=3:
            raise ValueError("invalid E round schema")
        for k,tree in enumerate(round_trees):
            nodes=tree.get("nodes") if isinstance(tree,dict) else None
            if not isinstance(nodes,list) or not nodes:
                raise ValueError("invalid E nodes")
            idx=0; steps=0
            while True:
                if not 0 <= idx < len(nodes) or steps > len(nodes): raise ValueError("invalid E topology")
                nd=nodes[idx]; steps+=1
                if not isinstance(nd,dict): raise ValueError("invalid E node")
                if nd.get("leaf") is True:
                    if set(nd)!={"leaf","value"}: raise ValueError("invalid E leaf schema")
                    value=float(nd["value"]);
                    if not math.isfinite(value): raise ValueError("non-finite E leaf")
                    raw[k]+=value; break
                if set(nd)!={"leaf","feature","threshold","left","right"}: raise ValueError("invalid E split schema")
                j=nd.get("feature"); threshold=float(nd.get("threshold")); left=nd.get("left"); right=nd.get("right")
                if not isinstance(j,int) or isinstance(j,bool) or not 0<=j<len(z) or not math.isfinite(threshold): raise ValueError("invalid E split")
                if not isinstance(left,int) or not isinstance(right,int): raise ValueError("invalid E children")
                idx=left if z[j] <= threshold else right
    return _softmax_vector(raw)

def model_family_probabilities(entry: dict, z: list[float]) -> list[float]:
    """Evaluate the closed numeric candidate schema; no executable objects."""
    if entry.get("model_schema_version") != MODEL_SCHEMA_VERSION:
        raise ValueError("unsupported candidate model schema")
    family=entry.get("model_family")
    payload=entry.get("model_payload")
    if family not in SUPPORTED_MODEL_FAMILIES or not isinstance(payload,dict):
        raise ValueError("unsupported candidate model family")
    if family == "B_regularized_logistic":
        if set(payload) != {"B_regularized_logistic"}:
            raise ValueError("B payload contains unexpected model blocks")
        return _predict_B(payload["B_regularized_logistic"],z)
    if family == "C_gradient_boosting":
        if set(payload) != {"C_gradient_boosting"}:
            raise ValueError("C payload contains unexpected model blocks")
        return _predict_C(payload["C_gradient_boosting"],z)
    if family == "E_hist_gradient_boosting":
        if set(payload) != {"E_hist_gradient_boosting"}:
            raise ValueError("E payload contains unexpected model blocks")
        return _predict_E(payload["E_hist_gradient_boosting"],z)
    if entry.get("ensemble_rule") != "mean_raw_probabilities_before_calibration":
        raise ValueError("unsupported D ensemble semantics")
    if set(payload) != {"B_regularized_logistic","C_gradient_boosting"}:
        raise ValueError("D payload must contain exactly B and C")
    pb=_predict_B(payload["B_regularized_logistic"],z)
    pc=_predict_C(payload["C_gradient_boosting"],z)
    return [(a+b)/2 for a,b in zip(pb,pc)]

def calibrated_candidate_probabilities(entry: dict, z: list[float]) -> list[float]:
    raw=model_family_probabilities(entry,z)
    temp=float(entry.get("temperature",1.0))
    if not math.isfinite(temp) or temp <= 0:
        raise ValueError("invalid calibration temperature")
    logs=[math.log(max(p,1e-9))/temp for p in raw]
    calibrated=_softmax_vector(logs)
    prior=entry.get("train_prior",[1/3,1/3,1/3]); alpha=float(entry.get("shrinkage_alpha",1.0))
    if (not isinstance(prior,list) or len(prior)!=3 or any(not math.isfinite(float(q)) or float(q)<0 for q in prior)
            or abs(sum(map(float,prior))-1)>.002 or not math.isfinite(alpha) or not 0<=alpha<=1):
        raise ValueError("invalid prior shrinkage calibration")
    published=[alpha*p+(1-alpha)*float(q) for p,q in zip(calibrated,prior)]
    if abs(sum(published)-1)>.002 or any(not math.isfinite(p) or p<0 or p>1 for p in published):
        raise ValueError("invalid published probabilities")
    return published

def frozen_artifact(path=None):
    path=Path(path or Path(__file__).with_name("frozen_v2930_candidate.json.gz"))
    raw=gzip.decompress(path.read_bytes())
    if hashlib.sha256(raw).hexdigest()!=PINNED_BYTES_SHA: raise ValueError("v2.9.30 artifact changed")
    a=json.loads(raw)
    body={k:v for k,v in a.items() if k not in ("artifact_sha256","approval_gate")}
    if hashlib.sha256(json.dumps(body,sort_keys=True,separators=(",",":")).encode()).hexdigest()!=a["artifact_sha256"]:
        raise ValueError("inner candidate hash mismatch")
    if a["version"]!="2.9.30-multi-horizon-uplift" or a["approval_gate"] is not None:
        raise ValueError("wrong frozen artifact")
    return a

def forecast(candles, issued_at, artifact=None):
    """Return frozen, diagnostic 4h/24h probabilities from 169 closed 1h bars."""
    artifact=artifact or frozen_artifact()
    if len(candles)<169: raise ValueError("169 closed 1h candles required")
    if isinstance(issued_at,str): issued_at=datetime.fromisoformat(issued_at.replace("Z","+00:00"))
    if issued_at.tzinfo is None: raise ValueError("timezone required")
    features=compute(candles,issued_at)
    results={}
    for h,names in (("4h",H4_FEATURES),("24h",H24_FEATURES)):
        e=artifact["horizons"][h]
        if e["features"] != ["features.mh"+h[:-1]+"."+name for name in names]: raise ValueError("feature order changed")
        values=[float(features[name]) for name in names]
        z=[(v-float(m))/float(sc) for v,m,sc in zip(values,e["means"],e["scales"])]
        if len(z)!=len(names) or max(map(abs,z))>float(e.get("max_abs_feature_z",4.0)):
            results[h]={"status":"ABSTAIN_MODEL_DRIFT","probabilities":None};continue
        p=calibrated_candidate_probabilities(e,z)
        results[h]={"status":"PRE_EXPERT_CANDIDATE_DIAGNOSTIC","probabilities":dict(zip(("upside","range","downside"),[round(v,3) for v in p])),"feature_hash":hashlib.sha256(json.dumps(values,separators=(",",":")).encode()).hexdigest()}
    return results
