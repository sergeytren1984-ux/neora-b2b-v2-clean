"""R7.1 research-only tail/magnitude model with coherent monotone outputs.

Q3 is explicitly a previously seen diagnostic block, not an untouched holdout.
No output from this module has admission or trading authority.
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
    future_low = np.full(len(ix), np.inf)
    future_high = np.full(len(ix), -np.inf)
    for step in range(1, horizon_steps + 1):
        future_low = np.minimum(future_low, lo[ix + step])
        future_high = np.maximum(future_high, hi[ix + step])
    scale = np.maximum(np.asarray(distance, dtype=float), 1e-12)
    down = np.maximum(c[ix] - future_low, 0.0) / scale
    up = np.maximum(future_high - c[ix], 0.0) / scale
    return down, up


def split_masks(dates, due_delta):
    due = dates + due_delta
    train = due < np.datetime64("2025-07-01")
    calibration = (
        (dates >= np.datetime64("2025-07-01"))
        & (due < np.datetime64("2026-01-01"))
    )
    selection = (
        (dates >= np.datetime64("2026-01-08"))
        & (due < np.datetime64("2026-07-01"))
    )
    q3_seen = (
        (dates >= np.datetime64("2026-07-08"))
        & (dates < np.datetime64("2026-09-24"))
    )
    return train, calibration, selection, q3_seen


def _fit_quantile(X, y, train, q):
    m = HistGradientBoostingRegressor(
        loss="quantile",
        quantile=q,
        max_iter=100,
        max_leaf_nodes=15,
        min_samples_leaf=100,
        learning_rate=0.04,
        l2_regularization=12,
        random_state=SEED,
    )
    m.fit(X[train], y[train])
    return m


def _logit(p):
    p = np.clip(np.asarray(p, dtype=float), 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p)).reshape(-1, 1)


def _fit_threshold(X, label, train, calibration):
    m = make_pipeline(
        StandardScaler(),
        LogisticRegression(C=0.03, max_iter=450),
    )
    m.fit(X[train], label[train])
    calibrator = None
    if len(np.unique(label[calibration])) >= 2:
        calibrator = LogisticRegression(C=0.05, max_iter=300)
        raw = m.predict_proba(X[calibration])[:, 1]
        calibrator.fit(_logit(raw), label[calibration])
    return m, calibrator


def _threshold_prob(model, calibrator, X):
    raw = model.predict_proba(X)[:, 1]
    if calibrator is None:
        return raw
    return calibrator.predict_proba(_logit(raw))[:, 1]


def monotone_quantiles(matrix):
    """q50 <= q75 <= q90, deterministic no-crossing projection."""
    x = np.maximum(np.asarray(matrix, dtype=float), 0.0)
    return np.maximum.accumulate(x, axis=1)


def monotone_exceedance(matrix):
    """P(X>=1x) >= P(X>=1.5x) >= P(X>=2x)."""
    x = np.clip(np.asarray(matrix, dtype=float), 0.0, 1.0)
    return np.minimum.accumulate(x, axis=1)


def quantile_crossings(matrix):
    x = np.asarray(matrix, dtype=float)
    return int(np.sum(np.any(np.diff(x, axis=1) < -1e-12, axis=1)))


def threshold_order_violations(matrix):
    x = np.asarray(matrix, dtype=float)
    return int(np.sum(np.any(np.diff(x, axis=1) > 1e-12, axis=1)))


def _brier(p, y):
    return float(np.mean((np.asarray(p) - np.asarray(y)) ** 2))


def evaluate_side(X, y, train, calibration, selection, q3_seen):
    q_models = {}
    q_shifts = {}
    q_baselines = {}
    for q in QUANTILES:
        model = _fit_quantile(X, y, train, q)
        raw_cal = model.predict(X[calibration])
        shift = float(np.quantile(y[calibration] - raw_cal, q))
        base_train = float(np.quantile(y[train], q))
        base_shift = float(np.quantile(y[calibration] - base_train, q))
        q_models[q] = model
        q_shifts[q] = shift
        q_baselines[q] = base_train + base_shift

    t_models = {}
    t_cal = {}
    t_baselines = {}
    t_train_freq = {}
    for threshold in THRESHOLDS:
        label = y >= threshold
        model, calibrator = _fit_threshold(
            X, label, train, calibration
        )
        t_models[threshold] = model
        t_cal[threshold] = calibrator
        t_train_freq[threshold] = float(np.mean(label[train]))
        t_baselines[threshold] = float(np.mean(label[calibration]))

    result = {
        "quantiles": {},
        "thresholds": {},
        "coherence": {},
    }

    for split_name, mask in (
        ("selection_2026h1", selection),
        ("seen_diagnostic_2026q3", q3_seen),
    ):
        raw_q = np.column_stack(
            [
                np.maximum(
                    q_models[q].predict(X[mask]) + q_shifts[q], 0.0
                )
                for q in QUANTILES
            ]
        )
        proj_q = monotone_quantiles(raw_q)
        base_q = monotone_quantiles(
            np.tile(
                np.asarray([q_baselines[q] for q in QUANTILES]),
                (int(np.sum(mask)), 1),
            )
        )

        raw_t = np.column_stack(
            [
                _threshold_prob(
                    t_models[t], t_cal[t], X[mask]
                )
                for t in THRESHOLDS
            ]
        )
        proj_t = monotone_exceedance(raw_t)
        base_t = monotone_exceedance(
            np.tile(
                np.asarray([t_baselines[t] for t in THRESHOLDS]),
                (int(np.sum(mask)), 1),
            )
        )

        result["coherence"][split_name] = {
            "raw_quantile_crossing_rows": quantile_crossings(raw_q),
            "projected_quantile_crossing_rows": quantile_crossings(proj_q),
            "raw_threshold_order_violation_rows": threshold_order_violations(raw_t),
            "projected_threshold_order_violation_rows": threshold_order_violations(proj_t),
        }

        for j, q in enumerate(QUANTILES):
            row = result["quantiles"].setdefault(str(q), {})
            actual = y[mask]
            row[split_name] = {
                "n": int(np.sum(mask)),
                "pinball": float(
                    mean_pinball_loss(actual, proj_q[:, j], alpha=q)
                ),
                "baseline_pinball": float(
                    mean_pinball_loss(actual, base_q[:, j], alpha=q)
                ),
                "coverage": float(np.mean(actual <= proj_q[:, j])),
                "target_coverage": q,
                "mean_prediction_barrier_multiples": float(
                    np.mean(proj_q[:, j])
                ),
            }

        for j, threshold in enumerate(THRESHOLDS):
            row = result["thresholds"].setdefault(str(threshold), {})
            actual = (y[mask] >= threshold).astype(float)
            row[split_name] = {
                "n": int(np.sum(mask)),
                "event_rate": float(np.mean(actual)),
                "mean_probability": float(np.mean(proj_t[:, j])),
                "brier": _brier(proj_t[:, j], actual),
                "baseline_brier": _brier(base_t[:, j], actual),
            }
            row["training_frequency"] = t_train_freq[threshold]
            row["calibration_frequency"] = t_baselines[threshold]

    return result


def load_head(head):
    if head in ("1h", "4h"):
        bars = 4 if head == "1h" else 16
        source = (
            R6_RESEARCH / "data"
            / "BTCUSDT_15m_2024-01_2026-09.json.gz"
        )
        t, o, hi, lo, c, v, trades, taker, source_sha = read_klines(
            source, 900000
        )
        ix, dates, X, names, regime, vol = build_15m_features(
            t, hi, lo, c, v, trades, taker, 16
        )
        distance = c[ix] * vol * np.sqrt(float(bars))
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
        due = np.timedelta64(24, "h")
    else:
        raise ValueError("unknown head")
    down, up = excursion_targets(ix, c, hi, lo, distance, bars)
    return dates, X, names, down, up, due, source_sha


def research_gate(side):
    wins = sum(
        side["thresholds"][str(t)]["selection_2026h1"]["brier"]
        < side["thresholds"][str(t)]["selection_2026h1"]["baseline_brier"]
        for t in THRESHOLDS
    )
    q90 = side["quantiles"]["0.9"]["selection_2026h1"]
    q90_ok = (
        q90["pinball"] < q90["baseline_pinball"]
        and abs(q90["coverage"] - 0.90) <= 0.05
    )
    coherent = (
        side["coherence"]["selection_2026h1"]["projected_quantile_crossing_rows"] == 0
        and side["coherence"]["selection_2026h1"]["projected_threshold_order_violation_rows"] == 0
        and side["coherence"]["seen_diagnostic_2026q3"]["projected_quantile_crossing_rows"] == 0
        and side["coherence"]["seen_diagnostic_2026q3"]["projected_threshold_order_violation_rows"] == 0
    )
    return {
        "threshold_brier_wins": int(wins),
        "q90_pinball_and_coverage_gate": bool(q90_ok),
        "coherence_gate": bool(coherent),
        "pass": bool(wins >= 2 and q90_ok and coherent),
    }


def run_head(head):
    dates, X, names, down, up, due, source_sha = load_head(head)
    train, cal, selection, q3 = split_masks(dates, due)
    downside = evaluate_side(X, down, train, cal, selection, q3)
    upside = evaluate_side(X, up, train, cal, selection, q3)
    return {
        "schema": "btc-predictive-vnext4r71-tail-research-v1",
        "status": "RESEARCH_ONLY_NO_ADMISSION_NO_TRADING_AUTHORITY",
        "head": head,
        "source_sha256": source_sha,
        "feature_names": names,
        "split": {
            "train_labels_due_before": "2025-07-01T00:00:00Z",
            "calibration": "2025H2",
            "selection": "2026H1",
            "q3": "SEEN_DIAGNOSTIC_NOT_HOLDOUT",
            "q3_used_for_gate": False,
            "n_train": int(np.sum(train)),
            "n_calibration": int(np.sum(cal)),
            "n_selection": int(np.sum(selection)),
            "n_q3_seen_diagnostic": int(np.sum(q3)),
        },
        "target": {
            "unit": "multiples_of_frozen_R6_volatility_barrier",
            "quantiles": list(QUANTILES),
            "exceedance_thresholds": list(THRESHOLDS),
            "quantile_projection": "cumulative_max",
            "threshold_probability_projection": "cumulative_min",
        },
        "downside": downside,
        "upside": upside,
        "gate": {
            "downside": research_gate(downside),
            "upside": research_gate(upside),
        },
        "prospective_admission": False,
        "trading_authority": False,
    }


def main():
    result = {
        "schema": "btc-predictive-vnext4r71-tail-research-suite-v1",
        "policy": {
            "selection_data": "2026H1 only",
            "q3_role": "SEEN_DIAGNOSTIC_NOT_HOLDOUT",
            "production_integration": "FORBIDDEN",
            "next_valid_evaluation": "NEW_PROSPECTIVE_EPOCH_ONLY",
        },
        "heads": {h: run_head(h) for h in ("1h", "4h", "24h")},
        "trading_authority": False,
    }
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
