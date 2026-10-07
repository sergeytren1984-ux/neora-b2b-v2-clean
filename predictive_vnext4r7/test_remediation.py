"""Regression tests for the five R7 remediation changes."""
from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from predictive_vnext4r7.checkpoint import (
    advance_state,
    checkpoint_document,
    initial_state,
    prefix_file_digest,
    verify_checkpoint,
)
from predictive_vnext4r7.episodes import independent_volatility_episodes
from predictive_vnext4r7.integrity import (
    canonical,
    digest,
    validate_event_collection,
    verify_event_workflow_against_manifest,
)

UTC = timezone.utc


def event(seq, previous_hash, *, head="1h", et="FORECAST_ISSUED", slot="20261007T000000Z"):
    anchor = datetime.strptime(slot, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    out = {
        "schema": "btc-predictive-test-event-v1",
        "sequence": seq,
        "previous_hash": previous_hash,
        "workflow_commit": "0" * 40,
        "published_at_utc": (anchor + timedelta(minutes=1)).isoformat(),
        "type": et,
        "idempotency_key": f"forecast:{slot}",
        "head": head,
        "slot": slot,
        "anchor_utc": anchor.isoformat(),
        "due_utc": (anchor + timedelta(hours=1)).isoformat(),
    }
    if et == "OUTCOME_RECORDED":
        out["idempotency_key"] = f"outcome:{slot}"
    return out


class IntegrityTests(unittest.TestCase):
    def test_duplicate_type_head_slot_rejected_even_with_different_key(self):
        a = event(1, None)
        b = event(2, digest(canonical(a)))
        b["idempotency_key"] = "different-but-signed-key"
        with self.assertRaises(ValueError):
            validate_event_collection(
                [a, b], head="1h", horizon=timedelta(hours=1)
            )

    def test_slot_anchor_due_invariant(self):
        a = event(1, None)
        a["anchor_utc"] = "2026-10-07T00:15:00+00:00"
        with self.assertRaises(ValueError):
            validate_event_collection(
                [a], head="1h", horizon=timedelta(hours=1)
            )

    def test_workflow_content_bound_to_manifest(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "test"], cwd=root, check=True)
            path = root / ".github/workflows/test.yml"
            path.parent.mkdir(parents=True)
            path.write_text("name: frozen\non: workflow_dispatch\n")
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(["git", "commit", "-m", "frozen"], cwd=root, check=True, capture_output=True)
            frozen_sha = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=root, check=True,
                capture_output=True, text=True
            ).stdout.strip()
            frozen_hash = digest(path.read_bytes())
            manifest = {"paths_sha256": {".github/workflows/test.yml": frozen_hash}}
            e = {"workflow_commit": frozen_sha}
            self.assertEqual(
                verify_event_workflow_against_manifest(
                    root, e, ".github/workflows/test.yml", manifest
                ),
                frozen_hash,
            )

            path.write_text("name: changed\non: workflow_dispatch\n")
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(["git", "commit", "-m", "changed"], cwd=root, check=True, capture_output=True)
            changed_sha = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=root, check=True,
                capture_output=True, text=True
            ).stdout.strip()
            with self.assertRaises(ValueError):
                verify_event_workflow_against_manifest(
                    root,
                    {"workflow_commit": changed_sha},
                    ".github/workflows/test.yml",
                    manifest,
                )


