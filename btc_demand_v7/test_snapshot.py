from __future__ import annotations
import datetime as dt
from btc_demand_v7.live_snapshot import strict_closed,open_interest_state,liquidity_state,spot_state,funding_state

def test():
    period=60000;t=1800000000000
    rows=[]
    for i in range(210):
        ts=t+i*period
        rows.append([ts,"83000","83100","82950","83050","10",ts+period-1,"830500",200,"6","498300","0"])
    # New attacks: malformed 5m trades and individual book lot must fail.
    import copy
    poisoned=copy.deepcopy(rows)
    poisoned[88][8]="NaN"
    try:strict_closed(poisoned,period,t+210*period,200)
    except ValueError:pass
    else:raise AssertionError("NaN trade count accepted")
    poisoned=copy.deepcopy(rows)
    poisoned[88][8]="2.5"
    try:strict_closed(poisoned,period,t+210*period,200)
    except ValueError:pass
    else:raise AssertionError("noninteger trade count accepted")
    anchor=t+210*period
    assert len(strict_closed(rows,period,anchor,200))==210
    for bad in (rows[:-1],rows[:200]+rows[201:]):
        try:strict_closed(bad,period,anchor,200)
        except ValueError:pass
        else:raise AssertionError("stale/gapped candle accepted")
    s=spot_state(rows,anchor)
    assert s["15m_taker_buy_fraction"]==.6
    data={"code":"0","data":[[str(anchor-5400000+i*300000),str(3000000000*(1+.001*i)),"0"] for i in range(19)]}
    # some values timestamp after cutoff are ignored
    state=open_interest_state(data,anchor)
    assert state["age_seconds"]==0
    oi_gap={"code":"0","data":[r for r in data["data"] if int(r[0])!=anchor-900000]}
    try:open_interest_state(oi_gap,anchor)
    except ValueError:pass
    else:raise AssertionError("30m OI substituted for exact 15m reference")
    try:open_interest_state(data,anchor+3600000)
    except ValueError:pass
    else:raise AssertionError("stale OI accepted")
    book={"code":"0","data":[{"ts":str(anchor),"bids":[["83000","50"]],"asks":[["83005","30"]]}]}
    assert liquidity_state(book)["top10_size_imbalance"]==.25
    for bad_lots in ("-10","NaN"):
        invalid_book={"code":"0","data":[{"ts":str(anchor),
            "bids":[["83000",bad_lots],["82999","20"]],
            "asks":[["83005","30"]]}]}
        try:liquidity_state(invalid_book)
        except ValueError:pass
        else:raise AssertionError("invalid individual book lot accepted")
    book["data"][0]["asks"][0][0]="82999"
    try:liquidity_state(book)
    except ValueError:pass
    else:raise AssertionError("crossed book accepted")
    event_ts=anchor
    funding={"code":"0","data":[{"instId":"BTC-USDT-SWAP",
             "ts":str(event_ts),"fundingTime":str(event_ts+8*3600*1000),
             "fundingRate":"0.0001"}]}
    assert funding_state(funding,anchor-1000,anchor+1000)["value"]==.0001
    for change in ("wrong_symbol","future_time","stale_time","nan"):
        import copy
        bad=copy.deepcopy(funding)
        e=bad["data"][0]
        if change=="wrong_symbol":e["instId"]="ETH-USDT-SWAP"
        if change=="future_time":e["ts"]=str(anchor+90000)
        if change=="stale_time":e["ts"]=str(anchor-240000)
        if change=="nan":e["fundingRate"]="NaN"
        try:funding_state(bad,anchor-1000,anchor+1000)
        except ValueError:pass
        else:raise AssertionError("invalid funding observation accepted: "+change)
    # Realistic book timestamp arrives after request_start but before response:
    fresh=liquidity_state({"code":"0","data":[{"ts":str(anchor+565),
        "bids":[["83000","50"]],"asks":[["83005","30"]]}]})
    assert anchor+1000-fresh["vendor_timestamp_ms"]==435
    print("BTC_V7_POINT_IN_TIME_REQUIRED_OPTIONAL_NEGATIVE_TESTS_PASS")
if __name__=="__main__":test()
