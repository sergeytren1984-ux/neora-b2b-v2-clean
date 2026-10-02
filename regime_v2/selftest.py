from datetime import datetime,timezone,timedelta
import json
from pathlib import Path
from model import forecast
from barrier import build_barrier_spec,resolve_barrier

def candles(direction=0.0):
    out=[]; p=84000.0; t=datetime(2026,9,20,tzinfo=timezone.utc)
    for i in range(169):
        prev=p; p*=1.0+direction
        v=1000+(i%7)*25
        out.append({"open_time":(t+timedelta(hours=i)).isoformat(),"close_time":(t+timedelta(hours=i+1)).isoformat(),
                    "open":prev,"high":max(prev,p)*1.0015,"low":min(prev,p)*0.9985,"close":p,
                    "volume":v,"trades":10000+i%11*70,"taker_buy_base":v*(.56 if direction>0 else .44 if direction<0 else .50)})
    return out

def context_pair(price_ret=0.0,bull=True):
    now=datetime(2026,10,2,8,tzinfo=timezone.utc); prev=now-timedelta(hours=1)
    d0={"captured_at_utc":prev.isoformat(),"factors":{
      "open_interest":{"status":"VALID","value_btc":29000},"funding":{"status":"VALID","value":.00004},
      "dxy":{"status":"VALID","value":102.1},"nasdaq_futures":{"status":"VALID","value":30700},
      "us10y":{"status":"VALID","value":5.30},"etf_flows":{"status":"VALID","numeric_value":0}}}
    d1={"captured_at_utc":now.isoformat(),"factors":{
      "open_interest":{"status":"VALID","value_btc":30000},"funding":{"status":"VALID","value":.00005},
      "dxy":{"status":"VALID","value":101.8 if bull else 102.4},"nasdaq_futures":{"status":"VALID","value":31000 if bull else 30400},
      "us10y":{"status":"VALID","value":5.20 if bull else 5.40},"etf_flows":{"status":"VALID","numeric_value":180 if bull else -180}}}
    st={k:{"available":True} for k in ("open_interest","funding","dxy","nasdaq_futures","us10y","etf_flows")}
    return {"current":d1,"previous":d0,"elapsed_seconds":3600,"current_factor_status":st,"previous_factor_status":st,
            "snapshot_names":["now","prev"],"legacy_numeric_challenger_authorized":False,"price_ret_1h":price_ret}

protocol=json.loads(Path(__file__).with_name("protocol.json").read_text())
assert abs(sum(protocol["regime_formula"].values())-1.0)<1e-12

bull=forecast(candles(.0008),context_pair(bull=True),protocol)
bear=forecast(candles(-.0008),context_pair(bull=False),protocol)
flat=forecast(candles(0),context_pair(bull=True),protocol)
assert bull["regime_probabilities"]["upside"]>bull["regime_probabilities"]["downside"]
assert bear["regime_probabilities"]["downside"]>bear["regime_probabilities"]["upside"]
for o in (bull,bear,flat):
    for h in ("1h","4h","24h"):
        p=o["horizons"][h]["probabilities"]
        assert set(p)=={"upside","range","downside"}
        assert abs(sum(p.values())-1)<1e-10
        assert o["horizons"][h]["threshold_pct"]>0

anchor=datetime(2026,10,2,8,tzinfo=timezone.utc)
spec=build_barrier_spec(100.0,1.0,anchor,protocol)[0]
assert spec["probabilities"] is None and spec["probability_status"]=="WITHHELD_UNTIL_CALIBRATED"
same=[{"close_time":(anchor+timedelta(hours=1)).isoformat(),"low":98.0,"high":102.0}]
assert resolve_barrier(spec,same,anchor)["class"]=="BOTH_SAME_BAR"
print("REGIME_V2_AUDIT_SELFTEST_OK")