class CheckpointTests(unittest.TestCase):
    def test_checkpoint_state_and_prefix_digest(self):
        with tempfile.TemporaryDirectory() as td:
            directory = Path(td)
            state = initial_state()
            prev = None
            for i, slot in enumerate(
                ["20261007T000000Z", "20261007T010000Z"], 1
            ):
                e = event(i, prev, slot=slot)
                raw = canonical(e)
                (directory / f"{i:08d}.json").write_bytes(raw)
                advance_state(
                    state, e, raw, head="1h", horizon=timedelta(hours=1)
                )
                prev = digest(raw)
            files = sorted(directory.glob("*.json"))
            prefix = prefix_file_digest(files, 2)
            doc = checkpoint_document(
                head="1h",
                state=state,
                source_commit_sha="1" * 40,
                manifest_sha256="2" * 64,
                workflow_commit="3" * 40,
                verified_branch_commit="4" * 40,
                prefix_files_sha256=prefix,
                created_at_utc="2026-10-07T02:00:00+00:00",
            )
            self.assertEqual(doc["verified_through_sequence"], 2)
            self.assertEqual(doc["prefix_files_sha256"], prefix)
            self.assertEqual(len(doc["seen_idempotency_keys"]), 2)

    def test_checkpoint_detects_prefix_rewrite(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "test"], cwd=root, check=True)

            workflow = root / ".github/workflows/test.yml"
            workflow.parent.mkdir(parents=True)
            workflow.write_text("name: frozen\non: workflow_dispatch\n")
            events_dir = root / "events"
            events_dir.mkdir()

            state = initial_state()
            prev = None
            for i, slot in enumerate(
                ["20261007T000000Z", "20261007T010000Z"], 1
            ):
                e = event(i, prev, slot=slot)
                raw = canonical(e)
                (events_dir / f"{i:08d}.json").write_bytes(raw)
                advance_state(
                    state, e, raw, head="1h", horizon=timedelta(hours=1)
                )
                prev = digest(raw)

            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(["git", "commit", "-m", "verified prefix"], cwd=root, check=True, capture_output=True)
            verified_commit = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=root, check=True,
                capture_output=True, text=True
            ).stdout.strip()
            manifest = {
                "source_commit_sha": verified_commit,
                "paths_sha256": {
                    ".github/workflows/test.yml": digest(workflow.read_bytes())
                },
            }
            prefix = prefix_file_digest(sorted(events_dir.glob("*.json")), 2)
            doc = checkpoint_document(
                head="1h",
                state=state,
                source_commit_sha=verified_commit,
                manifest_sha256=digest(canonical(manifest)),
                workflow_commit=verified_commit,
                verified_branch_commit=verified_commit,
                prefix_files_sha256=prefix,
                created_at_utc="2026-10-07T02:00:00+00:00",
            )
            checkpoint = root / "checkpoint.json"
            bundle = root / "checkpoint.sigstore.json"
            checkpoint.write_bytes(canonical(doc))
            bundle.write_text("{}")

            verified = verify_checkpoint(
                repo_root=root,
                events_dir=events_dir,
                checkpoint_path=checkpoint,
                checkpoint_bundle_path=bundle,
                manifest=manifest,
                manifest_sha256=digest(canonical(manifest)),
                workflow_path=".github/workflows/test.yml",
                current_branch_tip=verified_commit,
                verify_blob=lambda *args: None,
                expected_head="1h",
            )
            self.assertEqual(verified.sequence, 2)

            first = json.loads((events_dir / "00000001.json").read_text())
            first["published_at_utc"] = "2026-10-07T00:02:00+00:00"
            (events_dir / "00000001.json").write_bytes(canonical(first))
            with self.assertRaises(ValueError):
                verify_checkpoint(
                    repo_root=root,
                    events_dir=events_dir,
                    checkpoint_path=checkpoint,
                    checkpoint_bundle_path=bundle,
                    manifest=manifest,
                    manifest_sha256=digest(canonical(manifest)),
                    workflow_path=".github/workflows/test.yml",
                    current_branch_tip=verified_commit,
                    verify_blob=lambda *args: None,
                    expected_head="1h",
                )


class EpisodeTests(unittest.TestCase):
    def test_bin_flicker_does_not_create_many_independent_episodes(self):
        start = datetime(2026, 10, 7, tzinfo=UTC)
        anchors = [start + timedelta(hours=i) for i in range(12)]
        bins = [0, 1] * 6
        episodes = independent_volatility_episodes(
            anchors,
            bins,
            window_hours=1,
            minimum_duration_hours=3,
            minimum_separation_hours=6,
        )
        self.assertEqual(episodes, [])

    def test_persistent_separated_runs_count(self):
        start = datetime(2026, 10, 7, tzinfo=UTC)
        anchors = [start + timedelta(hours=i) for i in range(12)]
        bins = [0, 0, 0, 1, 1, 1, 1, 1, 1, 2, 2, 2]
        episodes = independent_volatility_episodes(
            anchors,
            bins,
            window_hours=1,
            minimum_duration_hours=3,
            minimum_separation_hours=3,
        )
        self.assertEqual(len(episodes), 3)
        self.assertEqual([e.volatility_bin for e in episodes], [0, 1, 2])


if __name__ == "__main__":
    unittest.main()
