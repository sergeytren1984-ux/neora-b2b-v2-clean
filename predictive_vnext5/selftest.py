"""Self-test frozen vNext5 first-passage artifacts."""
from __future__ import annotations
import json
from pathlib import Path
import joblib
import numpy as np

from predictive_vnext5.predictor import (
    classifier_raw_probability,hazard_raw_probability,
    display_three_state,validate_sigma_domain,
)

ROOT=Path(__file__).resolve().parents[1]
BUILD=ROOT/"predictive_vnext5/build"


def check(raw):
    p=np.asarray(raw,dtype=float)
    assert p.shape==(4,)
    assert np.all(np.isfinite(p))
    assert np.all(p>=0)
    assert abs(float(p.sum())-1.0)<1e-8
    d=display_three_state(p)
    assert abs(d["DOWN"]+d["RANGE"]+d["UP"]-1.0)<1e-8
    return d


def main():
    vec=json.loads((BUILD/"selftest_vectors.json").read_text())
    a1=joblib.load(BUILD/"head_1h_classifier.joblib")
    a4=joblib.load(BUILD/"head_4h_classifier.joblib")
    c24=joblib.load(BUILD/"head_24h_classifier.joblib")
    h24=joblib.load(BUILD/"head_24h_competing_risks.joblib")

    results={}
    for head,bundle in (("1h",a1),("4h",a4),("24h_classifier",c24)):
        base=vec["24h" if head.startswith("24h") else head]["base_features"]
        raw=classifier_raw_probability(bundle,base,1.0,1.0)
        results[head]={"canonical":check(raw)}
        raw2=classifier_raw_probability(bundle,base,0.5,2.0)
        results[head]["asymmetric_0.5_2.0"]=check(raw2)

    base=vec["24h"]["base_features"]
    results["24h_competing_risks"]={
        "canonical":check(hazard_raw_probability(h24,base,1.0,1.0)),
        "asymmetric_0.5_2.0":
            check(hazard_raw_probability(h24,base,0.5,2.0)),
    }

    for bad in ((0.1,1.0),(1.0,3.1),(0.25,3.0)):
        try:
            validate_sigma_domain(*bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"out-of-domain pair accepted: {bad}")

    print(json.dumps({
        "status":"VNEXT5_FROZEN_ARTIFACT_SELFTEST_PASS",
        "results":results,
        "prospective_skill_proven":False,
        "trading_authority":False,
    },indent=2,sort_keys=True))


if __name__=="__main__":
    main()
