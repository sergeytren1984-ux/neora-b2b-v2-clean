"""BTC v7R3: stateful, causal demand/positioning *experimental* pressure detector.

This is deliberately NOT a calibrated likelihood of price increase. For each
new *signed* as-of observation, update a two-sided decaying CUSUM. The previous
version reset the CUSUM every tick and accidentally made it a current-candle
threshold rather than a sequential detector.

Technical contract:
  - only prior retrieved observations may train the robust reference;
  - no vendor observation after its independently timestamped HTTP response;
  - baseline excludes the current observation;
  - no numeric substitution for absent OI/book;
  - only upstream order-flow/OI/book determine pressure;
  - price movement is a LATE-warning veto, not a directional feature;
  - every reading and state transition can be replayed from signed records;
  - alerts have a deterministic cooldown, with uncalibrated status;
  - price points/OTC advice are NOT derived from this detector.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from statistics import median
import hashlib
import json
import math

UTC = timezone.utc
SCHEMA = "btc-v7r3-causal-pressure-state-v1"
BASELINE_COUNT = 32
CADENCE_MINUTES = 15
GAP_MAX_MINUTES = 22
DRIFT = 0.55
DECAY = 0.94
WATCH_LEVEL = 3.25
ALERT_LEVEL = 7.25
COOLDOWN_MINUTES = 180
MAX_ADMISSIBLE_PRICE_MOVE_PCT = 0.30
ROBUST_CLIP = 4.0

def timestamp(value):
    value = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("timezone aware timestamp required")
    return value.astimezone(UTC)

def source_hash(snapshot):
    raw = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()

def feature(snapshot):
    """Validate actual causality and completeness, return (time, vector, price_veto)."""
    if snapshot.get("schema") != "btc-v7-live-shadow-snapshot-v1":
        raise ValueError("unexpected raw snapshot schema")
    if snapshot.get("symbol") != "BTCUSDT":
        raise ValueError("wrong instrument")
    at = timestamp(snapshot["retrieved_at_utc"])
    anchor = timestamp(snapshot["anchor_utc"])
    if not timedelta(0) <= at-anchor <= timedelta(minutes=12):
        raise ValueError("stale or future-dated spot snapshot")
    obs = snapshot["observation"]
    if not isinstance(obs.get("oi"), dict) or not isinstance(obs.get("book"), dict):
        return at, None, "MISSING_OI_OR_BOOK"
    receipt = snapshot.get("optional_receipts", {})
    for key in ("oi_okx", "book_okx"):
        info = receipt.get(key)
        if not info or not info.get("response_received_ms"):
            return at, None, "NO_OPTIONAL_SOURCE_RECEIPT"
        begin = int(info["request_started_ms"]); end = int(info["response_received_ms"])
        if begin > end or end > int(at.timestamp()*1000):
            raise ValueError("future HTTP observation response time")
    oi = obs["oi"];book = obs["book"]
    raw = (
        float(obs["15m_taker_buy_fraction"]),
        float(book["top10_size_imbalance"]),
        float(obs["15m_volume_vs_previous_1h_quarter"]),
        float(oi["oi_change_15m_pct"]),
        float(book["spread_bps"]),
        float(obs["15m_price_change_pct"]),
    )
    if not all(math.isfinite(v) for v in raw):
        return at, None, "NONFINITE_FACTOR"
    taker,book_imb,vol_ratio,oi_pct,spread_bps,price_pct = raw
    if not (0<=taker<=1 and -1<=book_imb<=1 and vol_ratio>0
            and spread_bps>=0 and spread_bps<300):
        return at, None, "OUT_OF_RANGE_FACTOR"
    oi_ts = int(oi["vendor_observation_ms"]);book_ts = int(book["vendor_timestamp_ms"])
    oi_recv = int(receipt["oi_okx"]["response_received_ms"])
    book_recv = int(receipt["book_okx"]["response_received_ms"])
    if not (0<=oi_recv-oi_ts<=15*60*1000 and 0<=book_recv-book_ts<=60*1000):
        return at, None, "STALE_OR_FUTURE_OPTIONAL_FACTOR"
    # Buying/selling pressure and intensity are separate. Positive OI can be
    # new longs or new shorts; it never carries directional sign itself.
    vector = (2*taker-1, book_imb, math.log(vol_ratio), oi_pct, spread_bps)
    return at, vector, ("ALREADY_MOVED" if abs(price_pct) >= MAX_ADMISSIBLE_PRICE_MOVE_PCT else "PRE_MOVE")

def zscore(history, value):
    center = median(history)
    spread = median(abs(x-center) for x in history)
    floor = max(1.4826*spread, 0.001)
    return max(-ROBUST_CLIP, min(ROBUST_CLIP, (value-center)/floor))

def state_zero():
    return {
        "schema": SCHEMA, "last_receipt_utc": None, "last_snapshot_sha256": None,
        "sequence": 0, "up_cusum": 0.0, "down_cusum": 0.0,
        "last_alert_utc": None, "last_alert_side": None,
        "trading_authority": False, "calibrated_probability": False,
    }

def advance(state, history, observation, *,issued_utc=None):
    """Advance one tick, carrying previous score and source hash forward.

    history: prior as-of signed snapshots, ordered chronologically, not including
    the current snapshot. Caller MUST validate signatures of these snapshots.
    """
    if state.get("schema") != SCHEMA or state.get("trading_authority") is not False:
        raise ValueError("invalid frozen pressure state")
    at, cur, readiness = feature(observation)
    issued = timestamp(issued_utc) if issued_utc else at
    if issued < at:
        raise ValueError("decision precedes received observation")
    if issued-at > timedelta(minutes=3):
        raise ValueError("stale detection decision")
    last = state["last_receipt_utc"]
    if last is not None:
        prev = timestamp(last)
        gap = (at-prev).total_seconds()/60
        if gap <= 0:
            raise ValueError("duplicate or backwards observation")
        if gap > GAP_MAX_MINUTES:
            # Fail closed rather than reset state and hide missing data.
            raise ValueError("observation grid gap: must start new provisional epoch")
        if state["last_snapshot_sha256"]!=source_hash(history[-1]):
            raise ValueError("state does not bind to most recent signed source")
    def advance_without_signal(status):
        # Explicitly record the unavailable reading in the cryptographic
        # state chain, but NEVER substitute zero factor values.
        updated={**state,"sequence":int(state["sequence"])+1,
                 "last_receipt_utc":at.isoformat(),
                 "last_snapshot_sha256":source_hash(observation),
                 "up_cusum":0.,"down_cusum":0.}
        return updated,{
            "schema":"btc-v7r3-pressure-diagnostic-v1",
            "observed_at_utc":at.isoformat(),"issued_at_utc":issued.isoformat(),
            "state_sequence":updated["sequence"],
            "current_snapshot_sha256":updated["last_snapshot_sha256"],
            "status":status,"watch":False,"alert":False,
            "trading_authority":False,"calibrated_probability":False}
    if cur is None:
        return advance_without_signal(readiness)
    if len(history)<BASELINE_COUNT:
        return advance_without_signal("INSUFFICIENT_PAST_SIGNED_HISTORY")
    previous = history[-BASELINE_COUNT:]
    previous_time = []
    prior_features=[]
    for snap in previous:
        ts,f,validity=feature(snap)
        if f is None:
            return advance_without_signal("CLEAN_BASELINE_REBUILD_REQUIRED")
        if ts>=at:
            raise ValueError("future point in pressure baseline")
        previous_time.append(ts)
        prior_features.append(f)
    for earlier,later in zip(previous_time, previous_time[1:]):
        gap=(later-earlier).total_seconds()/60
        if gap<=0 or gap>GAP_MAX_MINUTES:
            raise ValueError("noncausal or incomplete signed baseline grid")
    if (at-previous_time[-1]).total_seconds()/60>GAP_MAX_MINUTES:
        raise ValueError("baseline not contiguous with latest reading")
    if state["last_receipt_utc"] is not None and timestamp(state["last_receipt_utc"])!=previous_time[-1]:
        raise ValueError("state receipt does not match signed history")
    zs=[zscore([h[j] for h in prior_features],cur[j]) for j in range(len(cur))]
    flow_z,book_z,volume_z,oi_z,spread_z=zs
    directional = 0.7*flow_z + 0.7*book_z
    participation = min(1.5, 0.30*max(0,volume_z)+0.15*max(0,oi_z))
    # This is *signed* interaction, not raw direction of OI growth.
    pressure=directional + math.copysign(participation, directional) if directional else 0.0
    # Penalize both directions for abnormally wide, adverse execution spreads.
    if spread_z>2.5:
        pressure*=0.5
    up=max(0., DECAY*float(state["up_cusum"])+pressure-DRIFT)
    down=max(0., DECAY*float(state["down_cusum"])-pressure-DRIFT)
    if not math.isfinite(up+down):
        raise ValueError("unbounded pressure state")
    side=("UP" if up>=ALERT_LEVEL and up>down else
          "DOWN" if down>=ALERT_LEVEL and down>up else None)
    cooldown=False
    if side and state["last_alert_utc"] is not None:
        previous_alert=timestamp(state["last_alert_utc"])
        cooldown=(at-previous_alert<timedelta(minutes=COOLDOWN_MINUTES)
                  or at.date()==previous_alert.date())  # fixed <=1 alert per UTC day
    raw_alert=bool(side and not cooldown)
    # If the price already moved, this is not an advance warning.
    eligible = raw_alert and readiness=="PRE_MOVE"
    if readiness=="ALREADY_MOVED":
        # Do not allow an after-the-fact strong move to accumulate into a
        # "new early" alarm on the next quiet candle.
        up=0.
        down=0.
        status="LATE_PRESSURE_AFTER_PRICE_IMPULSE"
    elif cooldown:
        status="SUPPRESSED_IN_COOLDOWN"
    elif eligible:
        status="UNCALIBRATED_PRE_MOVE_"+side+"_PRESSURE"
    elif max(up,down)>=WATCH_LEVEL:
        status="UNVALIDATED_PRESSURE_WATCH"
    else:
        status="NO_PREMOVE_PRESSURE"
    next_state={
        **state,"sequence":int(state["sequence"])+1,
        "last_receipt_utc":at.isoformat(),
        "last_snapshot_sha256":source_hash(observation),
        "up_cusum":up,"down_cusum":down,
    }
    if eligible:
        next_state["last_alert_utc"]=at.isoformat()
        next_state["last_alert_side"]=side
    diagnostic={
        "schema":"btc-v7r3-pressure-diagnostic-v1",
        "observed_at_utc":at.isoformat(),
        "issued_at_utc":issued.isoformat(),
        "current_snapshot_sha256":source_hash(observation),
        "previous_snapshot_sha256":state["last_snapshot_sha256"],
        "previous_state_sequence":state["sequence"],
        "state_sequence":next_state["sequence"],
        "z_taker":flow_z, "z_book":book_z, "z_volume":volume_z,
        "z_oi":oi_z, "z_spread":spread_z,
        "pressure":pressure,"up_cusum":up,"down_cusum":down,
        "status":status,"warning_side":side if eligible else None,
        "watch":max(up,down)>=WATCH_LEVEL,
        "alert":eligible,
        "price_already_moved":readiness=="ALREADY_MOVED",
        "trading_authority":False,"calibrated_probability":False,
        "meaning":"pre-move heuristic pressure watch, not a future-price forecast or probability",
    }
    return next_state,diagnostic

def replay(snapshots,*,issued_utc=None):
    """Deterministic full causal replay. Every previous record must be signed upstream."""
    ordered=sorted(snapshots,key=lambda s:timestamp(s["retrieved_at_utc"]))
    state=state_zero()
    reports=[]
    for i,s in enumerate(ordered):
        ts=timestamp(s["retrieved_at_utc"])
        issued=timestamp(issued_utc) if i==len(ordered)-1 and issued_utc else ts
        state,diag=advance(state,ordered[:i],s,issued_utc=issued)
        reports.append(diag)
    return state,reports
