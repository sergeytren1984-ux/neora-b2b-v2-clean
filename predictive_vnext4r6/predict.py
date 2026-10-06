"""Prediction helpers for the frozen BTC Predictive vNext4R6 research candidate."""
from __future__ import annotations

import hashlib
from pathlib import Path

import joblib
import numpy as np

CLASSES = ("LOWER_FIRST", "UPPER_FIRST", "NEITHER", "AMBIGUOUS_SAME_BAR")
COMPONENTS = ("logistic", "gbdt", "competing_risks")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def full_proba(model, X):
    p = np.zeros((len(X), 4), dtype=float)
    p[:, model.classes_.astype(int)] = model.predict_proba(X)
    return p


def calibrated(calibrator, raw):
    x = np.log(np.clip(raw, 1e-8, 1.0))
    return full_proba(calibrator, x)


def load_artifact(path, expected_sha256=None):
    path = Path(path)
    if expected_sha256 is not None and digest(path) != expected_sha256:
        raise ValueError("R6 artifact SHA256 mismatch")
    artifact = joblib.load(path)
    if artifact.get("schema") != "btc-predictive-vnext4r6-frozen-head-v1":
        raise ValueError("unexpected R6 artifact schema")
    if artifact.get("selected_model") != "ensemble_equal":
        raise ValueError("R6 selected-model drift")
    if artifact.get("components") != list(COMPONENTS):
        raise ValueError("R6 component-set drift")
    if artifact.get("classes") != list(CLASSES):
        raise ValueError("R6 class contract drift")
    if artifact.get("trading_authority") is not False:
        raise ValueError("unexpected R6 trading authority")
    return artifact


def component_distribution(artifact, name, X):
    spec = artifact["models"][name]
    if name in ("logistic", "gbdt"):
        raw = full_proba(spec["model"], X)
    elif name == "competing_risks":
        horizon = int(spec["horizon_steps"])
        step = int(spec["hazard_step"])
        raw = np.zeros((len(X), 4), dtype=float)
        survive = np.ones(len(X), dtype=float)
        for elapsed in range(step, horizon + 1, step):
            h = full_proba(
                spec["model"],
                np.column_stack(
                    (X, np.full(len(X), elapsed / horizon))
                ),
            )
            raw[:, 0] += survive * h[:, 0]
            raw[:, 1] += survive * h[:, 1]
            raw[:, 3] += survive * h[:, 3]
            survive *= h[:, 2]
        raw[:, 2] = survive
        raw /= np.maximum(raw.sum(axis=1, keepdims=True), 1e-12)
    else:
        raise ValueError("unknown R6 component")
    return calibrated(spec["calibrator"], raw)


def predict_selected(artifact, x):
    X = np.asarray(x, dtype=float).reshape(1, -1)
    if X.shape[1] != len(artifact["feature_names"]):
        raise ValueError("R6 feature-count mismatch")
    parts = {
        name: component_distribution(artifact, name, X)[0]
        for name in COMPONENTS
    }
    p = sum(parts[name] for name in COMPONENTS) / 3.0
    if not np.all(np.isfinite(p)) or abs(float(p.sum()) - 1.0) > 1e-8:
        raise ValueError("invalid R6 ensemble probability distribution")
    return {
        "selected_model": "ensemble_equal",
        "class_distribution": {
            "lower_first": float(p[0]),
            "upper_first": float(p[1]),
            "neither": float(p[2]),
            "ambiguous_same_bar": float(p[3]),
        },
        "components": {
            name: {
                "lower_first": float(parts[name][0]),
                "upper_first": float(parts[name][1]),
                "neither": float(parts[name][2]),
                "ambiguous_same_bar": float(parts[name][3]),
            }
            for name in COMPONENTS
        },
    }
