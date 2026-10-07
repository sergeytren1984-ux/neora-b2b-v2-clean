"""Audit current R6 evidence with the stricter R7 workflow-binding rules.

This is read-only validation of the existing R6 epoch. It does not upgrade R6 and
does not make R6 admissible; it proves that the new verifier accepts the already
observed honest prefix while rejecting future workflow drift.
"""
from __future__ import annotations

import argparse
import json
from datetime import timedelta
from pathlib import Path

from predictive_vnext4r7.integrity import (
    canonical,
    validate_event_collection,
    verify_event_workflow_against_manifest,
)

CONFIG = {
    "1h": {
        "events": "predictive_vnext4r6_1h_events",
        "workflow": ".github/workflows/btc-predictive-vnext4r6-1h.yml",
        "horizon": timedelta(hours=1),
    },
    "4h": {
        "events": "predictive_vnext4r6_4h_events",
        "workflow": ".github/workflows/btc-predictive-vnext4r6-4h.yml",
        "horizon": timedelta(hours=4),
    },
    "24h": {
        "events": "predictive_vnext4r6_24h_events",
        "workflow": ".github/workflows/btc-predictive-vnext4r6-24h.yml",
        "horizon": timedelta(hours=24),
    },
}


def run(head: str, repo_root: str = "."):
    cfg = CONFIG[head]
    root = Path(repo_root).resolve()
    directory = root / cfg["events"]
    files = sorted(
        p for p in directory.glob("*.json")
        if len(p.stem) == 8 and p.stem.isdigit()
    )
    events = []
    for path in files:
        raw = path.read_bytes()
        event = json.loads(raw)
        if raw != canonical(event):
            raise ValueError("non-canonical R6 event: " + path.name)
        events.append(event)

    validate_event_collection(
        events,
        head=head,
        horizon=cfg["horizon"],
    )
    freezes = [
        e for e in events if e.get("type") == "CONFIG_FROZEN_PRESTART"
    ]
    if len(freezes) != 1:
        raise ValueError("R6 freeze count mismatch")
    manifest = freezes[0]["manifest"]

    verified = 0
    commits = set()
    for event in events:
        verify_event_workflow_against_manifest(
            root,
            event,
            cfg["workflow"],
            manifest,
        )
        verified += 1
        commits.add(event["workflow_commit"])

    return {
        "head": head,
        "events": len(events),
        "workflow_commits_checked": len(commits),
        "workflow_path": cfg["workflow"],
        "status": "R7_STRICT_BINDING_PASS",
        "note": "Read-only check of R6 evidence; no R6 admission implied.",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--head", required=True, choices=sorted(CONFIG))
    parser.add_argument("--repo-root", default=".")
    args = parser.parse_args()
    print(json.dumps(run(args.head, args.repo_root), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
