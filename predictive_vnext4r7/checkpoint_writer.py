"""Signed checkpoint writer for the R7 successor journal.

A checkpoint is created only after an already-published event prefix is verified.
It is stored outside the event sequence and therefore cannot masquerade as a
forecast/outcome. The checkpoint binds the verified sequence, event hash,
prefix-root, exact prefix-file digest, immutable source and the branch commit that
contained the verified prefix.
"""
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from predictive_vnext4r7.checkpoint import (
    checkpoint_document,
    event_files,
    prefix_file_digest,
)
from predictive_vnext4r7.integrity import canonical, digest
from predictive_vnext4r7.journal_runtime import bundle_time

UTC = timezone.utc


def _git(repo_root: Path, *args) -> str:
    return subprocess.run(
        ["git", "-C", str(repo_root), *args],
        check=True,
        capture_output=True,
        text=True,
        timeout=180,
    ).stdout.strip()


def should_checkpoint(
    state,
    checkpoint_path: Path,
    *,
    interval_events: int = 24,
) -> bool:
    if state.sequence < 2:
        return False
    if interval_events <= 0:
        raise ValueError("checkpoint interval must be positive")
    prior = 0
    if checkpoint_path.exists():
        doc = json.loads(checkpoint_path.read_bytes())
        prior = int(doc.get("verified_through_sequence", 0))
    return state.sequence - prior >= interval_events


def create_signed_checkpoint(
    *,
    repo_root: Path,
    events_dir: Path,
    checkpoint_path: Path,
    checkpoint_bundle_path: Path,
    head: str,
    state,
    manifest: dict,
    workflow_commit: str,
):
    source = str(manifest.get("source_commit_sha", ""))
    if len(source) != 40:
        raise ValueError("manifest source commit invalid")
    verified_branch_commit = _git(repo_root, "rev-parse", "HEAD")
    files = event_files(events_dir)
    if len(files) < state.sequence:
        raise ValueError("journal shorter than verified state")

    doc = checkpoint_document(
        head=head,
        state=state,
        source_commit_sha=source,
        manifest_sha256=digest(canonical(manifest)),
        workflow_commit=workflow_commit,
        verified_branch_commit=verified_branch_commit,
        prefix_files_sha256=prefix_file_digest(files, state.sequence),
        created_at_utc=datetime.now(UTC).isoformat(),
    )
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint_path.write_bytes(canonical(doc))
    checkpoint_bundle_path.unlink(missing_ok=True)

    subprocess.run(
        [
            "cosign",
            "sign-blob",
            "--yes",
            "--bundle",
            str(checkpoint_bundle_path),
            str(checkpoint_path),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=180,
        cwd=repo_root,
    )
    # Require a real Rekor inclusion proof immediately.
    bundle_time(checkpoint_bundle_path)
    return doc


def commit_and_push_checkpoint(
    *,
    repo_root: Path,
    branch: str,
    checkpoint_path: Path,
    checkpoint_bundle_path: Path,
    head: str,
):
    for path in (checkpoint_path, checkpoint_bundle_path):
        rel = str(path.resolve().relative_to(repo_root.resolve()))
        _git(repo_root, "add", rel)
    if subprocess.run(
        ["git", "-C", str(repo_root), "diff", "--cached", "--quiet"],
        timeout=60,
    ).returncode == 0:
        return _git(repo_root, "rev-parse", "HEAD")

    _git(
        repo_root,
        "commit",
        "-m",
        f"BTC predictive vNext4R7 {head} verified checkpoint",
    )
    _git(repo_root, "fetch", "origin", branch)
    _git(repo_root, "rebase", "origin/" + branch)
    _git(repo_root, "push", "origin", "HEAD:" + branch)
    local = _git(repo_root, "rev-parse", "HEAD")
    remote = _git(
        repo_root, "ls-remote", "origin", "refs/heads/" + branch
    ).split()[0]
    if local != remote:
        raise RuntimeError("checkpoint remote publication unconfirmed")
    return local
