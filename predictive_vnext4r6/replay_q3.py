"""Replay the frozen R6 candidate on the untouched 2026Q3 historical fold.

This is a parity test only. It must reproduce the research metrics already recorded
before the candidate freeze. It does not create new selection evidence.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from predictive_vnext4.core import (
    read_klines,
    build_15m_features,
    build_hourly_features,
    target_distance,
    masks,
    metrics,
)
from predictive_vnext4r6.predict import (
    load_artifact,
    component_distribution,
)

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / "predictive_vnext4r6"
RESEARCH = ROOT / "research_vnext4r6"
TOL = 1e-4
COMPONENT_TOL = 5e-4


def ensemble(artifact, X):
    parts = [
        component_distribution(artifact, name, X)
        for name in ("logistic", "gbdt", "competing_risks")
    ]
    p = sum(parts) / 3.0
    if not np.all(np.isfinite(p)):
        raise ValueError("non-finite replay probabilities")
    if not np.allclose(p.sum(axis=1), 1.0, atol=1e-10):
        raise ValueError("replay probabilities do not sum to one")
    return p


def q3_mask(dates, due):
    _, _, test = masks(
        dates,
        due,
        "2026-01-01",
        "2026-01-01",
        "2026-07-01",
        "2026-07-08",
        "2026-09-24",
    )
    return test


def replay_15m(head, bars):
    source = RESEARCH / "data" / "BTCUSDT_15m_2024-01_2026-09.json.gz"
    t, o, hi, lo, c, v, trades, taker, source_sha = read_klines(source, 900000)
    ix, dates, X, names, regime, vol = build_15m_features(
        t, hi, lo, c, v, trades, taker, 16
    )
    distance = c[ix] * vol * np.sqrt(float(bars))
    y, when = target_distance(ix, c, hi, lo, distance, bars)
    due = np.timedelta64(bars * 15, "m")
    test = q3_mask(dates, due)
    return source_sha, names, X[test], y[test], dates[test]


def replay_24h():
    source = ROOT / "btc_1h_2024_to_sep24_2026.json"
    t, o, hi, lo, c, v, trades, taker, source_sha = read_klines(source, 3600000)
    ix, dates, X, names, regime, vol, atr = build_hourly_features(
        t, hi, lo, c, v, trades, taker, 24
    )
    distance = c[ix] * vol * np.sqrt(24.0)
    y, when = target_distance(ix, c, hi, lo, distance, 24)
    due = np.timedelta64(24, "h")
    test = q3_mask(dates, due)
    return source_sha, names, X[test], y[test], dates[test]


def main():
    metadata = json.loads((HERE / "freeze_metadata.json").read_text())
    research = json.loads((RESEARCH / "structural_result.json").read_text())
    report = {
        "schema": "btc-predictive-vnext4r6-freeze-replay-v1",
        "status": "VALIDATION_ONLY",
        "trading_authority": False,
        "heads": {},
    }

    datasets = {
        "1h": replay_15m("1h", 4),
        "4h": replay_15m("4h", 16),
        "24h": replay_24h(),
    }

    for head in ("1h", "4h", "24h"):
        source_sha, names, X, y, dates = datasets[head]
        spec = metadata["artifacts"][head]
        artifact = load_artifact(ROOT / spec["path"], spec["sha256"])
        if source_sha != artifact["source_sha256"]:
            raise AssertionError(f"{head}: source SHA drift")
        if list(names) != artifact["feature_names"]:
            raise AssertionError(f"{head}: feature schema drift")

        component_probs = {
            name: component_distribution(artifact, name, X)
            for name in ("logistic", "gbdt", "competing_risks")
        }
        component_metrics = {
            name: metrics(p, y) for name, p in component_probs.items()
        }
        p = sum(component_probs.values()) / 3.0
        got = metrics(p, y)
        expected_models = research["heads"][head]["folds"]["2026Q3"]["models"]
        expected = expected_models["ensemble_equal"]

        if abs(got["brier"] - expected["brier"]) > TOL:
            raise AssertionError(
                f"{head}: Brier replay mismatch {got['brier']} != {expected['brier']}"
            )
        if abs(got["log_loss"] - expected["log_loss"]) > TOL:
            raise AssertionError(
                f"{head}: log-loss replay mismatch {got['log_loss']} != {expected['log_loss']}"
            )
        for name, cm in component_metrics.items():
            em = expected_models[name]
            if abs(cm["brier"] - em["brier"]) > COMPONENT_TOL:
                raise AssertionError(
                    f"{head}/{name}: component Brier replay mismatch "
                    f"{cm['brier']} != {em['brier']}"
                )
            if abs(cm["log_loss"] - em["log_loss"]) > COMPONENT_TOL:
                raise AssertionError(
                    f"{head}/{name}: component log-loss replay mismatch "
                    f"{cm['log_loss']} != {em['log_loss']}"
                )

        expected_n = int(
            research["heads"][head]["folds"]["2026Q3"]["meta"]["test_n"]
        )
        if len(y) != expected_n:
            raise AssertionError(f"{head}: Q3 sample-count mismatch")

        report["heads"][head] = {
            "n": int(len(y)),
            "brier": got["brier"],
            "expected_brier": expected["brier"],
            "log_loss": got["log_loss"],
            "expected_log_loss": expected["log_loss"],
            "brier_abs_error": abs(got["brier"] - expected["brier"]),
            "log_loss_abs_error": abs(got["log_loss"] - expected["log_loss"]),
            "source_sha256": source_sha,
            "components": {
                name: {
                    "brier": component_metrics[name]["brier"],
                    "expected_brier": expected_models[name]["brier"],
                    "brier_abs_error": abs(
                        component_metrics[name]["brier"] - expected_models[name]["brier"]
                    ),
                    "log_loss": component_metrics[name]["log_loss"],
                    "expected_log_loss": expected_models[name]["log_loss"],
                    "log_loss_abs_error": abs(
                        component_metrics[name]["log_loss"] - expected_models[name]["log_loss"]
                    ),
                }
                for name in ("logistic", "gbdt", "competing_risks")
            },
            "parity": True,
        }

    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
