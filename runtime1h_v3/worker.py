from __future__ import annotations
import gzip, hashlib, json, os, subprocess, sys, time, urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

UTC=timezone.utc
ROOT=Path(__file__).resolve().parents[1]
RUNTIME=ROOT/"runtime"
HERE=ROOT/"runtime1h_v3"
EVENTS=ROOT/"events1h_v3"
RAW=ROOT/"raw1h_v3"
sys.path.insert(0,str(ROOT/"runtime"))
sys.path.insert(0,str(HERE))
from frozen_inference import frozen_artifact
from inference import forecast_1h

IDENTITY="https://github.com/sergeytren1984-ux/neora-b2b-v2-clean/.github/workflows/btc-1h-evidence-v3.yml@refs/heads/main"
ISSUER="https://token.actions.githubusercontent.com"
HOSTS=("data-api.binance.vision","api.binance.com","api1.binance.com")

def canon(v): return json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()
def sha(b): return hashlib.sha256(b).hexdigest()
def now(): return datetime.now(UTC)
def ts(s):
    d=datetime.fromisoformat(s.replace("Z","+00:00"))
    if d.tzinfo is None: raise ValueError("UTC timestamp required")
    return d.astimezone(UTC)
def run(*args):
    return subprocess.run(args,check=True,capture_output=True,text=True,timeout=90).stdout

def bundle_time(path):
    b=json.loads(path.read_bytes())
    entries=b.get("verificationMaterial",{}).get("tlogEntries",[])
    if not entries: raise ValueError("missing Rekor entry")
    out=[]
    for e in entries:
        p=e.get("inclusionProof")
        if not isinstance(p,dict) or not p.get("checkpoint") or "hashes" not in p:
            raise ValueError("missing Rekor inclusion proof")
        out.append(datetime.fromtimestamp(int(e["integratedTime"]),UTC))
    return min(out)

def verify_signed(path,bundle):
    run("cosign","verify-blob",str(path),"--bundle",str(bundle),
        "--certificate-identity",IDENTITY,"--certificate-oidc-issuer",ISSUER)
    return bundle_time(bundle)

def evidence():
    EVENTS.mkdir(exist_ok=True)
    prior=[]; prev=None; seen=set()
    paths=sorted(p for p in EVENTS.glob("*.json") if p.stem.isdigit() and len(p.stem)==8)
    for n,p in enumerate(paths,1):
        b=p.with_suffix(".sigstore.json")
        signed=verify_signed(p,b)
        obj=json.loads(p.read_bytes())
        if p.read_bytes()!=canon(obj)+b"\n": raise ValueError("noncanonical event")
        if obj.get("sequence")!=n or obj.get("previous_hash")!=prev:
            raise ValueError("event chain fork/gap")
        key=obj.get("idempotency_key")
        if not isinstance(key,str) or key in seen:
            raise ValueError("idempotency failure")
        seen.add(key); prev=sha(p.read_bytes()); prior.append((obj,signed))
    return prior

def publish(event,*,before=None,not_before=None,attachments=()):
    prior=evidence()
    if any(e[0]["idempotency_key"]==event["idempotency_key"] for e in prior):
        return None
    obj={"schema":"btc-1h-rekor-event-v3","sequence":len(prior)+1,
         "previous_hash":sha(canon(prior[-1][0])+b"\n") if prior else None,
         "workflow_commit":os.environ["GITHUB_SHA"],**event}
    p=EVENTS/f"{obj['sequence']:08d}.json"
    p.write_bytes(canon(obj)+b"\n")
    bundle=p.with_suffix(".sigstore.json")
    run("cosign","sign-blob","--yes","--bundle",str(bundle),str(p))
    integrated=verify_signed(p,bundle)
    if before and integrated>=before: raise ValueError("Rekor time too late")
    if not_before and integrated<not_before: raise ValueError("Rekor time before due")
    for f in (p,bundle,*attachments):
        run("git","add",str(Path(f).relative_to(ROOT)))
    run("git","commit","-m",f"BTC 1h v3 evidence #{obj['sequence']}: {obj['type']}")
    run("git","push","origin","HEAD:btc-1h-v3")
    return obj

