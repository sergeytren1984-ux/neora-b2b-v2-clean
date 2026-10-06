"""Prospective governance and performance scorecard for BTC Predictive vNext4R6.

Admission always uses the trusted runner UTC clock. A historical diagnostic cutoff
may be requested, but it can never set admission_ready=true.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from predictive_vnext4r6.worker import (
    CONFIG,
    START,
    CLASS_TO_ID,
    canonical,
    digest,
    identity,
    signature_claim_args,
)

UTC = timezone.utc
ISSUER = "https://token.actions.githubusercontent.com"
SEED = 20261006


def parse_time(value):
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def bundle_time(path):
    bundle = json.loads(Path(path).read_bytes())
    entries = bundle.get("verificationMaterial", {}).get("tlogEntries", [])
    if not entries:
        raise ValueError("Rekor entry missing")
    for entry in entries:
        proof = entry.get("inclusionProof")
        if (
            not isinstance(proof, dict)
            or not proof.get("checkpoint")
            or "hashes" not in proof
        ):
            raise ValueError("Rekor inclusion proof missing")
    return min(
        datetime.fromtimestamp(int(entry["integratedTime"]), UTC)
        for entry in entries
    )


def verify_signature(path, bundle, workflow_path, event):
    subprocess.run(
        [
            "cosign",
            "verify-blob",
            str(path),
            "--bundle",
            str(bundle),
            "--certificate-identity",
            identity(workflow_path),
            "--certificate-oidc-issuer",
            ISSUER,
            *signature_claim_args(event),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=180,
    )
    return bundle_time(bundle)


def load_chain(root, cfg):
    directory = root / cfg["events"]
    files = sorted(
        p
        for p in directory.glob("*.json")
        if len(p.stem) == 8 and p.stem.isdigit()
    )
    events = []
    rekor = {}
    previous = None
    keys = set()
    for i, path in enumerate(files, 1):
        raw = path.read_bytes()
        event = json.loads(raw)
        workflow = (
            cfg["outcome_workflow"]
            if event.get("type") == "OUTCOME_RECORDED"
            else cfg["forecast_workflow"]
        )
        integrated = verify_signature(
            path, path.with_suffix(".sigstore.json"), workflow, event
        )
        if raw != canonical(event):
            raise ValueError("non-canonical event")
        if event.get("sequence") != i:
            raise ValueError("event sequence gap")
        if event.get("previous_hash") != previous:
            raise ValueError("event hash chain broken")
        key = event.get("idempotency_key")
        if not isinstance(key, str) or key in keys:
            raise ValueError("duplicate/missing idempotency key")
        keys.add(key)
        previous = digest(raw)
        events.append(event)
        rekor[i] = integrated
    return events, rekor


def distribution(obj):
    keys = (
        "lower_first",
        "upper_first",
        "neither",
        "ambiguous_same_bar",
    )
    try:
        p = np.asarray([float(obj[k]) for k in keys], dtype=float)
    except Exception as ex:
        raise ValueError("malformed probability distribution") from ex
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


def independent_episode_count(bins):
    if not bins:
        return 0
    episodes = 1
    for a, b in zip(bins, bins[1:]):
        if b != a:
            episodes += 1
    return episodes


def expected_slots(cutoff, nonoverlap_hours):
    slots = []
    step = timedelta(hours=nonoverlap_hours)
    anchor = START
    horizon = step
    while anchor + horizon <= cutoff:
        slots.append(anchor)
        anchor += step
    return slots


def verify_governance(root, events, rekor, cfg, protocol, current_cutoff):
    rejected = []
    schedules = [
        event
        for event in events
        if event.get("type") == "SCHEDULE_REGISTERED"
    ]
    freezes = [
        event
        for event in events
        if event.get("type") == "CONFIG_FROZEN_PRESTART"
    ]
    if len(schedules) != 1:
        rejected.append({"reason": "schedule_count", "count": len(schedules)})
    if len(freezes) != 1:
        rejected.append({"reason": "freeze_count", "count": len(freezes)})

    expected_source = None
    if len(schedules) == 1:
        schedule = schedules[0]
        expected_source = schedule.get("source_commit_sha")
        if parse_time(schedule.get("start_utc")) != START:
            rejected.append({"reason": "schedule_start_mismatch"})
        if schedule.get("head") != protocol["head"]:
            rejected.append({"reason": "schedule_head_mismatch"})
        if int(schedule.get("deadline_minutes", -1)) != int(
            protocol["issuance_deadline_minutes"]
        ):
            rejected.append({"reason": "schedule_deadline_mismatch"})
        if schedule.get("protocol_sha256") != digest(
            (root / cfg["protocol"]).read_bytes()
        ):
            rejected.append({"reason": "schedule_protocol_hash_mismatch"})
        integrated = rekor.get(int(schedule["sequence"]))
        if integrated is None or integrated >= START:
            rejected.append({"reason": "schedule_not_rekor_prestart"})

    manifest = None
    if len(freezes) == 1:
        freeze = freezes[0]
        integrated = rekor.get(int(freeze["sequence"]))
        if integrated is None or integrated >= START:
            rejected.append({"reason": "freeze_not_rekor_prestart"})
        manifest = freeze.get("manifest")
        if (
            not isinstance(manifest, dict)
            or digest(canonical(manifest)) != freeze.get("manifest_sha256")
        ):
            rejected.append({"reason": "freeze_manifest_hash_mismatch"})
        elif expected_source and manifest.get("source_commit_sha") != expected_source:
            rejected.append({"reason": "freeze_source_mismatch"})

    forecasts = {
        event["slot"]: event
        for event in events
        if event.get("type") == "FORECAST_ISSUED"
    }
    outcomes = {
        event["slot"]: event
        for event in events
        if event.get("type") == "OUTCOME_RECORDED"
    }
    receipts = {}
    for event in events:
        if event.get("type") == "DELIVERY_CONFIRMED":
            receipts[event.get("slot")] = event

    tip = None
    try:
        tip = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        ).stdout.strip()
    except Exception:
        rejected.append({"reason": "cannot_read_evidence_tip"})

    for slot, forecast in forecasts.items():
        try:
            anchor = parse_time(forecast["anchor_utc"])
            deadline = anchor + timedelta(
                minutes=int(protocol["issuance_deadline_minutes"])
            )
            integrated = rekor[int(forecast["sequence"])]
            if integrated >= deadline:
                rejected.append(
                    {"reason": "forecast_rekor_late", "slot": slot}
                )
            if parse_time(forecast["published_at_utc"]) >= deadline:
                rejected.append(
                    {"reason": "forecast_published_late", "slot": slot}
                )
            if forecast.get("artifact_sha256") != protocol["artifact_sha256"]:
                rejected.append(
                    {"reason": "forecast_artifact_hash_mismatch", "slot": slot}
                )
            if forecast.get("baseline_sha256") != protocol["baseline_sha256"]:
                rejected.append(
                    {"reason": "forecast_baseline_hash_mismatch", "slot": slot}
                )
            distribution(forecast["class_distribution"])
            distribution(forecast["control"]["primary_distribution"])
            raw_path = root / forecast["raw_path"]
            if (
                not raw_path.exists()
                or digest(raw_path.read_bytes()) != forecast["raw_sha256"]
            ):
                rejected.append(
                    {"reason": "forecast_raw_hash_mismatch", "slot": slot}
                )
        except Exception as ex:
            rejected.append(
                {"reason": "forecast_invalid", "slot": slot, "detail": str(ex)}
            )

        receipt = receipts.get(slot)
        if receipt is None:
            rejected.append({"reason": "delivery_missing", "slot": slot})
            continue
        try:
            if receipt.get("target_sequence") != forecast.get("sequence"):
                raise ValueError("delivery target sequence mismatch")
            if receipt.get("target_event_hash") != digest(canonical(forecast)):
                raise ValueError("delivery target hash mismatch")
            if parse_time(receipt["deadline_utc"]) != deadline:
                raise ValueError("delivery deadline mismatch")
            if rekor[int(receipt["sequence"])] >= deadline:
                raise ValueError("delivery Rekor time late")
            commit = receipt.get("remote_commit_sha")
            if not commit or len(commit) != 40:
                raise ValueError("delivery remote commit missing")
            path = f"{cfg['events']}/{int(forecast['sequence']):08d}.json"
            exact = subprocess.run(
                ["git", "-C", str(root), "show", f"{commit}:{path}"],
                check=True,
                capture_output=True,
                timeout=60,
            ).stdout
            if exact != canonical(forecast):
                raise ValueError("delivery commit lacks exact forecast")
            if tip:
                subprocess.run(
                    [
                        "git",
                        "-C",
                        str(root),
                        "merge-base",
                        "--is-ancestor",
                        commit,
                        tip,
                    ],
                    check=True,
                    capture_output=True,
                    timeout=60,
                )
        except Exception as ex:
            rejected.append(
                {
                    "reason": "delivery_remote_commit_invalid",
                    "slot": slot,
                    "detail": str(ex),
                }
            )

    for slot, outcome in outcomes.items():
        try:
            due = parse_time(outcome["due_utc"])
            if parse_time(outcome["published_at_utc"]) < due:
                raise ValueError("outcome published before due")
            if rekor[int(outcome["sequence"])] < due:
                raise ValueError("outcome Rekor before due")
            if slot not in forecasts:
                raise ValueError("outcome without forecast")
            if outcome.get("outcome_class") not in CLASS_TO_ID:
                raise ValueError("unknown outcome class")
            raw_path = root / outcome["raw_path"]
            if (
                not raw_path.exists()
                or digest(raw_path.read_bytes()) != outcome["raw_sha256"]
            ):
                raise ValueError("outcome raw hash mismatch")
        except Exception as ex:
            rejected.append(
                {"reason": "outcome_invalid", "slot": slot, "detail": str(ex)}
            )

    return {
        "ok": not rejected,
        "source_commit_sha": expected_source,
        "event_count": len(events),
        "rejected": rejected,
        "trusted_cutoff_utc": current_cutoff.isoformat(),
    }


def score_from_events(events, protocol, cutoff, allow_admission=True):
    forecasts = {
        event["slot"]: event
        for event in events
        if event.get("type") == "FORECAST_ISSUED"
    }
    outcomes = {
        event["slot"]: event
        for event in events
        if event.get("type") == "OUTCOME_RECORDED"
    }
    receipts = {
        event["slot"]: event
        for event in events
        if event.get("type") == "DELIVERY_CONFIRMED"
    }

    adm = protocol["admission"]
    nonoverlap_hours = int(adm["nonoverlap_window_hours"])
    due_slots = expected_slots(cutoff, nonoverlap_hours)
    due_text = [slot.strftime("%Y%m%dT%H%M%SZ") for slot in due_slots]
    missing = [
        slot
        for slot in due_text
        if slot not in forecasts
        or slot not in outcomes
        or slot not in receipts
    ]
    complete_slots = [slot for slot in due_text if slot not in missing]

    result = {
        "evaluation_mode": (
            "CURRENT_TRUSTED_CLOCK"
            if allow_admission
            else "HISTORICAL_DIAGNOSTIC_ONLY"
        ),
        "cutoff_utc": cutoff.isoformat(),
        "expected_due_nonoverlap_windows": len(due_text),
        "complete_due_nonoverlap_windows": len(complete_slots),
        "missing_due_nonoverlap_slots": missing,
        "complete_due_grid": len(missing) == 0,
        "calendar_days": max(
            0.0, (cutoff - START).total_seconds() / 86400.0
        ),
        "admission_ready": False,
        "status": "PENDING_NO_DUE_INDEPENDENT_WINDOWS",
        "prospective_winner": None,
    }
    if not complete_slots:
        return result

    y = np.asarray(
        [CLASS_TO_ID[outcomes[slot]["outcome_class"]] for slot in complete_slots],
        dtype=int,
    )
    model = np.vstack(
        [distribution(forecasts[slot]["class_distribution"]) for slot in complete_slots]
    )
    primary = np.vstack(
        [
            distribution(
                forecasts[slot]["control"]["primary_distribution"]
            )
            for slot in complete_slots
        ]
    )
    bins = [
        int(forecasts[slot]["control"]["volatility_bin"])
        for slot in complete_slots
    ]
    anchors = [parse_time(forecasts[slot]["anchor_utc"]) for slot in complete_slots]

    model_metrics = metrics(model, y)
    baseline_metrics = metrics(primary, y)
    one = np.eye(4)[y]
    eps = 1e-12
    brier_gain = (
        np.sum((primary - one) ** 2, axis=1)
        - np.sum((model - one) ** 2, axis=1)
    )
    logloss_gain = (
        -np.log(np.clip(primary[np.arange(len(y)), y], eps, 1))
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

    episodes = independent_episode_count(bins)
    result.update(
        {
            "selected_model": protocol["selected_model"],
            "selected_model_nonoverlap": model_metrics,
            "primary_baseline_nonoverlap": baseline_metrics,
            "brier_gain_mean": float(np.mean(brier_gain)),
            "logloss_gain_mean": float(np.mean(logloss_gain)),
            "block_lower_bounds": lowers,
            "volatility_bins_seen_nonoverlap": sorted(set(bins)),
            "independent_volatility_episode_count": episodes,
        }
    )

    lower_values = list(lowers.values())
    gates = {
        "complete_due_grid": result["complete_due_grid"],
        "calendar": result["calendar_days"]
        >= float(adm["minimum_calendar_days"]),
        "nonoverlap_expected_grid": len(complete_slots)
        >= int(adm["minimum_fixed_phase_nonoverlap_windows"]),
        "independent_episodes": episodes
        >= int(adm["minimum_independent_volatility_episodes"])
        and (
            not adm["require_all_three_volatility_bins"]
            or len(set(bins)) == 3
        ),
        "brier_better": model_metrics["brier"]
        < baseline_metrics["brier"],
        "logloss_better": model_metrics["log_loss"]
        < baseline_metrics["log_loss"],
        "block_ci": all(
            value is not None and value > 0 for value in lower_values
        ),
        "calibration": model_metrics["ece10"]
        <= baseline_metrics["ece10"]
        + float(adm["calibration_max_ece10_degradation_vs_primary"]),
    }
    result["gates"] = gates
    if allow_admission and all(gates.values()):
        result["admission_ready"] = True
        result["status"] = "PROSPECTIVE_GATE_PASS"
        result["prospective_winner"] = protocol["selected_model"]
    else:
        result["status"] = "PROSPECTIVE_GATE_PENDING_OR_FAIL"
    return result


def run(head, repo_root, diagnostic_as_of=None):
    if head not in CONFIG:
        raise ValueError("invalid head")
    root = Path(repo_root).resolve()
    cfg = CONFIG[head]
    protocol = json.loads((root / cfg["protocol"]).read_text())
    events, rekor = load_chain(root, cfg)

    trusted_now = datetime.now(UTC)
    governance = verify_governance(
        root, events, rekor, cfg, protocol, trusted_now
    )
    if diagnostic_as_of is None:
        cutoff = trusted_now
        allow_admission = governance["ok"]
    else:
        cutoff = parse_time(diagnostic_as_of)
        allow_admission = False

    score = score_from_events(
        events, protocol, cutoff, allow_admission=allow_admission
    )
    if not governance["ok"]:
        score["admission_ready"] = False
        score["status"] = "BLOCKED_GOVERNANCE"
        score["prospective_winner"] = None
    return {
        "schema": "btc-predictive-vnext4r6-scorecard-v1",
        "head": head,
        "governance": governance,
        "score": score,
        "trading_authority": False,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--head", required=True, choices=sorted(CONFIG))
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--diagnostic-as-of")
    args = parser.parse_args()
    print(
        json.dumps(
            run(args.head, args.repo_root, args.diagnostic_as_of),
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
