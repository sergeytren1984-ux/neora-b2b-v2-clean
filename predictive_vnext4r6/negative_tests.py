"""Negative tests for the frozen R6 candidate contract."""
from __future__ import annotations

import copy
import hashlib
import json
import tempfile
from pathlib import Path

import joblib

from predictive_vnext4r6.predict import load_artifact

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / "predictive_vnext4r6"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def must_fail(fn, label):
    try:
        fn()
    except Exception:
        return
    raise AssertionError(f"negative test unexpectedly accepted: {label}")


def main():
    metadata = json.loads((HERE / "freeze_metadata.json").read_text())
    original_path = ROOT / metadata["artifacts"]["1h"]["path"]
    expected_sha = metadata["artifacts"]["1h"]["sha256"]
    artifact = load_artifact(original_path, expected_sha)

    # 1) Byte tampering must fail the pinned file digest before deserialization.
    raw = bytearray(original_path.read_bytes())
    raw[len(raw) // 2] ^= 0x01
    with tempfile.TemporaryDirectory() as td:
        tampered = Path(td) / "tampered.joblib"
        tampered.write_bytes(raw)
        must_fail(
            lambda: load_artifact(tampered, expected_sha),
            "tampered artifact bytes",
        )

    # 2) Model-selection drift must be rejected even when a new file hash is supplied.
    drift = copy.deepcopy(artifact)
    drift["selected_model"] = "gbdt"
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "selection_drift.joblib"
        joblib.dump(drift, path, compress=3)
        must_fail(
            lambda: load_artifact(path, sha(path)),
            "selected-model drift",
        )

    # 3) Trading authority cannot be silently enabled inside the artifact.
    authority = copy.deepcopy(artifact)
    authority["trading_authority"] = True
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "authority_drift.joblib"
        joblib.dump(authority, path, compress=3)
        must_fail(
            lambda: load_artifact(path, sha(path)),
            "trading-authority drift",
        )

    # 4) Component deletion/reordering is a contract failure.
    components = copy.deepcopy(artifact)
    components["components"] = ["gbdt", "logistic"]
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "component_drift.joblib"
        joblib.dump(components, path, compress=3)
        must_fail(
            lambda: load_artifact(path, sha(path)),
            "component-set drift",
        )

    print("R6 frozen research candidate negative tests: PASS")


if __name__ == "__main__":
    main()
