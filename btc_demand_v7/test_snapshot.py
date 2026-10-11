from __future__ import annotations
import datetime as dt
from btc_demand_v7.live_snapshot import strict_closed,open_interest_state,liquidity_state,spot_state

def test():
    period=60000;t=1800000000000
    rows=[]
    for i in range(210):
        ts=t+i*period
        rows.append([ts,"83000","83100","82950","83050","10",ts+period-1,"",200,"6"])
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
    try:open_interest_state(data,anchor+3600000)
    except ValueError:pass
    else:raise AssertionError("stale OI accepted")
    book={"code":"0","data":[{"ts":str(anchor),"bids":[["83000","50"]],"asks":[["83005","30"]]}]}
    assert liquidity_state(book)["top10_size_imbalance"]==.25
    book["data"][0]["asks"][0][0]="82999"
    try:liquidity_state(book)
    except ValueError:pass
    else:raise AssertionError("crossed book accepted")
    print("BTC_V7_POINT_IN_TIME_REQUIRED_OPTIONAL_NEGATIVE_TESTS_PASS")
if __name__=="__main__":test()
