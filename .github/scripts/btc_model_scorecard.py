"""Signed-source, outcome-gated diagnostic scorecard for BTC shadow heads."""
from __future__ import annotations

import base64
import datetime as dt
import gzip
import hashlib
import json
import math
import os
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

UTC = dt.timezone.utc
MSK = ZoneInfo("Europe/Moscow")
REPO = "sergeytren1984-ux/neora-b2b-v2-clean"
ISSUER = "https://token.actions.githubusercontent.com"
SOURCES = {
    "v5": ("btc-evidence-v5", "events", "btc-prospective-evidence-v5.yml"),
    "regime": ("btc-regime-v4-hardened", "regime_v4_events", "btc-regime-v4-hardened.yml"),
    "up": ("btc-directional-v1", "directional_v1_events", "btc-directional-v1.yml"),
    "down": ("btc-directional-down-v1", "directional_down_v1_events", "btc-directional-down-v1.yml"),
    "arbiter": ("btc-arbitration-v3", "arbiter_v3_events", "btc-arbitration-v3.yml"),
    "arbiter_v4": ("btc-arbitration-v4", "arbiter_v4_events", "btc-arbitration-v4.yml"),
    "barrier": ("btc-first-passage-v1", "first_passage_v1_events", "btc-first-passage-v1.yml"),
}


def command(*args: str) -> bytes:
    return subprocess.run(args, check=True, capture_output=True, timeout=120).stdout


def get(ref: str, path: str) -> bytes:
    return command("git", "show", ref + ":" + path)


