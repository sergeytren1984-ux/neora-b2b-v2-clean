"""Independent valid latency jitter vs actual missing anchor attacks.

Reproduces the bug present in v7R4: two valid due anchor slots 15m apart
with receipt timestamps 23m apart were wrongly rejected under GAP_MAX=22.
All synthetic fixture inputs are causally valid, not future market data.
"""
from __future__ import annotations
import copy
from datetime import datetime,timedelta
from btc_demand_v7.test_demand_change_v2 import snap
from btc_demand_v7.demand_change_v2 import (
    replay,advance,feature,BASELINE_COUNT,GAP_MAX_MINUTES
)
UTC=datetime.fromisoformat("2026-10-14T00:00:00+00:00").tzinfo

def retime(snapshot,offset_minutes):
    s=copy.deepcopy(snapshot)
    original=datetime.fromisoformat(s["retrieved_at_utc"])
    anchor=datetime.fromisoformat(s["anchor_utc"])
    target=anchor+timedelta(minutes=offset_minutes)
    delta_ms=int((target-original).total_seconds()*1000)
    s["retrieved_at_utc"]=target.isoformat()
    m=s["observation"]["microflow"]
    for k in ("vendor_close_ms","request_started_ms","response_received_ms"):
        m[k]+=delta_ms
    for bar in s["microflow_rows"]:
        bar[0]+=delta_ms
        bar[6]+=delta_ms
    for key in ("oi","book"):
        obj=s["observation"][key]
        obj["vendor_observation_ms" if key=="oi" else "vendor_timestamp_ms"]+=delta_ms
    for receipts in s["optional_receipts"].values():
        receipts["request_started_ms"]+=delta_ms
        receipts["response_received_ms"]+=delta_ms
    return s

def invalid(f,explanation):
    try:f()
    except (ValueError,RuntimeError):
        print("EXPECTED_REJECTION",explanation)
        return
    raise AssertionError("accepted illegal "+explanation)

def test():
    # Baseline remains anchored precisely 15m, despite valid receipt jitter.
    baseline=[snap(i) for i in range(BASELINE_COUNT)]
    state,_=replay(baseline)
    late_received=retime(snap(BASELINE_COUNT,direction=1),11)
    assert feature(late_received)[1] is not None
    # Last previous receipt at +3, current at +11, gap=23m (>R4's 22m).
    prior=feature(baseline[-1])[0]
    assert (feature(late_received)[0]-prior).total_seconds()==23*60
    next_state,diag=advance(state,baseline,late_received,
                            issued_utc=feature(late_received)[0]+timedelta(seconds=30))
    assert next_state["sequence"]==BASELINE_COUNT+1
    assert diag["status"]!="STALE_OR_FUTURE_OPTIONAL_FACTOR"
    assert GAP_MAX_MINUTES==27
    # Absolute boundary: prior anchor receipt +0m, next +12m yields
    # maximum legitimate 27m. No implied missing candle.
    previous=retime(snap(31),0)
    baseline2=baseline[:-1]+[previous]
    state2,_=replay(baseline2)
    end=retime(snap(32,direction=1),12)
    newer,diagnostic=advance(state2,baseline2,end,issued_utc=feature(end)[0])
    assert newer["sequence"]==BASELINE_COUNT+1
    assert diagnostic["state_sequence"]==newer["sequence"]
    assert (feature(end)[0]-feature(previous)[0]).total_seconds()==27*60
    # True missing due anchor must fail even if HTTP responses are a
    # plausible 15m apart. Anchor grid is source of truth.
    bad=copy.deepcopy(late_received)
    bad["anchor_utc"]=(datetime.fromisoformat(bad["anchor_utc"])+timedelta(minutes=15)).isoformat()
    invalid(lambda:advance(state,baseline,bad),"missing exact candle anchor")
    # Missing one slot within the signed 32-slot reference also fails.
    misaligned=copy.deepcopy(baseline)
    misaligned[12]["anchor_utc"]=(datetime.fromisoformat(misaligned[12]["anchor_utc"])+timedelta(minutes=15)).isoformat()
    invalid(lambda:advance(state,misaligned,late_received),"baseline anchor duplicate/gap")
    # HTTP receipts outside their <=12m registration are unacceptable.
    stale=retime(snap(BASELINE_COUNT),13)
    invalid(lambda:feature(stale),"source acquired more than 12m after registered anchor")
    # Cryptographic hash remains mandatory to bind last raw to prior state.
    corrupted=copy.deepcopy(baseline)
    corrupted[-1]["observation"]["15m_taker_buy_fraction"]+=.01
    invalid(lambda:advance(state,corrupted,late_received),"signed state -> prior raw SHA mismatch")
    print("BTC_V7R5_REGISTERED_ANCHOR_JITTER_27M_NOT_FAKE_MISS_AND_ACTUAL_GAP_REJECTED")

if __name__=="__main__":test()
