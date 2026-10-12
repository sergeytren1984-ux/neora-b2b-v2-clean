"""Fail-closed operator OTC quotes and reproducible joint proxy stress."""
from datetime import datetime,timezone
import math
from btc_demand_v7.prospective_core import when
BUDGET=147600.

def actual_quote(action,quote,budget=BUDGET):
    mandatory=("requested_at_utc","reference_spot","quote_usdt_per_btc","accepted",
               "filled_btc","total_paid_usdt","filled_at_utc")
    if not quote or not all(k in quote for k in mandatory):
        return {"action":action,"status":"MISSING_EXECUTABLE_QUOTE","acquired_btc":None}
    if quote["accepted"] is None:
        return {"action":action,"status":"OPERATOR_ACCEPTANCE_UNKNOWN","acquired_btc":None}
    reference=float(quote["reference_spot"]);price=float(quote["quote_usdt_per_btc"])
    if not (math.isfinite(reference) and math.isfinite(price) and reference>0 and price>0):
        raise ValueError("invalid operator quote")
    requested=when(quote["requested_at_utc"])
    finished=when(quote["filled_at_utc"]) if quote["filled_at_utc"] is not None else None
    if finished is not None and finished<requested:raise ValueError("fill precedes request")
    if quote["accepted"] is False:
        if quote["filled_btc"] not in (0,None):raise ValueError("rejected quote reports fill")
        return {"action":action,"status":"OPERATOR_REJECTED","acquired_btc":0.}
    if finished is None or quote["filled_btc"] is None or quote["total_paid_usdt"] is None:
        return {"action":action,"status":"ACCEPTED_UNFILLED","acquired_btc":None}
    paid=float(quote["total_paid_usdt"]);qty=float(quote["filled_btc"])
    if not (math.isfinite(paid) and math.isfinite(qty) and 0<=paid<=budget and qty>=0):
        raise ValueError("invalid quantity or cost")
    return {"action":action,"status":"FILLED_FULL" if paid==budget else "FILLED_PARTIAL",
            "acquired_btc":qty,"spent_usdt":paid,"unspent_usdt":budget-paid,
            "latency_minutes":(finished-requested).total_seconds()/60,
            "filled_at_utc":finished.isoformat()}

def joint_proxy(scenarios,budget=BUDGET):
    """No fabricated operator acceptance. Same future scenario for every action."""
    results=[]
    actions=("BUY_NOW","WAIT_1H","WAIT_4H","WAIT_TILL_08_MSK")
    for scenario in scenarios:
        ref=float(scenario["reference_spot"])
        reject=float(scenario["operator_threshold_usdt"])
        if not(math.isfinite(ref) and ref>0 and math.isfinite(reject) and 300<=reject<=500):
            raise ValueError("invalid scenario guard")
        output={}
        for name in actions:
            data=scenario["actions"][name]
            price=float(data["market_spot_at_execution"])
            premium=float(data["operator_markup_per_btc"])
            fill_fraction=float(data["fill_fraction"])
            minutes=float(data["actual_delay_minutes"])
            if not all(math.isfinite(x) for x in (price,premium,fill_fraction,minutes)):
                raise ValueError("non-finite execution scenario")
            if not(price>0 and 300<=premium<=400 and 0<=fill_fraction<=1 and minutes>=0):
                raise ValueError("invalid scenario values")
            if abs(price-ref)>reject:
                output[name]={"status":"REJECTED_BY_OPERATOR_GUARD","acquired_btc":0.}
            else:
                output[name]={"status":"RESEARCH_PROXY_PARTIAL_OR_FULL",
                    "acquired_btc":budget*fill_fraction/(price+premium),
                    "delay_minutes":minutes}
        for v in output.values():
            v["btc_difference_vs_buy_now"]=v["acquired_btc"]-output["BUY_NOW"]["acquired_btc"]
        results.append({"scenario_id":scenario["scenario_id"],"actions":output})
    return {"schema":"btc-v7r2-otc-joint-stress-v1",
            "status":"RESEARCH_PROXY_NO_EXECUTABLE_OTC_QUOTES",
            "observed_joint_counterfactuals":False,
            "trading_authority":False,"scenarios":results}
