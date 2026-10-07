"""Full cryptographic journal verification for R7 admission/audit paths.

Critical-path forecast execution may use signed incremental checkpoints, but an
admission decision must never rely only on a checkpoint. This verifier replays the
entire journal, verifies every Sigstore/Rekor record, enforces all event invariants,
and binds every signer workflow commit to the frozen manifest.
"""
from __future__ import annotations

import json
from pathlib import Path

from predictive_vnext4r7.checkpoint import initial_state, advance_state, event_files
from predictive_vnext4r7.integrity import (
    canonical,
    digest,
    verify_event_workflow_against_manifest,
)


def full_verify_journal(
    *,
    repo_root: Path,
    events_dir: Path,
    workflow_path: str,
    manifest: dict,
    head: str,
    horizon,
    verify_event_signature,
):
    state = initial_state()
    rekor_times = {}
    files = event_files(events_dir)
    for i, path in enumerate(files, 1):
        raw = path.read_bytes()
        event = json.loads(raw)
        if raw != canonical(event):
            raise ValueError("non-canonical event")
        integrated = verify_event_signature(
            path,
            path.with_suffix(".sigstore.json"),
            event,
        )
        verify_event_workflow_against_manifest(
            repo_root,
            event,
            workflow_path,
            manifest,
        )
        advance_state(
            state,
            event,
            raw,
            head=head,
            horizon=horizon,
        )
        rekor_times[i] = integrated

    return {
        "event_count": state.sequence,
        "last_event_hash": state.last_event_hash,
        "prefix_root_sha256": state.prefix_root_sha256,
        "rekor_times": rekor_times,
        "full_verification": True,
        "trading_authority": False,
    }
