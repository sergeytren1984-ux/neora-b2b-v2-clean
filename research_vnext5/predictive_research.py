"""vNext5 predictive research: direct 3-state direction + target-zone first passage.

Research only.  No production integration, admission, or trading authority.
The engineering substrate is inherited unchanged from audited R7.6; this module
changes only targets/models/evaluation used to decide whether a new numerical
epoch is worth freezing.

Primary user-facing task:
  * P(DOWN), P(RANGE), P(UP) for 1h / 4h / 24h.
Secondary task:
  * P(lower zone first), P(no zone), P(upper zone first) for arbitrary
    asymmetric barriers expressed in pre-anchor volatility units.

All features are computed from candles closed at or before the anchor.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from predictive_vnext4.core import (
    read_klines,
    build_15m_features,
    build_hourly_features,
    first_touch_variable,
)

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "research_vnext5"
OUT.mkdir(exist_ok=True)
SEED = 20261008

DIRECTION_CLASSES = ("DOWN", "RANGE", "UP")
RAW_ZONE_CLASSES = ("LOWER_FIRST", "UPPER_FIRST", "NEITHER", "AMBIGUOUS_SAME_BAR")

# Frozen before this research run.  A 0.50-sigma terminal corridor is not
# selected from the evaluation folds; it is the declared user-facing target.
DIRECTION_CORRIDOR_SIGMA = 0.50

# Frozen barrier grid for learning a generic asymmetric target-zone surface.
ZONE_SIGMA_PAIRS = (
    (0.25, 2.50),
    (0.50, 0.50),
    (0.50, 2.00),
    (0.75, 1.50),
    (1.00, 1.00),
    (1.00, 3.00),
    (1.50, 0.75),
    (1.50, 1.50),
    (2.00, 0.50),
    (2.00, 2.00),
    (2.50, 0.25),
    (3.00, 1.00),
    (3.00, 3.00),
)

FOLD_SPECS = (
    ("2025Q3", "2025-04-01", "2025-04-01", "2025-07-01", "2025-07-08", "2025-10-01"),
    ("2025Q4", "2025-07-01", "2025-07-01", "2025-10-01", "2025-10-08", "2026-01-01"),
    ("2026H1", "2025-10-01", "2025-10-01", "2026-01-01", "2026-01-08", "2026-07-01"),
    ("2026Q3", "2026-01-01", "2026-01-01", "2026-07-01", "2026-07-08", "2026-09-24"),
)


def fold_masks(dates, due_delta, spec):
    _, train_end, cal_start, cal_end, test_start, test_end = spec
    dates = np.asarray(dates)
    due = dates + due_delta
    tr = due < np.datetime64(train_end)
    ca = (dates >= np.datetime64(cal_start)) & (due < np.datetime64(cal_end))
    te = (dates >= np.datetime64(test_start)) & (dates < np.datetime64(test_end))
    return tr, ca, te


def memory_features(o, hi, lo, c, ix, lookback, scan):
    rows = []
    for i in ix:
        fu = fd = su = sd = 0
        start = max(lookback, i - scan + 1)
        for j in range(start, i + 1):
            ph = float(np.max(hi[j - lookback:j]))
            pl = float(np.min(lo[j - lookback:j]))
            if hi[j] > ph:
                if c[j] <= ph:
                    fu += 1
                else:
                    su += 1
            if lo[j] < pl:
                if c[j] >= pl:
                    fd += 1
                else:
                    sd += 1
        wstart = max(0, i - scan + 1)
        hh = hi[wstart:i + 1]
        ll = lo[wstart:i + 1]
        ih = int(np.argmax(hh))
        il = int(np.argmin(ll))
        rng = max(float(hi[i] - lo[i]), 1e-12)
        rows.append([
            fu / scan,
            fd / scan,
            su / scan,
            sd / scan,
            (c[i] - float(np.max(hh))) / c[i],
            (c[i] - float(np.min(ll))) / c[i],
            (len(hh) - 1 - ih) / scan,
            (len(ll) - 1 - il) / scan,
            (hi[i] - max(o[i], c[i])) / rng,
            (min(o[i], c[i]) - lo[i]) / rng,
        ])
    x = np.asarray(rows, dtype=float)
    if not np.all(np.isfinite(x)):
        raise ValueError("non-finite breakout-memory features")
    return x


def full_proba(model, X, n_classes):
    out = np.zeros((len(X), n_classes), dtype=float)
    raw = model.predict_proba(X)
    out[:, model.classes_.astype(int)] = raw
    return out


def calibrate(cal_p, test_p, y_cal, n_classes):
    if len(np.unique(y_cal)) < 2:
        return test_p
    transform = lambda p: np.log(np.clip(p, 1e-8, 1.0))
    m = LogisticRegression(C=0.05, max_iter=450)
    m.fit(transform(cal_p), y_cal)
    return full_proba(m, transform(test_p), n_classes)


def fit_classifier_candidates(X, y, train, cal, test, n_classes):
    yy = y[train]
    if len(np.unique(yy)) < 2:
        raise ValueError("insufficient training classes")

    logistic = make_pipeline(
        StandardScaler(),
        LogisticRegression(C=0.03, max_iter=500),
    )
    logistic.fit(X[train], yy)
    lp_cal = full_proba(logistic, X[cal], n_classes)
    lp_test = full_proba(logistic, X[test], n_classes)
    p_log = calibrate(lp_cal, lp_test, y[cal], n_classes)

    gbdt = HistGradientBoostingClassifier(
        max_iter=120,
        max_leaf_nodes=15,
        min_samples_leaf=100,
        learning_rate=0.04,
        l2_regularization=12,
        random_state=SEED,
    )
    gbdt.fit(X[train], yy)
    gp_cal = full_proba(gbdt, X[cal], n_classes)
    gp_test = full_proba(gbdt, X[test], n_classes)
    p_gbdt = calibrate(gp_cal, gp_test, y[cal], n_classes)

    ensemble = (p_log + p_gbdt) / 2.0
    ensemble /= np.maximum(ensemble.sum(axis=1, keepdims=True), 1e-12)
    return {"logistic": p_log, "gbdt": p_gbdt, "ensemble_equal": ensemble}


def metrics(p, y, n_classes):
    one = np.eye(n_classes)[y]
    eps = 1e-12
    brier = float(np.mean(np.sum((p - one) ** 2, axis=1)))
    log_loss = float(-np.mean(np.log(np.clip(p[np.arange(len(y)), y], eps, 1))))
    confidence = p.max(axis=1)
    correct = p.argmax(axis=1) == y
    ece = 0.0
    edges = np.linspace(0, 1, 11)
    for a, b in zip(edges[:-1], edges[1:]):
        m = (confidence >= a) & (confidence < (b if b < 1 else 1.000001))
        if np.any(m):
            ece += float(np.mean(m)) * abs(
                float(np.mean(correct[m])) - float(np.mean(confidence[m]))
            )
    return {
        "brier": brier,
        "log_loss": log_loss,
        "ece10": float(ece),
        "accuracy": float(np.mean(correct)),
        "mean_probability": p.mean(axis=0).tolist(),
        "actual_frequency": (
            np.bincount(y, minlength=n_classes) / max(len(y), 1)
        ).tolist(),
    }


def block_ci_gain(reference, candidate, y, dates, n_classes, n_boot=500):
    one = np.eye(n_classes)[y]
    diff = (
        np.sum((reference - one) ** 2, axis=1)
        - np.sum((candidate - one) ** 2, axis=1)
    )
    weeks = np.asarray(dates).astype("datetime64[W]")
    blocks = [np.flatnonzero(weeks == w) for w in np.unique(weeks)]
    if len(blocks) < 2:
        return [None, None]
    rng = np.random.default_rng(SEED)
    boot = []
    for _ in range(n_boot):
        ids = np.concatenate(
            [blocks[j] for j in rng.integers(len(blocks), size=len(blocks))]
        )
        boot.append(float(np.mean(diff[ids])))
    return [float(x) for x in np.quantile(boot, [0.025, 0.975])]


def direction_target(ix, c, vol, bars):
    terminal = np.log(c[ix + bars] / c[ix])
    threshold = DIRECTION_CORRIDOR_SIGMA * vol * math.sqrt(float(bars))
    y = np.ones(len(ix), dtype=np.int8)
    y[terminal <= -threshold] = 0
    y[terminal >= threshold] = 2
    return y, terminal, threshold


def direction_vol90d_baseline(dates, due_delta, y, vol, train, test):
    dates = np.asarray(dates)
    due = dates + due_delta
    q = np.quantile(vol[train], [1 / 3, 2 / 3])
    vb = np.digitize(vol, q, right=True)
    train_counts = np.bincount(y[train], minlength=3) + 0.5
    out = np.zeros((int(np.sum(test)), 3), dtype=float)
    for pos, i in enumerate(np.flatnonzero(test)):
        t = dates[i]
        end = np.searchsorted(due, t, side="left")
        start = np.searchsorted(dates, t - np.timedelta64(90, "D"), side="left")
        ids = np.arange(start, end, dtype=int)
        same = ids[vb[ids] == vb[i]]
        cnt = (
            np.bincount(y[same], minlength=3) + 0.5
            if len(same) >= 30
            else train_counts.copy()
        )
        out[pos] = cnt / cnt.sum()
    return out


def evaluate_direction_head(head, X, X_memory, dates, y, vol, due_delta):
    result = {"folds": {}, "corridor_sigma": DIRECTION_CORRIDOR_SIGMA}
    for spec in FOLD_SPECS:
        label = spec[0]
        tr, ca, te = fold_masks(dates, due_delta, spec)
        if min(np.sum(tr), np.sum(ca), np.sum(te)) < 100:
            continue
        base = direction_vol90d_baseline(dates, due_delta, y, vol, tr, te)
        pred = fit_classifier_candidates(X, y, tr, ca, te, 3)
        if head == "1h" and X_memory is not None:
            mem = fit_classifier_candidates(X_memory, y, tr, ca, te, 3)
            pred["memory_gbdt"] = mem["gbdt"]
            pred["memory_ensemble"] = mem["ensemble_equal"]
        yt = y[te]
        dt = dates[te]
        fold = {
            "n": int(np.sum(te)),
            "vol90d": metrics(base, yt, 3),
            "models": {},
        }
        for name, p in pred.items():
            row = metrics(p, yt, 3)
            gain = float(
                fold["vol90d"]["brier"] - row["brier"]
            )
            row["brier_gain_vs_vol90d"] = gain
            row["brier_gain_vs_vol90d_ci95"] = block_ci_gain(
                base, p, yt, dt, 3
            )
            fold["models"][name] = row
        result["folds"][label] = fold

    names = sorted({
        name
        for fold in result["folds"].values()
        for name in fold["models"]
    })
    summary = {}
    for name in names:
        rows = [
            fold["models"][name]
            for fold in result["folds"].values()
            if name in fold["models"]
        ]
        gains = [r["brier_gain_vs_vol90d"] for r in rows]
        cis = [r["brier_gain_vs_vol90d_ci95"] for r in rows]
        summary[name] = {
            "folds": len(rows),
            "wins_vs_vol90d": sum(g > 0 for g in gains),
            "mean_brier_gain_vs_vol90d": float(np.mean(gains)),
            "mean_brier": float(np.mean([r["brier"] for r in rows])),
            "mean_log_loss": float(np.mean([r["log_loss"] for r in rows])),
            "mean_ece10": float(np.mean([r["ece10"] for r in rows])),
            "positive_ci_folds": sum(
                ci[0] is not None and ci[0] > 0 for ci in cis
            ),
        }
    result["summary"] = summary
    return result


def zone_augmented_dataset(
    X, dates, regime, vol, ix, c, hi, lo, bars, due_delta
):
    # Fixed-phase non-overlap anchors keep the generic zone experiment compact
    # and prevent duplicated overlapping outcomes from dominating metrics.
    keep = np.arange(len(ix)) % bars == 0
    bix = ix[keep]
    bx = X[keep]
    bd = dates[keep]
    br = regime[keep]
    bv = vol[keep]
    unit = c[bix] * bv * math.sqrt(float(bars))

    xs = []
    ys = []
    ds = []
    rs = []
    vs = []
    pair_ids = []
    for pid, (lm, um) in enumerate(ZONE_SIGMA_PAIRS):
        lower = c[bix] - lm * unit
        upper = c[bix] + um * unit
        y, _ = first_touch_variable(
            bix, hi, lo, c, lower, upper, bars
        )
        extra = np.column_stack((
            np.full(len(bix), lm),
            np.full(len(bix), um),
            np.full(len(bix), lm - um),
            np.full(len(bix), math.log(lm / um)),
        ))
        xs.append(np.column_stack((bx, extra)))
        ys.append(y)
        ds.append(bd)
        rs.append(br)
        vs.append(bv)
        pair_ids.append(np.full(len(bix), pid, dtype=np.int16))
    return (
        np.vstack(xs),
        np.concatenate(ys),
        np.concatenate(ds),
        np.concatenate(rs),
        np.concatenate(vs),
        np.concatenate(pair_ids),
        due_delta,
    )


def zone_pair_vol_baseline(
    dates, due_delta, y, vol, pair_id, train, test
):
    q = np.quantile(vol[train], [1 / 3, 2 / 3])
    vb = np.digitize(vol, q, right=True)
    out = np.zeros((int(np.sum(test)), 4), dtype=float)
    global_counts = np.bincount(y[train], minlength=4) + 0.5
    for pos, i in enumerate(np.flatnonzero(test)):
        same = train & (pair_id == pair_id[i]) & (vb == vb[i])
        ids = np.flatnonzero(same)
        if len(ids) < 30:
            ids = np.flatnonzero(train & (pair_id == pair_id[i]))
        cnt = (
            np.bincount(y[ids], minlength=4) + 0.5
            if len(ids)
            else global_counts.copy()
        )
        out[pos] = cnt / cnt.sum()
    return out


def map_zone4_to3(p):
    # Preserve raw ambiguous probability separately in artifacts.  For the
    # requested 3-state display only, unresolved within-bar ordering is split
    # neutrally between down/up; this mapping is explicit and frozen.
    out = np.column_stack((
        p[:, 0] + 0.5 * p[:, 3],
        p[:, 2],
        p[:, 1] + 0.5 * p[:, 3],
    ))
    out /= np.maximum(out.sum(axis=1, keepdims=True), 1e-12)
    return out


def zone_resolved_metrics(p4, y4):
    resolved = y4 != 3
    if not np.any(resolved):
        return None
    p3 = map_zone4_to3(p4[resolved])
    y = y4[resolved].copy()
    # raw LOWER_FIRST=0, UPPER_FIRST=1, NEITHER=2 ->
    # displayed DOWN=0, RANGE=1, UP=2.
    y3 = np.where(y == 0, 0, np.where(y == 2, 1, 2)).astype(int)
    return metrics(p3, y3, 3)


def evaluate_zone_head(
    head, X, y, dates, vol, pair_id, due_delta
):
    result = {
        "folds": {},
        "raw_classes": RAW_ZONE_CLASSES,
        "display_mapping": {
            "down": "lower_first + 0.5 * ambiguous_same_bar",
            "range": "neither",
            "up": "upper_first + 0.5 * ambiguous_same_bar",
        },
        "barrier_sigma_pairs": [list(x) for x in ZONE_SIGMA_PAIRS],
    }
    for spec in FOLD_SPECS:
        label = spec[0]
        tr, ca, te = fold_masks(dates, due_delta, spec)
        if min(np.sum(tr), np.sum(ca), np.sum(te)) < 100:
            continue
        base = zone_pair_vol_baseline(
            dates, due_delta, y, vol, pair_id, tr, te
        )
        pred = fit_classifier_candidates(X, y, tr, ca, te, 4)
        yt = y[te]
        dt = dates[te]
        fold = {
            "n": int(np.sum(te)),
            "ambiguous_fraction": float(np.mean(yt == 3)),
            "pair_vol_baseline": metrics(base, yt, 4),
            "pair_vol_baseline_3state_resolved": zone_resolved_metrics(base, yt),
            "models": {},
        }
        for name, p in pred.items():
            row = metrics(p, yt, 4)
            row["three_state_resolved"] = zone_resolved_metrics(p, yt)
            row["brier_gain_vs_pair_vol_baseline"] = float(
                fold["pair_vol_baseline"]["brier"] - row["brier"]
            )
            row["brier_gain_vs_pair_vol_baseline_ci95"] = block_ci_gain(
                base, p, yt, dt, 4
            )
            fold["models"][name] = row
        result["folds"][label] = fold

    names = ("logistic", "gbdt", "ensemble_equal")
    summary = {}
    for name in names:
        rows = [f["models"][name] for f in result["folds"].values()]
        gains = [r["brier_gain_vs_pair_vol_baseline"] for r in rows]
        cis = [r["brier_gain_vs_pair_vol_baseline_ci95"] for r in rows]
        summary[name] = {
            "folds": len(rows),
            "wins_vs_pair_vol_baseline": sum(g > 0 for g in gains),
            "mean_brier_gain_vs_pair_vol_baseline": float(np.mean(gains)),
            "mean_brier": float(np.mean([r["brier"] for r in rows])),
            "mean_log_loss": float(np.mean([r["log_loss"] for r in rows])),
            "positive_ci_folds": sum(
                ci[0] is not None and ci[0] > 0 for ci in cis
            ),
        }
    result["summary"] = summary
    result["max_ambiguous_fraction"] = max(
        (f["ambiguous_fraction"] for f in result["folds"].values()),
        default=None,
    )
    return result


def build_15m():
    path = ROOT / "research_vnext4r6/data/BTCUSDT_15m_2024-01_2026-09.json.gz"
    t, o, hi, lo, c, v, trades, taker, sha = read_klines(path, 900000)
    ix, dates, X, names, regime, vol = build_15m_features(
        t, hi, lo, c, v, trades, taker, 16
    )
    mem = memory_features(o, hi, lo, c, ix, 16, 16)
    Xmem = np.column_stack((X, mem))
    heads = {}
    zones = {}
    for head, bars in (("1h", 4), ("4h", 16)):
        y, _, _ = direction_target(ix, c, vol, bars)
        due = np.timedelta64(bars * 15, "m")
        heads[head] = evaluate_direction_head(
            head, X, Xmem if head == "1h" else None,
            dates, y, vol, due,
        )
        heads[head]["source_sha256"] = sha
        heads[head]["feature_names"] = names + (
            [
                "failed_up_break_count", "failed_down_break_count",
                "successful_up_break_count", "successful_down_break_count",
                "distance_from_recent_high", "distance_from_recent_low",
                "bars_since_recent_high", "bars_since_recent_low",
                "upper_wick_ratio", "lower_wick_ratio",
            ] if head == "1h" else []
        )
        z = zone_augmented_dataset(
            X, dates, regime, vol, ix, c, hi, lo, bars, due
        )
        zones[head] = evaluate_zone_head(
            head, z[0], z[1], z[2], z[4], z[5], z[6]
        )
        zones[head]["source_sha256"] = sha
    return heads, zones


def build_24h():
    path = ROOT / "btc_1h_2024_to_sep24_2026.json"
    t, o, hi, lo, c, v, trades, taker, sha = read_klines(path, 3600000)
    ix, dates, X, names, regime, vol, atr = build_hourly_features(
        t, hi, lo, c, v, trades, taker, 24
    )
    bars = 24
    due = np.timedelta64(24, "h")
    y, _, _ = direction_target(ix, c, vol, bars)
    direction = evaluate_direction_head(
        "24h", X, None, dates, y, vol, due
    )
    direction["source_sha256"] = sha
    direction["feature_names"] = names
    z = zone_augmented_dataset(
        X, dates, regime, vol, ix, c, hi, lo, bars, due
    )
    zone = evaluate_zone_head(
        "24h", z[0], z[1], z[2], z[4], z[5], z[6]
    )
    zone["source_sha256"] = sha
    return direction, zone


def acceptance(report):
    policy = json.loads((OUT / "acceptance_policy.json").read_text())
    decision = {"direction": {}, "zone": {}}

    for head, row in report["direction"].items():
        candidates = {}
        for name, s in row["summary"].items():
            ok = (
                s["folds"] >= policy["direction_gate"]["min_folds"]
                and s["wins_vs_vol90d"] >= policy["direction_gate"]["min_wins"]
                and s["positive_ci_folds"] >= policy["direction_gate"]["min_positive_ci_folds"]
                and s["mean_brier_gain_vs_vol90d"]
                    >= policy["direction_gate"]["min_mean_brier_gain"]
                and s["mean_ece10"]
                    <= policy["direction_gate"]["max_mean_ece10"]
            )
            candidates[name] = {"pass": bool(ok), **s}
        eligible = [
            (v["mean_brier"], k)
            for k, v in candidates.items() if v["pass"]
        ]
        eligible.sort()
        decision["direction"][head] = {
            "candidates": candidates,
            "selected": eligible[0][1] if eligible else None,
        }

    for head, row in report["zone_first_passage"].items():
        candidates = {}
        for name, s in row["summary"].items():
            ok = (
                s["folds"] >= policy["zone_gate"]["min_folds"]
                and s["wins_vs_pair_vol_baseline"] >= policy["zone_gate"]["min_wins"]
                and s["positive_ci_folds"] >= policy["zone_gate"]["min_positive_ci_folds"]
                and s["mean_brier_gain_vs_pair_vol_baseline"]
                    >= policy["zone_gate"]["min_mean_brier_gain"]
                and row["max_ambiguous_fraction"]
                    <= policy["zone_gate"]["max_ambiguous_fraction"]
            )
            candidates[name] = {"pass": bool(ok), **s}
        eligible = [
            (v["mean_brier"], k)
            for k, v in candidates.items() if v["pass"]
        ]
        eligible.sort()
        decision["zone"][head] = {
            "candidates": candidates,
            "selected": eligible[0][1] if eligible else None,
        }

    decision["all_direction_heads_pass"] = all(
        v["selected"] is not None for v in decision["direction"].values()
    )
    decision["all_zone_heads_pass"] = all(
        v["selected"] is not None for v in decision["zone"].values()
    )
    decision["status"] = (
        "PREDICTIVE_RESEARCH_CANDIDATE"
        if decision["all_direction_heads_pass"]
        else "PREDICTIVE_REWORK"
    )
    decision["trading_authority"] = False
    decision["prospective_skill_proven"] = False
    return decision


def main():
    direction, zones = build_15m()
    d24, z24 = build_24h()
    direction["24h"] = d24
    zones["24h"] = z24

    report = {
        "schema": "btc-predictive-vnext5-predictive-research-v1",
        "status": "RESEARCH_ONLY_NO_PRODUCTION_NO_TRADING_AUTHORITY",
        "parent_engineering_source_sha": "34304b7650421dfd07d3c9e9b2f7f3c937b96ec1",
        "design": {
            "primary_output": "direct_3state_terminal_direction",
            "primary_classes": DIRECTION_CLASSES,
            "direction_corridor_sigma": DIRECTION_CORRIDOR_SIGMA,
            "secondary_output": "generic_asymmetric_zone_first_passage",
            "zone_raw_classes": RAW_ZONE_CLASSES,
            "zone_display_mapping": {
                "down": "lower_first + 0.5 * ambiguous_same_bar",
                "range": "neither",
                "up": "upper_first + 0.5 * ambiguous_same_bar",
            },
            "macro_and_derivatives_policy": (
                "NOT_MERGED: prior R6 ablations failed vs spot; "
                "retest only in separate causal ablation"
            ),
            "breakout_memory_policy": (
                "TESTED_AS_1H_CANDIDATE_ONLY: prior R6 gate passed only 1h"
            ),
        },
        "direction": direction,
        "zone_first_passage": zones,
        "trading_authority": False,
        "prospective_skill_proven": False,
    }
    report["acceptance"] = acceptance(report)
    path = OUT / "predictive_research_result.json"
    path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps(report["acceptance"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
