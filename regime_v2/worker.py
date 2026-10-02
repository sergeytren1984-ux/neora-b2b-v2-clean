from __future__ import annotations
import hashlib,json,os,subprocess,sys,urllib.request
from datetime import datetime,timezone,timedelta
from pathlib import Path

from barrier import build_barrier_spec,resolve_barrier
from context_trust import context_pair
from model import forecast

UTC=timezone.utc
ROOT=Path(__file__).resolve().parents[1]
RUNTIME=ROOT/"regime_v2"
OUT=ROOT/"regime_v2_events"
START=datetime(2026,10,2,9,0,tzinfo=UTC)
DEADLINE_MINUTES=20
BRANCH="btc-regime-v2-audit"
REPO="sergeytren1984-ux/neora-b2b-v2-clean"
IDENTITY="https://github.com/sergeytren1984-ux/neora-b2b-v2-clean/.github/workflows/btc-regime-v2-audit.yml@refs/heads/main"
ISSUER="https://token.actions.githubusercontent.com"
WORKFLOW_PATH=".github/workflows/btc-regime-v2-audit.yml"
GUARD_PATH=".github/workflows/btc-evidence-dispatch-guard.yml"
FROZEN_FILES=("model.py","barrier.py","context_trust.py","worker.py","selftest.py","protocol.json","schemas.json")

