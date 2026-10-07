"""Incremental journal loader for R7.1 critical-path execution."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from predictive_vnext4r7.integrity import canonical, digest, parse_utc
from predictive_vnext4r71.checkpoint import event_files, verify_checkpoint
from predictive_vnext4r71.integrity import (
    validate_event_collection,
    verify_all_workflow_bindings,
)


def load_incremental_journal(
    *,
    repo_root: Path,
    events_dir: Path,
    checkpoint_path: Path,
    checkpoint_bundle_path: Path,
    head: str,
    horizon,
    issuance_deadline,
    start_utc: datetime,
    current_branch_tip: str,
    forecast_workflow: str,
    outcome_workflow: str,
    verify_event_blob,
    verify_checkpoint_blob,
    verify_workflow_binding,
):
    files = event_files(events_dir)
    if len(files) < 2:
        raise ValueError("pre-start authority events missing")

    # Authority is always verified directly, independent of checkpoint.
    authority = []
    authority_rekor = {}
    for i in (0, 1):
        path = files[i]
        raw = path.read_bytes()
        event = json.loads(raw)
        if raw != canonical(event):
            raise ValueError("authority event not canonical")
        integrated = verify_event_blob(path, path.with_suffix(".sigstore.json"), event)
        authority.append(event)
        authority_rekor[i + 1] = integrated

    if authority[0].get("type") != "SCHEDULE_REGISTERED":
        raise ValueError("event #1 must register schedule")
    if authority[1].get("type") != "CONFIG_FROZEN_PRESTART":
        raise ValueError("event #2 must freeze config")
    if parse_utc(authority[0].get("start_utc")) != start_utc:
        raise ValueError("registered start mismatch")
    if parse_utc(authority[1].get("start_utc")) != start_utc:
        raise ValueError("freeze start mismatch")
    if authority_rekor[1] >= start_utc or authority_rekor[2] >= start_utc:
        raise ValueError("authority not recorded in Rekor before start")

    manifest = authority[1].get("manifest")
    if not isinstance(manifest, dict):
        raise ValueError("signed manifest missing")
    manifest_sha = digest(canonical(manifest))
    if manifest_sha != authority[1].get("manifest_sha256"):
        raise ValueError("signed manifest hash mismatch")
    if manifest.get("source_commit_sha") != authority[0].get("source_commit_sha"):
        raise ValueError("schedule/freeze source mismatch")

    for event in authority:
        workflow = (
            outcome_workflow
            if event.get("type") == "OUTCOME_RECORDED"
            else forecast_workflow
        )
        verify_workflow_binding(repo_root, event, workflow, manifest)

    checkpoint_used = False
    verified_through = 0
    if checkpoint_path.exists() or checkpoint_bundle_path.exists():
        if not checkpoint_path.exists() or not checkpoint_bundle_path.exists():
            raise ValueError("partial checkpoint state")
        state = verify_checkpoint(
            repo_root=repo_root,
            events_dir=events_dir,
            checkpoint_path=checkpoint_path,
            checkpoint_bundle_path=checkpoint_bundle_path,
            manifest=manifest,
            manifest_sha256=manifest_sha,
            workflow_path=forecast_workflow,
            current_branch_tip=current_branch_tip,
            verify_blob=verify_checkpoint_blob,
            verify_workflow_binding=verify_workflow_binding,
            expected_head=head,
        )
        verified_through = state.sequence
        checkpoint_used = True

    # With no checkpoint we verify the full journal. With one, only the suffix.
    start_index = verified_through if checkpoint_used else 0
    suffix_rekor = {}
    for i, path in enumerate(files[start_index:], start_index + 1):
        event = json.loads(path.read_bytes())
        integrated = verify_event_blob(
            path, path.with_suffix(".sigstore.json"), event
        )
        workflow = (
            outcome_workflow
            if event.get("type") == "OUTCOME_RECORDED"
            else forecast_workflow
        )
        verify_workflow_binding(repo_root, event, workflow, manifest)
        suffix_rekor[i] = integrated

    events = [json.loads(path.read_bytes()) for path in files]
    validate_event_collection(
        events,
        head=head,
        horizon=horizon,
        issuance_deadline=issuance_deadline,
    )
    return {
        "events": events,
        "manifest": manifest,
        "manifest_sha256": manifest_sha,
        "checkpoint_used": checkpoint_used,
        "checkpoint_verified_through": verified_through,
        "verified_suffix_event_count": len(files) - start_index,
        "authority_rekor": authority_rekor,
        "suffix_rekor": suffix_rekor,
    }
