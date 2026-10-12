"""Fresh BTC demand and positioning receipts, prospective only and keyless.

Binance: spot 1m/5m closed candles. OKX: BTC open-interest history,
current swap funding and depth. Neither old candles nor OKX snapshots
are represented as pre-existing timestamped historical book data.
Failures in optional derivatives MUST NOT fabricate inputs.
"""
from __future__ import annotations
import argparse
import datetime as dt
import hashlib,json,math,pathlib,time,urllib.parse,urllib.request,urllib.error
UTC=dt.timezone.utc
SOURCE_SPOT="https://data-api.binance.vision/api/v3/klines"
SOURCE_OI="https://www.okx.com/api/v5/rubik/stat/contracts/open-interest-volume"
SOURCE_FUNDING="https://www.okx.com/api/v5/public/funding-rate"
SOURCE_BOOK="https://www.okx.com/api/v5/market/books"
SOURCE_SWAP="https://www.okx.com/api/v5/market/trades"

def json_get(url,query,timeout=15):
    req=urllib.request.Request(url+"?"+urllib.parse.urlencode(query),headers={"User-Agent":"btc-v7-point-in-time-research"})
    with urllib.request.urlopen(req,timeout=timeout) as resp:
        if resp.status!=200:raise RuntimeError("market HTTP "+str(resp.status))
        return json.load(resp)

def strict_closed(rows,interval_ms,anchor_ms,min_history):
    if not isinstance(rows,list) or len(rows)<min_history:raise ValueError("insufficient spot candle history")
    usable=[r for r in rows if int(r[6])+1<=anchor_ms]
    if len(usable)<min_history or int(usable[-1][6])+1!=anchor_ms:raise ValueError("stale spot close")
    prev=None
    for r in usable:
        op,hi,lo,cl,volume,taker=map(float,[r[1],r[2],r[3],r[4],r[5],r[9]])
        if not (0<lo<=min(op,cl)<=max(op,cl)<=hi and 0<=taker<=volume):
            raise ValueError("invalid spot OHLCV/taker")
        if int(r[6])+1!=int(r[0])+interval_ms:raise ValueError("unclosed candle")
        if prev is not None and int(r[0])-prev!=interval_ms:raise ValueError("spot candle gap")
        prev=int(r[0])
    return usable

def open_interest_state(data,cutoff):
    if data.get("code")!="0":raise ValueError("OI provider failed")
    entries=[]
    for r in data.get("data",[]):
        ts=int(r[0]); val=float(r[1])
        if ts<=cutoff and math.isfinite(val) and val>0:entries.append((ts,val))
    entries.sort()
    if len(entries)<15 or cutoff-entries[-1][0]>15*60*1000:
        raise ValueError("no current OI sample")
    now_t,now_v=entries[-1]
    previous_15=[x for x in entries if x[0]<=now_t-15*60*1000]
    previous_60=[x for x in entries if x[0]<=now_t-60*60*1000]
    if not previous_15:raise ValueError("missing OI 15m reference")
    return {
        "source":"OKX rubik BTC aggregated contracts open interest USD",
        "vendor_observation_ms":now_t,
        "age_seconds":round((cutoff-now_t)/1000),
        "oi_usd":now_v,
        "oi_change_15m_pct":100*(now_v/previous_15[-1][1]-1),
        "oi_change_60m_pct":100*(now_v/previous_60[-1][1]-1) if previous_60 else None,
        "numerically_trained_with_binance_oi":False,
    }

def liquidity_state(data):
    if data.get("code")!="0" or not data.get("data"):raise ValueError("book provider failed")
    b=data["data"][0]
    bids=b.get("bids",[])[:10];asks=b.get("asks",[])[:10]
    if not bids or not asks:raise ValueError("empty depth")
    bid_price=float(bids[0][0]);ask_price=float(asks[0][0])
    if bid_price<=0 or ask_price<=bid_price:raise ValueError("crossed order book")
    bs=sum(float(x[1]) for x in bids)
    ab=sum(float(x[1]) for x in asks)
    if bs<0 or ab<0 or bs+ab==0:raise ValueError("invalid book quantities")
    return {"source":"OKX BTC-USDT-SWAP top 10 depth, raw contract size units",
            "vendor_timestamp_ms":int(b["ts"]),
            "spread_bps":10000*(ask_price-bid_price)/((bid_price+ask_price)/2),
            "top10_size_imbalance":(bs-ab)/(bs+ab),
            "book_depth_is_historical":False}

