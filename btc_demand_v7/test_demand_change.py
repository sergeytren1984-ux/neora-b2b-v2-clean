"""Causal CUSUM demand-positioning tests: mirror, gaps and future effects."""
from datetime import datetime,timedelta,timezone
from btc_demand_v7.demand_change import estimate,MIN_BACKGROUND
UTC=timezone.utc

def example(t,price=0.,flow=.5,volume=1.2,oi=0.,book=0.,available=True):
    return {"anchor_utc":t.isoformat(),
            "observation":{"15m_price_change_pct":price,
                           "15m_taker_buy_fraction":flow,
                           "15m_volume_vs_previous_1h_quarter":volume,
                           "oi":{"oi_change_15m_pct":oi} if available else None,
                           "book":{"top10_size_imbalance":book,"spread_bps":1.} if available else None}}

def main():
    start=datetime(2026,10,13,tzinfo=UTC)
    samples=[example(start+timedelta(minutes=i*15),
                     price=.02*((i%4)-1),
                     flow=.50+.01*((i%5)-2),
                     volume=1.1+.05*(i%6),
                     oi=.01*((i%7)-3),
                     book=.04*((i%3)-1)) for i in range(33)]
    no=estimate(samples[:-1])
    assert no["state"]=="INSUFFICIENT_ASOF_HISTORY"
    normal=estimate(samples)
    assert normal["trading_authority"] is False
    assert normal["calibrated_probability"] is False
    up=[dict(x) for x in samples]
    up[-1]=example(start+timedelta(minutes=32*15),price=1.2,flow=.96,volume=7.,
                   oi=.5,book=.9)
    raised=estimate(up)
    assert raised["state"]=="UNCALIBRATED_UP_SHIFT"
    down=[dict(x) for x in samples]
    down[-1]=example(start+timedelta(minutes=32*15),price=-1.2,flow=.04,volume=7.,
                     oi=.5,book=-.9)
    lowered=estimate(down)
    assert lowered["state"]=="UNCALIBRATED_DOWN_SHIFT"
    assert raised["cusum_up"]>raised["cusum_down"]
    assert lowered["cusum_down"]>lowered["cusum_up"]
    assert estimate(samples[:-1]+[example(start+timedelta(minutes=32*15),available=False)])["state"]=="POSITIONING_OR_BOOK_UNAVAILABLE"
    wrong=[*samples[:-1],example(start+timedelta(minutes=50*15))]
    assert estimate(wrong)["state"]=="ASOF_HISTORY_GAP"
    # An after-the-fact future sample must not alter prior causal states.
    assert estimate(samples)==normal
    print("BTC_V7R2_SINGLE_CAUSAL_DEMAND_CUSUM_TEST_PASS")

if __name__=="__main__":main()
