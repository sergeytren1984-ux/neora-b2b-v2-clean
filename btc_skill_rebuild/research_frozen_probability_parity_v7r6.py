"""Mathematical invariant audit of immutable pre-epoch three-way probabilities.

No retraining, no forecast publication, no source collection. A frozen
validation_selected_shrink == 1.0 forces P == training prior identically,
independent of features and price. This is a NECESSARY (not sufficient)
provenance check for original pre-epoch forecast mathematics.
"""
from __future__ import annotations
import json, math, pathlib

HORIZONS=("1h","4h","24h")
LABELS=("up","down","range")
EPS=1e-12

def audit_frozen_probability_parity(weights,prediction):
    if set(weights.get("heads",{}))!=set(HORIZONS):
        raise ValueError("missing frozen head")
    if set(prediction.get("three_way",{}))!=set(HORIZONS):
        raise ValueError("missing published forecast head")
    if prediction.get("trading_authority") is not False:
        raise ValueError("research-only forecast cannot assert trade authority")
    results={}
    anchor=prediction["clock_anchor_utc"]
    for h in HORIZONS:
        frozen=weights["heads"][h]
        head=prediction["three_way"][h]
        if head.get("source_anchor_utc")!=anchor:
            raise ValueError("forecast head anchor mismatch")
        if float(head["endpoint_threshold_fraction"])!=float(frozen["threshold"]):
            raise ValueError("frozen endpoint threshold mismatch")
        p=[float(head[k]) for k in LABELS]
        if not all(math.isfinite(x) and 0<=x<=1 for x in p) or abs(sum(p)-1)>1e-9:
            raise ValueError("invalid published probability simplex")
        alpha=float(frozen["validation_selected_shrink"])
        if not math.isfinite(alpha) or not 0<=alpha<=1:
            raise ValueError("invalid frozen validation shrink")
        prior=[float(x) for x in frozen["model_parameters"][3]]
        if len(prior)!=3 or not all(math.isfinite(x) and 0<=x<=1 for x in prior) or abs(sum(prior)-1)>1e-9:
            raise ValueError("invalid frozen training prior")
        distance=sum(abs(x-y) for x,y in zip(p,prior))
        if abs(alpha-1.)<EPS:
            state="PASS" if distance<=EPS else "FAIL_NOT_PINNED_MODEL"
        else:
            state="NOT_DECIDABLE_FROM_ALPHA_ONLY"
        results[h]={
            "frozen_shrink":alpha,
            "published_probability":p,
            "frozen_training_prior":prior,
            "L1_distance_from_frozen_prior":distance,
            "necessary_parity_state":state,
        }
    return {
        "clock_anchor_utc":anchor,
        "horizons":results,
        "all_testable_frozen_prior_heads_pass":all(
            v["necessary_parity_state"]!="FAIL_NOT_PINNED_MODEL" for v in results.values()),
        "mathematical_provenance_only":True,
        "not_independent_Cosign_verification":True,
        "trading_authority":False,
    }

def audit_files(directory):
    directory=pathlib.Path(directory)
    weights=json.loads((directory/"frozen_historical_weights_first_asof_20261013.json").read_text())
    rows=[]
    for path in sorted(directory.glob("*_probabilities_unverified_research.json")):
        pred=json.loads(path.read_text())
        if not pred["clock_anchor_utc"].endswith(":00:00+00:00"):
            continue
        audit=audit_frozen_probability_parity(weights,pred)
        audit["forecast_filename"]=path.name
        rows.append(audit)
    return {
        "schema":"btc-v7r6-frozen-prior-necessary-parity-audit-v1",
        "checked_hourly_research_forecasts":len(rows),
        "failed_1h_pinned_parity":sum(
            r["horizons"]["1h"]["necessary_parity_state"]=="FAIL_NOT_PINNED_MODEL"
            for r in rows),
        "valid_1h_pinned_parity":sum(
            r["horizons"]["1h"]["necessary_parity_state"]=="PASS"
            for r in rows),
        "cannot_attribute_nonparity_1h_Brier_gain_to_original_frozen_math":True,
        "historical_research_weights_unchanged":True,
        "forecast_files_unchanged":True,
        "trading_authority":False,
        "individual_results":rows,
    }

if __name__=="__main__":
    import argparse
    p=argparse.ArgumentParser()
    p.add_argument("--directory",required=True)
    args=p.parse_args()
    report=audit_files(args.directory)
    print(json.dumps(report,sort_keys=True,indent=2,allow_nan=False))