def now(): return datetime.now(UTC)
def canon(x): return json.dumps(x,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()+b"\n"
def sha(b): return hashlib.sha256(b).hexdigest()
def run(*a): return subprocess.run(a,check=True,capture_output=True,text=True,timeout=120).stdout.strip()

def bundle_time(bundle_path):
    b=json.loads(bundle_path.read_bytes())
    es=b.get("verificationMaterial",{}).get("tlogEntries",[])
    if not es: raise ValueError("no Rekor entry")
    for e in es:
        pr=e.get("inclusionProof")
        if not isinstance(pr,dict) or not pr.get("checkpoint") or "hashes" not in pr:
            raise ValueError("missing Rekor inclusion proof")
    return min(datetime.fromtimestamp(int(e["integratedTime"]),UTC) for e in es)

def verify_blob(path,bundle):
    run("cosign","verify-blob",str(path),"--bundle",str(bundle),
        "--certificate-identity",IDENTITY,"--certificate-oidc-issuer",ISSUER)
    return bundle_time(bundle)

def events():
    OUT.mkdir(exist_ok=True)
    seen=set(); prev=None; result=[]
    files=sorted(p for p in OUT.glob("*.json") if p.stem.isdigit() and len(p.stem)==8)
    for i,p in enumerate(files,1):
        b=p.with_suffix(".sigstore.json")
        if not b.exists(): raise ValueError("missing event signature")
        integrated=verify_blob(p,b)
        obj=json.loads(p.read_bytes())
        if p.read_bytes()!=canon(obj): raise ValueError("noncanonical event")
        if obj.get("sequence")!=i or obj.get("previous_hash")!=prev: raise ValueError("event chain gap/fork")
        k=obj.get("idempotency_key")
        if not isinstance(k,str) or k in seen: raise ValueError("idempotency violation")
        seen.add(k); prev=sha(p.read_bytes()); result.append((obj,integrated))
    return result

def remote_clean():
    run("git","fetch","origin",BRANCH)
    local=run("git","rev-parse","HEAD"); remote=run("git","rev-parse",f"origin/{BRANCH}")
    if local!=remote: raise RuntimeError("remote branch advanced; refusing concurrent publish")

def publish(obj,before=None,attachments=()):
    remote_clean(); prior=events()
    if any(e[0].get("idempotency_key")==obj["idempotency_key"] for e in prior):
        return prior[-1][0] if prior else None
    seq=len(prior)+1
    event={"schema":"btc-regime-v2-event-v1","sequence":seq,
           "previous_hash":sha(canon(prior[-1][0])) if prior else None,
           "workflow_commit":os.environ["GITHUB_SHA"],"published_at_utc":now().isoformat(),**obj}
    p=OUT/f"{seq:08d}.json"; b=p.with_suffix(".sigstore.json")
    p.write_bytes(canon(event))
    run("cosign","sign-blob","--yes","--bundle",str(b),str(p))
    integrated=verify_blob(p,b)
    if before and integrated>=before:
        p.unlink(missing_ok=True); b.unlink(missing_ok=True)
        raise TimeoutError("Rekor integration missed deadline")
    for x in (p,b,*attachments): run("git","add",str(Path(x).relative_to(ROOT)))
    run("git","commit","-m",f"BTC regime v2 evidence #{seq}: {event['type']}")
    run("git","push","origin",f"HEAD:{BRANCH}")
    return event

def read_protocol():
    return json.loads((RUNTIME/"protocol.json").read_text())

def git_show_main(path):
    run("git","fetch","origin","main")
    return subprocess.run(["git","show",f"origin/main:{path}"],check=True,capture_output=True).stdout

def compute_manifest():
    files={n:sha((RUNTIME/n).read_bytes()) for n in FROZEN_FILES}
    wf=git_show_main(WORKFLOW_PATH); guard=git_show_main(GUARD_PATH)
    return {
      "schema":"btc-regime-v2-frozen-manifest-v1",
      "files_sha256":files,
      "workflow":{"path":WORKFLOW_PATH,"sha256":sha(wf)},
      "guard":{"path":GUARD_PATH,"sha256":sha(guard)},
      "python_version":".".join(map(str,sys.version_info[:3])),
      "cosign_version":run("cosign","version"),
      "branch":BRANCH
    }

def freeze_manifest():
    m=compute_manifest(); p=RUNTIME/"frozen_manifest.json"
    p.write_bytes(canon(m))
    return p,m

def verify_manifest():
    p=RUNTIME/"frozen_manifest.json"
    if not p.exists(): return False,{"manifest":"missing"}
    expected=json.loads(p.read_bytes()); actual=compute_manifest()
    return expected==actual,{"expected":expected,"actual":actual}

def fetch_klines(limit=500):
    url=f"https://data-api.binance.vision/api/v3/klines?symbol=BTCUSDT&interval=1h&limit={limit}"
    req=urllib.request.Request(url,headers={"User-Agent":"btc-regime-v2-audit"})
    with urllib.request.urlopen(req,timeout=20) as r:
        if r.status!=200: raise RuntimeError("Binance non-200")
        x=json.loads(r.read())
    if not isinstance(x,list) or len(x)<170: raise ValueError("insufficient Binance history")
    return x

def closed_candles(raw,anchor):
    out=[]
    for x in raw:
        opened=datetime.fromtimestamp(int(x[0])/1000,UTC)
        closed=opened+timedelta(hours=1)
        if int(x[6])!=int(closed.timestamp()*1000)-1: raise ValueError("exchange close timestamp invalid")
        if closed<=anchor:
            o,h,l,c=map(float,(x[1],x[2],x[3],x[4]))
            if l>min(o,c) or h<max(o,c) or h<l: raise ValueError("OHLC invariant invalid")
            if float(x[5])<0 or int(x[8])<0: raise ValueError("negative market activity")
            out.append({"open_time":opened.isoformat(),"close_time":closed.isoformat(),"open":o,"high":h,"low":l,"close":c,
                        "volume":float(x[5]),"trades":int(x[8]),"taker_buy_base":float(x[9])})
    for a,b in zip(out,out[1:]):
        if datetime.fromisoformat(b["open_time"])-datetime.fromisoformat(a["open_time"])!=timedelta(hours=1):
            raise ValueError("noncontiguous or duplicate 1h candles")
    if not out or datetime.fromisoformat(out[-1]["close_time"])!=anchor:
        raise ValueError("latest closed candle does not equal anchor")
    if len(out)<169: raise ValueError("need 169 closed candles")
    return out

def close_at(candles,due):
    for c in candles:
        if datetime.fromisoformat(c["close_time"])==due: return float(c["close"])
    return None

def resolve_outcomes(anchor,candles):
    ev=[x[0] for x in events()]; done={x["idempotency_key"] for x in ev}
    forecasts=[x for x in ev if x.get("type")=="REGIME_FORECAST_ISSUED"]
    for fc in forecasts:
        ref=float(fc["reference_price"]); fc_anchor=datetime.fromisoformat(fc["anchor_utc"])
        for h,hours in (("1h",1),("4h",4),("24h",24)):
            key=f"outcome:{fc['slot']}:{h}"
            if key in done: continue
            due=fc_anchor+timedelta(hours=hours)
            if due>anchor: continue
            close=close_at(candles,due)
            if close is None: continue
            threshold=float(fc["output"]["horizons"][h]["threshold_pct"]); ret=100*(close/ref-1)
            actual="upside" if ret>threshold else "downside" if ret<-threshold else "range"
            probs=fc["output"]["horizons"][h]["probabilities"]
            brier=sum((float(probs[k])-(1 if k==actual else 0))**2 for k in ("upside","range","downside"))
            publish({"type":"REGIME_OUTCOME_RECORDED","idempotency_key":key,"forecast_sequence":fc["sequence"],
                     "slot":fc["slot"],"horizon":h,"due_utc":due.isoformat(),"reference_price":ref,"close":close,
                     "return_pct":ret,"threshold_pct":threshold,"class":actual,"brier":brier,"trading_authority":False})
            done.add(key)
        for spec in fc.get("barriers",[]):
            key=f"barrier:{fc['slot']}:{spec['id']}"
            if key in done: continue
            r=resolve_barrier(spec,candles,fc_anchor)
            if r is not None:
                publish({"type":"BARRIER_OUTCOME_RECORDED","idempotency_key":key,"forecast_sequence":fc["sequence"],
                         "slot":fc["slot"],"barrier_id":spec["id"],"spec":spec,"outcome":r,"trading_authority":False})
                done.add(key)

def record_missed_slots(current):
    ev=[x[0] for x in events()]; done={x["idempotency_key"] for x in ev}
    slot=START
    while slot<=current.replace(minute=0,second=0,microsecond=0):
        s=slot.strftime("%Y%m%dT%H%M%SZ")
        keys=(f"regime:{s}",f"abstain-data:{s}",f"abstain-config:{s}",f"missed:{s}")
        if not any(k in done for k in keys) and current>=slot+timedelta(minutes=DEADLINE_MINUTES):
            k=f"missed:{s}"
            publish({"type":"SLOT_MISSED","idempotency_key":k,"slot":s,"anchor_utc":slot.isoformat(),
                     "deadline_utc":(slot+timedelta(minutes=DEADLINE_MINUTES)).isoformat(),
                     "reason":"NO_SIGNED_FORECAST_OR_ABSTENTION_BEFORE_DEADLINE","trading_authority":False})
            done.add(k)
        slot+=timedelta(hours=1)

def required_context_ok(pair,protocol):
    problems=[]
    for name,rule in protocol["factor_policy"].items():
        if not rule.get("required"): continue
        if not pair["current_factor_status"].get(name,{}).get("available"):
            problems.append(name+":current")
        if name=="open_interest" and not pair["previous_factor_status"].get(name,{}).get("available"):
            problems.append(name+":previous")
    return problems

def main():
    t=now(); protocol=read_protocol(); ev=events()
    if not ev:
        if t>=START: raise ValueError("cannot register schedule after start")
        publish({"type":"SCHEDULE_REGISTERED","idempotency_key":"btc-regime-v2-audit-20261002",
                 "start_utc":START.isoformat(),"deadline_minutes":DEADLINE_MINUTES,
                 "protocol_sha256":sha((RUNTIME/"protocol.json").read_bytes()),"trading_authority":False})
        ev=events()
    if not any(x[0].get("type")=="CONFIG_FROZEN_PRESTART" for x in ev):
        if t>=START: raise ValueError("cannot freeze config after start")
        path,m=freeze_manifest()
        publish({"type":"CONFIG_FROZEN_PRESTART","idempotency_key":"btc-regime-v2-audit-config",
                 "start_utc":START.isoformat(),"manifest_sha256":sha(path.read_bytes()),"manifest":m,
                 "trading_authority":False},attachments=(path,))
        return

    anchor=t.replace(minute=0,second=0,microsecond=0)
    raw=fetch_klines()
    latest_anchor=min(anchor, datetime.fromtimestamp(int(raw[-1][0])/1000,UTC))
    candles=closed_candles(raw,anchor)
    resolve_outcomes(anchor,candles)
    record_missed_slots(t)
    if anchor<START or t>=anchor+timedelta(minutes=DEADLINE_MINUTES): return
    slot=anchor.strftime("%Y%m%dT%H%M%SZ")
    existing={x[0]["idempotency_key"] for x in events()}
    if any(k in existing for k in (f"regime:{slot}",f"abstain-data:{slot}",f"abstain-config:{slot}",f"missed:{slot}")): return

    ok,detail=verify_manifest()
    if not ok:
        publish({"type":"ABSTAIN_CONFIG_DRIFT","idempotency_key":f"abstain-config:{slot}","slot":slot,
                 "anchor_utc":anchor.isoformat(),"detail":detail,"trading_authority":False},
                before=anchor+timedelta(minutes=DEADLINE_MINUTES))
        return
    try:
        pair=context_pair(REPO,anchor,protocol,os.environ.get("GITHUB_TOKEN"))
        problems=required_context_ok(pair,protocol)
        if problems: raise ValueError("required context invalid: "+",".join(problems))
        out=forecast(candles[-169:],pair,protocol)
    except Exception as exc:
        publish({"type":"ABSTAIN_DATA_INVALID","idempotency_key":f"abstain-data:{slot}","slot":slot,
                 "anchor_utc":anchor.isoformat(),"reason":type(exc).__name__+": "+str(exc)[:500],
                 "trading_authority":False},before=anchor+timedelta(minutes=DEADLINE_MINUTES))
        return
    ref=float(candles[-1]["close"])
    barriers=build_barrier_spec(ref,out["features"]["atr24_pct"],anchor,protocol)
    publish({"type":"REGIME_FORECAST_ISSUED","idempotency_key":f"regime:{slot}","slot":slot,
             "anchor_utc":anchor.isoformat(),"issued_at_utc":now().isoformat(),"reference_price":ref,
             "context_snapshots":pair["snapshot_names"],"context_elapsed_seconds":pair["elapsed_seconds"],
             "context_proofs":{"current":pair["current_proof"],"previous":pair["previous_proof"]},
             "factor_status":{"current":pair["current_factor_status"],"previous":pair["previous_factor_status"]},
             "legacy_numeric_challenger_authorized":pair["legacy_numeric_challenger_authorized"],
             "context_usage_status":"SIGNED_SHADOW_RESEARCH_ONLY",
             "output":out,"barriers":barriers,"publication_authorized":False,"trading_authority":False},
            before=anchor+timedelta(minutes=DEADLINE_MINUTES))

if __name__=="__main__": main()
