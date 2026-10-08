"""Frozen vNext5 first-passage inference utilities.

This module contains no market-data fetching.  The prospective worker must build
the exact base feature vector from candles closed at or before the anchor, then
call these functions.  Raw four-state probabilities are always retained.
"""
from __future__ import annotations
import math
import numpy as np
from predictive_vnext4.core import full_proba, _hazard_cumulative

RAW_CLASSES=("LOWER_FIRST","UPPER_FIRST","NEITHER","AMBIGUOUS_SAME_BAR")
DOMAIN_ABS_TOL=1e-12
PROB_SUM_TOL=1e-8


def _calibrated(calibrator, raw):
    x=np.log(np.clip(raw,1e-8,1.0))
    return full_proba(calibrator,x)


def _augment(base, lower_sigma, upper_sigma):
    b=np.asarray(base,dtype=float).reshape(1,-1)
    extra=np.asarray([[
        lower_sigma,
        upper_sigma,
        lower_sigma-upper_sigma,
        math.log(lower_sigma/upper_sigma),
    ]],dtype=float)
    return np.column_stack((b,extra))


def _inclusive(value, low, high, *, tol=DOMAIN_ABS_TOL):
    if not math.isfinite(value):
        return False
    return (
        (value > low or math.isclose(value, low, rel_tol=0.0, abs_tol=tol))
        and
        (value < high or math.isclose(value, high, rel_tol=0.0, abs_tol=tol))
    )


def validate_sigma_domain(lower_sigma, upper_sigma):
    lo=float(lower_sigma);up=float(upper_sigma)
    if not (_inclusive(lo,0.25,3.0) and _inclusive(up,0.25,3.0)):
        raise ValueError("OUT_OF_DOMAIN_NO_MODEL_PROBABILITY")
    ratio=lo/up
    if not _inclusive(ratio,0.1,10.0):
        raise ValueError("OUT_OF_DOMAIN_NO_MODEL_PROBABILITY")
    return lo,up


def _normalize_model_probability(raw):
    p=np.asarray(raw,dtype=float)
    if p.shape!=(4,) or not np.all(np.isfinite(p)) or np.any(p<0.0):
        raise ValueError("INVALID_MODEL_PROBABILITY")
    total=float(p.sum())
    if not math.isfinite(total) or total<=0.0:
        raise ValueError("INVALID_MODEL_PROBABILITY")
    p=p/total
    if not np.all(np.isfinite(p)) or np.any(p<0.0):
        raise ValueError("INVALID_MODEL_PROBABILITY")
    return p


def _validated_display_probability(raw):
    p=np.asarray(raw,dtype=float)
    if p.shape!=(4,) or not np.all(np.isfinite(p)) or np.any(p<0.0):
        raise ValueError("INVALID_RAW_PROBABILITY")
    total=float(p.sum())
    if not math.isfinite(total) or abs(total-1.0)>PROB_SUM_TOL:
        raise ValueError("INVALID_RAW_PROBABILITY")
    return p/total


def zone_edges_to_sigmas(reference, lower_zone, upper_zone, vol, horizon_steps):
    reference=float(reference);vol=float(vol)
    if reference<=0 or vol<=0:
        raise ValueError("invalid reference/volatility")
    l0,l1=sorted(map(float,lower_zone))
    u0,u1=sorted(map(float,upper_zone))
    if not l1 < reference:
        raise ValueError("lower zone must be strictly below anchor")
    if not u0 > reference:
        raise ValueError("upper zone must be strictly above anchor")
    unit=reference*vol*math.sqrt(float(horizon_steps))
    lower_sigma=(reference-l1)/unit
    upper_sigma=(u0-reference)/unit
    validate_sigma_domain(lower_sigma,upper_sigma)
    return {
        "lower_entry":l1,
        "upper_entry":u0,
        "lower_sigma":float(lower_sigma),
        "upper_sigma":float(upper_sigma),
        "volatility_unit":float(unit),
    }


def classifier_raw_probability(bundle, base_features, lower_sigma, upper_sigma):
    lo,up=validate_sigma_domain(lower_sigma,upper_sigma)
    X=_augment(base_features,lo,up)
    out=[]
    for key in ("logistic","gbdt"):
        item=bundle["models"][key]
        raw=full_proba(item["model"],X)
        out.append(_calibrated(item["calibrator"],raw)[0])
    p=np.mean(np.vstack(out),axis=0)
    return _normalize_model_probability(p)


def hazard_raw_probability(bundle, base_features, lower_sigma, upper_sigma):
    lo,up=validate_sigma_domain(lower_sigma,upper_sigma)
    X=_augment(base_features,lo,up)
    raw=_hazard_cumulative(
        bundle["model"],X,
        int(bundle["horizon_steps"]),
        int(bundle["hazard_step"]),
    )
    p=_calibrated(bundle["calibrator"],raw)[0]
    return _normalize_model_probability(p)


def display_three_state(raw):
    p=_validated_display_probability(raw)
    out={
        "DOWN":float(p[0]+0.5*p[3]),
        "RANGE":float(p[2]),
        "UP":float(p[1]+0.5*p[3]),
        "AMBIGUOUS_SAME_BAR_RAW":float(p[3]),
    }
    if abs(out["DOWN"]+out["RANGE"]+out["UP"]-1.0)>1e-8:
        raise ValueError("three-state probabilities do not sum to one")
    return out
