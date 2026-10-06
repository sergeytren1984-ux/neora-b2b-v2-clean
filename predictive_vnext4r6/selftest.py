"""Self-tests for the frozen BTC Predictive vNext4R6 research candidate."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

from predictive_vnext4r6.predict import load_artifact, predict_selected

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / "predictive_vnext4r6"
RESEARCH = ROOT / "research_vnext4r6"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    metadata = json.loads((HERE / "freeze_metadata.json").read_text())
    assert metadata["schema"] == "btc-predictive-vnext4r6-freeze-metadata-v1"
    assert metadata["status"] == "FROZEN_RESEARCH_CANDIDATE"
    assert metadata["predictive_accept"] is False
    assert metadata["prospective_admission"] is False
    assert metadata["trading_authority"] is False
    assert metadata["optional_blocks_in_executable_candidate"] == []

    assert sha(RESEARCH / "research_gate_result.json") == metadata["research_gate_sha256"]
    assert sha(RESEARCH / "acceptance_policy.json") == metadata["acceptance_policy_sha256"]

    for head in ("1h", "4h", "24h"):
        spec = metadata["artifacts"][head]
        path = ROOT / spec["path"]
        assert sha(path) == spec["sha256"]
        artifact = load_artifact(path, spec["sha256"])
        assert artifact["head"] == head
        assert artifact["selected_model"] == "ensemble_equal"
        assert artifact["training_contract"]["historical_validation_reused_for_fit"] is False
        assert artifact["source_sha256"] == spec["source_sha256"]
        assert spec["train_n"] == artifact["training_contract"]["train_n"]
        assert spec["cal_n"] == artifact["training_contract"]["cal_n"]

        x = np.zeros(len(artifact["feature_names"]), dtype=float)
        pred = predict_selected(artifact, x)
        p = pred["class_distribution"]
        values = np.asarray([
            p["lower_first"],
            p["upper_first"],
            p["neither"],
            p["ambiguous_same_bar"],
        ])
        assert np.all(np.isfinite(values))
        assert np.all(values >= 0.0)
        assert abs(float(values.sum()) - 1.0) < 1e-8

    print("R6 frozen research candidate selftest: PASS")


if __name__ == "__main__":
    main()
