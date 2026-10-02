from __future__ import annotations
import json, os, urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent / "regime_v3"))

from model import forecast
from context_trust import context_pair

UTC=timezone.utc
REPO="sergeytren1984-ux/neora-b2b-v2-clean"
ROOT=Path(__file__).resolve().parent
PROTOCOL=json.loads((ROOT/"regime_v3/protocol.json").read_text())

def fetch_klines():
    url="https://data-api.binance.vision/api/v3/klines?symbol=BTCUSDT&interval=1h&limit=500"
    req=urllib.request.Request(url, headers={"User-Agent":"btc-regime-v3-audit-repro"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())

def select(raw, anchor):
    out=[]
    for x in raw:
        opened=datetime.fromtimestamp(int(x[0])/1000, UTC)
        closed=opened+timedelta(hours=1)
        if closed<=anchor:
            out.append({
                "open_time":opened.isoformat(),"close_time":closed.isoformat(),
                "open":float(x[1]),"high":float(x[2]),"low":float(x[3]),"close":float(x[4]),
                "volume":float(x[5]),"trades":int(x[8]),"taker_buy_base":float(x[9])
            })
    if len(out)<169:
        raise RuntimeError(f"not enough candles for {anchor.isoformat()}: {len(out)}")
    return out[-169:]

raw=fetch_klines()
token=os.environ.get("GITHUB_TOKEN")
anchors=[]
t=datetime(2026,10,1,14,0,tzinfo=UTC)
end=datetime(2026,10,2,8,0,tzinfo=UTC)
while t<=end:
    anchors.append(t)
    t+=timedelta(hours=1)

rows=[]
for anchor in anchors:
    c=select(raw,anchor)
    pair=context_pair(REPO,anchor,PROTOCOL,token)
    out=forecast(c,pair,PROTOCOL)
    rows.append({
        "anchor_utc":anchor.isoformat(),
        "anchor_msk":(anchor+timedelta(hours=3)).strftime("%Y-%m-%d %H:%M"),
        "price":c[-1]["close"],
        "regime_state":out["regime_state"],
        "regime_score":out["regime_score"],
        "external_score":out["external"]["score"],
        "breakout_memory":out["features"]["breakout_memory"],
        "confirmed_breakout":out["features"]["confirmed_breakout"],
        "transition":out["features"]["transition"],
        "trend_quality":out["features"]["trend_quality"],
        "h1":out["horizons"]["1h"]["probabilities"],
        "h4":out["horizons"]["4h"]["probabilities"],
        "h24":out["horizons"]["24h"]["probabilities"]
    })
print("REAL_MARKET_REPLAY_BEGIN")
for row in rows:
    print(json.dumps(row, sort_keys=True))
print("REAL_MARKET_REPLAY_END")
