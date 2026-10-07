"""Admission-score core for the R7 successor candidate.

Unlike R6, this module validates exact event uniqueness/time semantics before any
slot dictionaries are built, and counts only persistent, separated volatility
episodes. It is intentionally decoupled from a production start date until the
successor epoch is independently approved.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np

from predictive_vnext4r7.episodes import episode_summary, stress_episode_skill_summary
from predictive_vnext4r7.integrity import parse_utc, validate_event_collection

UTC = timezone.utc
SEED = 20261007
CLASS_TO_ID = {
    "LOWER_FIRST": 0,
    "UPPER_FIRST": 1,
    "NEITHER": 2,
    "AMBIGUOUS_SAME_BAR": 3,
}


def distribution(obj):
    keys = (
        "lower_first",
        "upper_first",
        "neither",
        "ambiguous_same_bar",
    )
    p = np.asarray([float(obj[k]) for k in keys], dtype=float)
    if (
        len(p) != 4
        or not np.all(np.isfinite(p))
        or np.any(p < 0)
        or abs(float(p.sum()) - 1.0) > 1e-8
    ):
        raise ValueError("invalid probability distribution")
    return p


def metrics(p, y):
    one = np.eye(4)[y]
    eps = 1e-12
    brier = float(np.mean(np.sum((p - one) ** 2, axis=1)))
    log_loss = float(
        -np.mean(np.log(np.clip(p[np.arange(len(y)), y], eps, 1)))
    )
    confidence = p.max(axis=1)
    correct = p.argmax(axis=1) == y
    ece = 0.0
    edges = np.linspace(0, 1, 11)
    for a, b in zip(edges[:-1], edges[1:]):
        mask = (confidence >= a) & (
            confidence < (b if b < 1 else 1.000001)
        )
        if np.any(mask):
            ece += float(np.mean(mask)) * abs(
                float(np.mean(correct[mask]))
                - float(np.mean(confidence[mask]))
            )
    return {"brier": brier, "log_loss": log_loss, "ece10": ece}


def block_lower(values, anchors, block_days, alpha):
    values = np.asarray(values, dtype=float)
    if len(values) < 2:
        return None
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    block_seconds = block_days * 86400
    groups = {}
    for i, anchor in enumerate(anchors):
        key = int((anchor - epoch).total_seconds() // block_seconds)
        groups.setdefault(key, []).append(i)
    blocks = [np.asarray(v, dtype=int) for _, v in sorted(groups.items())]
    if len(blocks) < 2:
        return None
    rng = np.random.default_rng(SEED + block_days)
    samples = []
    for _ in range(1200):
        ids = np.concatenate(
            [blocks[j] for j in rng.integers(len(blocks), size=len(blocks))]
        )
        samples.append(float(np.mean(values[ids])))
    return float(np.quantile(samples, alpha))


def expected_slots(start, cutoff, nonoverlap_hours):
    slots = []
    step = timedelta(hours=nonoverlap_hours)
    anchor = start
    while anchor + step <= cutoff:
        slots.append(anchor)
        anchor += step
    return slots


def _slot_text(anchor):
    return anchor.strftime("%Y%m%dT%H%M%SZ")


def score_from_events(
    events,
    protocol,
    *,
    start_utc,
    horizon,
    allow_admission=False,
):
    # R7.1 security boundary: this numerical calculator can never authorize
    # admission. Only predictive_vnext4r71.admission.run_admission() may promote
    # verified gates to admission_ready=true after full cryptographic replay.
    if allow_admission:
        raise RuntimeError(
            "direct admission forbidden; use R7.1 mandatory admission entrypoint"
        )
    head = protocol["head"]
    validate_event_collection(
        events,
        head=head,
        horizon=horizon,
    )

    forecasts = {
        e["slot"]: e for e in events if e.get("type") == "FORECAST_ISSUED"
    }
    outcomes = {
        e["slot"]: e for e in events if e.get("type") == "OUTCOME_RECORDED"
    }
    receipts = {
        e["slot"]: e for e in events if e.get("type") == "DELIVERY_CONFIRMED"
    }

    cutoff = datetime.now(UTC)
    if protocol.get("diagnostic_cutoff_utc") is not None:
        cutoff = parse_utc(protocol["diagnostic_cutoff_utc"])
        allow_admission = False

    adm = protocol["admission"]
    nonoverlap_hours = int(adm["nonoverlap_window_hours"])
    due = expected_slots(start_utc, cutoff, nonoverlap_hours)
    due_slots = [_slot_text(x) for x in due]
    missing = [
        slot for slot in due_slots
        if slot not in forecasts or slot not in outcomes or slot not in receipts
    ]
    complete = [slot for slot in due_slots if slot not in missing]

    result = {
        "expected_due_nonoverlap_windows": len(due_slots),
        "complete_due_nonoverlap_windows": len(complete),
        "missing_due_nonoverlap_slots": missing,
        "complete_due_grid": not missing,
        "calendar_days": max(
            0.0, (cutoff - start_utc).total_seconds() / 86400.0
        ),
        "admission_ready": False,
        "prospective_winner": None,
    }
    if not complete:
        result["status"] = "PENDING_NO_DUE_INDEPENDENT_WINDOWS"
        return result

    y = np.asarray(
        [CLASS_TO_ID[outcomes[s]["outcome_class"]] for s in complete],
        dtype=int,
    )
    model = np.vstack(
        [distribution(forecasts[s]["class_distribution"]) for s in complete]
    )
    baseline = np.vstack(
        [
            distribution(forecasts[s]["control"]["primary_distribution"])
            for s in complete
        ]
    )
    anchors = [parse_utc(forecasts[s]["anchor_utc"]) for s in complete]
    bins = [int(forecasts[s]["control"]["volatility_bin"]) for s in complete]

    model_metrics = metrics(model, y)
    baseline_metrics = metrics(baseline, y)
    one = np.eye(4)[y]
    eps = 1e-12
    brier_gain = (
        np.sum((baseline - one) ** 2, axis=1)
        - np.sum((model - one) ** 2, axis=1)
    )
    logloss_gain = (
        -np.log(np.clip(baseline[np.arange(len(y)), y], eps, 1))
        + np.log(np.clip(model[np.arange(len(y)), y], eps, 1))
    )

    alpha = float(protocol["multiple_head_correction"]["per_head_alpha"])
    lowers = {}
    for days in adm["block_lengths_days"]:
        lowers[f"brier_gain_lower_{days}d"] = block_lower(
            brier_gain, anchors, int(days), alpha
        )
        lowers[f"logloss_gain_lower_{days}d"] = block_lower(
            logloss_gain, anchors, int(days), alpha
        )

    ep = adm["volatility_episode_policy"]
    episodes = episode_summary(
        anchors,
        bins,
        window_hours=nonoverlap_hours,
        minimum_duration_hours=int(ep["minimum_duration_hours"]),
        minimum_separation_hours=int(ep["minimum_separation_hours"]),
    )
    stress_policy = adm.get("stress_episode_policy")
    stress = None
    if stress_policy is not None:
        stress = stress_episode_skill_summary(
            anchors,
            bins,
            brier_gain,
            logloss_gain,
            window_hours=nonoverlap_hours,
            minimum_duration_hours=int(
                stress_policy["minimum_duration_hours"]
            ),
            minimum_separation_hours=int(
                stress_policy["minimum_separation_hours"]
            ),
            stress_bin=int(stress_policy["stress_bin"]),
        )

    result.update(
        {
            "selected_model": protocol["selected_model"],
            "selected_model_nonoverlap": model_metrics,
            "primary_baseline_nonoverlap": baseline_metrics,
            "brier_gain_mean": float(np.mean(brier_gain)),
            "logloss_gain_mean": float(np.mean(logloss_gain)),
            "block_lower_bounds": lowers,
            "volatility_episode_policy": ep,
            "volatility_episode_interpretation": (
                "HEURISTIC_DIVERSITY_REQUIREMENT_NOT_INDEPENDENCE_PROOF"
            ),
            "independent_volatility_episodes": episodes,
            "stress_episode_robustness": stress,
        }
    )

    gates = {
        "complete_due_grid": result["complete_due_grid"],
        "calendar": result["calendar_days"]
        >= float(adm["minimum_calendar_days"]),
        "nonoverlap_expected_grid": len(complete)
        >= int(adm["minimum_fixed_phase_nonoverlap_windows"]),
        "independent_episodes": episodes["count"]
        >= int(adm["minimum_independent_volatility_episodes"])
        and (
            not adm["require_all_three_volatility_bins"]
            or len(episodes["bins_seen"]) == 3
        ),
        "brier_better": model_metrics["brier"]
        < baseline_metrics["brier"],
        "logloss_better": model_metrics["log_loss"]
        < baseline_metrics["log_loss"],
        "block_ci": all(
            value is not None and value > 0
            for value in lowers.values()
        ),
        "stress_robustness": (
            True
            if stress_policy is None
            else (
                stress is not None
                and stress["count"]
                >= int(stress_policy["minimum_episodes_for_skill_claim"])
                and stress["episode_weighted_mean_brier_gain"] is not None
                and stress["episode_weighted_mean_brier_gain"] > 0
                and stress["episode_weighted_mean_logloss_gain"] is not None
                and stress["episode_weighted_mean_logloss_gain"] > 0
            )
        ),
        "calibration": model_metrics["ece10"]
        <= baseline_metrics["ece10"]
        + float(adm["calibration_max_ece10_degradation_vs_primary"]),
    }
    result["gates"] = gates
    result["admission_ready"] = False
    result["prospective_winner"] = None
    result["status"] = (
        "NUMERICAL_GATES_PASS_VERIFICATION_REQUIRED"
        if all(gates.values())
        else "PROSPECTIVE_GATE_PENDING_OR_FAIL"
    )
    return result
