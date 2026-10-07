"""R7.1 signed checkpoint format with exact git commit -> prefix binding."""
from __future__ import annotations

import hashlib
import io
import json
import subprocess
import tarfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from predictive_vnext4r7.integrity import canonical, digest
from predictive_vnext4r71.integrity import validate_event_collection

EMPTY_ROOT = "0" * 64


@dataclass
class ChainState:
    sequence: int
    last_event_hash: str | None
    prefix_root_sha256: str
    seen_idempotency_keys: set[str]
    seen_type_slot: set[str]


def event_files(events_dir: Path) -> list[Path]:
    return sorted(
        p for p in events_dir.glob("*.json")
        if len(p.stem) == 8 and p.stem.isdigit()
    )


def bundle_for_event(path: Path) -> Path:
    return path.with_suffix(".sigstore.json")


def root_step(root_hex: str, event_hash_hex: str) -> str:
    return digest(bytes.fromhex(root_hex) + bytes.fromhex(event_hash_hex))


def prefix_file_digest(files: list[Path], through_sequence: int) -> str:
    h = hashlib.sha256()
    for i, path in enumerate(files[:through_sequence], 1):
        if path.name != f"{i:08d}.json":
            raise ValueError("event filename sequence gap")
        for item in (path, bundle_for_event(path)):
            if not item.exists():
                raise ValueError("prefix event/bundle missing")
            raw = item.read_bytes()
            h.update(str(item.name).encode())
            h.update(len(raw).to_bytes(8, "big"))
            h.update(raw)
    return h.hexdigest()


def _git(repo_root: Path, *args, text=True):
    return subprocess.run(
        ["git", "-C", str(repo_root), *args],
        check=True,
        capture_output=True,
        text=text,
        timeout=180,
    ).stdout


def git_prefix_binding(
    repo_root: Path,
    events_dir: Path,
    commit: str,
    through_sequence: int,
) -> dict:
    """Recompute exact prefix bytes from one git archive subprocess.

    This proves that verified_branch_commit itself contains the exact event and
    Sigstore bundle bytes claimed by the signed checkpoint, without spawning a
    git process for every historical file.
    """
    rel_events = str(events_dir.resolve().relative_to(repo_root.resolve()))
    archive = subprocess.run(
        [
            "git", "-C", str(repo_root), "archive", "--format=tar",
            commit, "--", rel_events,
        ],
        check=True,
        capture_output=True,
        timeout=180,
    ).stdout
    members = {}
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as tf:
        for member in tf.getmembers():
            if member.isfile():
                fh = tf.extractfile(member)
                if fh is not None:
                    members[member.name] = fh.read()

    h = hashlib.sha256()
    count = 0
    for i in range(1, through_sequence + 1):
        for suffix in (".json", ".sigstore.json"):
            rel = f"{rel_events}/{i:08d}{suffix}"
            raw = members.get(rel)
            if raw is None:
                raise ValueError(
                    f"verified_branch_commit lacks prefix path: {rel}"
                )
            name = Path(rel).name
            h.update(name.encode())
            h.update(len(raw).to_bytes(8, "big"))
            h.update(raw)
            count += 1
    return {
        "path_count": count,
        "verified_commit_prefix_files_sha256": h.hexdigest(),
    }


def checkpoint_document(
    *,
    head: str,
    state: ChainState,
    source_commit_sha: str,
    manifest_sha256: str,
    workflow_commit: str,
    verified_branch_commit: str,
    prefix_files_sha256: str,
    verified_commit_prefix_files_sha256: str,
    git_prefix_path_count: int,
    created_at_utc: str,
) -> dict:
    return {
        "schema": "btc-predictive-vnext4r71-checkpoint-v1",
        "head": head,
        "verified_through_sequence": state.sequence,
        "verified_through_event_hash": state.last_event_hash,
        "prefix_root_sha256": state.prefix_root_sha256,
        "prefix_files_sha256": prefix_files_sha256,
        "verified_commit_prefix_files_sha256": verified_commit_prefix_files_sha256,
        "git_prefix_path_count": int(git_prefix_path_count),
        "seen_idempotency_keys": sorted(state.seen_idempotency_keys),
        "seen_type_slot": sorted(state.seen_type_slot),
        "source_commit_sha": source_commit_sha,
        "manifest_sha256": manifest_sha256,
        "workflow_commit": workflow_commit,
        "verified_branch_commit": verified_branch_commit,
        "created_at_utc": created_at_utc,
        "trading_authority": False,
    }


def state_from_checkpoint(doc: dict) -> ChainState:
    if doc.get("schema") != "btc-predictive-vnext4r71-checkpoint-v1":
        raise ValueError("unexpected checkpoint schema")
    if doc.get("trading_authority") is not False:
        raise ValueError("checkpoint trading authority drift")
    return ChainState(
        sequence=int(doc["verified_through_sequence"]),
        last_event_hash=doc.get("verified_through_event_hash"),
        prefix_root_sha256=doc["prefix_root_sha256"],
        seen_idempotency_keys=set(doc["seen_idempotency_keys"]),
        seen_type_slot=set(doc["seen_type_slot"]),
    )


def verify_checkpoint(
    *,
    repo_root: Path,
    events_dir: Path,
    checkpoint_path: Path,
    checkpoint_bundle_path: Path,
    manifest: dict,
    manifest_sha256: str,
    workflow_path: str,
    current_branch_tip: str,
    verify_blob: Callable[[Path, Path, dict], object],
    verify_workflow_binding: Callable[[Path, dict, str, dict], object],
    expected_head: str,
) -> ChainState:
    raw = checkpoint_path.read_bytes()
    doc = json.loads(raw)
    if raw != canonical(doc):
        raise ValueError("checkpoint is not canonical")
    if doc.get("head") != expected_head:
        raise ValueError("checkpoint head mismatch")
    if doc.get("manifest_sha256") != manifest_sha256:
        raise ValueError("checkpoint manifest mismatch")
    if doc.get("source_commit_sha") != manifest.get("source_commit_sha"):
        raise ValueError("checkpoint source mismatch")

    verify_blob(checkpoint_path, checkpoint_bundle_path, doc)
    verify_workflow_binding(
        repo_root, doc, workflow_path, manifest
    )

    verified_commit = str(doc["verified_branch_commit"])
    subprocess.run(
        [
            "git", "-C", str(repo_root),
            "merge-base", "--is-ancestor",
            verified_commit, current_branch_tip,
        ],
        check=True,
        capture_output=True,
        timeout=120,
    )

    files = event_files(events_dir)
    state = state_from_checkpoint(doc)
    if state.sequence <= 0 or state.sequence > len(files):
        raise ValueError("checkpoint sequence outside journal")
    if digest(files[state.sequence - 1].read_bytes()) != state.last_event_hash:
        raise ValueError("checkpoint last event hash mismatch")
    if prefix_file_digest(files, state.sequence) != doc["prefix_files_sha256"]:
        raise ValueError("checkpoint prefix files/bundles changed")

    binding = git_prefix_binding(
        repo_root, events_dir, verified_commit, state.sequence
    )
    if binding["verified_commit_prefix_files_sha256"] != doc.get(
        "verified_commit_prefix_files_sha256"
    ):
        raise ValueError("checkpoint verified-commit prefix bytes mismatch")
    if binding["verified_commit_prefix_files_sha256"] != doc.get(
        "prefix_files_sha256"
    ):
        raise ValueError("checkpoint local/verified-commit prefix mismatch")
    if binding["path_count"] != int(doc.get("git_prefix_path_count", -1)):
        raise ValueError("checkpoint git-prefix path count mismatch")

    return state
