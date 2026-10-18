"""Read-only mathematical parity of already-published BTC v7R6 research probabilities.

This audit never issues a forecast or changes frozen weights. A research
forecast is admissible as evidence for the pinned pre-epoch mathematical
model only if every reconstructable head agrees with that exact model.
When the R5 source window is too short, report UNKNOWN, never silently PASS.

Source SHA and first GitHub commit time must be supplied from the GitHub
contents and commits APIs; neither R5 source nor research probabilities
are independently Sigstore verified by this function.
"""
from __future__ import annotations
import datetime as dt
import math
from btc_skill_rebuild.research_signed_spot_forward_v7r6 import asof_last_feature
from btc_skill_rebuild.research_endpoint_24h_v7r6 import predict

UTC = dt.timezone.utc
PINNED_FORECAST_PRODUCER_BLOB = "9709e5c8b886f4f362fd003d0af91f74e3e9dc38"
PINNED_FROZEN_WEIGHTS_BLOB = "05e61325250fbd470c988326cbeaf24853bd6947"
HEADS = ("1h", "4h", "24h")
LABELS = ("up", "down", "range")
EPS = 1e-11

def utc(raw):
    x = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if x.tzinfo is None or x.utcoffset() is None:
        raise ValueError("timezone-aware UTC required")
    return x.astimezone(UTC)

def audit_published_heads(weights, forecast, source, source_blob_sha,
                          original_first_commit_utc):
    anchor = utc(forecast["clock_anchor_utc"])
    public = utc(original_first_commit_utc)
    if not anchor <= public <= anchor + dt.timedelta(minutes=13):
        raise ValueError("not a timely prospective research publication")
    if utc(source["anchor_utc"]) != anchor:
        raise ValueError("R5 snapshot anchor mismatch")
    if utc(source["retrieved_at_utc"]) > public:
        raise ValueError("source was not available by forecast publication")
    if source.get("no_backfill") is not True:
        raise ValueError("source is not a non-backfilled R5 snapshot")
    if source_blob_sha != forecast["input_R5_spot_source_blob_GitHub_sha1"]:
        raise ValueError("substituted source Git blob")
    if forecast.get("trading_authority") is not False:
        raise ValueError("research forecast has no trading authority")
    if set(weights["heads"]) != set(HEADS) or set(forecast["three_way"]) != set(HEADS):
        raise ValueError("three frozen heads required")
    rows = source["five_min_rows"]
    # Do not import an unseen historical archive or synthesize missing bars.
    can_reconstruct = len(rows) >= 290
    if can_reconstruct:
        feature_time, x, actual_reference = asof_last_feature(rows)
        if dt.datetime.fromtimestamp(feature_time / 1000, UTC) != anchor:
            raise ValueError("future or stale source feature anchor")
    else:
        x = None
        actual_reference = None
    outcomes = {}
    for h in HEADS:
        frozen = weights["heads"][h]
        head = forecast["three_way"][h]
        alpha = float(frozen["validation_selected_shrink"])
        if not math.isfinite(alpha) or not 0 <= alpha <= 1:
            raise ValueError("invalid frozen shrink")
        if utc(head["source_anchor_utc"]) != anchor:
            raise ValueError("head anchor mismatch")
        if float(head["endpoint_threshold_fraction"]) != float(frozen["threshold"]):
            raise ValueError("threshold drift")
        if utc(head["horizon_target_utc"]) != anchor + dt.timedelta(
                minutes=5 * int(frozen["duration_5m_steps"])):
            raise ValueError("horizon target drift")
        p = [float(head[k]) for k in LABELS]
        if not all(math.isfinite(v) and 0 <= v <= 1 for v in p) or abs(sum(p)-1) > 1e-9:
            raise ValueError("invalid published probability simplex")
        if can_reconstruct:
            if abs(float(head["reference_spot_usdt"])-actual_reference) > 1e-8:
                raise ValueError("published spot reference differs from frozen source")
            expected = predict(frozen["model_parameters"], x, alpha)
            basis = "EXACT_SOURCE_FEATURE_AND_FROZEN_MODEL"
        elif alpha == 1:
            expected = list(frozen["model_parameters"][3])
            basis = "ALPHA_ONE_EXACT_TRAIN_PRIOR_IDENTITY"
        else:
            expected = None
            basis = "INSUFFICIENT_SOURCE_HISTORY_TO_RECONSTRUCT"
        distance = sum(abs(a-b) for a,b in zip(p,expected)) if expected else None
        verdict = ("UNKNOWN" if expected is None else
                   "PASS" if distance <= EPS else "FAIL")
        outcomes[h] = {
            "verdict": verdict,
            "basis": basis,
            "published": p,
            "expected": expected,
            "L1": distance,
            "alpha": alpha,
        }
    return {
        "clock_anchor_utc": anchor.isoformat(),
        "original_GitHub_commit_utc": public.isoformat(),
        "source_blob": source_blob_sha,
        "source_closed_5m_count": len(rows),
        "heads": outcomes,
        "all_heads_mathematically_reproduced":
            all(v["verdict"] == "PASS" for v in outcomes.values()),
        "any_pinned_head_failed":
            any(v["verdict"] == "FAIL" for v in outcomes.values()),
        "any_unknown_head":
            any(v["verdict"] == "UNKNOWN" for v in outcomes.values()),
        "frozen_source_unchanged": True,
        "independently_Cosign_verified": False,
        "trading_authority": False,
    }