def fetch(url):
    req=urllib.request.Request(url,headers={"User-Agent":"BTC-1h-prospective-v3/1.0"})
    with urllib.request.urlopen(req,timeout=12) as r:
        if r.status!=200: raise ValueError("non-200")
        b=r.read(2_000_001)
        if len(b)>2_000_000: raise ValueError("oversized response")
    return {"url":url,"retrieved_at_utc":now().isoformat(),"sha256":sha(b),"raw":b.decode("utf-8")}

def capture_klines(interval,limit):
    errors=[]; success=[]
    for host in HOSTS:
        u=f"https://{host}/api/v3/klines?symbol=BTCUSDT&interval={interval}&limit={limit}"
        try:
            r=fetch(u); d=json.loads(r["raw"])
            if not isinstance(d,list) or len(d)<limit-2: raise ValueError("incomplete history")
            success.append((r,d))
            if len(success)==2: break
        except Exception as e:
            errors.append({"host":host,"error":str(e)[:160]})
            time.sleep(.2)
    if not success:
        raise RuntimeError("all kline transports failed: "+json.dumps(errors))
    if len(success)==2:
        a,b=success[0][1],success[1][1]
        common={int(x[0]):x for x in a[:-1]}
        for row in b[:-1]:
            first=common.get(int(row[0]))
            if first is not None and first[:11]!=row[:11]:
                raise ValueError("official Binance transports disagree on closed candle")
        success[0][0]["verification_response"]={k:success[1][0][k] for k in ("url","retrieved_at_utc","sha256")}
    return success[0]

def closed(parsed,seconds,anchor,minimum):
    out=[]
    for x in parsed:
        opened=datetime.fromtimestamp(int(x[0])/1000,UTC)
        cl=opened+timedelta(seconds=seconds)
        if int(x[6])!=int(cl.timestamp()*1000)-1:
            raise ValueError("bad exchange close timestamp")
        if cl<=anchor:
            out.append({"open_time":opened.isoformat(),"close_time":cl.isoformat(),
                        "open":float(x[1]),"high":float(x[2]),"low":float(x[3]),"close":float(x[4]),
                        "volume":float(x[5]),"trades":int(x[8]),"taker_buy_base":float(x[9])})
    if len(out)<minimum:
        raise ValueError("insufficient closed history")
    # Critical prospective invariant: every prior candle in the admitted window
    # must exist exactly once. A correct final close is not enough.
    admitted=out[-minimum:]
    for a,b in zip(admitted,admitted[1:]):
        if ts(b["open_time"])-ts(a["open_time"])!=timedelta(seconds=seconds):
            raise ValueError("noncontiguous closed history")
    if ts(admitted[-1]["close_time"])!=anchor:
        raise ValueError("latest closed candle != anchor")
    return admitted

def calendar_events(anchor):
    p=ROOT/"context"/"macro_calendar_seed_2026q4.json"
    if not p.exists(): return []
    doc=json.loads(p.read_text()); due=anchor+timedelta(hours=1); out=[]
    for e in doc.get("events",[]):
        if e.get("importance") not in ("TIER1","TIER2"): continue
        t=ts(e["scheduled_utc"])
        if anchor<t<due:
            out.append(e)
    return out

def deadline(anchor,schedule):
    d=anchor+timedelta(minutes=int(schedule["issuance_max_delay_minutes"]))
    ev=calendar_events(anchor)
    if ev:
        d=min([d]+[ts(e["scheduled_utc"])-timedelta(minutes=1) for e in ev])
    return d,ev

