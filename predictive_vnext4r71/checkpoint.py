"""R7.1 signed checkpoint format with exact git commit -> prefix binding."""
from __future__ import annotations

import hashlib
import json
import subprocess
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


def _prefix_paths(events_dir: Path, through_sequence: int) -> list[str]:
    root = events_dir.parent.resolve()
    out = []
    for i in range(1, through_sequence + 1):
        e = events_dir / f"{i:08d}.json"
        b = e.with_suffix(".sigstore.json")
        out.extend(
            [
                str(e.resolve().relative_to(root)),
                str(b.resolve().relative_to(root)),
            ]
        )
    return out


def git_prefix_binding(
    repo_root: Path,
    events_dir: Path,
    commit: str,
    through_sequence: int,
) -> dict:
    """Bind exact event+bundle bytes through N to one concrete git commit."""
    rel_events = str(events_dir.resolve().relative_to(repo_root.resolve()))
    output = _git(
        repo_root,
        "ls-tree",
        "-r",
        commit,
        "--",
        rel_events,
    )
    tree = {}
    for line in output.splitlines():
        if not line.strip():
            continue
        meta, path = line.split("\t", 1)
        parts = meta.split()
        if len(parts) != 3 or parts[1] != "blob":
            continue
        tree[path] = parts[2]

    rows = []
    for i in range(1, through_sequence + 1):
        for suffix in (".json", ".sigstore.json"):
            rel = f"{rel_events}/{i:08d}{suffix}"
            oid = tree.get(rel)
            if oid is None:
                raise ValueError(
                    f"verified_branch_commit lacks prefix path: {rel}"
                )
            local = repo_root / rel
            if not local.exists():
                raise ValueError(f"local prefix path missing: {rel}")
            local_oid = _git(
                repo_root, "hash-object", str(local), text=True
            ).strip()
            if local_oid != oid:
                raise ValueError(
                    f"local prefix bytes differ from verified commit: {rel}"
                )
            rows.append({"path": rel, "blob_oid": oid})

    payload = canonical(rows)
    return {
        "path_count": len(rows),
        "git_prefix_digest_sha256": digest(payload),
        "rows": rows,
    }


def build_state(events: list[dict]) -> ChainState:
    state = ChainState(
        sequence=0,
        last_event_hash=None,
        prefix_root_sha256=EMPTY_ROOT,
        seen_idempotency_keys=set(),
        seen_type_slot=set(),
    )
    for event in events:
        raw = canonical(event)
        event_hash = digest(raw)
        state.sequence += 1
        state.last_event_hash = event_hash
        state.prefix_root_sha256 = root_step(
            state.prefix_root_sha256, event_hash
        )
        state.seen_idempotency_keys.add(event["idempotency_key"])
        state.seen_type_slot.add(
            "|".join(
                [
                    str(event["type"]),
                    str(event["head"]),
                    str(event.get("slot", "")),
                ]
            )
        )
    return state


def checkpoint_document(
    *,
    head: str,
    state: ChainState,
    source_commit_sha: str,
    manifest_sha256: str,
    workflow_commit: str,
    verified_branch_commit: str,
    prefix_files_sha256: str,
    git_prefix_digest_sha256: str,
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
        "git_prefix_digest_sha256": git_prefix_digest_sha256,
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
    if binding["git_prefix_digest_sha256"] != doc.get(
        "git_prefix_digest_sha256"
    ):
        raise ValueError("checkpoint git-prefix digest mismatch")
    if binding["path_count"] != int(doc.get("git_prefix_path_count", -1)):
        raise ValueError("checkpoint git-prefix path count mismatch")

    return state
