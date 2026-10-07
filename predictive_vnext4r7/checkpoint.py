"""Incremental signed-checkpoint verification for the R7 successor candidate.

The expensive operation in R6 was re-running Cosign over the complete journal for
nearly every action. R7 keeps exact hash-chain semantics but allows the critical
path to trust a previously signed checkpoint, re-hash the prefix cheaply, and
perform Cosign/Rekor verification only for the suffix created after that checkpoint.

A separate full verifier remains required periodically and before any admission.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from predictive_vnext4r7.integrity import (
    canonical,
    digest,
    event_uniqueness_key,
    expected_idempotency_key,
    validate_event_semantics,
    verify_event_workflow_against_manifest,
)

EMPTY_ROOT = "0" * 64


@dataclass
class ChainState:
    sequence: int
    last_event_hash: str | None
    prefix_root_sha256: str
    seen_idempotency_keys: set[str]
    seen_uniqueness_keys: set[str]


def root_step(root_hex: str, event_hash_hex: str) -> str:
    if len(root_hex) != 64 or len(event_hash_hex) != 64:
        raise ValueError("invalid root/event hash")
    return digest(bytes.fromhex(root_hex) + bytes.fromhex(event_hash_hex))


def unique_token(event: dict) -> str | None:
    key = event_uniqueness_key(event)
    if key is None:
        return None
    return "|".join("" if x is None else str(x) for x in key)


def event_files(events_dir: Path) -> list[Path]:
    return sorted(
        p
        for p in events_dir.glob("*.json")
        if len(p.stem) == 8 and p.stem.isdigit()
    )


def prefix_file_digest(files: list[Path], through_sequence: int) -> str:
    """Cheap exact digest of all canonical event bytes in the trusted prefix."""
    h = __import__("hashlib").sha256()
    for i, path in enumerate(files[:through_sequence], 1):
        if path.name != f"{i:08d}.json":
            raise ValueError("event filename sequence gap")
        raw = path.read_bytes()
        h.update(i.to_bytes(8, "big"))
        h.update(len(raw).to_bytes(8, "big"))
        h.update(raw)
    return h.hexdigest()


def initial_state() -> ChainState:
    return ChainState(
        sequence=0,
        last_event_hash=None,
        prefix_root_sha256=EMPTY_ROOT,
        seen_idempotency_keys=set(),
        seen_uniqueness_keys=set(),
    )


def advance_state(
    state: ChainState,
    event: dict,
    raw: bytes,
    *,
    head: str,
    horizon,
) -> None:
    expected_sequence = state.sequence + 1
    if int(event.get("sequence", -1)) != expected_sequence:
        raise ValueError("event sequence gap")
    if raw != canonical(event):
        raise ValueError("event is not canonical JSON")
    if event.get("previous_hash") != state.last_event_hash:
        raise ValueError("event previous_hash mismatch")

    validate_event_semantics(event, head=head, horizon=horizon)

    key = event.get("idempotency_key")
    if not isinstance(key, str):
        raise ValueError("missing idempotency key")
    expected = expected_idempotency_key(event)
    if expected is not None and key != expected:
        raise ValueError("non-canonical idempotency key")
    if key in state.seen_idempotency_keys:
        raise ValueError("duplicate idempotency key")

    token = unique_token(event)
    if token is not None and token in state.seen_uniqueness_keys:
        raise ValueError("duplicate (type,head,slot)")

    event_hash = digest(raw)
    state.sequence = expected_sequence
    state.last_event_hash = event_hash
    state.prefix_root_sha256 = root_step(
        state.prefix_root_sha256, event_hash
    )
    state.seen_idempotency_keys.add(key)
    if token is not None:
        state.seen_uniqueness_keys.add(token)


def checkpoint_document(
    *,
    head: str,
    state: ChainState,
    source_commit_sha: str,
    manifest_sha256: str,
    workflow_commit: str,
    verified_branch_commit: str,
    prefix_files_sha256: str,
    created_at_utc: str,
) -> dict:
    return {
        "schema": "btc-predictive-vnext4r7-checkpoint-v1",
        "head": head,
        "verified_through_sequence": state.sequence,
        "verified_through_event_hash": state.last_event_hash,
        "prefix_root_sha256": state.prefix_root_sha256,
        "prefix_files_sha256": prefix_files_sha256,
        "seen_idempotency_keys": sorted(state.seen_idempotency_keys),
        "seen_uniqueness_keys": sorted(state.seen_uniqueness_keys),
        "source_commit_sha": source_commit_sha,
        "manifest_sha256": manifest_sha256,
        "workflow_commit": workflow_commit,
        "verified_branch_commit": verified_branch_commit,
        "created_at_utc": created_at_utc,
        "trading_authority": False,
    }


def state_from_checkpoint(doc: dict) -> ChainState:
    if doc.get("schema") != "btc-predictive-vnext4r7-checkpoint-v1":
        raise ValueError("unexpected checkpoint schema")
    if doc.get("trading_authority") is not False:
        raise ValueError("checkpoint trading authority drift")
    seq = int(doc.get("verified_through_sequence", -1))
    if seq < 0:
        raise ValueError("invalid checkpoint sequence")
    return ChainState(
        sequence=seq,
        last_event_hash=doc.get("verified_through_event_hash"),
        prefix_root_sha256=doc.get("prefix_root_sha256"),
        seen_idempotency_keys=set(doc.get("seen_idempotency_keys", [])),
        seen_uniqueness_keys=set(doc.get("seen_uniqueness_keys", [])),
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
    expected_head: str,
) -> ChainState:
    doc = json.loads(checkpoint_path.read_bytes())
    raw = checkpoint_path.read_bytes()
    if raw != canonical(doc):
        raise ValueError("checkpoint is not canonical")
    if doc.get("head") != expected_head:
        raise ValueError("checkpoint head mismatch")
    if doc.get("manifest_sha256") != manifest_sha256:
        raise ValueError("checkpoint manifest mismatch")
    if doc.get("source_commit_sha") != manifest.get("source_commit_sha"):
        raise ValueError("checkpoint source commit mismatch")

    verify_blob(checkpoint_path, checkpoint_bundle_path, doc)
    verify_event_workflow_against_manifest(
        repo_root,
        doc,
        workflow_path,
        manifest,
    )

    verified_commit = str(doc.get("verified_branch_commit", ""))
    subprocess.run(
        [
            "git",
            "-C",
            str(repo_root),
            "merge-base",
            "--is-ancestor",
            verified_commit,
            current_branch_tip,
        ],
        check=True,
        capture_output=True,
        timeout=120,
    )

    files = event_files(events_dir)
    state = state_from_checkpoint(doc)
    if state.sequence > len(files):
        raise ValueError("checkpoint extends past event journal")
    if state.sequence:
        raw_last = files[state.sequence - 1].read_bytes()
        if digest(raw_last) != state.last_event_hash:
            raise ValueError("checkpoint last-event hash mismatch")
    if prefix_file_digest(files, state.sequence) != doc.get(
        "prefix_files_sha256"
    ):
        raise ValueError("checkpoint prefix files were rewritten")

    return state


def verify_suffix(
    *,
    events_dir: Path,
    state: ChainState,
    head: str,
    horizon,
    manifest: dict,
    workflow_path: str,
    repo_root: Path,
    verify_event_signature: Callable[[Path, Path, dict], object],
) -> tuple[list[dict], ChainState]:
    files = event_files(events_dir)
    if len(files) < state.sequence:
        raise ValueError("event journal truncated below checkpoint")

    new_events = []
    for i in range(state.sequence + 1, len(files) + 1):
        path = files[i - 1]
        if path.name != f"{i:08d}.json":
            raise ValueError("event filename sequence gap")
        raw = path.read_bytes()
        event = json.loads(raw)

        verify_event_signature(
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
        new_events.append(event)
    return new_events, state


def load_all_event_json(events_dir: Path) -> list[dict]:
    """Parsing is cheap; signatures are not re-run for the checkpointed prefix."""
    return [json.loads(path.read_bytes()) for path in event_files(events_dir)]
