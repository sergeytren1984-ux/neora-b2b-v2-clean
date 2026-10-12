"""Mandatory negative tests for delayed OTC fill and right-censored targets."""
from datetime import datetime,timezone,timedelta
import math
import numpy as np
from btc_demand_v7.otc_decision import next_morning,schedules,compare
from btc_demand_v7.train import label_arrays,PRICE_TARGETS,EVENT_TARGETS
UTC=timezone.utc

def run():
    now=datetime(2026,10,11,18,45,tzinfo=UTC) # 21:45 MSK
    times=schedules(now)
    assert times["BUY_NOW"]==now+timedelta(hours=1)
    assert times["WAIT_1H"]==now+timedelta(hours=2)
    assert times["WAIT_4H"]==now+timedelta(hours=5)
    assert times["WAIT_TILL_08_MSK"]==datetime(2026,10,12,6,0,tzinfo=UTC)
    assert next_morning(datetime(2026,10,12,4,59,tzinfo=UTC))==datetime(2026,10,12,5,0,tzinfo=UTC)
    assert next_morning(datetime(2026,10,12,5,tzinfo=UTC))==datetime(2026,10,13,5,tzinfo=UTC)
    prices={k:83000. for k in ("1h","2h","4h","5h","morning","morning_plus_1h")}
    result=compare(now,prices,prediction_anchor=now)
    assert result["status"]=="NO_VERIFIED_EDGE"
    assert not result["trading_authority"] and not result["market_order_placed"]
    assert abs(result["actions"]["BUY_NOW"]["acquired_btc"]-147600/83350)<1e-12
    assert abs(result["actions"]["WAIT_1H"]["difference_in_btc_vs_buy_now"])<1e-12
    r=compare(now,{**prices,"2h":82000.},prediction_anchor=now,capital=147600,markup=400)
    assert r["actions"]["WAIT_1H"]["acquired_btc"]>r["actions"]["BUY_NOW"]["acquired_btc"]
    try:
        compare(now,{k:v for k,v in prices.items() if k!="5h"},prediction_anchor=now)
    except ValueError:
        pass
    else:raise AssertionError("missing execution horizon was silently inferred")
    # Paired scenario signs cannot be reshuffled; exact real signs propagate.
    scenarios={h:[0.0]*52 for h in ("1h","2h","5h","morning_plus_1h")}
    scenarios["2h"]=[math.log(.99)]*52
    paired=compare(now,prices,prediction_anchor=now,paired_errors=scenarios)
    assert paired["uncertainty"]["WAIT_1H"]["fraction_wait_better"]==1.0
    # Independent release time invalidates all paired buy/wait quantities.
    for seconds in (1,299,900):
        invalid=compare(now+timedelta(seconds=seconds),prices,prediction_anchor=now)
        assert invalid["status"]=="NO_EXECUTION_ALIGNED_FORECAST"
        assert all(x["acquired_btc"] is None for x in invalid["actions"].values())
    # The morning crossing cannot silently compare today's 09:00 with tomorrow's.
    start=datetime(2026,10,12,4,55,tzinfo=UTC)  # 07:55 MSK
    published=datetime(2026,10,12,5,1,tzinfo=UTC) # 08:01 MSK
    invalid=compare(published,prices,prediction_anchor=start)
    assert invalid["status"]=="NO_EXECUTION_ALIGNED_FORECAST"
    assert invalid["actions"]["WAIT_TILL_08_MSK"]["due_utc"]=="2026-10-13T06:00:00+00:00"
    assert invalid["actions"]["WAIT_TILL_08_MSK"]["forecast_target_utc"]=="2026-10-12T06:00:00+00:00"
    # A paired NaN in a VALID alignment must be explicitly rejected.
    bad={h:[0.0]*52 for h in ("1h","2h","5h","morning_plus_1h")}
    bad["2h"][4]=float("nan")
    try: compare(now,prices,prediction_anchor=now,paired_errors=bad)
    except ValueError:pass
    else:raise AssertionError("nonfinite paired residual accepted")
    # A future 1h outcome must be NaN for an anchor without 12 forward bars.
    n=420
    start=int(datetime(2026,10,1,tzinfo=UTC).timestamp()*1000)
    times_np=np.asarray([start+i*300000 for i in range(n)],dtype=np.int64)
    vals=np.asarray([[83000.0,83100.,82900.,83000.,10.,20.,5.]]*n)
    idx=np.asarray([n-2])
    labels=label_arrays(times_np,vals,idx)
    for h in PRICE_TARGETS:
        assert np.isnan(labels[h][0]),"future execution price backfilled: "+h
    for e in EVENT_TARGETS:
        assert np.isnan(labels[e][0]),"future event backfilled: "+e
    print("BTC_V7_OTC_DELAY_NO_LOOKAHEAD_TESTS_PASS")

if __name__=="__main__":run()
