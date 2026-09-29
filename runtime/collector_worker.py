"""GitHub Actions collector and public Sigstore evidence writer.

Only a pinned GitHub workflow may call this program. The branch is an
untrusted cache; every accepted event is independently verified with Cosign.
No probabilities or outcomes are accepted as workflow inputs.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

from frozen_inference import forecast, frozen_artifact

UTC = timezone.utc
RUNTIME = Path(__file__).resolve().parent
ROOT = RUNTIME.parent
EVENTS = ROOT / "events"
RAW = ROOT / "raw"
IDENTITY = "https://github.com/sergeytren1984-ux/neora-b2b-v2-clean/.github/workflows/btc-prospective-evidence.yml@refs/heads/main"
ISSUER = "https://token.actions.githubusercontent.com"
HOSTS = ("data-api.binance.vision", "api.binance.com", "api1.binance.com")
OPTIONAL_SOURCES = {
    "funding": "https://fapi.binance.com/fapi/v1/fundingRate?symbol=BTCUSDT&limit=2",
    "open_interest": "https://fapi.binance.com/fapi/v1/openInterest?symbol=BTCUSDT",
    "dxy": "https://www.investing.com/indices/usdollar",
    "nasdaq_futures": "https://www.investing.com/indices/nq-100-futures",
    "us10y": "https://www.cnbc.com/quotes/US10Y",
    "etf_flows": "https://farside.co.uk/btc/",
    "bls": "https://www.bls.gov/schedule/news_release/bls.ics",
    "ism": "https://www.ismworld.org/supply-management-news-and-reports/reports/ism-pmi-reports/",
    "treasury_tentative": "https://home.treasury.gov/system/files/221/Tentative-Auction-Schedule.xml",
}
PRECOMMITTED = {
    "frozen_v2930_candidate.json.gz": "577017d19e6a2c607c8d7fb77b4ddce35dd8e3fc9be98db85e700d8862784a35",
    "multi_horizon_features.py": "c15f264a73c5efb9ac6123b4c51b4c21d6bcfff0cd84261b8c7876e25221e006",
    "protocol.json": "399d2eb51108bf697f4ede4837bcf9768d39fb3acc07bd7ea25737727a2c7719",
    "schedule.json": "248d0a4a495f5f6438147c9de50df9eda572a9a7160d0b02e50d6ede88cb4dbd",
}


def canon(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def now():
    return datetime.now(UTC)


def ts(value):
    value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        raise ValueError("UTC timestamp required")
    return value.astimezone(UTC)


def run(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=90).stdout


def verify_frozen():
    for name, expected in PRECOMMITTED.items():
        data = (RUNTIME / name).read_bytes()
        if name.endswith(".gz"):
            data = gzip.decompress(data)
        if sha(data) != expected:
            raise ValueError("frozen file changed: " + name)
    if os.environ.get("GITHUB_REPOSITORY") != "sergeytren1984-ux/neora-b2b-v2-clean":
        raise ValueError("wrong GitHub Actions repository")
    if os.environ.get("GITHUB_REF") != "refs/heads/main":
        raise ValueError("wrong workflow ref")
    protocol = json.loads((RUNTIME / "protocol.json").read_bytes())
    if sha((RUNTIME / "frozen_inference.py").read_bytes()) != protocol["frozen_inference_code_sha256"]:
        raise ValueError("inference implementation changed")
    return protocol, json.loads((RUNTIME / "schedule.json").read_bytes())


def bundle_time(path):
    bundle = json.loads(path.read_bytes())
    entries = bundle.get("verificationMaterial", {}).get("tlogEntries", [])
    if not entries:
        raise ValueError("no public Rekor log entry")
    result = []
    for entry in entries:
        proof = entry.get("inclusionProof")
        if not isinstance(proof, dict) or not proof.get("checkpoint") or "hashes" not in proof:
            raise ValueError("no Rekor inclusion proof")
        result.append(datetime.fromtimestamp(int(entry["integratedTime"]), UTC))
    return min(result)


def verify_signed(path, bundle):
    run("cosign", "verify-blob", str(path), "--bundle", str(bundle),
        "--certificate-identity", IDENTITY, "--certificate-oidc-issuer", ISSUER)
    return bundle_time(bundle)


def evidence():
    seen = set()
    previous = None
    result = []
    for number, path in enumerate(sorted(p for p in EVENTS.glob("*.json") if p.stem.isdigit() and len(p.stem) == 8), 1):
        bundle = path.with_suffix(".sigstore.json")
        signed = verify_signed(path, bundle)
        obj = json.loads(path.read_bytes())
        if path.read_bytes() != canon(obj) + b"\n":
            raise ValueError("non-canonical event")
        if obj.get("sequence") != number or obj.get("previous_hash") != previous:
            raise ValueError("event chain fork or gap")
        key = obj.get("idempotency_key")
        if not isinstance(key, str) or key in seen:
            raise ValueError("event idempotency violation")
        if number == 1 and obj.get("type") != "SCHEDULE_REGISTERED":
            raise ValueError("no prior registered schedule")
        seen.add(key)
        previous = sha(path.read_bytes())
        result.append((obj, signed))
    return result


def publish(event, *, not_before=None, before=None, attachments=()):
    EVENTS.mkdir(exist_ok=True)
    prior = evidence()
    if event["type"] == "SCHEDULE_REGISTERED" and any(
        x[0]["idempotency_key"] == event["idempotency_key"] for x in prior
    ):
        raise ValueError("schedule already registered")
    event = {"schema": "btc-gh-rekor-event-v1", "sequence": len(prior) + 1,
             "previous_hash": sha(canon(prior[-1][0]) + b"\n") if prior else None,
             "workflow_commit": os.environ["GITHUB_SHA"], **event}
    if any(x[0]["idempotency_key"] == event["idempotency_key"] for x in prior):
        raise ValueError("duplicate event idempotency key")
    path = EVENTS / f"{event['sequence']:08d}.json"
    path.write_bytes(canon(event) + b"\n")
    bundle = path.with_suffix(".sigstore.json")
    run("cosign", "sign-blob", "--yes", "--bundle", str(bundle), str(path))
    integrated = verify_signed(path, bundle)
    if not_before and integrated < not_before:
        raise ValueError("Rekor time precedes due")
    if before and integrated >= before:
        raise ValueError("Rekor time is too late")
    for p in (path, bundle, *attachments):
        run("git", "add", str(Path(p).relative_to(ROOT)))
    run("git", "commit", "-m", f"BTC evidence #{event['sequence']}: {event['type']}")
    run("git", "push", "origin", "HEAD:btc-evidence")
    return event, integrated


def fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": "BTC-prospective-evidence/1.0"})
    with urllib.request.urlopen(request, timeout=12) as response:
        if response.status != 200 or response.url != url:
            raise ValueError("redirect or non-200 source response")
        data = response.read(2_000_001)
        if len(data) > 2_000_000:
            raise ValueError("raw response too large")
    return {"url": url, "retrieved_at_utc": now().isoformat(),
            "sha256": sha(data), "raw": data.decode("utf-8")}


def capture_klines(interval, limit):
    errors = []
    successes = []
    for host in HOSTS:
        url = f"https://{host}/api/v3/klines?symbol=BTCUSDT&interval={interval}&limit={limit}"
        for _ in range(2):
            try:
                row = fetch(url)
                parsed = json.loads(row["raw"])
                if not isinstance(parsed, list) or len(parsed) < limit - 2:
                    raise ValueError("incomplete kline history")
                successes.append((row, parsed))
                break
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                errors.append({"source": host, "error": str(exc)[:120]})
                time.sleep(0.3)
        if len(successes) == 2:
            break
    if not successes:
        raise RuntimeError("all official Binance kline transports failed: " + json.dumps(errors))
    if len(successes) == 2:
        # The only potentially mutable row is the current forming candle.
        a, b = successes[0][1], successes[1][1]
        common = {int(x[0]): x for x in a[:-1]}
        for row in b[:-1]:
            first = common.get(int(row[0]))
            if first is not None and first[:11] != row[:11]:
                raise ValueError("official Binance transports disagree on a closed candle")
        successes[0][0]["verification_response"] = successes[1][0]
    return successes[0]


def closed_candles(parsed, interval_seconds, anchor):
    candles = []
    for item in parsed:
        opened = datetime.fromtimestamp(int(item[0]) / 1000, UTC)
        closed = opened + timedelta(seconds=interval_seconds)
        if int(item[6]) != int(closed.timestamp() * 1000) - 1:
            raise ValueError("incorrect exchange candle close time")
        if closed <= anchor:
            candles.append({"open_time": opened.isoformat(), "close_time": closed.isoformat(),
                            "open": float(item[1]), "high": float(item[2]), "low": float(item[3]),
                            "close": float(item[4]), "volume": float(item[5]),
                            "trades": int(item[8]), "taker_buy_base": float(item[9])})
    for a, b in zip(candles, candles[1:]):
        if ts(b["open_time"]) - ts(a["open_time"]) != timedelta(seconds=interval_seconds):
            raise ValueError("noncontiguous closed history")
    if not candles or ts(candles[-1]["close_time"]) != anchor:
        raise ValueError("latest closed candle not at scheduled anchor")
    return candles


def slot_anchor(schedule):
    current = now()
    anchor = current.replace(minute=0, second=0, microsecond=0)
    start, end = ts(schedule["start_utc"]), ts(schedule["end_exclusive_utc"])
    if not start <= anchor < end:
        return None
    if current - anchor > timedelta(minutes=int(schedule["issuance_max_delay_minutes"])):
        return None
    return anchor


def bootstrap(protocol, schedule):
    if any(e["idempotency_key"] == schedule["id"] for e, _ in evidence()):
        return
    start = ts(schedule["start_utc"])
    if now() >= start:
        raise ValueError("cannot register schedule after first slot")
    frozen_artifact()
    publish({"type": "SCHEDULE_REGISTERED", "idempotency_key": schedule["id"],
             "protocol_sha256": sha((RUNTIME / "protocol.json").read_bytes()),
             "schedule_sha256": sha((RUNTIME / "schedule.json").read_bytes()),
             "frozen_v2930_sha256": protocol["frozen_v2930_artifact_sha256"],
             "workflow_identity": IDENTITY, "schedule_start_utc": schedule["start_utc"]},
            before=start)


def raw_capture(anchor):
    hrow, hparsed = capture_klines("1h", 200)
    qrow, qparsed = capture_klines("4h", 25)
    extra = {}
    with ThreadPoolExecutor(max_workers=9) as pool:
        futures = {pool.submit(fetch, url): name for name, url in OPTIONAL_SOURCES.items()}
        for future in as_completed(futures):
            name = futures[future]
            try:
                extra[name] = {"status": "RAW_CAPTURED_NOT_ADMITTED", **future.result()}
            except Exception as exc:
                extra[name] = {"status": "TRANSPORT_FAILED", "url": OPTIONAL_SOURCES[name],
                               "error": (type(exc).__name__ + ": " + str(exc))[:180]}
    h = closed_candles(hparsed, 3600, anchor)
    # Four-hour candles can close before the hourly anchor.
    q_anchor = anchor - timedelta(hours=anchor.hour % 4)
    q = closed_candles(qparsed, 14400, q_anchor)
    if len(h) < 169 or len(q) < 15:
        raise ValueError("insufficient closed history")
    return (hrow, qrow), (h[-169:], q[-15:]), extra


def run_slot(protocol, schedule, anchor):
    slot = anchor.strftime("%Y%m%dT%H%M%SZ")
    prior = evidence()
    if anchor.hour % 4:
        return
    if all(any(e["idempotency_key"] == "forecast:" + slot + ":" + h for e, _ in prior)
           for h in (("4h", "24h") if anchor.hour == 0 else ("4h",))):
        return
    RAW.mkdir(exist_ok=True)
    raw_path = RAW / (slot + ".json.gz")
    prior_raw = next((e for e, _ in prior if e["idempotency_key"] == "raw:" + slot), None)
    if prior_raw:
        raw_bytes = gzip.decompress(raw_path.read_bytes())
        if sha(raw_bytes) != prior_raw["raw_sha256"]:
            raise ValueError("raw receipt mismatch on recovery")
        persisted = json.loads(raw_bytes)
        rows = persisted["captures"]
        optional = persisted["optional_context"]
        h = closed_candles(json.loads(rows[0]["raw"]), 3600, anchor)[-169:]
        q = closed_candles(json.loads(rows[1]["raw"]), 14400, anchor)[-15:]
        candles = h, q
    else:
        rows, candles, optional = raw_capture(anchor)
        raw_bytes = canon({"schema": "btc-raw-bundle-v1", "anchor_utc": anchor.isoformat(),
                           "captures": rows, "optional_context": optional}) + b"\n"
        raw_path.write_bytes(gzip.compress(raw_bytes, mtime=0))
        publish({"type": "RAW_ATTESTED", "idempotency_key": "raw:" + slot,
                 "slot": slot, "raw_sha256": sha(raw_bytes),
                 "source_receipts": [{k: r[k] for k in ("url", "retrieved_at_utc", "sha256")} for r in rows]},
                before=anchor + timedelta(minutes=45), attachments=(raw_path,))
    probs = forecast(candles[0], now())
    reference = candles[0][-1]["close"]
    # The frozen target threshold uses the preceding 14 true-range 4h bars.
    q = candles[1]
    tr = []
    for previous, current in zip(q, q[1:]):
        prev = previous["close"]
        tr.append(max(current["high"] - current["low"], abs(current["high"] - prev), abs(current["low"] - prev)))
    atr = sum(tr) / 14
    prior = evidence()
    factor_id = "factors:" + slot
    if not any(e["idempotency_key"] == factor_id for e, _ in prior):
        publish({"type": "FACTORS_VALIDATED", "idempotency_key": factor_id,
                 "slot": slot, "raw_sha256": sha(raw_bytes),
                 "factors": {"closed_1h_klines": {"status": "VALID", "count": 169},
                             "closed_4h_klines": {"status": "VALID", "count": 15},
                             "optional_context": {k: {"status": v["status"],
                                  "sha256": v.get("sha256"), "url": v["url"]}
                                  for k, v in sorted(optional.items())},
                             "bls_event_status": "UNKNOWN_NOT_USED_BY_FROZEN_NUMERIC_CORE"}},
                before=anchor + timedelta(minutes=45))
    for horizon in ("4h", "24h"):
        if horizon == "4h" and anchor.hour % 4 or horizon == "24h" and anchor.hour:
            continue
        if any(e["idempotency_key"] == "forecast:" + slot + ":" + horizon for e, _ in evidence()):
            continue
        if probs[horizon]["probabilities"] is None:
            continue
        mult = 0.35 if horizon == "4h" else 1.0
        threshold = max(.05, min(6.0, mult * 100 * atr / reference))
        due = anchor + timedelta(hours=int(horizon[:-1]))
        state = latest_overlay_state(horizon)
        overlay = overlay_probs(probs[horizon]["probabilities"], state)
        publish({"type": "FORECAST_ISSUED", "idempotency_key": "forecast:" + slot + ":" + horizon,
                 "slot": slot, "horizon": horizon, "anchor_utc": anchor.isoformat(),
                 "due_utc": due.isoformat(), "reference_price": reference,
                 "threshold_pct": threshold, "base": probs[horizon]["probabilities"],
                 "overlay": overlay, "overlay_state_hash": sha(canon(state)),
                 "raw_sha256": sha(raw_bytes), "feature_hash": probs[horizon]["feature_hash"],
                 "model_sha256": protocol["frozen_v2930_artifact_sha256"],
                 "publication_authorized": False, "trading_authority": False},
                before=anchor + timedelta(minutes=45))


def latest_overlay_state(horizon):
    states = [e["learning"]["state"] for e, _ in evidence()
              if e["type"] == "OUTCOME_AND_LEARNING_APPLIED" and e["horizon"] == horizon]
    return states[-1] if states else {"horizon": horizon, "samples_seen": 0, "bias": [0.0, 0.0, 0.0]}


def overlay_probs(base, state):
    if state["samples_seen"] == 0:
        return base.copy()  # exact zero-overlay equivalence
    import math
    classes = ("upside", "range", "downside")
    logits = [math.log(float(base[k])) + state["bias"][i] for i, k in enumerate(classes)]
    mx = max(logits)
    exponentials = [math.exp(x - mx) for x in logits]
    total = sum(exponentials)
    return {k: exponentials[i] / total for i, k in enumerate(classes)}


def learning_update(forecast_event, actual):
    horizon = forecast_event["horizon"]
    state = latest_overlay_state(horizon)
    base = forecast_event["base"]
    pred = overlay_probs(base, state)
    classes = ("upside", "range", "downside")
    gradients = [pred[k] - float(k == actual) for k in classes]
    import math
    norm = math.sqrt(sum(x*x for x in gradients))
    scale = min(1.0, .08 / norm) if norm else 1.0
    lr = .025 if horizon == "4h" else .020
    updated = {"horizon": horizon, "samples_seen": state["samples_seen"] + 1,
               "bias": [max(-.75, min(.75, b - lr*scale*g)) for b, g in zip(state["bias"], gradients)]}
    return {"previous_state_hash": sha(canon(state)), "state": updated}


def due_close(due):
    start_ms = int((due - timedelta(hours=1)).timestamp() * 1000)
    end_ms = int(due.timestamp() * 1000) - 1
    errors = []
    for host in HOSTS:
        url = (f"https://{host}/api/v3/klines?symbol=BTCUSDT&interval=1h"
               f"&startTime={start_ms}&endTime={end_ms}&limit=1")
        try:
            row = fetch(url)
            data = json.loads(row["raw"])
            if len(data) != 1 or int(data[0][0]) != start_ms or int(data[0][6]) != end_ms:
                raise ValueError("paired due candle not closed")
            price = float(data[0][4])
            if not 0 < price < 1_000_000:
                raise ValueError("outcome close invalid")
            return row, price
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append({"source": host, "error": str(exc)[:120]})
    raise RuntimeError("no attested paired due close: " + json.dumps(errors))


def resolve_due():
    entries = evidence()
    issued = [e for e, _ in entries if e["type"] == "FORECAST_ISSUED"]
    for forecast_event in issued:
        due = ts(forecast_event["due_utc"])
        if due + timedelta(minutes=2) > now():
            continue
        key = forecast_event["slot"] + ":" + forecast_event["horizon"]
        outcome_event = next((e for e, _ in evidence() if e["idempotency_key"] == "outcome:" + key), None)
        if outcome_event is None:
            row, close = due_close(due)
            RAW.mkdir(exist_ok=True)
            raw_bytes = canon({"schema": "btc-due-close-v1", "paired_issuance_hash": sha(canon(forecast_event) + b"\n"),
                               "capture": row}) + b"\n"
            path = RAW / (key.replace(":", "-") + "-outcome.json.gz")
            path.write_bytes(gzip.compress(raw_bytes, mtime=0))
            realized = 100 * (close / float(forecast_event["reference_price"]) - 1)
            threshold = float(forecast_event["threshold_pct"])
            actual = "upside" if realized > threshold else "downside" if realized < -threshold else "range"
            learning = learning_update(forecast_event, actual)
            publish({"type": "OUTCOME_AND_LEARNING_APPLIED",
                "idempotency_key": "outcome:" + key, "slot": forecast_event["slot"],
                "horizon": forecast_event["horizon"], "due_utc": forecast_event["due_utc"],
                "paired_issuance_hash": sha(canon(forecast_event) + b"\n"), "close": close,
                "return_pct": realized, "threshold_pct": threshold, "class": actual,
                "raw_sha256": sha(raw_bytes), "source_url": row["url"],
                "learning": learning},
                not_before=due, attachments=(path,))


def mark_missed(schedule):
    start = ts(schedule["start_utc"])
    end = min(ts(schedule["end_exclusive_utc"]), now() - timedelta(minutes=46))
    point = start
    seen = {e["idempotency_key"] for e, _ in evidence()}
    while point < end:
        if point.hour % 4 == 0:
            slot = point.strftime("%Y%m%dT%H%M%SZ")
            for horizon in (("4h", "24h") if point.hour == 0 else ("4h",)):
                forecast_key = "forecast:" + slot + ":" + horizon
                missed_key = "missed:" + slot + ":" + horizon
                if forecast_key not in seen and missed_key not in seen:
                    publish({"type": "SLOT_MISSED", "idempotency_key": missed_key,
                             "slot": slot, "horizon": horizon,
                             "reason": "no valid timely signed forecast by issuance deadline"})
                    seen.add(missed_key)
        point += timedelta(hours=1)


def main():
    protocol, schedule = verify_frozen()
    before = evidence()
    current = next((e for e, _ in before if e["idempotency_key"] == schedule["id"]), None)
    if current is None:
        bootstrap(protocol, schedule)
        return
    if (current["workflow_commit"] != os.environ["GITHUB_SHA"] or
        current["protocol_sha256"] != sha((RUNTIME / "protocol.json").read_bytes()) or
        current["schedule_sha256"] != sha((RUNTIME / "schedule.json").read_bytes())):
        raise ValueError("frozen workflow/protocol/schedule changed")
    resolve_due()
    mark_missed(schedule)
    anchor = slot_anchor(schedule)
    if anchor is not None:
        run_slot(protocol, schedule, anchor)


if __name__ == "__main__":
    main()
