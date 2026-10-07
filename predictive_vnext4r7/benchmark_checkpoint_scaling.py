"""Measured scaling benchmark for R6 full replay vs R7 checkpoints."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from predictive_vnext4r7.checkpoint import event_files, prefix_file_digest
from predictive_vnext4r7.journal_runtime import make_blob_verifier

CONFIG = {
    "1h": {
        "events": "predictive_vnext4r6_1h_events",
        "workflow": ".github/workflows/btc-predictive-vnext4r6-1h.yml",
        "days": 42,
        "events_per_day": 288,
    },
    "4h": {
        "events": "predictive_vnext4r6_4h_events",
        "workflow": ".github/workflows/btc-predictive-vnext4r6-4h.yml",
        "days": 42,
        "events_per_day": 288,
    },
    "24h": {
        "events": "predictive_vnext4r6_24h_events",
        "workflow": ".github/workflows/btc-predictive-vnext4r6-24h.yml",
        "days": 60,
        "events_per_day": 72,
    },
}


def run(head, repo_root=".", sample_signatures=12):
    cfg = CONFIG[head]
    root = Path(repo_root).resolve()
    directory = root / cfg["events"]
    files = event_files(directory)
    if not files:
        raise ValueError("no evidence files")

    # Measure actual JSON prefix hashing on the evidence filesystem.
    t0 = time.perf_counter()
    prefix_file_digest(files, len(files))
    hash_seconds = time.perf_counter() - t0
    hash_per_event = hash_seconds / len(files)

    # Measure real Cosign+Rekor verification cost on a bounded current sample.
    verify = make_blob_verifier(root, cfg["workflow"])
    sample = files[: min(sample_signatures, len(files))]
    t0 = time.perf_counter()
    for path in sample:
        event = json.loads(path.read_bytes())
        verify(path, path.with_suffix(".sigstore.json"), event)
    signature_seconds = time.perf_counter() - t0
    signature_per_event = signature_seconds / len(sample)

    projected_events = 2 + cfg["days"] * cfg["events_per_day"]
    full_one_scan = projected_events * (
        signature_per_event + hash_per_event
    )
    # R6 calls complete-history verification multiple times on common paths.
    conservative_four_scans = 4.0 * full_one_scan

    # R7: two authority signatures + one checkpoint signature + at most
    # checkpoint_interval-1 suffix signatures. Prefix JSON re-hash remains linear
    # but cheap and detects post-checkpoint file rewrites.
    checkpoint_interval = 24
    max_signature_checks = 2 + 1 + (checkpoint_interval - 1)
    checkpoint_critical = (
        max_signature_checks * signature_per_event
        + projected_events * hash_per_event
    )

    return {
        "schema": "btc-predictive-vnext4r7-scaling-benchmark-v1",
        "head": head,
        "current_events": len(files),
        "sample_signature_verifications": len(sample),
        "measured": {
            "json_prefix_hash_seconds": hash_seconds,
            "json_hash_seconds_per_event": hash_per_event,
            "cosign_rekor_seconds_total_sample": signature_seconds,
            "cosign_rekor_seconds_per_event": signature_per_event,
        },
        "projection": {
            "days": cfg["days"],
            "events_per_day_nominal": cfg["events_per_day"],
            "projected_events": projected_events,
            "r6_one_full_scan_seconds": full_one_scan,
            "r6_four_full_scans_seconds": conservative_four_scans,
            "r7_checkpoint_interval_events": checkpoint_interval,
            "r7_max_signature_checks_on_critical_path": max_signature_checks,
            "r7_critical_path_seconds_estimate": checkpoint_critical,
            "estimated_speedup_vs_one_full_scan": (
                full_one_scan / checkpoint_critical
                if checkpoint_critical > 0 else None
            ),
            "estimated_speedup_vs_four_full_scans": (
                conservative_four_scans / checkpoint_critical
                if checkpoint_critical > 0 else None
            ),
        },
        "limitations": [
            "Projection assumes current average Cosign/Rekor verification latency.",
            "GitHub, network and git push latency are not included.",
            "Event rate is nominal forecast+delivery+outcome and excludes abstention/checkpoint commits.",
            "This benchmark measures evidence-verification scaling, not end-to-end SLA.",
        ],
        "trading_authority": False,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--head", required=True, choices=sorted(CONFIG))
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--sample-signatures", type=int, default=12)
    args = parser.parse_args()
    print(
        json.dumps(
            run(args.head, args.repo_root, args.sample_signatures),
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
