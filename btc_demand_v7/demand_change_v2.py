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
from btc_demand_v7.live_snapshot import strict_closed

UTC = timezone.utc
SCHEMA = "btc-v7r3-causal-pressure-state-v1"
BASELINE_COUNT = 32
CADENCE_MINUTES = 15
# Due anchors are EXACTLY 15m apart. Valid HTTP receipt offsets vary
# between anchor+0 and anchor+12m, so two consecutive valid receipts
# can be separated by as much as 27m. A 22m receipt gap wrongly rejects
# valid slots. Exact anchor grid is the continuity authority.
GAP_MAX_MINUTES = 27
DRIFT = 0.55
DECAY = 0.94
WATCH_LEVEL = 3.25
ALERT_LEVEL = 7.25
COOLDOWN_MINUTES = 180
# Public GitHub completion is only verified AFTER emitting the research alert.
# Since a valid alert can be publicly available up to 13 minutes AFTER its
# closed source candle anchor, the previous source-time rule allowed two
# alerts PUBLICLY DELIVERED ON THE SAME UTC DAY at the midnight boundary.
# A conservative >=24h+13m rolling source cooldown is strictly stronger
# than the promised <=1 public alert per UTC date, independent of jitter.
PUBLICATION_LATENCY_BOUND_MINUTES = 13
GLOBAL_PUBLIC_DAILY_ALERT_SAFETY_MINUTES = 24*60 + PUBLICATION_LATENCY_BOUND_MINUTES
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
    micro=obs.get("microflow")
    bars=snapshot.get("microflow_rows")
    if not isinstance(micro,dict) or not isinstance(bars,list):
        return at,None,"MISSING_CURRENT_3M_TAKER_FLOW"
    timestamp_close=int(micro["vendor_close_ms"])
    timestamp_received=int(micro["response_received_ms"])
    if not(int(micro["request_started_ms"])<=timestamp_received
           and timestamp_close<=timestamp_received<=int(at.timestamp()*1000)
           and timestamp_received-timestamp_close<=120000):
        raise ValueError("out-of-time microflow receipt")
    last=strict_closed(bars,60000,timestamp_close,6)
    if len(last)!=6 or len(last)!=len(bars):
        raise ValueError("noncanonical microflow raw 1m grid")
    v3=sum(float(row[5]) for row in last[-3:])
    vprev=sum(float(row[5]) for row in last[:3])
    if v3<=0 or vprev<=0:
        raise ValueError("no 3m/previous3m trade volume")
    micro_buy=sum(float(row[9]) for row in last[-3:])/v3
    micro_ratio=v3/vprev
    if (not math.isclose(micro_buy,float(micro["recent3_taker_buy_fraction"]),rel_tol=1e-11,abs_tol=1e-9)
        or not math.isclose(micro_ratio,float(micro["recent3_volume_vs_prior3"]),rel_tol=1e-11,abs_tol=1e-9)
        or not math.isclose(float(micro["price_last_closed_1m"]),float(last[-1][4]),rel_tol=0,abs_tol=1e-8)):
        raise ValueError("forged signed contemporary microflow observation")
    raw = (
        float(obs["15m_taker_buy_fraction"]),
        micro_buy,
        float(book["top10_size_imbalance"]),
        float(obs["15m_volume_vs_previous_1h_quarter"]),
        micro_ratio,
        float(oi["oi_change_15m_pct"]),
        float(book["spread_bps"]),
        float(obs["15m_price_change_pct"]),
    )
    if not all(math.isfinite(v) for v in raw):
        return at, None, "NONFINITE_FACTOR"
    taker,micro_taker,book_imb,vol_ratio,micro_vol_ratio,oi_pct,spread_bps,price_pct = raw
    if not (0<=taker<=1 and 0<=micro_taker<=1 and -1<=book_imb<=1
            and vol_ratio>0 and micro_vol_ratio>0
            and spread_bps>=0 and spread_bps<300):
        return at, None, "OUT_OF_RANGE_FACTOR"
    oi_ts = int(oi["vendor_observation_ms"]);book_ts = int(book["vendor_timestamp_ms"])
    oi_recv = int(receipt["oi_okx"]["response_received_ms"])
    book_recv = int(receipt["book_okx"]["response_received_ms"])
    if not (0<=oi_recv-oi_ts<=15*60*1000 and 0<=book_recv-book_ts<=60*1000):
        return at, None, "STALE_OR_FUTURE_OPTIONAL_FACTOR"
    # Buying/selling pressure and intensity are separate. Positive OI can be
    # new longs or new shorts; it never carries directional sign itself.
    vector = (2*taker-1, 2*micro_taker-1, book_imb,
              math.log(vol_ratio), math.log(micro_vol_ratio),
              oi_pct, spread_bps)
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