def funding_state(data,request_started_ms,response_received_ms):
    if data.get("code")!="0" or not data.get("data"):
        raise ValueError("invalid funding response")
    item=data["data"][0]
    if item.get("instId")!="BTC-USDT-SWAP":
        raise ValueError("unexpected instrument")
    timestamp=int(item["ts"])
    if not request_started_ms-180000<=timestamp<=response_received_ms:
        raise ValueError("observation out of admissible time")
    value=float(item["fundingRate"])
    if not math.isfinite(value):
        raise ValueError("nonfinite funding rate")
    return {"source":"OKX BTC-USDT-SWAP current projected funding",
            "value":value,"vendor_observation_ms":timestamp,
            "funding_time_ms":int(item["fundingTime"])}


def spot_state(one_min,anchor_ms):
    c=[float(r[4]) for r in one_min];h=[float(r[2]) for r in one_min]
    v=[float(r[5]) for r in one_min];t=[float(r[9]) for r in one_min]
    if len(c)<75:raise ValueError("insufficient spot minutes")
    k=len(c)-1
    buy15=sum(t[k-14:k+1])/max(sum(v[k-14:k+1]),1e-12)
    volume15=sum(v[k-14:k+1])
    previous_hour=4*sum(v[k-74:k-14])/max(60,1)
    hourly_mean15=sum(v[k-74:k-14])/4
    vol_multiple=volume15/max(hourly_mean15,1e-12)
    prev1h_high=max(h[k-74:k-14])
    ret15=100*(c[k]/c[k-15]-1)
    return {
        "reference_spot":c[k],
        "15m_price_change_pct":ret15,
        "15m_taker_buy_fraction":buy15,
        "15m_volume_vs_previous_1h_quarter":vol_multiple,
        "previous_1h_high":prev1h_high,
        "breakout_pct":100*(c[k]/prev1h_high-1),
    }

