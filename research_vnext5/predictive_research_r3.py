"""vNext5R3: 24h probability calibration repair only.

R2 established:
  * 1h first-passage surface passes the stronger predictive gate.
  * 4h first-passage surface passes the stronger predictive gate.
  * 24h wins strongly on Brier but fails the absolute canonical calibration gate.

R3 does not change targets, features, baselines, thresholds, or engineering.
It tests scalar temperature calibration for 24h probabilities, selected only on
the calibration split.  Pair-specific temperature uses the barrier-pair id but
never test outcomes.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from predictive_vnext4.core import read_klines, build_hourly_features
from research_vnext5 import predictive_research as r1
from research_vnext5 import predictive_research_r2 as r2

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "research_vnext5"
POLICY_PATH = OUT / "acceptance_policy_r3.json"
CANONICAL_PID = r1.ZONE_SIGMA_PAIRS.index((1.0, 1.0))


def softmax_log(logp):
    z = logp - np.max(logp, axis=1, keepdims=True)
    e = np.exp(z)
    return e / np.maximum(e.sum(axis=1, keepdims=True), 1e-12)


def apply_temperature(p, temperature):
    return softmax_log(
        np.log(np.clip(np.asarray(p, dtype=float), 1e-12, 1.0))
        / float(temperature)
    )


def choose_temperature(p, y, grid):
    y = np.asarray(y, dtype=int)
    best = None
    for t in grid:
        q = apply_temperature(p, t)
        loss = float(
            -np.mean(
                np.log(np.clip(q[np.arange(len(y)), y], 1e-12, 1.0))
            )
        )
        candidate = (loss, float(t))
        if best is None or candidate < best:
            best = candidate
    return best[1]


def raw_candidates(X, y, train, cal, test):
    yy = y[train]

    logistic = make_pipeline(
        StandardScaler(),
        LogisticRegression(C=0.03, max_iter=500),
    )
    logistic.fit(X[train], yy)
    lcal = r1.full_proba(logistic, X[cal], 4)
    ltest = r1.full_proba(logistic, X[test], 4)

    gbdt = HistGradientBoostingClassifier(
        max_iter=120,
        max_leaf_nodes=15,
        min_samples_leaf=100,
        learning_rate=0.04,
        l2_regularization=12,
        random_state=r1.SEED,
    )
    gbdt.fit(X[train], yy)
    gcal = r1.full_proba(gbdt, X[cal], 4)
    gtest = r1.full_proba(gbdt, X[test], 4)

    ecal = (lcal + gcal) / 2.0
    etest = (ltest + gtest) / 2.0
    ecal /= np.maximum(ecal.sum(axis=1, keepdims=True), 1e-12)
    etest /= np.maximum(etest.sum(axis=1, keepdims=True), 1e-12)
    return {
        "logistic": (lcal, ltest),
        "gbdt": (gcal, gtest),
        "ensemble": (ecal, etest),
    }


def pair_temperature(cal_p, test_p, ycal, cal_pid, test_pid, policy):
    grid = np.asarray(policy["temperature_grid"], dtype=float)
    minimum = int(policy["min_calibration_rows_per_pair"])
    global_t = choose_temperature(cal_p, ycal, grid)
    out = np.zeros_like(test_p)
    chosen = {}
    for pid in range(len(r1.ZONE_SIGMA_PAIRS)):
        cm = cal_pid == pid
        tm = test_pid == pid
        if not np.any(tm):
            continue
        t = (
            choose_temperature(cal_p[cm], ycal[cm], grid)
            if np.sum(cm) >= minimum and len(np.unique(ycal[cm])) >= 2
            else global_t
        )
        out[tm] = apply_temperature(test_p[tm], t)
        chosen[str(pid)] = {
            "pair": list(r1.ZONE_SIGMA_PAIRS[pid]),
            "temperature": float(t),
            "calibration_rows": int(np.sum(cm)),
            "fallback_global": bool(
                np.sum(cm) < minimum or len(np.unique(ycal[cm])) < 2
            ),
        }
    return out, float(global_t), chosen


def evaluate_candidate(p, base, yt, dt, canon):
    row = r1.metrics(p, yt, 4)
    row["baseline_ece10"] = r1.metrics(base, yt, 4)["ece10"]
    row["brier_gain_vs_rolling_pair_vol90d"] = float(
        r1.metrics(base, yt, 4)["brier"] - row["brier"]
    )
    row["brier_gain_vs_rolling_pair_vol90d_ci95"] = r1.block_ci_gain(
        base, p, yt, dt, 4
    )
    cp = p[canon]
    cb = base[canon]
    cy = yt[canon]
    cd = dt[canon]
    cm = r1.metrics(cp, cy, 4)
    cbase = r1.metrics(cb, cy, 4)
    cm["baseline_ece10"] = cbase["ece10"]
    cm["brier_gain_vs_canonical_baseline"] = float(
        cbase["brier"] - cm["brier"]
    )
    cm["brier_gain_vs_canonical_baseline_ci95"] = r1.block_ci_gain(
        cb, cp, cy, cd, 4
    )
    cm["three_state_resolved"] = r1.zone_resolved_metrics(cp, cy)
    row["canonical_1sigma"] = cm
    return row


def evaluate_24h_r3():
    policy = json.loads(POLICY_PATH.read_text())
    path = ROOT / "btc_1h_2024_to_sep24_2026.json"
    t, o, hi, lo, c, v, trades, taker, sha = read_klines(path, 3600000)
    ix, dates, X, names, regime, vol, atr = build_hourly_features(
        t, hi, lo, c, v, trades, taker, 24
    )
    due = np.timedelta64(24, "h")
    z = r1.zone_augmented_dataset(
        X, dates, regime, vol, ix, c, hi, lo, 24, due
    )
    ZX, zy, zd, zr, zv, zpid, zdue = z

    result = {
        "source_sha256": sha,
        "feature_names": names + [
            "lower_barrier_sigma",
            "upper_barrier_sigma",
            "barrier_sigma_asymmetry",
            "log_lower_to_upper_sigma_ratio",
        ],
        "folds": {},
        "calibration_repair": {
            "method": "scalar_temperature",
            "pair_specific": True,
            "temperature_grid": policy["temperature_grid"],
            "test_outcomes_used_for_temperature": False,
        },
    }

    for spec in r1.FOLD_SPECS:
        label = spec[0]
        tr, ca, te = r1.fold_masks(zd, zdue, spec)
        base = r2.rolling_pair_vol90d_baseline(
            zd, zdue, zy, zv, zpid, tr, te
        )
        old = r1.fit_classifier_candidates(ZX, zy, tr, ca, te, 4)
        raw = raw_candidates(ZX, zy, tr, ca, te)

        yt = zy[te]
        dt = zd[te]
        cal_pid = zpid[ca]
        test_pid = zpid[te]
        canon = test_pid == CANONICAL_PID

        candidates = {
            "r2_ensemble_multinomial": old["ensemble_equal"],
        }
        temperature_meta = {}

        for prefix, (cal_p, test_p) in raw.items():
            grid = np.asarray(policy["temperature_grid"], dtype=float)
            gt = choose_temperature(cal_p, zy[ca], grid)
            candidates[prefix + "_global_temperature"] = apply_temperature(
                test_p, gt
            )
            pp, global_t, chosen = pair_temperature(
                cal_p, test_p, zy[ca], cal_pid, test_pid, policy
            )
            candidates[prefix + "_pair_temperature"] = pp
            temperature_meta[prefix] = {
                "global_temperature": global_t,
                "pair_temperatures": chosen,
            }

        fold = {
            "n": int(np.sum(te)),
            "canonical_n": int(np.sum(canon)),
            "canonical_ambiguous_fraction": float(np.mean(yt[canon] == 3)),
            "baseline": r1.metrics(base, yt, 4),
            "canonical_baseline": r1.metrics(base[canon], yt[canon], 4),
            "temperature_meta": temperature_meta,
            "models": {},
        }
        for name, p in candidates.items():
            fold["models"][name] = evaluate_candidate(
                p, base, yt, dt, canon
            )
        result["folds"][label] = fold

    result["summary"] = {}
    result["canonical_summary"] = {}
    names = sorted({
        n for f in result["folds"].values() for n in f["models"]
    })
    for name in names:
        rows = [f["models"][name] for f in result["folds"].values()]
        result["summary"][name] = r2._candidate_summary(
            rows,
            "brier_gain_vs_rolling_pair_vol90d",
            "brier_gain_vs_rolling_pair_vol90d_ci95",
            "baseline_ece10",
        )
        cr = [x["canonical_1sigma"] for x in rows]
        result["canonical_summary"][name] = r2._candidate_summary(
            cr,
            "brier_gain_vs_canonical_baseline",
            "brier_gain_vs_canonical_baseline_ci95",
            "baseline_ece10",
        )
    result["max_canonical_ambiguous_fraction"] = max(
        f["canonical_ambiguous_fraction"] for f in result["folds"].values()
    )
    return result


def gate_candidate(s, c, row, og, cg):
    overall = (
        s["folds"] >= og["min_folds"]
        and s["wins"] >= og["min_wins"]
        and s["positive_ci_folds"] >= og["min_positive_ci_folds"]
        and s["mean_brier_gain"] >= og["min_mean_brier_gain"]
        and s["mean_ece10"] <= og["max_mean_ece10"]
        and s["mean_ece10"]
            <= s["mean_baseline_ece10"]
            + og["max_ece10_degradation_vs_baseline"]
    )
    canonical = (
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
    return bool(overall), bool(canonical)


def acceptance(heads_1h_4h, h24):
    policy = json.loads(POLICY_PATH.read_text())
    og = policy["overall_zone_gate"]
    cg = policy["canonical_1sigma_gate"]
    out = {"heads": {}}

    # 1h/4h are intentionally unchanged R2 calculations and gates.
    for head, row in heads_1h_4h.items():
        candidates = {}
        for name in ("logistic", "gbdt", "ensemble_equal"):
            s = row["summary"][name]
            c = row["canonical_summary"][name]
            overall, canonical = gate_candidate(s, c, row, og, cg)
            candidates[name] = {
                "overall_pass": overall,
                "canonical_pass": canonical,
                "pass": bool(overall and canonical),
                "overall": s,
                "canonical_1sigma": c,
            }
        eligible = [
            (
                candidates[n]["overall"]["mean_brier"]
                + candidates[n]["canonical_1sigma"]["mean_brier"],
                n,
            )
            for n in candidates if candidates[n]["pass"]
        ]
        eligible.sort()
        out["heads"][head] = {
            "source": "UNCHANGED_R2",
            "selected": eligible[0][1] if eligible else None,
            "candidates": candidates,
        }

    candidates = {}
    for name in h24["summary"]:
        s = h24["summary"][name]
        c = h24["canonical_summary"][name]
        overall, canonical = gate_candidate(s, c, h24, og, cg)
        candidates[name] = {
            "overall_pass": overall,
            "canonical_pass": canonical,
            "pass": bool(overall and canonical),
            "overall": s,
            "canonical_1sigma": c,
        }
    eligible = [
        (
            candidates[n]["overall"]["mean_brier"]
            + candidates[n]["canonical_1sigma"]["mean_brier"],
            n,
        )
        for n in candidates if candidates[n]["pass"]
    ]
    eligible.sort()
    out["heads"]["24h"] = {
        "source": "R3_CALIBRATION_REPAIR",
        "selected": eligible[0][1] if eligible else None,
        "candidates": candidates,
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
    # Recompute unchanged R2 1h/4h under the same data rebuild.
    heads = r2.build_15m()
    h24 = evaluate_24h_r3()

    report = {
        "schema": "btc-predictive-vnext5r3-calibration-research-v1",
        "status": "RESEARCH_ONLY_NO_PRODUCTION_NO_TRADING_AUTHORITY",
        "parent_r2_source_sha":
            "25854966f9aeb48233bb8309be6b8c80e7f13177",
        "parent_engineering_source_sha":
            "34304b7650421dfd07d3c9e9b2f7f3c937b96ec1",
        "change_scope":
            "24h calibration only; no target/feature/baseline/gate changes",
        "heads_r2_unchanged": {
            "1h": heads["1h"],
            "4h": heads["4h"],
        },
        "head_24h_r3": h24,
        "acceptance_policy": json.loads(POLICY_PATH.read_text()),
        "prospective_skill_proven": False,
        "trading_authority": False,
    }
    report["acceptance"] = acceptance(
        {"1h": heads["1h"], "4h": heads["4h"]}, h24
    )
    path = OUT / "predictive_research_r3_result.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report["acceptance"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
