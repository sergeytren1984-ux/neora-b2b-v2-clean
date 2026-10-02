from __future__ import annotations
import json,os,subprocess,urllib.request,hashlib
from datetime import datetime,timezone,timedelta
from pathlib import Path
from regime_challenger import forecast
UTC=timezone.utc; ROOT=Path(__file__).resolve().parents[1]; OUT=ROOT/"regime_events"; START=datetime(2026,10,2,8,tzinfo=UTC)
IDENTITY="https://github.com/sergeytren1984-ux/neora-b2b-v2-clean/.github/workflows/btc-regime-v1.yml@refs/heads/main"
ISSUER="https://token.actions.githubusercontent.com"
def now(): return datetime.now(UTC)
def canon(x): return json.dumps(x,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()+b"\n"
def sha(b): return hashlib.sha256(b).hexdigest()
def run(*a): return subprocess.run(a,check=True,capture_output=True,text=True,timeout=90).stdout
def fetch_json(url):
    h={"User-Agent":"btc-regime-v1"}
    tok=os.environ.get("GITHUB_TOKEN")
    if tok and "api.github.com" in url: h["Authorization"]="Bearer "+tok
    with urllib.request.urlopen(urllib.request.Request(url,headers=h),timeout=15) as r: return json.loads(r.read())
def events():
    OUT.mkdir(exist_ok=True); xs=[]
    for p in sorted(OUT.glob("*.json")):
        if p.name.endswith(".sigstore.json"): continue
        xs.append(json.loads(p.read_text()))
    return xs
def publish(obj):
    prev=events(); seq=len(prev)+1
    obj={"schema":"btc-regime-prospective-event-v1","sequence":seq,"previous_hash":sha(canon(prev[-1])) if prev else None,
         "workflow_commit":os.environ["GITHUB_SHA"],**obj}
    p=OUT/f"{seq:08d}.json"; p.write_bytes(canon(obj)); b=p.with_suffix(".sigstore.json")
    run("cosign","sign-blob","--yes","--bundle",str(b),str(p))
    run("cosign","verify-blob",str(p),"--bundle",str(b),"--certificate-identity",IDENTITY,"--certificate-oidc-issuer",ISSUER)
    run("git","add",str(p.relative_to(ROOT)),str(b.relative_to(ROOT)))
    run("git","commit","-m",f"BTC regime evidence #{seq}: {obj['type']}")
    run("git","push","origin","HEAD:btc-regime-v1")
def candles(anchor):
    u="https://data-api.binance.vision/api/v3/klines?symbol=BTCUSDT&interval=1h&limit=200"
    raw=fetch_json(u); out=[]
    for x in raw:
        opened=datetime.fromtimestamp(int(x[0])/1000,UTC); closed=opened+timedelta(hours=1)
        if closed<=anchor:
            out.append({"open_time":opened.isoformat(),"close_time":closed.isoformat(),"open":float(x[1]),"high":float(x[2]),"low":float(x[3]),"close":float(x[4]),"volume":float(x[5]),"trades":int(x[8]),"taker_buy_base":float(x[9])})
    if len(out)<169 or datetime.fromisoformat(out[-1]["close_time"])!=anchor: raise ValueError("closed candle anchor mismatch")
    return out[-169:]
def contexts(anchor):
    api="https://api.github.com/repos/sergeytren1984-ux/neora-b2b-v2-clean/contents/context_live?ref=btc-context"
    arr=fetch_json(api); names=sorted(x["name"] for x in arr if x["name"].endswith("Z.json") and not x["name"].endswith(".sigstore.json"))
    chosen=[]
    for n in reversed(names):
        ts=datetime.strptime(n[:15],"%Y%m%dT%H%M%S").replace(tzinfo=UTC)
        if ts<=anchor: chosen.append(n)
        if len(chosen)==2: break
    if len(chosen)<2: return None,None,[]
    docs=[]
    for n in reversed(chosen):
        url=f"https://raw.githubusercontent.com/sergeytren1984-ux/neora-b2b-v2-clean/btc-context/context_live/{n}"
        docs.append(fetch_json(url))
    return docs[-1],docs[-2],list(reversed(chosen))
def main():
    t=now(); ev=events()
    if not ev:
        if t>=START: raise ValueError("schedule registration missed")
        publish({"type":"SCHEDULE_REGISTERED","idempotency_key":"btc-regime-v1-20261002","start_utc":START.isoformat(),
                 "protocol_sha256":sha((ROOT/"regime_v1/protocol.json").read_bytes()),"trading_authority":False}); return
    anchor=t.replace(minute=0,second=0,microsecond=0)
    if anchor<START or t-anchor>timedelta(minutes=20): return
    slot=anchor.strftime("%Y%m%dT%H%M%SZ"); key="regime:"+slot
    if any(x.get("idempotency_key")==key for x in ev): return
    c=candles(anchor); ctx,prev,names=contexts(anchor); out=forecast(c,anchor,ctx,prev)
    publish({"type":"REGIME_FORECAST_ISSUED","idempotency_key":key,"slot":slot,"anchor_utc":anchor.isoformat(),
             "reference_price":c[-1]["close"],"context_snapshots":names,"output":out,
             "publication_authorized":False,"trading_authority":False})
if __name__=="__main__": main()