def digest(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def stamp(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def verify(blob: bytes, bundle: bytes, identity: str) -> dt.datetime:
    record = json.loads(bundle)
    entries = record.get("verificationMaterial", {}).get("tlogEntries", [])
    if not entries or not all(e.get("inclusionProof", {}).get("checkpoint") for e in entries):
        raise ValueError("missing Rekor inclusion proof")
    with tempfile.TemporaryDirectory() as tmp:
        a = Path(tmp) / "event.json"
        b = Path(tmp) / "event.sigstore.json"
        a.write_bytes(blob)
        b.write_bytes(bundle)
        command("cosign", "verify-blob", str(a), "--bundle", str(b),
                "--certificate-identity", identity,
                "--certificate-oidc-issuer", ISSUER)
    return min(dt.datetime.fromtimestamp(int(e["integratedTime"]), UTC) for e in entries)


def signed_events(source: str) -> list[dict]:
    branch, directory, workflow = SOURCES[source]
    ref = "refs/remotes/origin/" + branch
    command("git", "fetch", "--quiet", "origin",
            "+refs/heads/" + branch + ":" + ref)
    paths = command("git", "ls-tree", "-r", "--name-only", ref, directory).decode().splitlines()
    files = sorted(p for p in paths if len(p.rsplit("/", 1)[-1]) == 13
                   and p.rsplit("/", 1)[-1][:8].isdigit() and p.endswith(".json"))
    identity = f"https://github.com/{REPO}/.github/workflows/{workflow}@refs/heads/main"
    out = []
    previous_hash = None
    seen = set()
    for n, path in enumerate(files, 1):
        blob = get(ref, path)
        event = json.loads(blob)
        canonical = (json.dumps(event, sort_keys=True, separators=(",", ":"),
                                ensure_ascii=False, allow_nan=False) + "\n").encode()
        if blob != canonical or event["sequence"] != n or event.get("previous_hash") != previous_hash:
            raise ValueError(f"{source}: broken chain at {path}")
        key = event["idempotency_key"]
        if key in seen:
            raise ValueError(f"{source}: duplicate key {key}")
        seen.add(key)
        integrated = verify(blob, get(ref, path[:-5] + ".sigstore.json"), identity)
        if event.get("type") in ("FORECAST_ISSUED", "REGIME_FORECAST_ISSUED",
                                  "DIRECTIONAL_4H_ALERT_ISSUED",
                                  "DIRECTIONAL_4H_DOWNSIDE_ALERT_ISSUED",
                                  "ARBITRATION_DECISION_ISSUED", "BARRIER_QUESTION_ISSUED"):
            anchor = stamp(event["anchor_utc"])
            if not anchor <= integrated < anchor + dt.timedelta(minutes=45):
                raise ValueError(f"{source}: nonprospective forecast {path}")
        if event.get("type") in ("OUTCOME_AND_LEARNING_APPLIED", "REGIME_OUTCOME_RECORDED",
                                  "OUTCOME_RECORDED", "ARBITRATION_OUTCOME_RECORDED") or (
                                      source == "barrier" and event.get("type") == "BARRIER_OUTCOME_RECORDED"):
            if not event.get("due_utc"):
                raise ValueError(f"{source}: outcome due_utc missing in {path}")
            if integrated < stamp(event["due_utc"]):
                raise ValueError(f"{source}: early outcome {path}")
        if source == "regime" and event.get("type") == "BARRIER_OUTCOME_RECORDED":
            touch = event.get("outcome", {}).get("first_touch_time_utc")
            earliest = touch or event["spec"]["deadline_utc"]
            if integrated < stamp(earliest):
                raise ValueError(f"{source}: barrier outcome before observable touch/deadline {path}")
        if source == "barrier" and event.get("raw_path"):
            if digest(get(ref,event["raw_path"])) != event["raw_sha256"]:
                raise ValueError(f"{source}: raw mismatch {path}")
        event["_source_path"] = f"https://github.com/{REPO}/blob/{branch}/{path}"
        event["_rekor_integrated_utc"] = integrated.isoformat()
        out.append(event)
        previous_hash = digest(blob)
    return out


def audit_oi_source_consistency(regime_events: list[dict], now: dt.datetime) -> dict:
    ref = "refs/remotes/origin/btc-context"
    command("git", "fetch", "--quiet", "origin", "+refs/heads/btc-context:" + ref)
    checked = 0
    mismatches = []
    for event in regime_events:
        if event["type"] != "REGIME_FORECAST_ISSUED":
            continue
        if stamp(event["anchor_utc"]) < now - dt.timedelta(hours=72):
            continue
        names = event["context_snapshots"]
        proofs = event["context_proofs"]
        factors = []
        for name, role in zip(names, ("current", "previous")):
            blob = get(ref, "context_live/" + name)
            if digest(blob) != proofs[role]["snapshot_sha256"]:
                raise ValueError("signed regime context snapshot changed: " + name)
            factors.append(json.loads(blob)["factors"]["open_interest"])
        checked += 1
        sources = [f.get("source") for f in factors]
        if sources[0] != sources[1] and "open_interest" in event["output"]["external"]["used_factors"]:
            mismatches.append({"slot": event["slot"], "sources": sources,
                               "defect": "CROSS_EXCHANGE_OI_NUMERIC_CHANGE"})
    return {"checked_recent_forecasts": checked, "window_hours": 72,
            "numeric_cross_exchange_defects": mismatches}


def brier(prob: dict, truth: str) -> float:
    return sum((float(prob[k]) - (k == truth)) ** 2 for k in ("upside", "range", "downside"))


def loss(prob: dict, truth: str) -> float:
    return -math.log(max(1e-12, float(prob[truth])))


def binary_score(p: float, truth: bool) -> dict:
    p = max(1e-9, min(1 - 1e-9, float(p)))
    return {"brier": round((p - int(truth)) ** 2, 6),
            "log_loss": round(-math.log(p if truth else 1 - p), 6)}


def constant_baseline_comparison(rows: list[dict], head: str, prior: float) -> dict:
    closed = [r[head] for r in rows if r[head]["actual"] is not None
              and r[head]["score_diagnostic"] is not None]
    if not closed:
        return {"n": 0, "positive_events": 0, "constant": prior,
                "model_brier": None, "baseline_brier": None,
                "model_log_loss": None, "baseline_log_loss": None}
    return {"n": len(closed), "positive_events": sum(bool(r["actual"]) for r in closed),
            "constant": prior,
            "model_brier": round(sum(r["score_diagnostic"]["brier"] for r in closed)/len(closed), 6),
            "baseline_brier": round(sum(binary_score(prior, r["actual"])["brier"]
                                         for r in closed)/len(closed), 6),
            "model_log_loss": round(sum(r["score_diagnostic"]["log_loss"]
                                        for r in closed)/len(closed), 6),
            "baseline_log_loss": round(sum(binary_score(prior, r["actual"])["log_loss"]
                                           for r in closed)/len(closed), 6)}


def episodes(rows: list[dict], head: str) -> dict:
    finished = [r for r in rows if r.get(head, {}).get("actual") is not None]
    blocks = []
    current = []
    for row in finished:
        if row[head]["actual"] and (not current or stamp(row["slot_utc"]) -
                                      stamp(current[-1]["slot_utc"]) == dt.timedelta(hours=1)):
            current.append(row)
        else:
            if current:
                blocks.append(current)
            current = [row] if row[head]["actual"] else []
    if current:
        blocks.append(current)
    delays = []
    for block in blocks:
        alerts = [i for i, row in enumerate(block) if row[head]["alert"]]
        delays.append(alerts[0] if alerts else None)
    return {"positive_episodes": len(blocks), "detection_delays_hours": delays,
            "missed_episodes": sum(x is None for x in delays)}


def confusion(rows: list[dict], head: str) -> dict:
    counts = {k: 0 for k in ("TP", "FP", "FN", "TN")}
    for row in rows:
        x = row[head]
        if x["alert"] is None or x["actual"] is None:
            continue
        counts[("T" if x["alert"] == x["actual"] else "F") +
               ("P" if x["alert"] else "N")] += 1
    counts["closed_pairs"] = sum(counts.values())
    counts["precision"] = (counts["TP"] / (counts["TP"] + counts["FP"])
                           if counts["TP"] + counts["FP"] else None)
    counts["recall"] = (counts["TP"] / (counts["TP"] + counts["FN"])
                        if counts["TP"] + counts["FN"] else None)
    return counts


def audit_v5(events: list[dict], now: dt.datetime) -> dict:
    """Check the frozen epoch-5 cadence and concrete raw/factor linkage."""
    by_key = {e["idempotency_key"]: e for e in events}
    ref = "refs/remotes/origin/btc-evidence-v5"
    defects = []
    issued = 0
    checked_raw = set()
    start = stamp("2026-09-30T20:00:00Z")
    anchor = start
    while anchor + dt.timedelta(minutes=45) <= now:
        slot = anchor.strftime("%Y%m%dT%H%M%SZ")
        if anchor.hour % 4 == 0:
            horizons = ("4h", "24h") if anchor.hour == 0 else ("4h",)
            raw = by_key.get("raw:" + slot)
            factors = by_key.get("factors:" + slot)
            for horizon in horizons:
                key = f"forecast:{slot}:{horizon}"
                forecast = by_key.get(key)
                missed = by_key.get(f"missed:{slot}:{horizon}")
                if forecast is None:
                    defects.append({"slot": slot, "horizon": horizon,
                                    "defect": "NO_FORECAST" if missed is None else "SLOT_MISSED"})
                    continue
                issued += 1
                if forecast["type"] != "FORECAST_ISSUED" or forecast.get("base") is None:
                    defects.append({"slot": slot, "horizon": horizon, "defect": "NO_PROBABILITIES"})
                if forecast.get("model_status") == "DEGRADED_CLIPPED_DRIFT":
                    continuity = forecast.get("continuity") or {}
                    if (continuity.get("primary_status") != "ABSTAIN_MODEL_DRIFT" or
                            not continuity.get("clipped_features")):
                        defects.append({"slot": slot, "horizon": horizon,
                                        "defect": "DRIFT_CONTINUITY_INVALID"})
                if raw is None or factors is None or any(
                        x.get("raw_sha256") != forecast.get("raw_sha256") for x in (raw, factors)):
                    defects.append({"slot": slot, "horizon": horizon,
                                    "defect": "RAW_FACTORS_LINK_INVALID"})
            if raw is not None and slot not in checked_raw:
                checked_raw.add(slot)
                try:
                    plain = gzip.decompress(get(ref, "raw/" + slot + ".json.gz"))
                    if digest(plain) != raw["raw_sha256"]:
                        raise ValueError("raw digest mismatch")
                    bundle = json.loads(plain)
                    receipts = raw["source_receipts"]
                    if (bundle["anchor_utc"] != anchor.isoformat() or
                            len(bundle["captures"]) != len(receipts)):
                        raise ValueError("raw bundle slot/receipt mismatch")
                    for capture, receipt in zip(bundle["captures"], receipts):
                        if (digest(capture["raw"].encode()) != capture["sha256"] or
                                {k: capture[k] for k in ("url", "retrieved_at_utc", "sha256")} != receipt or
                                not anchor <= stamp(capture["retrieved_at_utc"]) <
                                anchor + dt.timedelta(minutes=45)):
                            raise ValueError("raw capture receipt invalid")
                except (subprocess.CalledProcessError, OSError, ValueError, KeyError, TypeError):
                    defects.append({"slot": slot, "defect": "RAW_BUNDLE_INVALID"})
        anchor += dt.timedelta(hours=1)
    return {"start_utc": start.isoformat(), "deadline_minutes": 45,
            "forecasts_issued": issued, "raw_bundles_checked": len(checked_raw),
            "defects": defects}


def build() -> tuple[dict, str]:
    streams = {name: signed_events(name) for name in SOURCES}
    by_type = {name: {e["idempotency_key"]: e for e in events}
               for name, events in streams.items()}
    since = stamp("2026-10-02T22:00:00Z")
    now = dt.datetime.now(UTC)
    rows = []
    point = since
    while point <= now.replace(minute=0, second=0, microsecond=0):
        slot = point.strftime("%Y%m%dT%H%M%SZ")
        slot_time = point.isoformat()
        row = {"slot_utc": slot_time, "slot_msk": point.astimezone(MSK).isoformat(),
               "due_4h_utc": (point + dt.timedelta(hours=4)).isoformat()}
        f = by_type["v5"].get("forecast:" + slot + ":4h")
        fo = by_type["v5"].get("outcome:" + slot + ":4h")
        fm = by_type["v5"].get("missed:" + slot + ":4h")
        if point.hour % 4 == 0:
            row["v2_9_30"] = {"status": f["model_status"] if f else
                             "SLOT_MISSED" if fm else "PENDING",
                             "probabilities_diagnostic": f["base"] if f else None,
                             "actual_native_class": fo["class"] if fo else None,
                             "score": {"brier": round(brier(f["base"], fo["class"]), 6),
                                       "log_loss": round(loss(f["base"], fo["class"]), 6)}
                             if f and fo else None}
        rf = by_type["regime"].get("regime:" + slot)
        ra = by_type["regime"].get("abstain-data:" + slot)
        rm = by_type["regime"].get("missed:" + slot)
        ro = by_type["regime"].get("outcome:" + slot + ":4h")
        r4 = rf.get("output", {}).get("horizons", {}).get("4h") if rf else None
        row["regime_v4"] = {"state": r4.get("regime_state") if r4 else None,
                            "source_status": "ISSUED" if rf else "ABSTAIN_DATA_INVALID" if ra else
                            "SLOT_MISSED" if rm else "PENDING",
                            "missing_reason": ra.get("reason") if ra else rm.get("reason") if rm else None,
                            "shadow_scores_uncalibrated": r4.get("shadow_class_scores") if r4 else None,
                            "actual_native_class": ro.get("class") if ro else None,
                            "shadow_brier_diagnostic_only": ro.get("shadow_brier_diagnostic_only") if ro else None,
                            "shadow_log_loss_diagnostic_only": round(loss(
                                r4["shadow_class_scores"], ro["class"]), 6) if r4 and ro else None,
                            "calibrated_brier": None}
        for name, prefix in (("up", "alert:"), ("down", "down-alert:")):
            e = by_type[name].get(prefix + slot)
            o = by_type[name].get(("outcome:" if name == "up" else "down-outcome:") + slot)
            m = by_type[name].get(("missed:" if name == "up" else "down-missed:") + slot)
            actual = o.get("actual_rise_gt_1pct" if name == "up" else
                           "actual_fall_lt_minus_1pct") if o else None
            row[name] = {"status": "ISSUED" if e else "SLOT_MISSED" if m else "PENDING",
                         "candidate_estimate_unproven": e["output"]["candidate_estimate"] if e else None,
                         "rank_30d": e["output"]["rank_30d"] if e else None,
                         "alert": e["output"]["alert"] if e else None,
                         "actual": actual,
                         "score_diagnostic": binary_score(e["output"]["candidate_estimate"], actual)
                         if e and o else None}
        arbiter_stream = "arbiter_v4" if point >= stamp("2026-10-03T09:00:00Z") else "arbiter"
        a = by_type[arbiter_stream].get("decision:" + slot + ":4h")
        ao = by_type[arbiter_stream].get("outcome:" + slot + ":4h")
        am = by_type[arbiter_stream].get("missed:" + slot)
        invalid = by_type[arbiter_stream].get("invalid:" + slot)
        arb_status = (a.get("status") if a else "SOURCE_INVALID" if invalid else
                      "SLOT_MISSED" if am else "UNRECORDED_MISS" if
                      point + dt.timedelta(minutes=45) <= now else "PENDING")
        row["regime_v4"]["used_by_arbiter_at_decision"] = (
            bool(a.get("sources", {}).get("regime")) if a and arbiter_stream == "arbiter_v4"
            else None)
        row["arbiter"] = {"status": arb_status,
                          "signed_sources": {name: bool(a.get("sources", {}).get(name))
                                             for name in ("directional", "downside", "regime")}
                          if a and arbiter_stream == "arbiter_v4" else None,
                          "reason": a.get("reason") if a else invalid.get("reason") if invalid else
                          am.get("reason") if am else None,
                          "action_status": a.get("action_status") if a else None,
                          "actual_rise_gt_1pct": ao.get("actual_rise_gt_1pct") if ao else None,
                          "actual_fall_lt_minus_1pct": ao.get("actual_fall_lt_minus_1pct") if ao else None,
                          "source_epoch": arbiter_stream,
                          "slot_missed": am is not None or arb_status == "UNRECORDED_MISS",
                          "trading_authority": False}
        if point.hour == 14 and point >= stamp("2026-10-03T14:00:00Z"):
            row["first_passage"] = {}
            for scenario in ("entry_72h", "entry_7d"):
                question = by_type["barrier"].get(f"barrier:{slot}:{scenario}")
                outcome = by_type["barrier"].get(f"barrier-outcome:{slot}:{scenario}")
                missing = by_type["barrier"].get(f"barrier-missed:{slot}:{scenario}")
                ineligible = by_type["barrier"].get(f"barrier-ineligible:{slot}:{scenario}")
                row["first_passage"][scenario] = {
                    "status": "ISSUED" if question else "INELIGIBLE" if ineligible else
                              "SLOT_MISSED" if missing else "UNRECORDED_MISS" if
                              point + dt.timedelta(minutes=45) <= now else "PENDING",
                    "reference_price": question.get("reference_price") if question else None,
                    "lower_usdt": question.get("lower_usdt") if question else None,
                    "upper_usdt": question.get("upper_usdt") if question else None,
                    "due_utc": question.get("due_utc") if question else None,
                    "outcome": outcome.get("outcome") if outcome else None,
                    "probability": None}
        rows.append(row)
        point += dt.timedelta(hours=1)
    counts = {name: {kind: sum(e["type"] == kind for e in events)
                     for kind in sorted({e["type"] for e in events})}
              for name, events in streams.items()}
    regime_closed = {h: sum(e.get("type") == "REGIME_OUTCOME_RECORDED" and
                            e.get("horizon") == h for e in streams["regime"])
                     for h in ("1h", "4h", "24h")}
    calibration_gate = {"status": "PENDING_NOT_CALIBRATED",
                        "closed_outcomes": regime_closed,
                        "preregistered_minimum": {"1h": 500, "4h": 250, "24h": 120},
                        "also_requires": "30 separate up and down episodes each; paired Brier and Log Loss gain with positive 95% weekly block bootstrap bound; future calibration/reliability test"}
    due_v4 = [r for r in rows if r["arbiter"]["source_epoch"] == "arbiter_v4" and
              stamp(r["slot_utc"]) + dt.timedelta(minutes=45) <= now]
    continuity = {"assessed_slots": len(due_v4),
                  "decisions": sum(r["arbiter"]["status"] not in
                                   ("SLOT_MISSED", "UNRECORDED_MISS", "SOURCE_INVALID") for r in due_v4),
                  "source_fallbacks": [{"slot_msk": r["slot_msk"],
                                        "status": r["arbiter"]["status"],
                                        "reason": r["regime_v4"]["missing_reason"] or
                                                  r["arbiter"]["reason"],
                                        "missing_sources": [name for name, used in
                                                            (r["arbiter"]["signed_sources"] or {}).items()
                                                            if not used]}
                                       for r in due_v4 if r["arbiter"]["signed_sources"] and
                                       not all(r["arbiter"]["signed_sources"].values())],
                  "unrecorded_misses": [r["slot_msk"] for r in due_v4 if
                                        r["arbiter"]["status"] == "UNRECORDED_MISS"],
                  "signed_slot_misses": [r["slot_msk"] for r in due_v4 if
                                        r["arbiter"]["status"] == "SLOT_MISSED"]}
    oi_audit = audit_oi_source_consistency(streams["regime"], now)
    baseline = json.loads(Path("btc_research/constant_tail_baseline_v1.json").read_bytes())
    comparison = {"status": "POST_START_DESCRIPTIVE_ONLY_NO_UNTOUCHED_PROOF",
                  "source_uncompressed_sha256": baseline["source_uncompressed_sha256"],
                  "training_anchors": baseline["training_anchors"],
                  "up": constant_baseline_comparison(rows, "up", baseline["up_constant"]),
                  "down": constant_baseline_comparison(rows, "down", baseline["down_constant"])}
    out = {"schema": "btc-signed-diagnostic-scorecard-v1",
           "constant_baseline_comparison": comparison,
           "external_oi_source_audit": oi_audit,
           "generated_at_utc": now.isoformat(), "source_event_counts": counts,
           "arbiter_v4_continuity": continuity,
           "epoch_5_e2e_audit": audit_v5(streams["v5"], now),
           "event_definitions_differ": True,
           "regime_scores_are_not_calibrated_probabilities": True,
           "downside_admitted_to_arbiter_from_utc": "2026-10-03T09:00:00Z",
           "regime_calibration_gate": calibration_gate,
           "transition_delay_up": episodes(rows, "up"),
           "transition_delay_down": episodes(rows, "down"),
           "prospective_confusion_up": confusion(rows, "up"),
           "prospective_confusion_down": confusion(rows, "down"),
           "rows": rows}
    names = {"UP_TRANSITION": "переход к росту", "UP_CONTINUATION": "рост",
             "UP_EXHAUSTION": "ослабление роста", "FALSE_BREAKOUT_UP": "ложный пробой вверх",
             "DOWN_TRANSITION": "переход к снижению", "DOWN_CONTINUATION": "снижение",
             "DOWN_EXHAUSTION": "ослабление снижения", "FALSE_BREAKOUT_DOWN": "ложный пробой вниз",
             "RANGE": "диапазон", "NO_DIRECTIONAL_TAIL_WARNING": "нет сигнала роста",
             "UP_REGIME_UNCONFIRMED": "рост режима без подтверждения",
             "DOWNSIDE_REGIME_UNVALIDATED": "снижение режима без независимой проверки",
             "UPSIDE_TAIL_RISK_CONCORDANT": "повышен риск роста; согласие",
             "UPSIDE_TAIL_RISK_WITH_REGIME_DISAGREEMENT": "повышен риск роста; расхождение",
             "UPSIDE_TAIL_RISK_REGIME_UNAVAILABLE": "риск роста; режим недоступен",
             "BIDIRECTIONAL_TAIL_RISK_CONFLICT": "конфликт хвостовых сигналов",
             "DOWNSIDE_TAIL_RISK_CONCORDANT": "повышен риск падения; согласие",
             "DOWNSIDE_TAIL_RISK_WITH_REGIME_DISAGREEMENT": "повышен риск падения; расхождение",
             "DOWNSIDE_TAIL_RISK_REGIME_UNAVAILABLE": "риск падения; режим недоступен",
             "NO_UPSIDE_TAIL_WARNING_REGIME_UNAVAILABLE": "нет сигнала роста; режим недоступен",
             "UPSIDE_TAIL_RISK_DOWN_HEAD_UNAVAILABLE": "риск роста; голова падения недоступна",
             "DOWN_HEAD_UNAVAILABLE_NO_DIRECTIONAL_CONCLUSION": "голова падения недоступна",
             "PENDING": "ожидание", "PENDING_OR_MISSED": "ожидание или пропуск",
             "SLOT_MISSED": "пропуск", "UNRECORDED_MISS": "пропуск без события",
             "SOURCE_INVALID": "источник недействителен",
             "upside": "рост", "downside": "снижение", "range": "диапазон"}
    lines = ["# BTC: подписанная сравнительная таблица (теневой режим)", "",
             "Обновлено: " + now.astimezone(MSK).strftime("%d.%m.%Y %H:%M МСК") + ".",
             (f"Арбитр v4: {continuity['decisions']}/{continuity['assessed_slots']} решений к дедлайну; "
              f"необъяснённых пропусков {len(continuity['unrecorded_misses'])}; "
              f"пропусков с событием {len(continuity['signed_slot_misses'])}; "
              f"неполных источников {len(continuity['source_fallbacks'])}."),
             "В колонке v4 указаны некалиброванные баллы. Brier v4 — только диагностика;",
             "события v5 и v4 используют собственные определения классов, их оценки нельзя",
             "считать прямым сравнением качества без общей метки. Исходы появляются после наступления срока.", "",
             "В v2.9.30 порядок чисел: рост / диапазон / снижение. В метриках: Brier / Log Loss.", "",
             ("Постоянная база из 2024–2025 введена после старта наблюдений: сравнительные "
              "метрики описательные, не зачётная проверка преимущества. "
              f"Закрытых пар рост/падение: {comparison['up']['n']}/{comparison['down']['n']}; "
              f"положительных: {comparison['up']['positive_events']}/{comparison['down']['positive_events']}."),
             (f"OI: сверено {oi_audit['checked_recent_forecasts']} подписанных прогнозов за 72 ч; "
              f"межбиржевых численных сравнений {len(oi_audit['numeric_cross_exchange_defects'])}."), "",
             "| Якорь МСК | v2.9.30 4ч | v4 режим | Рост >1% | Падение <−1% | Арбитр | Исходы | Метрики после срока |",
             "|---|---|---|---|---|---|---|---|"]
    for r in rows[-72:]:
        t = stamp(r["slot_msk"]).strftime("%d.%m %H:%M")
        v = r.get("v2_9_30", {})
        vp = v.get("probabilities_diagnostic")
        vtxt = ("/".join(f"{vp[k]:.3f}" for k in ("upside", "range", "downside"))
                if vp else names.get(v.get("status"), "—"))
        reg = names.get(r["regime_v4"]["state"], "—")
        if r["regime_v4"]["used_by_arbiter_at_decision"] is False and r["regime_v4"]["state"] is not None:
            reg += " (после решения арбитра)"
        if r["regime_v4"]["state"] is None and r["regime_v4"]["missing_reason"]:
            reason = r["regime_v4"]["missing_reason"]
            reg = ("нет OI предыдущего снимка" if "open_interest:previous" in reason
                   else "нет режима: " + names.get(r["regime_v4"]["source_status"], "данные недействительны"))
        def signal(name):
            x = r[name]
            return (f"ранг 30д {x['rank_30d']:.3f} / " +
                    ("тревога" if x["alert"] else "нет") if x["alert"] is not None
                    else names.get(x["status"], x["status"]))
        actuals = []
        for name in ("up", "down"):
            actual = r[name]["actual"]
            if actual is not None:
                actuals.append(("↑" if name == "up" else "↓") + ("да" if actual else "нет"))
        if v.get("actual_native_class"):
            actuals.append("v5:" + names[v["actual_native_class"]])
        metric = []
        if v.get("score"):
            metric.append("v5 " + f"{v['score']['brier']:.3f}/{v['score']['log_loss']:.3f}")
        shadow = r["regime_v4"]
        if shadow["shadow_brier_diagnostic_only"] is not None:
            metric.append("v4 тень " + f"{shadow['shadow_brier_diagnostic_only']:.3f}/" +
                          f"{shadow['shadow_log_loss_diagnostic_only']:.3f}")
        for name, label in (("up", "↑"), ("down", "↓")):
            s = r[name]["score_diagnostic"]
            if s:
                metric.append(label + " " + f"{s['brier']:.3f}/{s['log_loss']:.3f}")
        lines.append("| " + " | ".join((t, vtxt, reg, signal("up"), signal("down"),
                                          ("ПРОПУСК" if r["arbiter"]["slot_missed"] else
                                           names.get(r["arbiter"]["status"], "без статуса")),
                                          ", ".join(actuals) or "ожидание",
                                          "; ".join(metric) or "ожидание")) + " |")
    lines += ["", "## Окно возврата ядра: фиксированные барьеры", "",
              "С 17:00 МСК 03.10.2026 подписываются два ежедневных вопроса: 82 500 раньше 87 000 за 72 ч;",
              "81 500 раньше 88 000 за 7 суток. Классы: нижний первым, верхний первым, ни один,",
              "оба в одном часовом баре. Вероятности для торговли не опубликованы.", ""]
    for r in rows[-72:]:
        for key, title in (("entry_72h", "72 ч"), ("entry_7d", "7 суток")):
            b = r.get("first_passage", {}).get(key)
            if b:
                barrier_names = {"ISSUED": "вопрос подписан", "INELIGIBLE": "вне фиксированных границ",
                                 "SLOT_MISSED": "слот пропущен", "UNRECORDED_MISS": "нет события к дедлайну",
                                 "PENDING": "ожидание"}
                outcome_names = {"lower_first": "нижняя граница первой",
                                 "upper_first": "верхняя граница первой",
                                 "neither": "ни одна граница", "ambiguous": "обе в одном часовом баре"}
                lines.append(f"- {stamp(r['slot_msk']).strftime('%d.%m %H:%M')} МСК, {title}: "
                             f"{barrier_names.get(b['status'], b['status'])}; "
                             f"исход: {outcome_names.get(b['outcome'], 'после срока')}.")
    lines += ["", "Численные Brier и Log Loss по каждому завершённому исходу, пропуски и задержки",
              "доступны в `latest.json`. Вероятности класса v4 не опубликованы."]
    return out, "\n".join(lines) + "\n"


def publish(path: str, contents: bytes) -> None:
    repo = os.environ["GITHUB_REPOSITORY"]
    headers = {"Authorization": "Bearer " + os.environ["GH_TOKEN"],
               "Accept": "application/vnd.github+json",
               "User-Agent": "btc-signed-diagnostic-scorecard"}
    url = f"https://api.github.com/repos/{repo}/contents/{path}"
    sha = None
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=25) as result:
            sha = json.load(result)["sha"]
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise
    body = {"message": "Update BTC signed prospective diagnostic scorecard",
            "branch": "main", "content": base64.b64encode(contents).decode()}
    if sha:
        body["sha"] = sha
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="PUT")
    with urllib.request.urlopen(req, timeout=25) as result:
        if result.status not in (200, 201):
            raise RuntimeError("scorecard publication failed")


if __name__ == "__main__":
    data, markdown = build()
    publish("btc_scorecard/latest.json", (json.dumps(data, sort_keys=True, indent=2,
                                                        ensure_ascii=False) + "\n").encode())
    publish("btc_scorecard/latest.md", markdown.encode())
    print("SCORECARD_UPDATED", len(data["rows"]), data["generated_at_utc"])
