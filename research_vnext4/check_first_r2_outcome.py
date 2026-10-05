"""One-off factual reconstruction of the first vNext4R2 15m forecast outcome.
This does not write to the prospective evidence branch and cannot repair a missing outcome.
"""
import json, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"research_vnext4/first_r2_outcome_check.json"
anchor=datetime.fromisoformat("2026-10-05T00:45:00+00:00")
due=datetime.fromisoformat("2026-10-05T04:45:00+00:00")
lower=85755.78989999999
upper=87488.2301
start_ms=int(anchor.timestamp()*1000)
end_ms=int(due.timestamp()*1000)-1
q=urllib.parse.urlencode({"symbol":"BTCUSDT","interval":"15m","startTime":start_ms,"endTime":end_ms,"limit":100})
req=urllib.request.Request("https://data-api.binance.vision/api/v3/klines?"+q,headers={"User-Agent":"btc-r2-outcome-check"})
with urllib.request.urlopen(req,timeout=30) as r:
    rows=json.loads(r.read())
outcome="NEITHER";touch=None
for x in rows:
    dn=float(x[3])<=lower; up=float(x[2])>=upper
    t=datetime.fromtimestamp((int(x[6])+1)/1000,timezone.utc).isoformat()
    if dn and up:
        outcome="AMBIGUOUS_SAME_BAR";touch=t;break
    if dn:
        outcome="LOWER_FIRST";touch=t;break
    if up:
        outcome="UPPER_FIRST";touch=t;break
result={
  "status":"FACTUAL_RECONSTRUCTION_ONLY_NOT_PROSPECTIVE_REPAIR",
  "anchor_utc":anchor.isoformat(),"due_utc":due.isoformat(),
  "lower":lower,"upper":upper,"candle_count":len(rows),
  "first_open":rows[0][0] if rows else None,
  "last_close_ms":rows[-1][6] if rows else None,
  "period_high":max(float(x[2]) for x in rows) if rows else None,
  "period_low":min(float(x[3]) for x in rows) if rows else None,
  "period_last_close":float(rows[-1][4]) if rows else None,
  "outcome":outcome,"first_touch_time_utc":touch
}
OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
print(json.dumps(result,ensure_ascii=False,indent=2))
