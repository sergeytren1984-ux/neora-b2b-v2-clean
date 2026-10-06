"""Freeze the BTC Predictive vNext4R6 research candidate.

This script does not launch prospective production and grants no trading authority.
It freezes exactly the core architecture selected by the immutable R6 research gate.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import joblib
import numpy as np
import sklearn
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from predictive_vnext4.core import (
    read_klines,
    build_15m_features,
    build_hourly_features,
    target_distance,
    masks,
    full_proba,
    _fit_hazard,
)

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / "predictive_vnext4r6"
RESEARCH = ROOT / "research_vnext4r6"
HERE.mkdir(exist_ok=True)

SEED = 20261004
PARENT_R5_SHA = "16c4fd69e6c4e6f58310ecbd597daa80af270f83"
CLASSES = ["LOWER_FIRST", "UPPER_FIRST", "NEITHER", "AMBIGUOUS_SAME_BAR"]
COMPONENTS = ["logistic", "gbdt", "competing_risks"]
SELECTED = "ensemble_equal"


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha_file(path: Path) -> str:
    return sha_bytes(path.read_bytes())


def load_json(path: Path):
    return json.loads(path.read_text())


def fit_calibrator(raw, y):
    model = LogisticRegression(C=.05, max_iter=400)
    model.fit(np.log(np.clip(raw, 1e-8, 1.0)), y)
    return model


def calibrated(calibrator, raw):
    x = np.log(np.clip(raw, 1e-8, 1.0))
    return full_proba(calibrator, x)


def fit_components(X, y, when, train, cal, horizon_steps, hazard_step):
    yy = y[train]
    models = {}

    logistic = make_pipeline(
        StandardScaler(),
        LogisticRegression(C=.03, max_iter=450),
    )
    logistic.fit(X[train], yy)
    lraw = full_proba(logistic, X[cal])
    lcal = fit_calibrator(lraw, y[cal])
    models["logistic"] = {"model": logistic, "calibrator": lcal}

    gbdt = HistGradientBoostingClassifier(
        max_iter=110,
        max_leaf_nodes=15,
        min_samples_leaf=80,
        learning_rate=.04,
        l2_regularization=12,
        random_state=SEED,
    )
    gbdt.fit(X[train], yy)
    graw = full_proba(gbdt, X[cal])
    gcal = fit_calibrator(graw, y[cal])
    models["gbdt"] = {"model": gbdt, "calibrator": gcal}

    hazard = _fit_hazard(X, y, when, train, horizon_steps, hazard_step)

    # Recreate the exact cumulative competing-risks distribution used by the
    # structural benchmark before fitting the multiclass calibrator.
    survive = np.ones(int(np.sum(cal)), dtype=float)
    hraw = np.zeros((int(np.sum(cal)), 4), dtype=float)
    Xcal = X[cal]
    for elapsed in range(hazard_step, horizon_steps + 1, hazard_step):
        h = full_proba(
            hazard,
            np.column_stack(
                (Xcal, np.full(len(Xcal), elapsed / horizon_steps))
            ),
        )
        hraw[:, 0] += survive * h[:, 0]
        hraw[:, 1] += survive * h[:, 1]
        hraw[:, 3] += survive * h[:, 3]
        survive *= h[:, 2]
    hraw[:, 2] = survive
    hraw /= np.maximum(hraw.sum(axis=1, keepdims=True), 1e-12)
    hcal = fit_calibrator(hraw, y[cal])
    models["competing_risks"] = {
        "model": hazard,
        "calibrator": hcal,
        "horizon_steps": int(horizon_steps),
        "hazard_step": int(hazard_step),
    }

    return models


def fixed_masks(dates, due):
    train, cal, _ = masks(
        dates,
        due,
        "2026-01-01",
        "2026-01-01",
        "2026-07-01",
        "2026-07-08",
        "2026-09-24",
    )
    if int(np.sum(train)) < 500 or int(np.sum(cal)) < 100:
        raise RuntimeError("insufficient fixed R6 train/calibration rows")
    return train, cal


def artifact_common(head, X, feature_names, source_sha, y, when, train, cal,
                    models, target, horizon_steps, hazard_step):
    return {
        "schema": "btc-predictive-vnext4r6-frozen-head-v1",
        "status": "FROZEN_RESEARCH_CANDIDATE",
        "parent_r5_source_sha": PARENT_R5_SHA,
        "head": head,
        "selected_model": SELECTED,
        "components": COMPONENTS,
        "component_weights": {
            "logistic": 1.0 / 3.0,
            "gbdt": 1.0 / 3.0,
            "competing_risks": 1.0 / 3.0,
        },
        "models": models,
        "classes": CLASSES,
        "feature_names": list(feature_names),
        "target": target,
        "training_contract": {
            "model_fit_labels_due_before_utc": "2026-01-01T00:00:00Z",
            "calibration_anchor_start_utc": "2026-01-01T00:00:00Z",
            "calibration_labels_due_before_utc": "2026-07-01T00:00:00Z",
            "historical_validation_start_utc": "2026-07-08T00:00:00Z",
            "historical_validation_end_utc": "2026-09-24T00:00:00Z",
            "historical_validation_reused_for_fit": False,
            "train_n": int(np.sum(train)),
            "cal_n": int(np.sum(cal)),
            "class_count_train": np.bincount(y[train], minlength=4).astype(int).tolist(),
            "class_count_calibration": np.bincount(y[cal], minlength=4).astype(int).tolist(),
        },
        "source_sha256": source_sha,
        "horizon_steps": int(horizon_steps),
        "hazard_step": int(hazard_step),
        "numpy_version": np.__version__,
        "sklearn_version": sklearn.__version__,
        "trading_authority": False,
        "prospective_admission": False,
    }


def build_15m_head(head, bars):
    path = RESEARCH / "data" / "BTCUSDT_15m_2024-01_2026-09.json.gz"
    t, o, hi, lo, c, v, trades, taker, source_sha = read_klines(path, 900000)
    ix, dates, X, names, regime, vol = build_15m_features(
        t, hi, lo, c, v, trades, taker, 16
    )
    distance = c[ix] * vol * np.sqrt(float(bars))
    y, when = target_distance(ix, c, hi, lo, distance, bars)
    due = np.timedelta64(bars * 15, "m")
    train, cal = fixed_masks(dates, due)
    models = fit_components(X, y, when, train, cal, bars, 1)
    ratio = distance / c[ix]
    target = {
        "type": "realized_vol_scaled_first_passage",
        "source_interval": "15m",
        "vol_window": "4h",
        "distance_formula": (
            f"reference * std(15m_log_returns,4h) * sqrt({bars})"
        ),
        "distance_ratio_quantiles_full_history": [
            float(x) for x in np.quantile(ratio, [.01, .1, .5, .9, .99])
        ],
        "horizon_minutes": int(bars * 15),
        "classes": CLASSES,
        "same_bar_rule": "AMBIGUOUS_SAME_BAR",
    }
    return artifact_common(
        head, X, names, source_sha, y, when, train, cal, models, target, bars, 1
    )


def build_24h_head():
    path = ROOT / "btc_1h_2024_to_sep24_2026.json"
    t, o, hi, lo, c, v, trades, taker, source_sha = read_klines(path, 3600000)
    ix, dates, X, names, regime, vol, atr = build_hourly_features(
        t, hi, lo, c, v, trades, taker, 24
    )
    bars = 24
    distance = c[ix] * vol * np.sqrt(24.0)
    y, when = target_distance(ix, c, hi, lo, distance, bars)
    due = np.timedelta64(24, "h")
    train, cal = fixed_masks(dates, due)
    models = fit_components(X, y, when, train, cal, bars, 3)
    ratio = distance / c[ix]
    target = {
        "type": "realized_vol_scaled_first_passage",
        "source_interval": "1h",
        "vol_window": "24h",
        "distance_formula": "reference * std(1h_log_returns,24h) * sqrt(24)",
        "distance_ratio_quantiles_full_history": [
            float(x) for x in np.quantile(ratio, [.01, .1, .5, .9, .99])
        ],
        "horizon_hours": 24,
        "classes": CLASSES,
        "same_bar_rule": "AMBIGUOUS_SAME_BAR",
    }
    return artifact_common(
        "24h", X, names, source_sha, y, when, train, cal, models, target, 24, 3
    )


def validate_gate():
    gate_path = RESEARCH / "research_gate_result.json"
    policy_path = RESEARCH / "acceptance_policy.json"
    gate = load_json(gate_path)
    if gate.get("status") != "READY_FOR_FREEZE_RESEARCH_CANDIDATE":
        raise RuntimeError("R6 research gate does not authorize candidate freeze")
    if gate.get("trading_authority") is not False:
        raise RuntimeError("unexpected trading authority in research gate")
    for head in ("1h", "4h", "24h"):
        if gate["core"][head].get("selected") != SELECTED:
            raise RuntimeError(f"research-selected model drift for {head}")
        if gate["core"][head].get("target_ok") is not True:
            raise RuntimeError(f"target gate failed for {head}")
    return gate_path, policy_path, gate


def dump_artifact(name, artifact):
    path = HERE / name
    joblib.dump(artifact, path, compress=3)
    return path


def main():
    gate_path, policy_path, gate = validate_gate()

    heads = {
        "1h": build_15m_head("1h", 4),
        "4h": build_15m_head("4h", 16),
        "24h": build_24h_head(),
    }

    paths = {
        "1h": dump_artifact("head_1h.joblib", heads["1h"]),
        "4h": dump_artifact("head_4h.joblib", heads["4h"]),
        "24h": dump_artifact("head_24h.joblib", heads["24h"]),
    }

    metadata = {
        "schema": "btc-predictive-vnext4r6-freeze-metadata-v1",
        "status": "FROZEN_RESEARCH_CANDIDATE",
        "parent_r5_source_sha": PARENT_R5_SHA,
        "research_gate_status": gate["status"],
        "research_gate_sha256": sha_file(gate_path),
        "acceptance_policy_sha256": sha_file(policy_path),
        "selected_core": {
            head: gate["core"][head]["selected"] for head in ("1h", "4h", "24h")
        },
        "artifacts": {
            head: {
                "path": str(path.relative_to(ROOT)),
                "sha256": sha_file(path),
                "source_sha256": heads[head]["source_sha256"],
                "train_n": heads[head]["training_contract"]["train_n"],
                "cal_n": heads[head]["training_contract"]["cal_n"],
            }
            for head, path in paths.items()
        },
        "optional_blocks_in_executable_candidate": [],
        "optional_blocks_excluded": {
            "macro_daily_market": "paired research gate failed",
            "funding_oi": "paired research gate failed",
            "breakout_memory": (
                "1h GBDT-only ablation passed, but incremental value versus the "
                "selected equal-weight ensemble has not been established"
            ),
            "regime_selector": (
                "diagnostic only; not the selected core architecture under the "
                "frozen acceptance gate"
            ),
        },
        "historical_validation_reused_for_component_fit": False,
        "research_iteration_note": (
            "equal-weight ensemble was introduced during historical research; "
            "historical metrics remain tuning evidence and require prospective validation"
        ),
        "predictive_accept": False,
        "prospective_admission": False,
        "trading_authority": False,
    }

    out = HERE / "freeze_metadata.json"
    out.write_text(json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