def load():
    protocol=json.loads((HERE/"protocol.json").read_text())
    schedule=json.loads((HERE/"schedule.json").read_text())
    a=frozen_artifact()
    if protocol["frozen_v2930_artifact_sha256"]!="577017d19e6a2c607c8d7fb77b4ddce35dd8e3fc9be98db85e700d8862784a35":
        raise ValueError("wrong frozen artifact binding")
    if sha((HERE/"inference.py").read_bytes())!=protocol["inference_code_sha256"]:
        raise ValueError("1h inference code changed")
    if sha((HERE/"worker.py").read_bytes())!=protocol["worker_code_sha256"]:
        raise ValueError("1h worker code changed")
    if sha((HERE/"selftest.py").read_bytes())!=protocol["selftest_code_sha256"]:
        raise ValueError("1h selftest code changed")
    if a["horizons"]["1h"]["status"]!="CANDIDATE_ONLY":
        raise ValueError("wrong 1h artifact status")
    return protocol,schedule,a

def bootstrap(protocol,schedule):
    if evidence(): return
    start=ts(schedule["start_utc"])
    if now()>=start: raise ValueError("cannot preregister after schedule start")
    publish({"type":"SCHEDULE_REGISTERED","idempotency_key":schedule["id"],
             "schedule_start_utc":schedule["start_utc"],
             "schedule_sha256":sha((HERE/"schedule.json").read_bytes()),
             "protocol_sha256":sha((HERE/"protocol.json").read_bytes()),
             "inference_code_sha256":protocol["inference_code_sha256"],
             "worker_code_sha256":protocol["worker_code_sha256"],
             "frozen_v2930_sha256":protocol["frozen_v2930_artifact_sha256"],
             "workflow_identity":IDENTITY},before=start)

def atr14_4h(q):
    if len(q)<15: raise ValueError("15 closed 4h candles required")
    tr=[]
    for prev,cur in zip(q[-15:],q[-14:]):
        pc=float(prev["close"])
        tr.append(max(float(cur["high"])-float(cur["low"]),
                      abs(float(cur["high"])-pc),abs(float(cur["low"])-pc)))
    return sum(tr)/14.0

def run_slot(protocol,schedule,a,anchor):
    slot=anchor.strftime("%Y%m%dT%H%M%SZ"); key="forecast:"+slot+":1h"
    if any(e[0]["idempotency_key"]==key for e in evidence()): return
    dl,ev=deadline(anchor,schedule)
    if now()>=dl: return

    hrow,hraw=capture_klines("1h",200)
    qrow,qraw=capture_klines("4h",25)
    h=closed(hraw,3600,anchor,169)
    qa=anchor-timedelta(hours=anchor.hour%4)
    q=closed(qraw,14400,qa,15)

    probs=forecast_1h(h,a)
    if probs["probabilities"] is None:
        publish({"type":"ABSTAIN","idempotency_key":"abstain:"+slot+":1h","slot":slot,
                 "anchor_utc":anchor.isoformat(),"reason":probs["status"]},before=dl)
        return

    reference=float(h[-1]["close"]); atr=atr14_4h(q)
    threshold=max(.05,min(6.0,.35*100.0*atr/reference))
    RAW.mkdir(exist_ok=True)
    raw_bytes=canon({"schema":"btc-1h-raw-v3","anchor_utc":anchor.isoformat(),
                     "captures":[hrow,qrow]})+b"\n"
    rp=RAW/(slot+".json.gz"); rp.write_bytes(gzip.compress(raw_bytes,mtime=0))

    publish({"type":"FORECAST_ISSUED","idempotency_key":key,"slot":slot,
             "anchor_utc":anchor.isoformat(),"due_utc":(anchor+timedelta(hours=1)).isoformat(),
             "reference_price":reference,"threshold_pct":threshold,
             "probabilities":probs["probabilities"],"feature_hash":probs["feature_hash"],
             "model_status":probs["status"],"continuity":probs.get("continuity"),
             "model_sha256":protocol["frozen_v2930_artifact_sha256"],
             "inference_code_sha256":protocol["inference_code_sha256"],
             "raw_sha256":sha(raw_bytes),"event_sensitive":bool(ev),
             "events_inside_horizon":[{"id":e["id"],"type":e["type"],
                                      "scheduled_utc":e["scheduled_utc"],"importance":e["importance"]} for e in ev],
             "issuance_deadline_utc":dl.isoformat(),
             "publication_authorized":False,"trading_authority":False},
            before=dl,attachments=(rp,))

