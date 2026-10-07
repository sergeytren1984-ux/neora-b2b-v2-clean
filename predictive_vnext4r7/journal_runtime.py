"""Runtime journal verifier for the R7 successor candidate.

The critical path verifies:
1) the two pre-start authority events,
2) one signed checkpoint when available,
3) only post-checkpoint event signatures/Rekor entries,
while still hashing the checkpointed prefix files to detect later rewrites.

This module is staging code. No R7 production epoch is activated by it.
"""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from predictive_vnext4r7.checkpoint import (
    event_files,
    initial_state,
    load_all_event_json,
    verify_checkpoint,
    verify_suffix,
)
from predictive_vnext4r7.integrity import (
    canonical,
    digest,
    parse_utc,
    verify_event_workflow_against_manifest,
)

UTC = timezone.utc
ISSUER = "https://token.actions.githubusercontent.com"
REPOSITORY = "sergeytren1984-ux/neora-b2b-v2-clean"


def identity(workflow_path: str) -> str:
    return (
        f"https://github.com/{REPOSITORY}/"
        f"{workflow_path}@refs/heads/main"
    )


def signature_claim_args(doc: dict):
    sha = str(doc.get("workflow_commit", ""))
    if len(sha) != 40 or any(c not in "0123456789abcdef" for c in sha.lower()):
        raise ValueError("invalid workflow_commit")
    return [
        "--certificate-github-workflow-sha",
        sha,
        "--certificate-github-workflow-repository",
        REPOSITORY,
        "--certificate-github-workflow-ref",
        "refs/heads/main",
        "--certificate-github-workflow-trigger",
        "workflow_dispatch",
    ]


def bundle_time(bundle_path: Path) -> datetime:
    bundle = json.loads(bundle_path.read_bytes())
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
        datetime.fromtimestamp(int(e["integratedTime"]), UTC)
        for e in entries
    )


def make_blob_verifier(repo_root: Path, workflow_path: str):
    def verify(path: Path, bundle: Path, doc: dict):
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
                *signature_claim_args(doc),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=180,
            cwd=repo_root,
        )
        return bundle_time(bundle)
    return verify


def _bootstrap_manifest(
    *,
    repo_root: Path,
    events_dir: Path,
    workflow_path: str,
    expected_head: str,
    start_utc: datetime,
):
    files = event_files(events_dir)
    if len(files) < 2:
        raise ValueError("pre-start schedule/freeze missing")
    verify = make_blob_verifier(repo_root, workflow_path)

    first = []
    for i in (0, 1):
        path = files[i]
        raw = path.read_bytes()
        event = json.loads(raw)
        if raw != canonical(event):
            raise ValueError("non-canonical pre-start event")
        integrated = verify(path, path.with_suffix(".sigstore.json"), event)
        if integrated >= start_utc:
            raise ValueError("pre-start event not in Rekor before start")
        first.append(event)

    schedule, freeze = first
    if schedule.get("type") != "SCHEDULE_REGISTERED":
        raise ValueError("event #1 is not schedule registration")
    if freeze.get("type") != "CONFIG_FROZEN_PRESTART":
        raise ValueError("event #2 is not config freeze")
    if schedule.get("head") != expected_head or freeze.get("head") != expected_head:
        raise ValueError("pre-start head mismatch")
    if parse_utc(schedule["start_utc"]) != start_utc:
        raise ValueError("registered start mismatch")
    if parse_utc(freeze["start_utc"]) != start_utc:
        raise ValueError("freeze start mismatch")

    manifest = freeze.get("manifest")
    if not isinstance(manifest, dict):
        raise ValueError("signed manifest missing")
    if digest(canonical(manifest)) != freeze.get("manifest_sha256"):
        raise ValueError("signed manifest hash mismatch")
    if schedule.get("source_commit_sha") != manifest.get("source_commit_sha"):
        raise ValueError("schedule/freeze source mismatch")

    for event in first:
        verify_event_workflow_against_manifest(
            repo_root, event, workflow_path, manifest
        )
    return manifest, verify


def load_verified_journal(
    *,
    repo_root: Path,
    events_dir: Path,
    checkpoint_path: Path,
    checkpoint_bundle_path: Path,
    workflow_path: str,
    head: str,
    horizon,
    start_utc: datetime,
    current_branch_tip: str,
):
    """Load a journal without O(N) Cosign verification on every action."""
    manifest, verify = _bootstrap_manifest(
        repo_root=repo_root,
        events_dir=events_dir,
        workflow_path=workflow_path,
        expected_head=head,
        start_utc=start_utc,
    )
    manifest_sha = digest(canonical(manifest))

    if checkpoint_path.exists() and checkpoint_bundle_path.exists():
        state = verify_checkpoint(
            repo_root=repo_root,
            events_dir=events_dir,
            checkpoint_path=checkpoint_path,
            checkpoint_bundle_path=checkpoint_bundle_path,
            manifest=manifest,
            manifest_sha256=manifest_sha,
            workflow_path=workflow_path,
            current_branch_tip=current_branch_tip,
            verify_blob=verify,
            expected_head=head,
        )
        checkpoint_used = True
    else:
        state = initial_state()
        checkpoint_used = False

    _, state = verify_suffix(
        events_dir=events_dir,
        state=state,
        head=head,
        horizon=horizon,
        manifest=manifest,
        workflow_path=workflow_path,
        repo_root=repo_root,
        verify_event_signature=verify,
    )

    return {
        "events": load_all_event_json(events_dir),
        "manifest": manifest,
        "manifest_sha256": manifest_sha,
        "state": state,
        "checkpoint_used": checkpoint_used,
        "verified_suffix_events": state.sequence if not checkpoint_used else None,
    }
