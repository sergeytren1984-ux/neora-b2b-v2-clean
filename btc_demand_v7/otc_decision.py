"""OTC BTC comparison with exact forecast-target and execution-time contract.

If no prediction exists for the exact execution timestamp, returns a fail-closed
NO_EXECUTION_ALIGNED_FORECAST instead of comparing prices from another day/hour.
No OTC action is executed; price forecasts alone are not executable quotes.
"""
from __future__ import annotations
from datetime import datetime,timedelta,timezone
from statistics import mean
import math

UTC=timezone.utc
BUDGET=147600.0
TARGET={"BUY_NOW":"1h","WAIT_1H":"2h","WAIT_4H":"5h","WAIT_TILL_08_MSK":"morning_plus_1h"}
REQUIRED=("1h","2h","4h","5h","morning","morning_plus_1h")

def utc(value:datetime)->datetime:
    if value.tzinfo is None:raise ValueError("timezone required")
    return value.astimezone(UTC)

def next_morning(now:datetime)->datetime:
    u=utc(now)
    out=u.replace(hour=5,minute=0,second=0,microsecond=0)
    return out if out>u else out+timedelta(days=1)

def schedules(now:datetime)->dict[str,datetime]:
    now=utc(now)
    return {"BUY_NOW":now+timedelta(hours=1),
            "WAIT_1H":now+timedelta(hours=2),
            "WAIT_4H":now+timedelta(hours=5),
            "WAIT_TILL_08_MSK":next_morning(now)+timedelta(hours=1)}

def prediction_target_times(anchor:datetime)->dict[str,datetime]:
    """Exact target endpoint for every price head, relative to its CLOSED candle."""
    a=utc(anchor)
    morning=next_morning(a)
    return {"1h":a+timedelta(hours=1),"2h":a+timedelta(hours=2),
            "4h":a+timedelta(hours=4),"5h":a+timedelta(hours=5),
            "morning":morning,"morning_plus_1h":morning+timedelta(hours=1)}

def compare(now:datetime,prices:dict[str,float],*,prediction_anchor:datetime,
            capital:float=BUDGET,markup:float=350.,
            paired_errors:dict[str,list[float]]|None=None,
            demonstrated_price_skill:bool=False)->dict:
    execution_now=utc(now)
    anchor=utc(prediction_anchor)
    if not math.isfinite(capital) or capital<=0 or not math.isfinite(markup) or not 0<=markup<=10000:
        raise ValueError("invalid OTC inputs")
    for name in REQUIRED:
        if name not in prices or not math.isfinite(float(prices[name])) or float(prices[name])<=0:
            raise ValueError("missing/invalid forecast "+name)
    due=schedules(execution_now)
    forecast_targets=prediction_target_times(anchor)
    aligned=all(due[action]==forecast_targets[head] for action,head in TARGET.items())
    rows={}
    if not aligned:
        for action,h in TARGET.items():
            rows[action]={"due_utc":due[action].isoformat(),
                          "forecast_target_utc":forecast_targets[h].isoformat(),
                          "horizon":h,"status":"NO_EXECUTION_ALIGNED_FORECAST",
                          "predicted_spot":None,"executed_otc_price":None,
                          "acquired_btc":None,"difference_in_btc_vs_buy_now":None}
        return {"schema":"btc-otc-delay-v2","trading_authority":False,
                "market_order_placed":False,"budget_usdt":capital,
                "otc_markup_per_btc":markup,"execution_delay_hours":1,
                "anchor_utc":anchor.isoformat(),"published_at_utc":execution_now.isoformat(),
                "status":"NO_EXECUTION_ALIGNED_FORECAST","actions":rows,
                "uncertainty":{},
                "reason":"Forecast endpoint timestamps differ from OTC execution timestamps; no interpolated or day-shifted price is permitted."}
    for action,h in TARGET.items():
        price=float(prices[h]);fill_price=price+markup
        rows[action]={"due_utc":due[action].isoformat(),
                      "forecast_target_utc":forecast_targets[h].isoformat(),
                      "horizon":h,"status":"RESEARCH_PROXY_NOT_EXECUTABLE",
                      "predicted_spot":price,"executed_otc_price":fill_price,
                      "acquired_btc":capital/fill_price}
    base=rows["BUY_NOW"]["acquired_btc"]
    for row in rows.values():
        row["difference_in_btc_vs_buy_now"]=row["acquired_btc"]-base
    sensitivities={}
    if paired_errors is not None:
        if any(h not in paired_errors for h in TARGET.values()):
            raise ValueError("paired residual horizon missing")
        n=len(paired_errors["1h"])
        if n<50 or any(len(paired_errors[h])!=n for h in TARGET.values()):
            raise ValueError("incomplete paired residual grid")
        if any(not math.isfinite(float(v)) for h in TARGET.values() for v in paired_errors[h]):
            raise ValueError("nonfinite OTC residuals")
        for action,h in TARGET.items():
            if action=="BUY_NOW":continue
            changes=[]
            for i in range(n):
                pb=float(prices["1h"])*math.exp(float(paired_errors["1h"][i]))
                pw=float(prices[h])*math.exp(float(paired_errors[h][i]))
                b=capital/(pb+markup); w=capital/(pw+markup)
                if not math.isfinite(w-b):raise ValueError("nonfinite OTC outcome")
                changes.append(w-b)
            ordered=sorted(changes)
            sensitivities[action]={"n":n,"mean_btc":mean(changes),
                "p05_btc":ordered[int(.05*(n-1))],
                "p95_btc":ordered[int(.95*(n-1))],
                "fraction_wait_better":sum(x>0 for x in changes)/n,
                "status":"VALIDATION_RESIDUAL_SENSITIVITY_NOT_CALIBRATED"}
    status="NO_VERIFIED_EDGE"
    if demonstrated_price_skill and sensitivities and max(x["p05_btc"] for x in sensitivities.values())>0:
        status="VALIDATION_ADVANTAGE_ONLY_NOT_TRADING_AUTHORITY"
    return {"schema":"btc-otc-delay-v2","trading_authority":False,
            "market_order_placed":False,"budget_usdt":capital,
            "otc_markup_per_btc":markup,"execution_delay_hours":1,
            "anchor_utc":anchor.isoformat(),"published_at_utc":execution_now.isoformat(),
            "status":status,"actions":rows,"uncertainty":sensitivities}
