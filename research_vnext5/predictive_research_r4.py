"""vNext5R4 final historical calibration research.

Scope is deliberately narrow:
- 1h / 4h remain unchanged passing R2 candidates.
- 24h target, features, causal rolling baseline and gates remain unchanged.
- Only probability calibration transforms are tested.
- This is the final iteration allowed to inspect the already-seen historical folds.
  Any further model choice must be evaluated in a new clean prospective epoch.

Research only; no production integration and no trading authority.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression

from predictive_vnext4.core import read_klines, build_hourly_features
from research_vnext5 import predictive_research as r1
from research_vnext5 import predictive_research_r2 as r2
from research_vnext5 import predictive_research_r3 as r3

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "research_vnext5"
POLICY_PATH = OUT / "acceptance_policy_r4.json"
CANONICAL_PID = r1.ZONE_SIGMA_PAIRS.index((1.0, 1.0))


def meta_calibrate(cal_p, test_p, y_cal, C):
    """Regularized multinomial calibration of log probabilities."""
    xcal = np.log(np.clip(cal_p, 1e-8, 1.0))
    xtest = np.log(np.clip(test_p, 1e-8, 1.0))
    m = LogisticRegression(C=float(C), max_iter=500)
    m.fit(xcal, y_cal)
    return r1.full_proba(m, xtest, 4)


def normalize(p):
    p = np.clip(np.asarray(p, dtype=float), 0.0, None)
    return p / np.maximum(p.sum(axis=1, keepdims=True), 1e-12)


def shrink_to(p, target, alpha):
    target = np.asarray(target, dtype=float)
    if target.ndim == 1:
        target = np.tile(target, (len(p), 1))
    return normalize((1.0 - float(alpha)) * p + float(alpha) * target)


def evaluate_24h():
    policy = json.loads(POLICY_PATH.read_text())
    path = ROOT / "btc_1h_2024_to_sep24_2026.json"
    t, o, hi, lo, c, v, trades, taker, sha = read_klines(path, 3600000)
    ix, dates, X, names, regime, vol, atr = build_hourly_features(
        t, hi, lo, c, v, trades, taker, 24
    )
    due = np.timedelta64(24, "h")
    ZX, zy, zd, zr, zv, zpid, zdue = r1.zone_augmented_dataset(
        X, dates, regime, vol, ix, c, hi, lo, 24, due
    )

    result = {
        "source_sha256": sha,
        "folds": {},
        "scope": "24h probability calibration only",
        "historical_folds_seen_before_r4": True,
        "future_iteration_policy": (
            "NO_FURTHER_HISTORICAL_MODEL_SELECTION_AFTER_R4; "
            "next selection evidence must be clean prospective"
        ),
    }

    for spec in r1.FOLD_SPECS:
        label = spec[0]
        tr, ca, te = r1.fold_masks(zd, zdue, spec)

        base = r2.rolling_pair_vol90d_baseline(
            zd, zdue, zy, zv, zpid, tr, te
        )
        r2_pred = r1.fit_classifier_candidates(ZX, zy, tr, ca, te, 4)
        raw = r3.raw_candidates(ZX, zy, tr, ca, te)

        yt = zy[te]
        ycal = zy[ca]
        dt = zd[te]
        test_pid = zpid[te]
        canon = test_pid == CANONICAL_PID

        candidates = {
            "r2_ensemble_multinomial": r2_pred["ensemble_equal"],
        }

        # Raw ensemble from independently trained logistic + GBDT.
        ecal = raw["ensemble"][0]
        etest = raw["ensemble"][1]

        for C in policy["meta_calibration_C"]:
            candidates[f"ensemble_meta_C{C:g}"] = meta_calibrate(
                ecal, etest, ycal, C
            )

        # Fixed shrinkage candidates.  No test-label fitting occurs.
        neutral = np.asarray([1/3, 1/3, 1/3, 0.0], dtype=float)
        cal_freq = (
            np.bincount(ycal, minlength=4).astype(float)
            + np.asarray([0.5, 0.5, 0.5, 0.05])
        )
        cal_freq /= cal_freq.sum()
        for a in policy["neutral_shrink_alpha"]:
            candidates[f"r2_neutral_shrink_{a:g}"] = shrink_to(
                r2_pred["ensemble_equal"], neutral, a
            )
        for a in policy["calibration_prior_shrink_alpha"]:
            candidates[f"r2_calprior_shrink_{a:g}"] = shrink_to(
                r2_pred["ensemble_equal"], cal_freq, a
            )

        fold = {
            "n": int(np.sum(te)),
            "calibration_n": int(np.sum(ca)),
            "canonical_n": int(np.sum(canon)),
            "canonical_ambiguous_fraction": float(np.mean(yt[canon] == 3)),
            "calibration_class_frequency": cal_freq.tolist(),
            "baseline": r1.metrics(base, yt, 4),
            "canonical_baseline": r1.metrics(base[canon], yt[canon], 4),
            "models": {},
        }
        for name, p in candidates.items():
            fold["models"][name] = r3.evaluate_candidate(
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


def passes(s, c, row, policy):
    og = policy["overall_zone_gate"]
    cg = policy["canonical_1sigma_gate"]
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
    out = {"heads": {}}

    # Preserve already-passing R2 selections exactly.
    for head, row in heads_1h_4h.items():
        name = "ensemble_equal"
        s = row["summary"][name]
        c = row["canonical_summary"][name]
        overall, canonical = passes(s, c, row, policy)
        out["heads"][head] = {
            "source": "UNCHANGED_R2",
            "selected": name if overall and canonical else None,
            "candidate": {
                "overall_pass": overall,
                "canonical_pass": canonical,
                "overall": s,
                "canonical_1sigma": c,
            },
        }

    candidates = {}
    for name in h24["summary"]:
        s = h24["summary"][name]
        c = h24["canonical_summary"][name]
        overall, canonical = passes(s, c, h24, policy)
        candidates[name] = {
            "overall_pass": overall,
            "canonical_pass": canonical,
            "pass": bool(overall and canonical),
            "overall": s,
            "canonical_1sigma": c,
        }

    eligible = [
        (
            candidates[name]["overall"]["mean_brier"]
            + candidates[name]["canonical_1sigma"]["mean_brier"],
            candidates[name]["canonical_1sigma"]["mean_ece10"],
            name,
        )
        for name in candidates if candidates[name]["pass"]
    ]
    eligible.sort()
    selected = eligible[0][2] if eligible else None
    out["heads"]["24h"] = {
        "source": "R4_FINAL_HISTORICAL_CALIBRATION",
        "selected": selected,
        "candidates": candidates,
    }

    out["all_heads_pass"] = all(
        x["selected"] is not None for x in out["heads"].values()
    )
    out["status"] = (
        "PREDICTIVE_CANDIDATE_READY_FOR_INDEPENDENT_REVIEW_AND_PROSPECTIVE_FREEZE"
        if out["all_heads_pass"]
        else "PREDICTIVE_REWORK_24H_NOT_HISTORICALLY_RESOLVED"
    )
    out["historical_selection_exhausted"] = True
    out["next_valid_model_selection_evidence"] = "CLEAN_PROSPECTIVE_EPOCH"
    out["prospective_skill_proven"] = False
    out["trading_authority"] = False
    return out


def main():
    heads = r2.build_15m()
    h24 = evaluate_24h()
    report = {
        "schema": "btc-predictive-vnext5r4-final-calibration-v1",
        "status": "RESEARCH_ONLY_NO_PRODUCTION_NO_TRADING_AUTHORITY",
        "parent_r3_source_sha":
            "5254de289bccc656d8e9464fd3f4cdeee61bf38b",
        "parent_engineering_source_sha":
            "34304b7650421dfd07d3c9e9b2f7f3c937b96ec1",
        "change_scope": (
            "24h probability calibration transforms only; "
            "1h/4h, targets, features, baselines and gates unchanged"
        ),
        "heads_r2_unchanged": {"1h": heads["1h"], "4h": heads["4h"]},
        "head_24h_r4": h24,
        "acceptance_policy": json.loads(POLICY_PATH.read_text()),
        "prospective_skill_proven": False,
        "trading_authority": False,
    }
    report["acceptance"] = acceptance(
        {"1h": heads["1h"], "4h": heads["4h"]}, h24
    )
    path = OUT / "predictive_research_r4_result.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report["acceptance"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
