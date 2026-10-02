from __future__ import annotations
import json, os, urllib.request, subprocess, tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT/"regime_v3"))
from model import forecast
from context_trust import factor_status

UTC=timezone.utc
REPO="sergeytren1984-ux/neora-b2b-v2-clean"
PROTOCOL=json.loads((ROOT/"regime_v3/protocol.json").read_text())
IDENTITY=PROTOCOL["external_context"]["identity"]
ISSUER=PROTOCOL["external_context"]["oidc_issuer"]
KEYS=("open_interest","funding","dxy","nasdaq_futures","us10y","etf_flows")

def get(url,token=None):
    h={"User-Agent":"btc-regime-v3-independent-audit"}
    if token: h["Authorization"]="Bearer "+token
    with urllib.request.urlopen(urllib.request.Request(url,headers=h),timeout=30) as r:
        return r.read()

def dt(v):
    return datetime.fromisoformat(str(v).replace("Z","+00:00")).astimezone(UTC)

def verify_at_expected(snapshot_bytes,bundle_bytes,anchor,expected,max_deviation):
    with tempfile.TemporaryDirectory() as td:
        p=Path(td)/"s.json"; b=Path(td)/"s.sigstore.json"
        p.write_bytes(snapshot_bytes); b.write_bytes(bundle_bytes)
        subprocess.run(["cosign","verify-blob",str(p),"--bundle",str(b),
                        "--certificate-identity",IDENTITY,"--certificate-oidc-issuer",ISSUER],
                       check=True,capture_output=True,text=True,timeout=90)
    bundle=json.loads(bundle_bytes)
    entries=bundle.get("verificationMaterial",{}).get("tlogEntries",[])
    if not entries: raise ValueError("no Rekor entry")
    integrated=min(datetime.fromtimestamp(int(e["integratedTime"]),UTC) for e in entries)
    if integrated>anchor+timedelta(seconds=2): raise ValueError("Rekor after anchor")
    obj=json.loads(snapshot_bytes); captured=dt(obj["captured_at_utc"])
    if captured>anchor+timedelta(seconds=2): raise ValueError("captured after anchor")
    if abs((captured-expected).total_seconds())>max_deviation:
        raise ValueError("snapshot outside expected-time tolerance")
    return obj,{"captured_at_utc":captured.isoformat(),"rekor_integrated_utc":integrated.isoformat()}

def fixed_pair(anchor,token):
    api=f"https://api.github.com/repos/{REPO}/contents/context_live?ref=btc-context"
    arr=json.loads(get(api,token))
    parsed=[]
    for x in arr:
        n=x["name"]
        if not (n.endswith("Z.json") and not n.endswith(".sigstore.json")): continue
        try: t=datetime.strptime(n[:15],"%Y%m%dT%H%M%S").replace(tzinfo=UTC)
        except Exception: continue
        if t<=anchor: parsed.append((t,n))
    parsed.sort()
    current_candidates=[x for x in parsed if 0 <= (anchor-x[0]).total_seconds() <= PROTOCOL["external_context"]["snapshot_max_age_seconds"]]
    if not current_candidates: raise ValueError("no current snapshot")
    cur=min(current_candidates,key=lambda x:abs((x[0]-anchor).total_seconds()))
    target=anchor-timedelta(seconds=PROTOCOL["external_context"]["comparison_window_seconds"])
    tol=PROTOCOL["external_context"]["comparison_tolerance_seconds"]
    prev_candidates=[x for x in parsed if abs((x[0]-target).total_seconds())<=tol]
    if not prev_candidates: raise ValueError("no previous snapshot")
    prev=min(prev_candidates,key=lambda x:abs((x[0]-target).total_seconds()))
    docs=[]
    for (t,n),expected,dev in ((cur,anchor,PROTOCOL["external_context"]["snapshot_max_age_seconds"]),
                               (prev,target,tol)):
        base=f"https://raw.githubusercontent.com/{REPO}/btc-context/context_live/{n}"
        obj,proof=verify_at_expected(get(base,token),get(base+".sigstore.json",token),anchor,expected,dev)
        st={k:factor_status(obj,k,anchor,PROTOCOL) for k in KEYS}
        docs.append((obj,proof,st,n))
    elapsed=(dt(docs[0][0]["captured_at_utc"])-dt(docs[1][0]["captured_at_utc"])).total_seconds()
    if elapsed<=0: raise ValueError("bad elapsed")
    return {"current":docs[0][0],"previous":docs[1][0],"current_proof":docs[0][1],"previous_proof":docs[1][1],
            "current_factor_status":docs[0][2],"previous_factor_status":docs[1][2],
            "snapshot_names":[docs[0][3],docs[1][3]],"elapsed_seconds":elapsed,
            "legacy_numeric_challenger_authorized":False}

def fetch_klines():
    url="https://data-api.binance.vision/api/v3/klines?symbol=BTCUSDT&interval=1h&limit=500"
    return json.loads(get(url))

def select(raw,anchor):
    out=[]
    for x in raw:
        op=datetime.fromtimestamp(int(x[0])/1000,UTC); cl=op+timedelta(hours=1)
        if cl<=anchor:
            out.append({"open_time":op.isoformat(),"close_time":cl.isoformat(),"open":float(x[1]),"high":float(x[2]),
                        "low":float(x[3]),"close":float(x[4]),"volume":float(x[5]),"trades":int(x[8]),"taker_buy_base":float(x[9])})
    if len(out)<169: raise ValueError("not enough candles")
    return out[-169:]

raw=fetch_klines(); token=os.environ.get("GITHUB_TOKEN")
start=datetime(2026,10,1,14,tzinfo=UTC); end=datetime(2026,10,2,8,tzinfo=UTC)
rows=[]; anchor=start
while anchor<=end:
    c=select(raw,anchor)
    try:
        pair=fixed_pair(anchor,token); out=forecast(c,pair,PROTOCOL)
        rows.append({"anchor_msk":(anchor+timedelta(hours=3)).strftime("%Y-%m-%d %H:%M"),"price":c[-1]["close"],
                     "state":out["regime_state"],"score":out["regime_score"],
                     "up_1h":out["horizons"]["1h"]["probabilities"]["upside"],
                     "up_4h":out["horizons"]["4h"]["probabilities"]["upside"],
                     "up_24h":out["horizons"]["24h"]["probabilities"]["upside"],
                     "snapshots":pair["snapshot_names"]})
    except Exception as exc:
        rows.append({"anchor_msk":(anchor+timedelta(hours=3)).strftime("%Y-%m-%d %H:%M"),"price":c[-1]["close"],
                     "state":"NO_VALID_CONTEXT","reason":type(exc).__name__+": "+str(exc)})
    anchor+=timedelta(hours=1)
print("REAL_MARKET_REPLAY_FIXED_BEGIN")
for r in rows: print(json.dumps(r,sort_keys=True))
print("REAL_MARKET_REPLAY_FIXED_END")
