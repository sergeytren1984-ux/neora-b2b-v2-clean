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
    micro_close=t-60000
    bars=[]
    for j in range(6):
        end=micro_close-(5-j)*60000
        buy_fraction=.5 if j<3 else flow
        size=10. if j<3 or direction==0 else 50.
        bars.append([end-60000,"83000","83010","82990","83000",
                     str(size),end-1,str(83000*size),100,
                     str(buy_fraction*size),str(83000*buy_fraction*size),"0"])
    micro={
        "vendor_close_ms":micro_close,
        "request_started_ms":t-1200,
        "response_received_ms":t-500,
        "recent3_taker_buy_fraction":flow,
        "recent3_volume_vs_prior3":(5. if direction else 1.),
        "price_last_closed_1m":83000.}
    result={
        "schema":"btc-v7-live-shadow-snapshot-v1",
        "symbol":"BTCUSDT","anchor_utc":anchor.isoformat(),
        "retrieved_at_utc":received.isoformat(),
        "microflow_rows":bars,
        "observation":{
            "microflow":micro,
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
    # If the market rose AFTER the 15m candle / signed book and BEFORE
    # actual decision publication, calling it "early" is invalid.
    from btc_demand_v7.demand_change_v2 import MAX_ADMISSIBLE_PRICE_MOVE_PCT
    price_late_state,price_late=advance(
        replay(baseline)[0],baseline,snap(BASELINE_COUNT,direction=1),
        live_change_since_anchor_pct=1.2)
    assert price_late["status"]=="LATE_PRESSURE_AFTER_PRICE_IMPULSE"
    assert price_late["alert"] is False
    assert price_late["after_anchor_move_veto_applied"] is True
    assert price_late_state["up_cusum"]==0.
    try:advance(replay(baseline)[0],baseline,snap(BASELINE_COUNT,direction=1),
                live_change_since_anchor_pct=float("nan"))
    except ValueError:pass
    else:raise AssertionError("nonfinite publication gap accepted")
    # Current 3m signed flow must reject fabricated/retroactive samples.
    poisoned=copy.deepcopy(snap(BASELINE_COUNT,direction=1))
    poisoned["observation"]["microflow"]["recent3_taker_buy_fraction"]=-1.
    require_error(lambda:feature(poisoned),"forged contemporary 3m taker ratio")
    poisoned=copy.deepcopy(snap(BASELINE_COUNT,direction=1))
    poisoned["observation"]["microflow"]["vendor_close_ms"]+=90000
    require_error(lambda:feature(poisoned),"future 3m vendor minute")
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
    # A relative Z-score rise out of an extremely SELL-heavy baseline is
    # not yet absolute buy pressure. Conversely weakening STRONG buying
    # is not absolute aggressive selling. Both cases used to emit alerts.
    def fewer_sellers(i):
        item=snap(i,direction=-1)
        item["observation"]["15m_taker_buy_fraction"]=.45
        item["observation"]["book"]["top10_size_imbalance"]=-.20
        item["observation"]["microflow"]["recent3_taker_buy_fraction"]=.45
        for row in item["microflow_rows"][-3:]:
            size=float(row[5]);row[9]=str(.45*size);row[10]=str(83000*.45*size)
        return item
    bearish=[snap(i,direction=-1) for i in range(BASELINE_COUNT)]
    _,less_bearish=replay(bearish+[fewer_sellers(BASELINE_COUNT+i) for i in range(5)])
    relative_up=less_bearish[BASELINE_COUNT:]
    assert any(e.get("relative_pressure_side")=="UP" for e in relative_up)
    assert not any(e["alert"] for e in relative_up),relative_up
    assert any(e.get("absolute_side_consensus_veto") for e in relative_up)
    from btc_demand_v7.demand_change_v2 import paired_shadow_replay
    paired=paired_shadow_replay(bearish+[fewer_sellers(BASELINE_COUNT+i) for i in range(5)])
    assert any(e["alert"] and e["warning_side"]=="UP"
               for e in paired["baseline_diagnostics"][BASELINE_COUNT:])
    assert not any(e["alert"] for e in paired["challenger_diagnostics"][BASELINE_COUNT:])
    assert paired["trade_skill_proven"] is False
    # The challenger did not waste its daily alert budget on weak buying:
    # it remains able to warn on a later absolute buy-pressure reversal.
    future=[*bearish,*[fewer_sellers(BASELINE_COUNT+i) for i in range(5)],
            *[snap(BASELINE_COUNT+5+i,direction=1) for i in range(8)]]
    staged=paired_shadow_replay(future)
    assert any(e["alert"] and e["warning_side"]=="UP"
               for e in staged["challenger_diagnostics"][BASELINE_COUNT+5:])
    assert not any(e["alert"] for e in staged["baseline_diagnostics"][BASELINE_COUNT+5:])
    def fewer_buyers(i):
        item=snap(i,direction=1)
        item["observation"]["15m_taker_buy_fraction"]=.55
        item["observation"]["book"]["top10_size_imbalance"] = .20
        item["observation"]["microflow"]["recent3_taker_buy_fraction"]=.55
        for row in item["microflow_rows"][-3:]:
            size=float(row[5]);row[9]=str(.55*size);row[10]=str(83000*.55*size)
        return item
    bullish=[snap(i,direction=1) for i in range(BASELINE_COUNT)]
    _,less_bullish=replay(bullish+[fewer_buyers(BASELINE_COUNT+i) for i in range(5)])
    relative_down=less_bullish[BASELINE_COUNT:]
    assert any(e.get("relative_pressure_side")=="DOWN" for e in relative_down)
    assert not any(e["alert"] for e in relative_down),relative_down
    assert any(e.get("absolute_side_consensus_veto") for e in relative_down)
    print("BTC_V7R3_STATEFUL_CAUSAL_PREMOVE_DETECTOR_NEGATIVE_TESTS_PASS",
          {"UP_first_alert_at_index":[i for i,x in enumerate(valid) if x["alert"]],
           "DOWN_first_alert_at_index":[i for i,x in enumerate(down) if x["alert"]],
           "final_up_cusum":state["up_cusum"]})

if __name__=="__main__":
    test()