def due_close(due):
    start=int((due-timedelta(hours=1)).timestamp()*1000)
    end=int(due.timestamp()*1000)-1
    errors=[]
    for host in HOSTS:
        u=f"https://{host}/api/v3/klines?symbol=BTCUSDT&interval=1h&startTime={start}&endTime={end}&limit=1"
        try:
            r=fetch(u); d=json.loads(r["raw"])
            if len(d)!=1 or int(d[0][0])!=start or int(d[0][6])!=end:
                raise ValueError("wrong due candle")
            return r,float(d[0][4])
        except Exception as exc:
            errors.append({"host":host,"error":str(exc)[:120]})
    raise RuntimeError("no valid due candle: "+json.dumps(errors))

def resolve_due():
    for f,_ in evidence():
        if f["type"]!="FORECAST_ISSUED": continue
        due=ts(f["due_utc"])
        if now()<due+timedelta(minutes=2): continue
        key="outcome:"+f["slot"]+":1h"
        if any(e[0]["idempotency_key"]==key for e in evidence()): continue
        row,price=due_close(due)
        realized=100.0*(price/float(f["reference_price"])-1.0)
        th=float(f["threshold_pct"])
        cls="upside" if realized>th else "downside" if realized<-th else "range"
        RAW.mkdir(exist_ok=True)
        rb=canon({"schema":"btc-1h-due-v3","capture":row})+b"\n"
        rp=RAW/(f["slot"]+"-outcome.json.gz"); rp.write_bytes(gzip.compress(rb,mtime=0))
        publish({"type":"OUTCOME_RECORDED","idempotency_key":key,"slot":f["slot"],
                 "due_utc":f["due_utc"],"close":price,"return_pct":realized,
                 "threshold_pct":th,"class":cls,"raw_sha256":sha(rb)},
                not_before=due,attachments=(rp,))

def mark_missed(schedule):
    start=ts(schedule["start_utc"]); end=min(ts(schedule["end_exclusive_utc"]),now())
    seen={e[0]["idempotency_key"] for e in evidence()}
    p=start
    while p<end:
        dl,ev=deadline(p,schedule)
        if now()>=dl:
            slot=p.strftime("%Y%m%dT%H%M%SZ")
            fk="forecast:"+slot+":1h"; mk="missed:"+slot+":1h"; ak="abstain:"+slot+":1h"
            if fk not in seen and mk not in seen and ak not in seen:
                publish({"type":"SLOT_MISSED","idempotency_key":mk,"slot":slot,"horizon":"1h",
                         "event_sensitive":bool(ev),
                         "reason":"no valid signed 1h forecast by preregistered deadline"})
                seen.add(mk)
        p+=timedelta(hours=1)

def main():
    protocol,schedule,a=load()
    if not evidence():
        bootstrap(protocol,schedule); return
    first=evidence()[0][0]
    if first.get("idempotency_key")!=schedule["id"]: raise ValueError("wrong schedule registration")
    if first.get("schedule_sha256")!=sha((HERE/"schedule.json").read_bytes()):
        raise ValueError("schedule changed")
    if first.get("protocol_sha256")!=sha((HERE/"protocol.json").read_bytes()):
        raise ValueError("protocol changed")
    resolve_due(); mark_missed(schedule)
    cur=now(); anchor=cur.replace(minute=0,second=0,microsecond=0)
    if ts(schedule["start_utc"])<=anchor<ts(schedule["end_exclusive_utc"]):
        dl,_=deadline(anchor,schedule)
        if cur<dl: run_slot(protocol,schedule,a,anchor)

if __name__=="__main__": main()
