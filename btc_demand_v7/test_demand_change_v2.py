"""Adversarial synthetic tests for stateful *pre-move* flow/OI/book CUSUM."""
from __future__ import annotations
import copy
from datetime import datetime,timedelta,timezone
from btc_demand_v7.demand_change_v2 import (
    advance,replay,state_zero,source_hash,feature,BASELINE_COUNT)
UTC=timezone.utc

def snap(i, *,direction=0,price_pct=0.01,valid=True):
    start=datetime(2026,10,14,tzinfo=UTC)
    anchor=start+timedelta(minutes=15*i)
    received=anchor+timedelta(minutes=3)
    t=int(received.timestamp()*1000)
    flow=.5 + .015*((i%5)-2) if direction==0 else (.88 if direction>0 else .12)
    book=.06*((i%5)-2) if direction==0 else (.75 if direction>0 else -.75)
    oi=.015*((i%7)-3) if direction==0 else .35
    vol=1.1+.05*(i%6) if direction==0 else 4.0
    result={
        "schema":"btc-v7-live-shadow-snapshot-v1",
        "symbol":"BTCUSDT","anchor_utc":anchor.isoformat(),
        "retrieved_at_utc":received.isoformat(),
        "observation":{
            "15m_taker_buy_fraction":flow,
            "15m_volume_vs_previous_1h_quarter":vol,
            "15m_price_change_pct":price_pct,
            "oi":{"oi_change_15m_pct":oi,"vendor_observation_ms":t-240000},
            "book":{"top10_size_imbalance":book,"spread_bps":.8,
                    "vendor_timestamp_ms":t-150}
        },
        "optional_receipts":{
            "oi_okx":{"request_started_ms":t-900,"response_received_ms":t-500},
            "book_okx":{"request_started_ms":t-350,"response_received_ms":t-100},
        }
    }
    if not valid:result["observation"]["oi"]=None
    return result

def require_error(callback,why):
    try:callback()
    except (ValueError,RuntimeError):
        print("REJECTED",why);return
    raise AssertionError("invalid case accepted "+why)

def test():
    baseline=[snap(i) for i in range(BASELINE_COUNT)]
    assert replay(baseline)[0]["sequence"]==BASELINE_COUNT
    # Two pressure runs with identical 15m prices. Pressure must accumulate.
    sequence=baseline+[snap(BASELINE_COUNT+j,direction=1) for j in range(8)]
    state,events=replay(sequence)
    valid=events[BASELINE_COUNT:]
    assert len(valid)==8
    assert valid[1]["up_cusum"]>valid[0]["up_cusum"]
    assert any(x["alert"] and x["warning_side"]=="UP" for x in valid)
    assert all(x["calibrated_probability"] is False and x["trading_authority"] is False for x in valid)
    assert state["sequence"]==BASELINE_COUNT+8
    assert sum(x["alert"] for x in valid)<=1  # 3h cooldown
    assert state["last_snapshot_sha256"]==source_hash(sequence[-1])
    # Symmetric down pressure, no need for price to fall first.
    negative=baseline+[snap(BASELINE_COUNT+j,direction=-1) for j in range(8)]
    nstate,negative_events=replay(negative)
    down=negative_events[BASELINE_COUNT:]
    assert any(x["alert"] and x["warning_side"]=="DOWN" for x in down)
    assert down[1]["down_cusum"]>down[0]["down_cusum"]
    # Signal after the price has already moved cannot count as an early warning.
    late=baseline+[snap(BASELINE_COUNT+j,direction=1,price_pct=1.2) for j in range(8)]
    _,late_events=replay(late)
    assert not any(x["alert"] for x in late_events)
    assert any(x["status"]=="LATE_PRESSURE_AFTER_PRICE_IMPULSE" for x in late_events)
    missing=baseline+[snap(BASELINE_COUNT,valid=False)]
    _,missing_events=replay(missing)
    assert missing_events[-1]["status"]=="MISSING_OI_OR_BOOK"
    assert not missing_events[-1]["alert"]
    assert replay(missing)[0]["sequence"]==BASELINE_COUNT+1
    # Missing observations must RESET accumulated pressure and require
    # 32 clean new readings; never interpret missing OI/book as zero.
    reset_base=baseline+[snap(BASELINE_COUNT,valid=False)]
    rebuilt=reset_base+[snap(BASELINE_COUNT+i) for i in range(1,35)]
    st,recovery=replay(rebuilt)
    assert all(not e["alert"] for e in recovery[BASELINE_COUNT:BASELINE_COUNT+32])
    assert any(e["status"]=="CLEAN_BASELINE_REBUILD_REQUIRED"
               for e in recovery[BASELINE_COUNT+1:BASELINE_COUNT+32])
    assert st["sequence"]==len(rebuilt)
    # Mutate future optional snapshot receipt; no hindsight permitted.
    future=snap(BASELINE_COUNT,direction=1)
    future["observation"]["book"]["vendor_timestamp_ms"] += 100_000
    _,bad=replay(baseline+[future])
    assert bad[-1]["status"]=="STALE_OR_FUTURE_OPTIONAL_FACTOR"
    # State->previous raw binding must be exact. A corrected earlier history
    # cannot be substituted after a state was already published.
    swapped=copy.deepcopy(sequence)
    swapped[-2]["observation"]["15m_taker_buy_fraction"]+=.01
    require_error(lambda:advance(state,swapped[:-1],swapped[-1]),"tampered previous signed snapshot")
    require_error(lambda:advance(state,sequence[:-1],sequence[-1]),"duplicate receipt")
    out_of_order=copy.deepcopy(sequence)
    out_of_order[-1]["retrieved_at_utc"]=(datetime(2026,10,17,tzinfo=UTC)).isoformat()
    require_error(lambda:replay(out_of_order),"missing 15m due slots")
    require_error(lambda:feature({**snap(34),"symbol":"ETHUSDT"}),"wrong instrument")
    # Local as-of HTTP observation cannot postdate its signed response.
    altered=snap(34)
    altered["optional_receipts"]["oi_okx"]["response_received_ms"] = int(datetime(2026,10,30,tzinfo=UTC).timestamp()*1000)
    require_error(lambda:feature(altered),"future HTTP response")
    print("BTC_V7R3_STATEFUL_CAUSAL_PREMOVE_DETECTOR_NEGATIVE_TESTS_PASS",
          {"UP_first_alert_at_index":[i for i,x in enumerate(valid) if x["alert"]],
           "DOWN_first_alert_at_index":[i for i,x in enumerate(down) if x["alert"]],
           "final_up_cusum":state["up_cusum"]})

if __name__=="__main__":
    test()
