"""vNext5R2 predictive research.

Primary candidate is the generic asymmetric first-passage surface because vNext5R1
showed that the direct terminal 3-state head did not clear the predeclared gate on
1h/4h, while the zone surface cleared its initial gate on all three heads.

R2 makes the predictive test harder:
  * rolling 90-day pair+volatility baseline with due-time semantics;
  * explicit calibration/ECE gate;
  * separate canonical ±1 sigma gate for the normal DOWN/RANGE/UP report;
  * raw 4-state probabilities preserved; 3-state mapping remains explicit.

Research only. No production integration or trading authority.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

from predictive_vnext4.core import (
    read_klines,
    build_15m_features,
    build_hourly_features,
)
from research_vnext5 import predictive_research as r1

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "research_vnext5"
POLICY_PATH = OUT / "acceptance_policy_r2.json"
CANONICAL_PAIR = (1.0, 1.0)
CANONICAL_PID = r1.ZONE_SIGMA_PAIRS.index(CANONICAL_PAIR)


def rolling_pair_vol90d_baseline(
    dates, due_delta, y, vol, pair_id, train, test
):
    """Adaptive baseline using only outcomes due before each test anchor.

    The generic-zone dataset is stacked by barrier pair.  Each pair block is
    chronologically sorted, so searchsorted is applied inside a pair block only.
    """
    dates = np.asarray(dates)
    q = np.quantile(vol[train], [1 / 3, 2 / 3])
    vb = np.digitize(vol, q, right=True)
    full = np.zeros((len(y), 4), dtype=float)
    global_train = np.bincount(y[train], minlength=4) + 0.5

    for pid in range(len(r1.ZONE_SIGMA_PAIRS)):
        ids = np.flatnonzero(pair_id == pid)
        d = dates[ids]
        due = d + due_delta
        yy = y[ids]
        vv = vb[ids]
        tr = train[ids]
        te = test[ids]
        pair_train = np.bincount(yy[tr], minlength=4) + 0.5

        for j in np.flatnonzero(te):
            t = d[j]
            end = int(np.searchsorted(due, t, side="left"))
            start = int(
                np.searchsorted(
                    d, t - np.timedelta64(90, "D"), side="left"
                )
            )
            cand = np.arange(start, end, dtype=int)
            same = cand[vv[cand] == vv[j]]
            if len(same) >= 30:
                cnt = np.bincount(yy[same], minlength=4) + 0.5
            elif len(cand) >= 30:
                cnt = np.bincount(yy[cand], minlength=4) + 0.5
            elif np.sum(tr) >= 10:
                cnt = pair_train.copy()
            else:
                cnt = global_train.copy()
            full[ids[j]] = cnt / cnt.sum()

    return full[test]


def _candidate_summary(rows, gain_key, ci_key, baseline_key):
    gains = [x[gain_key] for x in rows]
    cis = [x[ci_key] for x in rows]
    return {
        "folds": len(rows),
        "wins": sum(g > 0 for g in gains),
        "mean_brier_gain": float(np.mean(gains)),
        "mean_brier": float(np.mean([x["brier"] for x in rows])),
        "mean_log_loss": float(np.mean([x["log_loss"] for x in rows])),
        "mean_ece10": float(np.mean([x["ece10"] for x in rows])),
        "mean_baseline_ece10": float(
            np.mean([x[baseline_key] for x in rows])
        ),
        "positive_ci_folds": sum(
            ci[0] is not None and ci[0] > 0 for ci in cis
        ),
    }


def evaluate_zone_head_r2(
    head, X, y, dates, vol, pair_id, due_delta
):
    result = {
        "folds": {},
        "raw_classes": r1.RAW_ZONE_CLASSES,
        "canonical_pair_sigma": list(CANONICAL_PAIR),
        "display_mapping": {
            "down": "lower_first + 0.5 * ambiguous_same_bar",
            "range": "neither",
            "up": "upper_first + 0.5 * ambiguous_same_bar",
            "raw_ambiguous_probability_always_preserved": True,
        },
        "barrier_sigma_pairs": [list(x) for x in r1.ZONE_SIGMA_PAIRS],
        "baseline": "rolling_90d_same_pair_same_frozen_volatility_bin",
    }

    for spec in r1.FOLD_SPECS:
        label = spec[0]
        tr, ca, te = r1.fold_masks(dates, due_delta, spec)
        if min(np.sum(tr), np.sum(ca), np.sum(te)) < 100:
            continue

        base = rolling_pair_vol90d_baseline(
            dates, due_delta, y, vol, pair_id, tr, te
        )
        pred = r1.fit_classifier_candidates(X, y, tr, ca, te, 4)
        yt = y[te]
        dt = dates[te]
        pids = pair_id[te]
        canon = pids == CANONICAL_PID
        if not np.any(canon):
            raise RuntimeError("canonical pair missing from test fold")

        fold = {
            "n": int(np.sum(te)),
            "ambiguous_fraction": float(np.mean(yt == 3)),
            "rolling_pair_vol90d": r1.metrics(base, yt, 4),
            "canonical_n": int(np.sum(canon)),
            "canonical_ambiguous_fraction": float(np.mean(yt[canon] == 3)),
            "canonical_baseline": r1.metrics(base[canon], yt[canon], 4),
            "canonical_baseline_3state_resolved":
                r1.zone_resolved_metrics(base[canon], yt[canon]),
            "models": {},
        }

        for name, p in pred.items():
            row = r1.metrics(p, yt, 4)
            row["three_state_resolved"] = r1.zone_resolved_metrics(p, yt)
            row["baseline_ece10"] = fold["rolling_pair_vol90d"]["ece10"]
            row["brier_gain_vs_rolling_pair_vol90d"] = float(
                fold["rolling_pair_vol90d"]["brier"] - row["brier"]
            )
            row["brier_gain_vs_rolling_pair_vol90d_ci95"] = (
                r1.block_ci_gain(base, p, yt, dt, 4)
            )

            cp = p[canon]
            cb = base[canon]
            cy = yt[canon]
            cd = dt[canon]
            cm = r1.metrics(cp, cy, 4)
            cm["three_state_resolved"] = r1.zone_resolved_metrics(cp, cy)
            cm["baseline_ece10"] = fold["canonical_baseline"]["ece10"]
            cm["brier_gain_vs_canonical_baseline"] = float(
                fold["canonical_baseline"]["brier"] - cm["brier"]
            )
            cm["brier_gain_vs_canonical_baseline_ci95"] = (
                r1.block_ci_gain(cb, cp, cy, cd, 4)
            )
            row["canonical_1sigma"] = cm
            fold["models"][name] = row

        result["folds"][label] = fold

    result["summary"] = {}
    result["canonical_summary"] = {}
    for name in ("logistic", "gbdt", "ensemble_equal"):
        rows = [f["models"][name] for f in result["folds"].values()]
        result["summary"][name] = _candidate_summary(
            rows,
            "brier_gain_vs_rolling_pair_vol90d",
            "brier_gain_vs_rolling_pair_vol90d_ci95",
            "baseline_ece10",
        )
        canon_rows = [r["canonical_1sigma"] for r in rows]
        result["canonical_summary"][name] = _candidate_summary(
            canon_rows,
            "brier_gain_vs_canonical_baseline",
            "brier_gain_vs_canonical_baseline_ci95",
            "baseline_ece10",
        )

    result["max_ambiguous_fraction"] = max(
        f["ambiguous_fraction"] for f in result["folds"].values()
    )
    result["max_canonical_ambiguous_fraction"] = max(
        f["canonical_ambiguous_fraction"]
        for f in result["folds"].values()
    )
    return result


def build_15m():
    path = (
        ROOT
        / "research_vnext4r6/data/BTCUSDT_15m_2024-01_2026-09.json.gz"
    )
    t, o, hi, lo, c, v, trades, taker, sha = read_klines(path, 900000)
    ix, dates, X, names, regime, vol = build_15m_features(
        t, hi, lo, c, v, trades, taker, 16
    )
    out = {}
    for head, bars in (("1h", 4), ("4h", 16)):
        due = np.timedelta64(bars * 15, "m")
        z = r1.zone_augmented_dataset(
            X, dates, regime, vol, ix, c, hi, lo, bars, due
        )
        row = evaluate_zone_head_r2(
            head, z[0], z[1], z[2], z[4], z[5], z[6]
        )
        row["source_sha256"] = sha
        row["feature_names"] = names + [
            "lower_barrier_sigma",
            "upper_barrier_sigma",
            "barrier_sigma_asymmetry",
            "log_lower_to_upper_sigma_ratio",
        ]
        out[head] = row
    return out


def build_24h():
    path = ROOT / "btc_1h_2024_to_sep24_2026.json"
    t, o, hi, lo, c, v, trades, taker, sha = read_klines(
        path, 3600000
    )
    ix, dates, X, names, regime, vol, atr = build_hourly_features(
        t, hi, lo, c, v, trades, taker, 24
    )
    due = np.timedelta64(24, "h")
    z = r1.zone_augmented_dataset(
        X, dates, regime, vol, ix, c, hi, lo, 24, due
    )
    row = evaluate_zone_head_r2(
        "24h", z[0], z[1], z[2], z[4], z[5], z[6]
    )
    row["source_sha256"] = sha
    row["feature_names"] = names + [
        "lower_barrier_sigma",
        "upper_barrier_sigma",
        "barrier_sigma_asymmetry",
        "log_lower_to_upper_sigma_ratio",
    ]
    return row


def acceptance(report):
    policy = json.loads(POLICY_PATH.read_text())
    out = {"heads": {}}
    for head, row in report["heads"].items():
        candidates = {}
        for name in ("logistic", "gbdt", "ensemble_equal"):
            s = row["summary"][name]
            c = row["canonical_summary"][name]
            og = policy["overall_zone_gate"]
            cg = policy["canonical_1sigma_gate"]
            overall_pass = (
                s["folds"] >= og["min_folds"]
                and s["wins"] >= og["min_wins"]
                and s["positive_ci_folds"] >= og["min_positive_ci_folds"]
                and s["mean_brier_gain"] >= og["min_mean_brier_gain"]
                and s["mean_ece10"] <= og["max_mean_ece10"]
                and s["mean_ece10"]
                    <= s["mean_baseline_ece10"]
                    + og["max_ece10_degradation_vs_baseline"]
                and row["max_ambiguous_fraction"]
                    <= og["max_ambiguous_fraction"]
            )
            canonical_pass = (
                c["folds"] >= cg["min_folds"]
                and c["wins"] >= cg["min_wins"]
                and c["positive_ci_folds"] >= cg["min_positive_ci_folds"]
                and c["mean_brier_gain"] >= cg["min_mean_brier_gain"]
                and c["mean_ece10"] <= cg["max_mean_ece10"]
                and c["mean_ece10"]
                    <= c["mean_baseline_ece10"]
                    + cg["max_ece10_degradation_vs_baseline"]
                and row["max_canonical_ambiguous_fraction"]
                    <= cg["max_ambiguous_fraction"]
            )
            candidates[name] = {
                "overall_pass": bool(overall_pass),
                "canonical_pass": bool(canonical_pass),
                "pass": bool(overall_pass and canonical_pass),
                "overall": s,
                "canonical_1sigma": c,
            }

        eligible = [
            (
                candidates[n]["canonical_1sigma"]["mean_brier"]
                + candidates[n]["overall"]["mean_brier"],
                n,
            )
            for n in candidates if candidates[n]["pass"]
        ]
        eligible.sort()
        out["heads"][head] = {
            "candidates": candidates,
            "selected": eligible[0][1] if eligible else None,
        }

    out["all_heads_pass"] = all(
        x["selected"] is not None for x in out["heads"].values()
    )
    out["status"] = (
        "PREDICTIVE_CANDIDATE_READY_FOR_FREEZE_REVIEW"
        if out["all_heads_pass"]
        else "PREDICTIVE_REWORK"
    )
    out["prospective_skill_proven"] = False
    out["trading_authority"] = False
    return out


def main():
    heads = build_15m()
    heads["24h"] = build_24h()
    report = {
        "schema": "btc-predictive-vnext5r2-zone-research-v1",
        "status": "RESEARCH_ONLY_NO_PRODUCTION_NO_TRADING_AUTHORITY",
        "parent_r1_source_sha": "f2b2c31f20d019d653076bd149b3a3e0b2b03a0f",
        "parent_engineering_source_sha":
            "34304b7650421dfd07d3c9e9b2f7f3c937b96ec1",
        "reason_for_r2": (
            "R1 terminal direction failed frozen gate on 1h/4h; "
            "zone surface passed initial gate on all heads. "
            "R2 strengthens baseline, calibration and canonical corridor tests."
        ),
        "primary_output_contract": {
            "raw": list(r1.RAW_ZONE_CLASSES),
            "display": ["DOWN", "RANGE", "UP"],
            "canonical_range": "symmetric +/-1 pre-anchor volatility sigma",
            "custom_zone_support": True,
            "raw_ambiguous_probability_preserved": True,
        },
        "heads": heads,
        "acceptance_policy": json.loads(POLICY_PATH.read_text()),
        "prospective_skill_proven": False,
        "trading_authority": False,
    }
    report["acceptance"] = acceptance(report)
    path = OUT / "predictive_research_r2_result.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report["acceptance"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