def collect():
    obtained=int(time.time()*1000)
    # Ensure last full 5-min closed candle is available; exact vendor close verified.
    anchor_ms=(obtained//300000)*300000
    one=json_get(SOURCE_SPOT,{"symbol":"BTCUSDT","interval":"1m","endTime":anchor_ms-1,"limit":220})
    five=json_get(SOURCE_SPOT,{"symbol":"BTCUSDT","interval":"5m","endTime":anchor_ms-1,"limit":1000})
    one=strict_closed(one,60000,anchor_ms,200)
    five=strict_closed(five,300000,anchor_ms,600)
    spot_recorded=int(time.time()*1000)
    state={"schema":"btc-v7-live-shadow-snapshot-v1",
           "anchor_utc":dt.datetime.fromtimestamp(anchor_ms/1000,UTC).isoformat(),
           "retrieved_at_utc":None,
           "spot_received_utc":dt.datetime.fromtimestamp(spot_recorded/1000,UTC).isoformat(),
           "source_policy":{"spot_1m":"REQUIRED","spot_5m":"REQUIRED",
                            "oi_okx":"OPTIONAL","funding_okx":"OPTIONAL","book_okx":"OPTIONAL"},
           "symbol":"BTCUSDT","raw_source":"Binance data-api closed 1m/5m",
           "no_backfill":True,"one_min_rows":one,"five_min_rows":five,
           "raw_optional":{},"optional_status":{},"optional_receipts":{}}
    for name,url,query in (
        ("oi_okx",SOURCE_OI,{"ccy":"BTC","period":"5m"}),
        ("funding_okx",SOURCE_FUNDING,{"instId":"BTC-USDT-SWAP"}),
        ("book_okx",SOURCE_BOOK,{"instId":"BTC-USDT-SWAP","sz":20}),
    ):
        request_start=int(time.time()*1000)
        try:
            data=json_get(url,query)
            response_end=int(time.time()*1000)
            state["raw_optional"][name]=data
            state["optional_status"][name]={"state":"AVAILABLE","source":url}
        except Exception as exc:
            response_end=int(time.time()*1000)
            state["optional_status"][name]={"state":"UNAVAILABLE","reason":type(exc).__name__}
        state["optional_receipts"][name]={
            "request_started_ms":request_start,
            "response_received_ms":response_end,
            "url":url,"query":query,
        }
    recorded=int(time.time()*1000)
    state["retrieved_at_utc"]=dt.datetime.fromtimestamp(recorded/1000,UTC).isoformat()
    observation=spot_state(one,anchor_ms)
    observation["oi"]=None;observation["book"]=None;observation["funding"]=None
    for name,compute in (("oi_okx",lambda d:open_interest_state(d,recorded)),
                         ("book_okx",liquidity_state)):
        if name not in state["raw_optional"]:continue
        try:
            value=compute(state["raw_optional"][name])
            if name=="book_okx" and not (0<=recorded-value["vendor_timestamp_ms"]<=60_000):
                raise ValueError("future or stale order book")
            observation["oi" if name=="oi_okx" else "book"]=value
        except Exception as e:
            state["optional_status"][name]={"state":"UNAVAILABLE_OR_STALE","reason":type(e).__name__}
    if "funding_okx" in state["raw_optional"]:
        try:
            raw=state["raw_optional"]["funding_okx"]
            if raw.get("code")!="0" or not raw.get("data"):raise ValueError("invalid funding")
            d=raw["data"][0]
            observation["funding"]={"source":"OKX BTC-USDT-SWAP current projected funding",
                                    "value":float(d["fundingRate"]),
                                    "funding_time_ms":int(d["fundingTime"])}
        except Exception as e:state["optional_status"]["funding_okx"]={"state":"INVALID","reason":type(e).__name__}
    up=observation["15m_price_change_pct"]>0.20 and observation["15m_taker_buy_fraction"]>0.58 and observation["15m_volume_vs_previous_1h_quarter"]>2 and observation["breakout_pct"]>.10
    down=observation["15m_price_change_pct"]<-.20 and observation["15m_taker_buy_fraction"]<.42 and observation["15m_volume_vs_previous_1h_quarter"]>2
    if up:state_name="UNCALIBRATED_UP_DEMAND_WATCH"
    elif down:state_name="UNCALIBRATED_DOWN_SUPPLY_WATCH"
    else:state_name="NO_EXTREME_FLOW_WATCH"
    if observation["oi"] is None:pos="POSITIONING_UNAVAILABLE"
    elif observation["oi"]["oi_change_15m_pct"]>.15:pos="OI_EXPANDING_POSSIBLE_NEW_POSITIONS"
    elif observation["oi"]["oi_change_15m_pct"]<-.15:pos="OI_CONTRACTING_POSSIBLE_POSITION_CLOSURE"
    else:pos="OI_NEAR_FLAT"
    observation["demand_watch"]=state_name
    observation["positioning_context"]=pos
    observation["calibrated_prediction"]=False
    observation["trading_authority"]=False
    state["observation"]=observation
    return state

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--out",required=True)
    args=ap.parse_args()
    p=pathlib.Path(args.out);p.mkdir(parents=True,exist_ok=True)
    data=collect()
    canonical=(json.dumps(data,ensure_ascii=False,allow_nan=False,sort_keys=True,separators=(",",":"))+"\n").encode()
    (p/"snapshot.json").write_bytes(canonical)
    d={"schema":"btc-v7-shadow-observation-v1",
       "sha256_raw_snapshot":hashlib.sha256(canonical).hexdigest(),
       "anchor_utc":data["anchor_utc"],
       "retrieved_at_utc":data["retrieved_at_utc"],
       "spot":data["observation"]["reference_spot"],
       "demand_watch":data["observation"]["demand_watch"],
       "positioning_context":data["observation"]["positioning_context"],
       "spot_signal":{k:v for k,v in data["observation"].items() if k not in ("oi","book","funding")},
       "oi":data["observation"]["oi"],"book":data["observation"]["book"],
       "funding":data["observation"]["funding"],
       "source_status":data["optional_status"],
       "prospective_skill_proven":False,"trading_authority":False}
    (p/"observation.json").write_text(json.dumps(d,ensure_ascii=False,allow_nan=False,sort_keys=True,indent=2)+"\n")
    print("BTC_V7_LIVE_SHADOW_RECEIPT",json.dumps({k:d[k] for k in ("anchor_utc","spot","demand_watch","positioning_context","prospective_skill_proven")},ensure_ascii=False),flush=True)

if __name__=="__main__":main()