def advance(state, history, observation, *,issued_utc=None,
            live_change_since_anchor_pct=None):
    """Advance one tick, carrying previous score and source hash forward.

    history: prior as-of signed snapshots, ordered chronologically, not including
    the current snapshot. Caller MUST validate signatures of these snapshots.
    """
    if state.get("schema") != SCHEMA or state.get("trading_authority") is not False:
        raise ValueError("invalid frozen pressure state")
    at, cur, readiness = feature(observation)
    if live_change_since_anchor_pct is not None:
        gap_move=float(live_change_since_anchor_pct)
        if not math.isfinite(gap_move):
            raise ValueError("invalid price movement after source anchor")
        if abs(gap_move)>=MAX_ADMISSIBLE_PRICE_MOVE_PCT:
            readiness="ALREADY_MOVED"
    issued = timestamp(issued_utc) if issued_utc else at
    if issued < at:
        raise ValueError("decision precedes received observation")
    if issued-at > timedelta(minutes=10):
        raise ValueError("stale detection decision: signed source older than 10 minutes")
    # Invariant: a 15m *candle anchor*, not variable API latency,
    # defines every due slot. Accept variable collection latency ONLY
    # within the strictly checked <=12m fresh-as-of bound in feature().
    current_anchor=timestamp(observation["anchor_utc"])
    if history:
        previous_anchor=timestamp(history[-1]["anchor_utc"])
        if current_anchor-previous_anchor!=timedelta(minutes=CADENCE_MINUTES):
            raise ValueError("missed/duplicate 15m anchor slot, not allowable latency jitter")
    last = state["last_receipt_utc"]
    if last is not None:
        prev = timestamp(last)
        gap = (at-prev).total_seconds()/60
        if gap <= 0:
            raise ValueError("duplicate or backwards observation")
        if gap > GAP_MAX_MINUTES:
            raise ValueError("as-of HTTP receipt age exceeds anchored 15m+12m maximum")
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
    # Signed candle anchors MUST be contiguous even if receipt times
    # legitimately fluctuate by up to 12 minutes per due window.
    anchor_times=[timestamp(snap["anchor_utc"]) for snap in previous]
    for earlier,later in zip(anchor_times,anchor_times[1:]):
        if later-earlier!=timedelta(minutes=CADENCE_MINUTES):
            raise ValueError("missing or duplicated signed candle in 32-slot baseline")
    for earlier,later in zip(previous_time,previous_time[1:]):
        gap=(later-earlier).total_seconds()/60
        if gap<=0 or gap>GAP_MAX_MINUTES:
            raise ValueError("noncausal HTTP receipt order in signed baseline")
    if current_anchor-anchor_times[-1]!=timedelta(minutes=CADENCE_MINUTES):
        raise ValueError("current signed anchor not adjacent to baseline")
    if not 0<(at-previous_time[-1]).total_seconds()/60<=GAP_MAX_MINUTES:
        raise ValueError("noncausal/missing current signed receipt")
    if state["last_receipt_utc"] is not None and timestamp(state["last_receipt_utc"])!=previous_time[-1]:
        raise ValueError("state receipt does not match signed history")
    zs=[zscore([h[j] for h in prior_features],cur[j]) for j in range(len(cur))]
    flow_z,micro_z,book_z,volume_z,micro_volume_z,oi_z,spread_z=zs
    # Contemporary 3m buy pressure is available BEFORE the forecast, and
    # leads the older full 15m candle in detecting demand transitions.
    directional = 0.30*flow_z + 0.85*micro_z + 0.65*book_z
    participation = min(1.5, 0.20*max(0,volume_z)
                       +0.25*max(0,micro_volume_z)+0.15*max(0,oi_z))
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
        if at < previous_alert:
            raise ValueError("previous signed alert timestamp is in the future")
        cooldown=(at-previous_alert<=timedelta(minutes=GLOBAL_PUBLIC_DAILY_ALERT_SAFETY_MINUTES)
                  or at.date()==previous_alert.date())  # public UTC day guard
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
        "source_age_seconds_at_publication":(issued-at).total_seconds(),
        "current_snapshot_sha256":source_hash(observation),
        "previous_snapshot_sha256":state["last_snapshot_sha256"],
        "previous_state_sequence":state["sequence"],
        "state_sequence":next_state["sequence"],
        "z_taker_15m":flow_z,"z_current_taker_3m":micro_z,
        "z_book":book_z,"z_volume_15m":volume_z,
        "z_micro_volume_3m":micro_volume_z,
        "z_oi":oi_z,"z_spread":spread_z,
        "pressure":pressure,"up_cusum":up,"down_cusum":down,
        "status":status,"warning_side":side if eligible else None,
        "watch":max(up,down)>=WATCH_LEVEL,
        "alert":eligible,
        "price_already_moved":readiness=="ALREADY_MOVED",
        "price_change_since_anchor_pct":live_change_since_anchor_pct,
        "after_anchor_move_veto_applied":bool(
            live_change_since_anchor_pct is not None
            and abs(live_change_since_anchor_pct)>=MAX_ADMISSIBLE_PRICE_MOVE_PCT),
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
