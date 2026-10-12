"""OTC: missing real operator quotes, rejection and shared stress scenarios."""
import datetime as dt,copy
from btc_demand_v7.otc_execution import actual_quote,joint_proxy
UTC=dt.timezone.utc
def test():
    now=dt.datetime(2026,10,12,tzinfo=UTC)
    assert actual_quote("BUY_NOW",{})["status"]=="MISSING_EXECUTABLE_QUOTE"
    quote={"requested_at_utc":now.isoformat(),"reference_spot":83000.,
           "quote_usdt_per_btc":83350.,"accepted":True,"filled_btc":0.9,
           "total_paid_usdt":75015.,
           "filled_at_utc":(now+dt.timedelta(hours=1,minutes=5)).isoformat()}
    r=actual_quote("BUY_NOW",quote)
    assert r["status"]=="FILLED_PARTIAL" and r["acquired_btc"]==.9
    assert r["latency_minutes"]==65.
    r=actual_quote("BUY_NOW",{**quote,"accepted":False,"filled_btc":0,
                                 "total_paid_usdt":None,"filled_at_utc":None})
    assert r["status"]=="OPERATOR_REJECTED"
    try:actual_quote("BUY_NOW",{**quote,"filled_at_utc":(now-dt.timedelta(seconds=1)).isoformat()})
    except ValueError:pass
    else:raise AssertionError("fill before request accepted")
    a={x:{"market_spot_at_execution":83000.,"operator_markup_per_btc":350.,
           "fill_fraction":1.0,"actual_delay_minutes":60.}
       for x in ("BUY_NOW","WAIT_1H","WAIT_4H","WAIT_TILL_08_MSK")}
    a["WAIT_1H"]={**a["WAIT_1H"],"market_spot_at_execution":82500.}
    scenarios=[{"scenario_id":"same-market","reference_spot":83000.,
                "operator_threshold_usdt":500.,"actions":a}]
    report=joint_proxy(scenarios)
    assert report["status"]=="RESEARCH_PROXY_NO_EXECUTABLE_OTC_QUOTES"
    assert report["scenarios"][0]["actions"]["WAIT_1H"]["acquired_btc"]>0
    r=joint_proxy([{**scenarios[0],"operator_threshold_usdt":300.}])
    assert r["scenarios"][0]["actions"]["WAIT_1H"]["status"]=="REJECTED_BY_OPERATOR_GUARD"
    try:joint_proxy([{**scenarios[0],"actions":{**a,"WAIT_1H":{**a["WAIT_1H"],"operator_markup_per_btc":float("nan")}}}])
    except ValueError:pass
    else:raise AssertionError("invalid premium accepted")
    print("BTC_V7R2_REAL_OTC_REJECTION_PARTIAL_STRESS_TEST_PASS")
if __name__=="__main__":test()
