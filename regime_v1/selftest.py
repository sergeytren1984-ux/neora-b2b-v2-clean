from datetime import datetime,timezone,timedelta
from regime_challenger import forecast

def candles(direction=0.0):
    out=[]; p=84000.0
    t=datetime(2026,9,25,tzinfo=timezone.utc)
    for i in range(169):
        prev=p; p*=1.0+direction
        hi=max(prev,p)*1.0015; lo=min(prev,p)*0.9985
        out.append({"open_time":(t+timedelta(hours=i)).isoformat(),"close_time":(t+timedelta(hours=i+1)).isoformat(),
                    "open":prev,"high":hi,"low":lo,"close":p,"volume":1000+i%7*30,"trades":10000+i%9*80,
                    "taker_buy_base":(0.54 if direction>0 else 0.46 if direction<0 else 0.50)*(1000+i%7*30)})
    return out
def ctx(ts,oi,dxy,nq,y,etf,funding=.00005):
    return {"captured_at_utc":ts.isoformat(),"factors":{
      "open_interest":{"status":"VALID","value_btc":oi},"funding":{"status":"VALID","value":funding},
      "dxy":{"status":"VALID","value":dxy},"nasdaq_futures":{"status":"VALID","value":nq},
      "us10y":{"status":"VALID","value":y},"etf_flows":{"status":"VALID","numeric_value":etf}}}
now=datetime(2026,10,2,8,tzinfo=timezone.utc)
bull=forecast(candles(.0008),now,ctx(now-timedelta(minutes=1),30000,101.8,31000,5.20,180),ctx(now-timedelta(hours=1),29000,102.1,30700,5.30,0))
bear=forecast(candles(-.0008),now,ctx(now-timedelta(minutes=1),30000,102.3,30400,5.38,-180),ctx(now-timedelta(hours=1),29000,102.0,30700,5.28,0))
flat=forecast(candles(0),now,ctx(now-timedelta(minutes=1),29000,102,30700,5.28,0),ctx(now-timedelta(hours=1),29000,102,30700,5.28,0))
assert bull["regime_probabilities"]["upside"]>bull["regime_probabilities"]["range"]
assert bull["risk_waiting_for_lower_price_pct"]>=65
assert bear["regime_probabilities"]["downside"]>bear["regime_probabilities"]["range"]
assert flat["regime_probabilities"]["range"]>flat["regime_probabilities"]["upside"]
assert flat["regime_probabilities"]["range"]>flat["regime_probabilities"]["downside"]
print("REGIME_V1_SELFTEST_OK")
