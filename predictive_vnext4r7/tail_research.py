"""Research-only magnitude/tail head for the BTC Predictive R7 candidate.

This module is deliberately separate from the frozen R6 numerical core.  It asks a
different question: how deep can the adverse/favourable excursion become within the
horizon, measured in multiples of the already-frozen R6 volatility barrier.

No output from this file has trading authority or prospective-admission authority.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import mean_pinball_loss
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from predictive_vnext4.core import (
    read_klines,
    build_15m_features,
    build_hourly_features,
)

ROOT = Path(__file__).resolve().parents[1]
R6_RESEARCH = ROOT / "research_vnext4r6"
SEED = 20261007
QUANTILES = (0.50, 0.75, 0.90)
THRESHOLDS = (1.0, 1.5, 2.0)


def excursion_targets(ix, c, hi, lo, distance, horizon_steps):
    """Maximum down/up excursion in units of the frozen R6 barrier distance."""
    future_low = np.full(len(ix), np.inf)
    future_high = np.full(len(ix), -np.inf)
    for step in range(1, horizon_steps + 1):
        future_low = np.minimum(future_low, lo[ix + step])
        future_high = np.maximum(future_high, hi[ix + step])
    scale = np.maximum(np.asarray(distance, dtype=float), 1e-12)
    down = np.maximum(c[ix] - future_low, 0.0) / scale
    up = np.maximum(future_high - c[ix], 0.0) / scale
    if not np.all(np.isfinite(down)) or not np.all(np.isfinite(up)):
        raise ValueError("non-finite excursion target")
    return down, up


def split_masks(dates, due_delta):
    """Predeclared research split; 2026Q3 is diagnostic only, never a selector."""
    due = dates + due_delta
    train = due < np.datetime64("2025-07-01")
    calibration = (
        (dates >= np.datetime64("2025-07-01"))
        & (due < np.datetime64("2026-01-01"))
    )
    test = (
        (dates >= np.datetime64("2026-01-08"))
        & (due < np.datetime64("2026-07-01"))
    )
    diagnostic_q3 = (
        (dates >= np.datetime64("2026-07-08"))
        & (dates < np.datetime64("2026-09-24"))
    )
    return train, calibration, test, diagnostic_q3


def brier_binary(p, y):
    p = np.asarray(p, dtype=float)
    y = np.asarray(y, dtype=float)
    return float(np.mean((p - y) ** 2))


def _fit_quantile(X, y, train, q):
    model = HistGradientBoostingRegressor(
        loss="quantile",
        quantile=q,
        max_iter=100,
        max_leaf_nodes=15,
        min_samples_leaf=100,
        learning_rate=0.04,
        l2_regularization=12,
        random_state=SEED,
    )
    model.fit(X[train], y[train])
    return model


def _quantile_calibration(model, X, y, calibration, train_values, q):
    raw_cal = model.predict(X[calibration])
    model_shift = float(np.quantile(y[calibration] - raw_cal, q))
    baseline_value = float(np.quantile(train_values, q))
    baseline_shift = float(
        np.quantile(y[calibration] - baseline_value, q)
    )
    return model_shift, baseline_value + baseline_shift


def _quantile_metrics(
    model,
    X,
    y,
    mask,
    q,
    model_shift,
    calibrated_baseline_value,
):
    pred = np.maximum(model.predict(X[mask]) + model_shift, 0.0)
    baseline = np.full(len(pred), calibrated_baseline_value)
    actual = y[mask]
    return {
        "n": int(np.sum(mask)),
        "pinball": float(mean_pinball_loss(actual, pred, alpha=q)),
        "baseline_pinball": float(
            mean_pinball_loss(actual, baseline, alpha=q)
        ),
        "coverage": float(np.mean(actual <= pred)),
        "target_coverage": q,
        "mean_prediction_barrier_multiples": float(np.mean(pred)),
        "calibration_shift_barrier_multiples": float(model_shift),
        "calibrated_constant_baseline_barrier_multiples": float(
            calibrated_baseline_value
        ),
    }


def _logit(p):
    p = np.clip(np.asarray(p, dtype=float), 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p)).reshape(-1, 1)


def _fit_threshold_classifier(X, y, train, calibration):
    if len(np.unique(y[train])) < 2:
        raise ValueError("threshold target has one training class")
    model = make_pipeline(
        StandardScaler(),
        LogisticRegression(C=0.03, max_iter=450),
    )
    model.fit(X[train], y[train])

    calibrator = None
    if len(np.unique(y[calibration])) >= 2:
        calibrator = LogisticRegression(C=0.05, max_iter=300)
        calibrator.fit(
            _logit(model.predict_proba(X[calibration])[:, 1]),
            y[calibration],
        )
    train_frequency = float(np.mean(y[train]))
    cal_frequency = float(np.mean(y[calibration]))
    return model, calibrator, train_frequency, cal_frequency


def _threshold_probability(model, calibrator, X):
    raw = model.predict_proba(X)[:, 1]
    if calibrator is None:
        return raw
    return calibrator.predict_proba(_logit(raw))[:, 1]


def _threshold_metrics(
    model,
    calibrator,
    X,
    y,
    mask,
    calibrated_baseline_frequency,
):
    p = _threshold_probability(model, calibrator, X[mask])
    actual = y[mask].astype(float)
    baseline = np.full(len(p), float(calibrated_baseline_frequency))
    return {
        "n": int(np.sum(mask)),
        "event_rate": float(np.mean(actual)),
        "mean_probability": float(np.mean(p)),
        "brier": brier_binary(p, actual),
        "baseline_brier": brier_binary(baseline, actual),
        "calibrated_baseline_frequency": float(
            calibrated_baseline_frequency
        ),
    }


def evaluate_side(X, y, train, calibration, test, diagnostic_q3):
    result = {"quantiles": {}, "thresholds": {}}
    for q in QUANTILES:
        model = _fit_quantile(X, y, train, q)
        shift, baseline_value = _quantile_calibration(
            model, X, y, calibration, y[train], q
        )
        result["quantiles"][str(q)] = {
            "test_2026h1": _quantile_metrics(
                model, X, y, test, q, shift, baseline_value
            ),
            "diagnostic_2026q3": _quantile_metrics(
                model, X, y, diagnostic_q3, q, shift, baseline_value
            ),
        }

    for threshold in THRESHOLDS:
        label = y >= threshold
        model, calibrator, train_frequency, cal_frequency = (
            _fit_threshold_classifier(
                X, label, train, calibration
            )
        )
        result["thresholds"][str(threshold)] = {
            "test_2026h1": _threshold_metrics(
                model,
                calibrator,
                X,
                label,
                test,
                cal_frequency,
            ),
            "diagnostic_2026q3": _threshold_metrics(
                model,
                calibrator,
                X,
                label,
                diagnostic_q3,
                cal_frequency,
            ),
            "training_frequency": train_frequency,
            "calibration_frequency": cal_frequency,
            "probability_calibrated_on_2025h2": calibrator is not None,
        }
    return result


def load_head(head):
    if head in ("1h", "4h"):
        bars = 4 if head == "1h" else 16
        source = (
            R6_RESEARCH
            / "data"
            / "BTCUSDT_15m_2024-01_2026-09.json.gz"
        )
        t, o, hi, lo, c, v, trades, taker, source_sha = read_klines(
            source, 900000
        )
        ix, dates, X, names, regime, vol = build_15m_features(
            t, hi, lo, c, v, trades, taker, 16
        )
        distance = c[ix] * vol * np.sqrt(float(bars))
        down, up = excursion_targets(ix, c, hi, lo, distance, bars)
        due = np.timedelta64(bars * 15, "m")
    elif head == "24h":
        bars = 24
        source = ROOT / "btc_1h_2024_to_sep24_2026.json"
        t, o, hi, lo, c, v, trades, taker, source_sha = read_klines(
            source, 3600000
        )
        ix, dates, X, names, regime, vol, atr = build_hourly_features(
            t, hi, lo, c, v, trades, taker, 24
        )
        distance = c[ix] * vol * np.sqrt(24.0)
        down, up = excursion_targets(ix, c, hi, lo, distance, bars)
        due = np.timedelta64(24, "h")
    else:
        raise ValueError("unknown head")
    return {
        "head": head,
        "bars": bars,
        "source_sha256": source_sha,
        "dates": dates,
        "X": X,
        "feature_names": names,
        "down": down,
        "up": up,
        "due": due,
    }


def research_gate(side_result):
    """Predeclared feasibility gate; Q3 diagnostics are intentionally ignored."""
    threshold_wins = sum(
        row["test_2026h1"]["brier"]
        < row["test_2026h1"]["baseline_brier"]
        for row in side_result["thresholds"].values()
    )
    q90 = side_result["quantiles"]["0.9"]["test_2026h1"]
    q90_ok = (
        q90["pinball"] < q90["baseline_pinball"]
        and abs(q90["coverage"] - 0.90) <= 0.05
    )
    return {
        "threshold_brier_wins": int(threshold_wins),
        "threshold_gate": threshold_wins >= 2,
        "q90_pinball_and_coverage_gate": bool(q90_ok),
        "pass": bool(threshold_wins >= 2 and q90_ok),
    }


def run_head(head):
    data = load_head(head)
    train, cal, test, q3 = split_masks(data["dates"], data["due"])
    if min(
        int(np.sum(train)),
        int(np.sum(cal)),
        int(np.sum(test)),
        int(np.sum(q3)),
    ) <= 100:
        raise RuntimeError("insufficient tail-research split")

    down = evaluate_side(
        data["X"], data["down"], train, cal, test, q3
    )
    up = evaluate_side(
        data["X"], data["up"], train, cal, test, q3
    )
    return {
        "schema": "btc-predictive-vnext4r7-tail-research-v1",
        "status": "RESEARCH_ONLY_NO_TRADING_AUTHORITY",
        "head": head,
        "source_sha256": data["source_sha256"],
        "feature_names": data["feature_names"],
        "target": {
            "unit": "multiples_of_frozen_R6_volatility_barrier",
            "down": "(reference - future_min_low) / R6_barrier_distance",
            "up": "(future_max_high - reference) / R6_barrier_distance",
            "quantiles": list(QUANTILES),
            "exceedance_thresholds": list(THRESHOLDS),
        },
        "split": {
            "train_labels_due_before": "2025-07-01T00:00:00Z",
            "calibration": "2025-07-01..2026-01-01",
            "selection_test": "2026-01-08..2026-07-01",
            "diagnostic_only_q3": "2026-07-08..2026-09-24",
            "q3_used_for_gate": False,
            "n_train": int(np.sum(train)),
            "n_calibration": int(np.sum(cal)),
            "n_test": int(np.sum(test)),
            "n_q3_diagnostic": int(np.sum(q3)),
        },
        "downside": down,
        "upside": up,
        "gate": {
            "downside": research_gate(down),
            "upside": research_gate(up),
        },
        "prospective_admission": False,
        "trading_authority": False,
    }


def main():
    result = {
        "schema": "btc-predictive-vnext4r7-tail-research-suite-v1",
        "policy": {
            "selection_data": "2026H1 only",
            "q3_role": "diagnostic only",
            "minimum_threshold_brier_wins": 2,
            "q90_max_absolute_coverage_error": 0.05,
            "require_q90_pinball_better_than_constant": True,
            "production_integration": "FORBIDDEN_UNTIL_NEW_PROSPECTIVE_EPOCH",
        },
        "heads": {head: run_head(head) for head in ("1h", "4h", "24h")},
        "trading_authority": False,
    }
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
