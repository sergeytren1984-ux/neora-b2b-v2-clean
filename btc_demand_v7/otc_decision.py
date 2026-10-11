"""OTC BTC units comparison. The order takes one hour, so buying now is NOT instant."""
from __future__ import annotations
from datetime import datetime,timedelta,timezone
from statistics import mean
import math

UTC=timezone.utc
BUDGET=147600.0
TARGET={"BUY_NOW":"1h","WAIT_1H":"2h","WAIT_4H":"5h","WAIT_TILL_08_MSK":"morning_plus_1h"}
REQUIRED=("1h","2h","4h","5h","morning","morning_plus_1h")

def next_morning(now:datetime)->datetime:
    if now.tzinfo is None:raise ValueError("timezone required")
    utc=now.astimezone(UTC)
    out=utc.replace(hour=5,minute=0,second=0,microsecond=0)
    return out if out>utc else out+timedelta(days=1)

def schedules(now:datetime)->dict[str,datetime]:
    if now.tzinfo is None:raise ValueError("timezone required")
    utc=now.astimezone(UTC)
    return {"BUY_NOW":utc+timedelta(hours=1),"WAIT_1H":utc+timedelta(hours=2),
            "WAIT_4H":utc+timedelta(hours=5),
            "WAIT_TILL_08_MSK":next_morning(utc)+timedelta(hours=1)}

def compare(now:datetime,prices:dict[str,float],*,capital:float=BUDGET,
            markup:float=350.,paired_errors:dict[str,list[float]]|None=None,
            demonstrated_price_skill:bool=False)->dict:
    if not math.isfinite(capital) or capital<=0 or not math.isfinite(markup) or not 0<=markup<=10000:
        raise ValueError("invalid OTC inputs")
    for name in REQUIRED:
        if name not in prices or not math.isfinite(float(prices[name])) or float(prices[name])<=0:
            raise ValueError("missing/invalid forecast "+name)
    due=schedules(now)
    rows={}
    for name,target in TARGET.items():
        price=float(prices[target])
        rows[name]={"due_utc":due[name].isoformat(),"horizon":target,"predicted_spot":price,
                    "executed_otc_price":price+markup,"acquired_btc":capital/(price+markup)}
    baseline=rows["BUY_NOW"]["acquired_btc"]
    for a in rows:rows[a]["difference_in_btc_vs_buy_now"]=rows[a]["acquired_btc"]-baseline
    sensitivities={}
    if paired_errors:
        if any(h not in paired_errors for h in TARGET.values()):raise ValueError("paired residual horizon missing")
        n=len(paired_errors["1h"])
        if n<50 or any(len(paired_errors[h])!=n for h in TARGET.values()):
            raise ValueError("incomplete paired residual grid")
        for name,h in TARGET.items():
            if name=="BUY_NOW":continue
            changes=[]
            for i in range(n):
                pb=float(prices["1h"])*math.exp(float(paired_errors["1h"][i]))
                pw=float(prices[h])*math.exp(float(paired_errors[h][i]))
                changes.append(capital/(pw+markup)-capital/(pb+markup))
            sort=sorted(changes)
            sensitivities[name]={"n":n,"mean_btc":mean(changes),"p05_btc":sort[int(.05*(n-1))],
                                 "p95_btc":sort[int(.95*(n-1))],
                                 "fraction_wait_better":sum(x>0 for x in changes)/n,
                                 "status":"VALIDATION_RESIDUAL_SENSITIVITY_NOT_CALIBRATED"}
    decision="NO_VERIFIED_EDGE"
    if demonstrated_price_skill and sensitivities and max(x["p05_btc"] for x in sensitivities.values())>0:
        decision="VALIDATION_ADVANTAGE_ONLY_NOT_TRADING_AUTHORITY"
    return {"schema":"btc-otc-delay-v1","trading_authority":False,"market_order_placed":False,
            "budget_usdt":capital,"otc_markup_per_btc":markup,"execution_delay_hours":1,
            "anchor_utc":now.astimezone(UTC).isoformat(),
            "status":decision,"actions":rows,"uncertainty":sensitivities}
