"""Signed checkpoint writer used by the actual R7.1 successor worker."""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from predictive_vnext4r7.integrity import canonical, digest
from predictive_vnext4r71.checkpoint import (
    build_state,
    checkpoint_document,
    event_files,
    git_prefix_binding,
    prefix_file_digest,
)

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
    events_count: int,
    checkpoint_path: Path,
    *,
    interval_events: int = 24,
) -> bool:
    if interval_events <= 0:
        raise ValueError("checkpoint interval must be positive")
    if events_count < interval_events:
        return False
    prior = 0
    if checkpoint_path.exists():
        prior = int(
            json.loads(checkpoint_path.read_bytes()).get(
                "verified_through_sequence", 0
            )
        )
    return events_count - prior >= interval_events


def create_signed_checkpoint(
    *,
    repo_root: Path,
    events_dir: Path,
    checkpoint_path: Path,
    checkpoint_bundle_path: Path,
    events: list[dict],
    head: str,
    manifest: dict,
    workflow_commit: str,
    sign_blob,
    require_bundle_time,
):
    """Create a checkpoint only for a prefix already present in HEAD."""
    if not events:
        raise ValueError("cannot checkpoint empty journal")
    files = event_files(events_dir)
    if len(files) != len(events):
        raise ValueError("event list/files mismatch")

    verified_branch_commit = _git(repo_root, "rev-parse", "HEAD")
    state = build_state(events)
    binding = git_prefix_binding(
        repo_root,
        events_dir,
        verified_branch_commit,
        state.sequence,
    )

    local_prefix = prefix_file_digest(files, state.sequence)
    if binding["verified_commit_prefix_files_sha256"] != local_prefix:
        raise ValueError("verified git commit prefix differs from local prefix")

    previous_checkpoint_sequence=0
    previous_checkpoint_sha256=None
    if checkpoint_path.exists():
        previous_raw=checkpoint_path.read_bytes()
        previous_doc=json.loads(previous_raw)
        previous_checkpoint_sequence=int(
            previous_doc.get("verified_through_sequence",0)
        )
        previous_checkpoint_sha256=digest(previous_raw)
        if previous_checkpoint_sequence>=state.sequence:
            raise ValueError("new checkpoint does not advance predecessor")

    doc = checkpoint_document(
        head=head,
        state=state,
        source_commit_sha=str(manifest["source_commit_sha"]),
        manifest_sha256=digest(canonical(manifest)),
        workflow_commit=workflow_commit,
        verified_branch_commit=verified_branch_commit,
        prefix_files_sha256=local_prefix,
        verified_commit_prefix_files_sha256=binding["verified_commit_prefix_files_sha256"],
        git_prefix_path_count=binding["path_count"],
        previous_checkpoint_sequence=previous_checkpoint_sequence,
        previous_checkpoint_sha256=previous_checkpoint_sha256,
        created_at_utc=datetime.now(UTC).isoformat(),
    )
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint_path.write_bytes(canonical(doc))
    checkpoint_bundle_path.unlink(missing_ok=True)

    sign_blob(checkpoint_path, checkpoint_bundle_path)
    require_bundle_time(checkpoint_bundle_path)
    return doc


def commit_and_push_checkpoint(
    *,
    repo_root: Path,
    branch: str,
    checkpoint_path: Path,
    checkpoint_bundle_path: Path,
    head: str,
) -> str:
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
        f"BTC predictive vNext4R7.1 {head} signed checkpoint",
    )
    _git(repo_root, "fetch", "origin", branch)
    remote_before = _git(
        repo_root, "rev-parse", "origin/" + branch
    )
    parent = _git(repo_root, "rev-parse", "HEAD^")
    if parent != remote_before:
        raise RuntimeError("checkpoint writer lost single-writer tip")
    _git(repo_root, "push", "origin", "HEAD:" + branch)
    local = _git(repo_root, "rev-parse", "HEAD")
    remote = _git(
        repo_root, "ls-remote", "origin", "refs/heads/" + branch
    ).split()[0]
    if local != remote:
        raise RuntimeError("checkpoint remote publication unconfirmed")
    return local
