"""Signed prospective worker for BTC Predictive vNext4R3.

The executable runtime is loaded from a clean immutable source archive, not from
the mutable evidence branch. The evidence checkout is used only for the signed
ledger, raw observations and git publication.

Every forecast and every outcome validates the signed pre-start manifest before
processing market data.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import joblib
import numpy as np
import sklearn

UTC=timezone.utc
CODE_ROOT=Path(__file__).resolve().parents[1]
EVIDENCE_ROOT=Path(os.environ.get("BTC_VNEXT4R3_EVIDENCE_ROOT",str(CODE_ROOT))).resolve()
if str(CODE_ROOT) not in sys.path:
    sys.path.insert(0,str(CODE_ROOT))

START=datetime(2026,10,5,12,0,tzinfo=UTC)
DELIVERY_SAFETY=timedelta(seconds=45)
ISSUER="https://token.actions.githubusercontent.com"
CLASS_TO_ID={"LOWER_FIRST":0,"UPPER_FIRST":1,"NEITHER":2,"AMBIGUOUS_SAME_BAR":3}

CONFIG={
    "hourly":{
        "branch":"btc-predictive-vnext4r3-hourly",
        "protocol":"predictive_vnext4r3/protocol_hourly.json",
        "artifact":"predictive_vnext4/hourly_contenders.joblib",
        "seed_source":"predictive_vnext4/baseline_seed_hourly_source.json.gz",
        "events":"predictive_vnext4r3_hourly_events",
        "raw":"predictive_vnext4r3_hourly_raw",
        "cadence":timedelta(hours=1),"deadline":timedelta(minutes=45),
        "interval":"1h","duration_ms":3600000,"min_history":170,
        "forecast_workflow":".github/workflows/btc-predictive-vnext4r3-hourly.yml",
        "outcome_workflow":".github/workflows/btc-predictive-vnext4r3-hourly.yml",
    },
    "early15m":{
        "branch":"btc-predictive-vnext4r3-early15m",
        "protocol":"predictive_vnext4r3/protocol_early15m.json",
        "artifact":"predictive_vnext4/early15m_contenders.joblib",
        "seed_source":"predictive_vnext4/baseline_seed_early15m_source.json.gz",
        "events":"predictive_vnext4r3_early15m_events",
        "raw":"predictive_vnext4r3_early15m_raw",
        "cadence":timedelta(minutes=15),"deadline":timedelta(minutes=14),
        "interval":"15m","duration_ms":900000,"min_history":385,
        "forecast_workflow":".github/workflows/btc-predictive-vnext4r3-early15m.yml",
        "outcome_workflow":".github/workflows/btc-predictive-vnext4r3-early15m.yml",
    }
}


def utcnow(): return datetime.now(UTC)
def canonical(obj): return (json.dumps(obj,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False)+"\n").encode()
def digest(data): return hashlib.sha256(data).hexdigest()

def cmd(*args):
    return subprocess.run(args,check=True,capture_output=True,text=True,timeout=180,cwd=EVIDENCE_ROOT).stdout.strip()

def git_bytes(commit,path):
    return subprocess.run(["git","-C",str(EVIDENCE_ROOT),"show",f"{commit}:{path}"],
                          check=True,capture_output=True,timeout=180).stdout

def identity(path):
    return f"https://github.com/sergeytren1984-ux/neora-b2b-v2-clean/{path}@refs/heads/main"

def bundle_time(path):
    b=json.loads(Path(path).read_bytes())
    entries=b.get("verificationMaterial",{}).get("tlogEntries",[])
    if not entries: raise ValueError("Rekor entry missing")
    for e in entries:
        proof=e.get("inclusionProof")
        if not isinstance(proof,dict) or not proof.get("checkpoint") or "hashes" not in proof:
            raise ValueError("Rekor inclusion proof missing")
    return min(datetime.fromtimestamp(int(e["integratedTime"]),UTC) for e in entries)

def event_identity(cfg,event_type):
    return identity(cfg["outcome_workflow"] if event_type in ("OUTCOME_RECORDED","OPERATIONAL_OUTCOME_RECORDED") else cfg["forecast_workflow"])

def signature_claim_args(event):
    sha=str(event.get("workflow_commit",""))
    if len(sha)!=40 or any(ch not in "0123456789abcdef" for ch in sha.lower()):
        raise ValueError("invalid event workflow_commit")
    return [
        "--certificate-github-workflow-sha",sha,
        "--certificate-github-workflow-repository","sergeytren1984-ux/neora-b2b-v2-clean",
        "--certificate-github-workflow-ref","refs/heads/main",
        "--certificate-github-workflow-trigger","workflow_dispatch",
    ]

def verify_signature(path,bundle,cfg,event):
    subprocess.run([
        "cosign","verify-blob",str(path),"--bundle",str(bundle),
        "--certificate-identity",event_identity(cfg,event.get("type")),
        "--certificate-oidc-issuer",ISSUER,
        *signature_claim_args(event),
    ],check=True,capture_output=True,text=True,timeout=180,cwd=EVIDENCE_ROOT)
    return bundle_time(bundle)

def prior_events(cfg):
    d=EVIDENCE_ROOT/cfg["events"];d.mkdir(exist_ok=True)
    files=sorted(p for p in d.glob("*.json") if len(p.stem)==8 and p.stem.isdigit())
    out=[];prev=None;keys=set()
    for i,p in enumerate(files,1):
        raw=p.read_bytes();e=json.loads(raw)
        integrated=verify_signature(p,p.with_suffix(".sigstore.json"),cfg,e)
        if raw!=canonical(e) or e.get("sequence")!=i or e.get("previous_hash")!=prev:
            raise ValueError("event hash chain broken")
        if e.get("idempotency_key") in keys: raise ValueError("duplicate event key")
        keys.add(e["idempotency_key"]);prev=digest(raw);out.append((e,integrated))
    return out

def remote_clean(cfg):
    cmd("git","fetch","origin",cfg["branch"])
    if cmd("git","rev-parse","HEAD")!=cmd("git","rev-parse","origin/"+cfg["branch"]):
        raise RuntimeError("remote evidence branch advanced")

def publish(cfg,obj,deadline=None,attachments=()):
    if deadline and utcnow()>=deadline-DELIVERY_SAFETY:
        raise TimeoutError("deadline safety margin reached")
    remote_clean(cfg);prior=prior_events(cfg);keys={e["idempotency_key"] for e,_ in prior}
    if obj["idempotency_key"] in keys:return
    n=len(prior)+1
    e={"schema":"btc-predictive-vnext4r3-event-v1","sequence":n,
       "previous_hash":digest(canonical(prior[-1][0])) if prior else None,
       "workflow_commit":os.environ["GITHUB_SHA"],
       "published_at_utc":utcnow().isoformat(),**obj}
    events=EVIDENCE_ROOT/cfg["events"];p=events/f"{n:08d}.json";b=p.with_suffix(".sigstore.json")
    p.write_bytes(canonical(e))
    subprocess.run(["cosign","sign-blob","--yes","--bundle",str(b),str(p)],
                   check=True,capture_output=True,text=True,timeout=180,cwd=EVIDENCE_ROOT)
    if deadline and (bundle_time(b)>=deadline or utcnow()>=deadline):
        p.unlink(missing_ok=True);b.unlink(missing_ok=True)
        raise TimeoutError("signed forecast missed deadline")
    verify_signature(p,b,cfg,e)
    for x in (p,b,*attachments):
        rel=str(Path(x).resolve().relative_to(EVIDENCE_ROOT))
        cmd("git","add",rel)
    cmd("git","commit","-m",f"BTC predictive vNext4R3 {cfg['interval']} evidence #{n}: {e['type']}")
    cmd("git","push","origin","HEAD:"+cfg["branch"])
    remote_sha=cmd("git","ls-remote","origin","refs/heads/"+cfg["branch"]).split()[0]
    local_sha=cmd("git","rev-parse","HEAD")
    if remote_sha!=local_sha:
        raise RuntimeError("remote publication unconfirmed")

    # Forecast publication is a two-stage transaction. If the forecast commit
    # reached the remote branch but the runner dies before the receipt commit,
    # a successor must be able to complete the receipt while the deadline is
    # still open. The receipt remains idempotent and cannot be created late.
    if deadline and e.get("type")=="FORECAST_ISSUED":
        if not ensure_delivery_receipt(cfg,e,deadline):
            raise TimeoutError("delivery receipt could not be recovered before deadline")


def _verify_remote_forecast_commit(cfg,forecast_event,commit):
    seq=int(forecast_event["sequence"])
    path=f"{cfg['events']}/{seq:08d}.json"
    if git_bytes(commit,path)!=canonical(forecast_event):
        raise RuntimeError("remote commit does not contain exact forecast event")
    cmd("git","fetch","origin",cfg["branch"])
    remote_tip=cmd("git","rev-parse","origin/"+cfg["branch"])
    subprocess.run(
        ["git","-C",str(EVIDENCE_ROOT),"merge-base","--is-ancestor",commit,remote_tip],
        check=True,capture_output=True,text=True,timeout=180
    )
    return path


def forecast_commit_for_event(cfg,forecast_event):
    remote_clean(cfg)
    seq=int(forecast_event["sequence"])
    path=f"{cfg['events']}/{seq:08d}.json"
    commit=cmd("git","log","-1","--format=%H","--",path)
    if not commit:
        raise RuntimeError("forecast commit not found")
    _verify_remote_forecast_commit(cfg,forecast_event,commit)
    return commit


def ensure_delivery_receipt(cfg,forecast_event,deadline):
    """Idempotently complete/verify remote delivery evidence before deadline."""
    prior=prior_events(cfg)
    key="delivery:"+forecast_event["idempotency_key"]
    matches=[x for x in prior if x[0].get("idempotency_key")==key]
    if len(matches)>1:
        raise RuntimeError("duplicate delivery receipt")
    if len(matches)==1:
        receipt,integrated=matches[0]
        if (receipt.get("target_sequence")!=forecast_event.get("sequence") or
            receipt.get("target_event_hash")!=digest(canonical(forecast_event)) or
            receipt.get("slot")!=forecast_event.get("slot")):
            raise RuntimeError("delivery receipt target mismatch")
        if integrated>=deadline:
            raise RuntimeError("delivery receipt Rekor time is late")
        remote_commit=receipt.get("remote_commit_sha")
        if not remote_commit:
            raise RuntimeError("delivery receipt remote commit missing")
        _verify_remote_forecast_commit(cfg,forecast_event,remote_commit)
        return True

    # No receipt exists. Recovery is allowed only while the same signed
    # pre-registered deadline is still safely open.
    if utcnow()>=deadline-DELIVERY_SAFETY:
        return False

    remote_commit=forecast_commit_for_event(cfg,forecast_event)
    confirmed_at=utcnow()
    if confirmed_at>=deadline-DELIVERY_SAFETY:
        return False

    publish(cfg,{
        "type":"DELIVERY_CONFIRMED",
        "idempotency_key":key,
        "slot":forecast_event.get("slot"),
        "target_sequence":int(forecast_event["sequence"]),
        "target_event_hash":digest(canonical(forecast_event)),
        "remote_commit_sha":remote_commit,
        "remote_confirmed_at_utc":confirmed_at.isoformat(),
        "deadline_utc":deadline.isoformat(),
        "trading_authority":False,
    },deadline=deadline)
    return True

def static_paths(cfg):
    return [
        "predictive_vnext4r3/worker.py","predictive_vnext4r3/scorecard.py",
        "predictive_vnext4r3/test_scorecard.py","predictive_vnext4r3/scheduler.py","predictive_vnext4r3/test_scheduler.py","predictive_vnext4r3/test_scheduler_stress.py",cfg["protocol"],
        "predictive_vnext4/live_features.py","predictive_vnext4/predict.py",
        "predictive_vnext4/core.py","predictive_vnext4/selftest.py",
        "predictive_vnext4/freeze_metadata.json",cfg["artifact"],cfg["seed_source"],
    ]

def workflow_hash(commit,path):
    return digest(git_bytes(commit,path))

def manifest(cfg,source_sha):
    if not source_sha or len(source_sha)!=40: raise ValueError("immutable source commit missing")
    # Source commit must exist in repository history and all runtime files must match it.
    subprocess.run(["git","-C",str(EVIDENCE_ROOT),"cat-file","-e",source_sha+"^{commit}"],
                   check=True,capture_output=True,timeout=180)
    paths={}
    for p in static_paths(cfg):
        local=(CODE_ROOT/p).read_bytes()
        committed=git_bytes(source_sha,p)
        if local!=committed:
            raise RuntimeError("clean runtime does not match immutable source: "+p)
        paths[p]=digest(local)
    workflow_commit=os.environ["GITHUB_SHA"]
    for p in (cfg["forecast_workflow"],cfg["outcome_workflow"]):
        paths[p]=workflow_hash(workflow_commit,p)
    return {
        "schema":"btc-predictive-vnext4r3-frozen-manifest-v1",
        "source_commit_sha":source_sha,"paths_sha256":paths,
        "forecast_workflow":cfg["forecast_workflow"],
        "outcome_workflow":cfg["outcome_workflow"],
        "python_version":".".join(map(str,sys.version_info[:3])),
        "numpy_version":np.__version__,"sklearn_version":sklearn.__version__,
        "joblib_version":joblib.__version__,"cosign_version":cmd("cosign","version"),
        "evidence_branch":cfg["branch"],
        "runtime_isolation":"python -I + clean git archive of immutable source commit",
    }

def signed_freeze(cfg):
    events=prior_events(cfg)
    freezes=[x for x in events if x[0].get("type")=="CONFIG_FROZEN_PRESTART"]
    if len(freezes)!=1: raise RuntimeError("exactly one signed pre-start freeze required")
    e,integrated=freezes[0]
    if integrated>=START: raise RuntimeError("freeze Rekor time is not pre-start")
    m=e.get("manifest")
    if not isinstance(m,dict) or digest(canonical(m))!=e.get("manifest_sha256"):
        raise RuntimeError("signed freeze manifest hash mismatch")
    return e,m,events

def verify_signed_freeze(cfg,head,action):
    freeze,m,events=signed_freeze(cfg)
    source=os.environ.get("BTC_VNEXT4R3_SOURCE_SHA","")
    if source!=m.get("source_commit_sha"): raise RuntimeError("runtime source SHA differs from signed freeze")
    expected=cfg["forecast_workflow"] if action=="forecast" else cfg["outcome_workflow"]
    if os.environ.get("BTC_VNEXT4R3_WORKFLOW_PATH")!=expected:
        raise RuntimeError("workflow path environment mismatch")
    if workflow_hash(os.environ["GITHUB_SHA"],expected)!=m["paths_sha256"].get(expected):
        raise RuntimeError("current workflow content differs from signed freeze")
    for p in static_paths(cfg):
        local=(CODE_ROOT/p).read_bytes()
        if digest(local)!=m["paths_sha256"].get(p):
            raise RuntimeError("runtime path differs from signed freeze: "+p)
        if local!=git_bytes(source,p):
            raise RuntimeError("runtime path differs from immutable source: "+p)
    copy=EVIDENCE_ROOT/"predictive_vnext4r3"/f"frozen_manifest_{head}.json"
    if not copy.exists() or copy.read_bytes()!=canonical(m):
        raise RuntimeError("evidence manifest copy differs from signed manifest")
    return events

def initialize(cfg,head):
    now=utcnow();proto=json.loads((CODE_ROOT/cfg["protocol"]).read_bytes());events=prior_events(cfg)
    if proto["start_utc"]!=START.strftime("%Y-%m-%dT%H:%M:%SZ"): raise ValueError("start mismatch")
    source=os.environ.get("BTC_VNEXT4R3_SOURCE_SHA","")
    if not events:
        if now>=START: raise RuntimeError("no registration before start")
        publish(cfg,{"type":"SCHEDULE_REGISTERED","idempotency_key":f"{head}:schedule",
                     "start_utc":START.isoformat(),
                     "deadline_minutes":int(cfg["deadline"].total_seconds()/60),
                     "protocol_sha256":digest((CODE_ROOT/cfg["protocol"]).read_bytes()),
                     "source_commit_sha":source,"trading_authority":False})
        events=prior_events(cfg)
    if not any(e["type"]=="CONFIG_FROZEN_PRESTART" for e,_ in events):
        if now>=START: raise RuntimeError("no freeze before start")
        m=manifest(cfg,source)
        d=EVIDENCE_ROOT/"predictive_vnext4r3";d.mkdir(exist_ok=True)
        p=d/f"frozen_manifest_{head}.json";p.write_bytes(canonical(m))
        publish(cfg,{"type":"CONFIG_FROZEN_PRESTART","idempotency_key":f"{head}:freeze",
                     "start_utc":START.isoformat(),"manifest_sha256":digest(p.read_bytes()),
                     "manifest":m,"trading_authority":False},attachments=(p,))
        return False
    verify_signed_freeze(cfg,head,"forecast")
    return True

def slot_floor(now,cadence):
    if cadence==timedelta(hours=1):return now.replace(minute=0,second=0,microsecond=0)
    return now.replace(minute=(now.minute//15)*15,second=0,microsecond=0)

def slot_text(anchor): return anchor.strftime("%Y%m%dT%H%M%SZ")

def fetch_recent(anchor,cfg):
    params=urllib.parse.urlencode({"symbol":"BTCUSDT","interval":cfg["interval"],"limit":1000})
    req=urllib.request.Request("https://data-api.binance.vision/api/v3/klines?"+params,
                               headers={"User-Agent":"btc-predictive-vnext4r3"})
    with urllib.request.urlopen(req,timeout=30) as response:
        if response.status!=200: raise RuntimeError("Binance HTTP not 200")
        raw=json.loads(response.read())
    closed=[]
    for x in raw:
        if int(x[6])!=int(x[0])+cfg["duration_ms"]-1: raise ValueError("invalid candle timestamp")
        close_time=datetime.fromtimestamp((int(x[6])+1)/1000,UTC)
        if close_time>anchor:continue
        o,h,l,c=map(float,(x[1],x[2],x[3],x[4]));vol=float(x[5]);taker=float(x[9]);trades=int(x[8])
        if not all(map(math.isfinite,(o,h,l,c,vol,taker))) or min(o,h,l,c)<=0 or l>min(o,c) or h<max(o,c) or h<l or vol<0 or taker<0 or taker>vol or trades<0:
            raise ValueError("invalid OHLC/activity")
        closed.append(x)
    if len(closed)<cfg["min_history"]: raise ValueError("insufficient closed candles")
    if datetime.fromtimestamp((int(closed[-1][6])+1)/1000,UTC)!=anchor:
        raise ValueError("latest closed candle != anchor")
    if any(int(b[0])-int(a[0])!=cfg["duration_ms"] for a,b in zip(closed,closed[1:])):
        raise ValueError("candle gap or duplicate")
    return raw,closed

def arrays(closed):
    return tuple(np.asarray([float(x[j]) for x in closed]) for j in (2,3,4,5,8,9))

def resolved_control_records(events):
    forecasts={e["slot"]:e for e,_ in events if e.get("type")=="FORECAST_ISSUED"}
    out=[]
    for e,_ in events:
        if e.get("type")!="OUTCOME_RECORDED":continue
        f=forecasts.get(e["slot"])
        if not f:continue
        cls=CLASS_TO_ID.get(e.get("outcome_class"));b=f.get("control",{}).get("volatility_bin")
        if cls is None or b not in (0,1,2):continue
        out.append({"anchor_utc":f["anchor_utc"],"due_utc":f["due_utc"],
                    "class_id":cls,"vol_bin":int(b)})
    return out

def operational_questions(anchor,reference):
    if anchor.hour!=14:return []
    specs=[
        ("FP_82500_87000_72H",82500.0,87000.0,72),
        ("FP_81500_88000_168H",81500.0,88000.0,168),
    ]
    out=[]
    for qid,lower,upper,hours in specs:
        status="OPEN" if lower<reference<upper else "NOT_APPLICABLE_REFERENCE_OUTSIDE_CORRIDOR"
        out.append({"question_id":qid,"lower_price":lower,"upper_price":upper,
                    "horizon_hours":hours,"due_utc":(anchor+timedelta(hours=hours)).isoformat(),
                    "status":status,"probability_status":"NOT_MODELED_SEPARATE_OPERATIONAL_ENDPOINT"})
    return out

def forecast(cfg,head):
    events=verify_signed_freeze(cfg,head,"forecast")
    now=utcnow();anchor=slot_floor(now,cfg["cadence"]);deadline=anchor+cfg["deadline"]
    if anchor<START or now>=deadline:return False
    keys={e["idempotency_key"] for e,_ in events};slot=slot_text(anchor)
    existing=[e for e,_ in events if e.get("idempotency_key")=="forecast:"+slot]
    if existing:
        return ensure_delivery_receipt(cfg,existing[0],deadline)
    proto=json.loads((CODE_ROOT/cfg["protocol"]).read_bytes())
    try:
        from predictive_vnext4.live_features import HOURLY_NAMES,EARLY15M_NAMES,hourly_feature,early15m_feature
        from predictive_vnext4.predict import load_artifact,predict_contenders,control_prediction
        raw,closed=fetch_recent(anchor,cfg);hi,lo,c,v,trades,taker=arrays(closed)
        art=load_artifact(CODE_ROOT/cfg["artifact"],proto["artifact_sha256"])
        if head=="hourly":
            x,meta=hourly_feature(hi,lo,c,v,trades,taker)
            if art["feature_names"]!=HOURLY_NAMES: raise ValueError("hourly feature schema mismatch")
            distance=meta["reference_price"]*meta["rv24"]*math.sqrt(72.0)
            lower=meta["reference_price"]-distance;upper=meta["reference_price"]+distance
            due=anchor+timedelta(hours=72);vol_value=meta["rv24"]
        else:
            x,meta=early15m_feature(hi,lo,c,v,trades,taker)
            if art["feature_names"]!=EARLY15M_NAMES: raise ValueError("15m feature schema mismatch")
            lower=meta["reference_price"]*.99;upper=meta["reference_price"]*1.01
            due=anchor+timedelta(hours=4);vol_value=meta["rv4h"]
        contenders=predict_contenders(art,x)
        control=control_prediction(art,vol_value,anchor.isoformat(),resolved_control_records(events))
    except Exception as ex:
        k="abstain-data:"+slot
        if k not in keys:
            publish(cfg,{"type":"ABSTAIN_DATA_INVALID","idempotency_key":k,"slot":slot,
                         "reason":type(ex).__name__+": "+str(ex)[:300],
                         "retryable_before_deadline":True},deadline=deadline)
        return False
    rawdir=EVIDENCE_ROOT/cfg["raw"];rawdir.mkdir(exist_ok=True)
    p=rawdir/(slot+".json");p.write_bytes(canonical({
        "slot":slot,"anchor_utc":anchor.isoformat(),"retrieved_at_utc":utcnow().isoformat(),
        "source":"Binance BTCUSDT closed "+cfg["interval"]+" klines","klines":raw}))
    event={"type":"FORECAST_ISSUED","idempotency_key":"forecast:"+slot,"slot":slot,"head":head,
           "anchor_utc":anchor.isoformat(),"due_utc":due.isoformat(),
           "reference_price":meta["reference_price"],"lower_price":float(lower),"upper_price":float(upper),
           "contenders":contenders,"control":control,
           "probability_status":"HISTORICALLY_CALIBRATED_PROSPECTIVE_UNVALIDATED",
           "artifact_sha256":proto["artifact_sha256"],"raw_path":str(p.relative_to(EVIDENCE_ROOT)),
           "raw_sha256":digest(p.read_bytes()),"trading_authority":False}
    if head=="hourly":event["operational_questions"]=operational_questions(anchor,meta["reference_price"])
    publish(cfg,event,deadline=deadline,attachments=(p,))
    return True

def mark_missed(cfg,head):
    events=verify_signed_freeze(cfg,head,"forecast")
    now=utcnow();keys={e["idempotency_key"] for e,_ in events};slot=START
    while slot+cfg["deadline"]<=now:
        s=slot_text(slot)
        if "forecast:"+s not in keys and "missed:"+s not in keys:
            publish(cfg,{"type":"SLOT_MISSED","idempotency_key":"missed:"+s,"slot":s,
                         "reason":"NO_TIMELY_FORECAST","deadline_utc":(slot+cfg["deadline"]).isoformat(),
                         "trading_authority":False})
            keys.add("missed:"+s)
        slot+=cfg["cadence"]

def fetch_outcome_rows(anchor,due,cfg):
    start_ms=int(anchor.timestamp()*1000);end_ms=int(due.timestamp()*1000)-1
    params=urllib.parse.urlencode({"symbol":"BTCUSDT","interval":cfg["interval"],
                                   "startTime":start_ms,"endTime":end_ms,"limit":1000})
    req=urllib.request.Request("https://data-api.binance.vision/api/v3/klines?"+params,
                               headers={"User-Agent":"btc-predictive-vnext4r3-outcome"})
    with urllib.request.urlopen(req,timeout=30) as response:
        if response.status!=200:raise RuntimeError("Binance outcome HTTP not 200")
        rows=json.loads(response.read())
    expected=int((due-anchor).total_seconds()*1000/cfg["duration_ms"])
    if len(rows)!=expected:raise ValueError(f"outcome candle count {len(rows)} != {expected}")
    if int(rows[0][0])!=start_ms or int(rows[-1][6])+1!=int(due.timestamp()*1000):
        raise ValueError("outcome boundaries mismatch")
    if any(int(b[0])-int(a[0])!=cfg["duration_ms"] for a,b in zip(rows,rows[1:])):
        raise ValueError("outcome candle gap")
    return rows

def classify(rows,lower,upper):
    for x in rows:
        dn=float(x[3])<=lower;up=float(x[2])>=upper
        close=datetime.fromtimestamp((int(x[6])+1)/1000,UTC).isoformat()
        if dn and up:return "AMBIGUOUS_SAME_BAR",close
        if dn:return "LOWER_FIRST",close
        if up:return "UPPER_FIRST",close
    return "NEITHER",None

def outcomes(cfg,head):
    events=verify_signed_freeze(cfg,head,"outcome")
    now=utcnow();keys={e["idempotency_key"] for e,_ in events}
    for f,_ in events:
        if f.get("type")!="FORECAST_ISSUED":continue
        key="outcome:"+f["slot"];due=datetime.fromisoformat(f["due_utc"])
        if key not in keys and due<=now:
            try:
                rows=fetch_outcome_rows(datetime.fromisoformat(f["anchor_utc"]),due,cfg)
                cls,touch=classify(rows,float(f["lower_price"]),float(f["upper_price"]))
            except Exception:
                rows=None
            if rows is not None:
                rawdir=EVIDENCE_ROOT/cfg["raw"];rawdir.mkdir(exist_ok=True)
                p=rawdir/(f["slot"]+"-outcome.json");p.write_bytes(canonical({
                    "slot":f["slot"],"due_utc":f["due_utc"],
                    "retrieved_at_utc":utcnow().isoformat(),"klines":rows}))
                publish(cfg,{"type":"OUTCOME_RECORDED","idempotency_key":key,"slot":f["slot"],"head":head,
                             "anchor_utc":f["anchor_utc"],"due_utc":f["due_utc"],"outcome_class":cls,
                             "first_touch_time_utc":touch,"lower_price":f["lower_price"],"upper_price":f["upper_price"],
                             "raw_path":str(p.relative_to(EVIDENCE_ROOT)),"raw_sha256":digest(p.read_bytes()),
                             "trading_authority":False},attachments=(p,))
                keys.add(key)
        if head!="hourly":continue
        for q in f.get("operational_questions",[]):
            if q.get("status")!="OPEN":continue
            qkey="operational-outcome:"+f["slot"]+":"+q["question_id"]
            qdue=datetime.fromisoformat(q["due_utc"])
            if qkey in keys or qdue>now:continue
            try:
                qrows=fetch_outcome_rows(datetime.fromisoformat(f["anchor_utc"]),qdue,cfg)
                qcls,qtouch=classify(qrows,float(q["lower_price"]),float(q["upper_price"]))
            except Exception:
                continue
            rawdir=EVIDENCE_ROOT/cfg["raw"];rawdir.mkdir(exist_ok=True)
            qp=rawdir/(f["slot"]+"-"+q["question_id"]+"-outcome.json")
            qp.write_bytes(canonical({"slot":f["slot"],"question_id":q["question_id"],
                                      "due_utc":q["due_utc"],"retrieved_at_utc":utcnow().isoformat(),
                                      "klines":qrows}))
            publish(cfg,{"type":"OPERATIONAL_OUTCOME_RECORDED","idempotency_key":qkey,
                         "slot":f["slot"],"question_id":q["question_id"],
                         "anchor_utc":f["anchor_utc"],"due_utc":q["due_utc"],
                         "outcome_class":qcls,"first_touch_time_utc":qtouch,
                         "lower_price":q["lower_price"],"upper_price":q["upper_price"],
                         "probability_status":"NOT_MODELED_SEPARATE_OPERATIONAL_ENDPOINT",
                         "raw_path":str(qp.relative_to(EVIDENCE_ROOT)),
                         "raw_sha256":digest(qp.read_bytes()),"trading_authority":False},
                        attachments=(qp,))
            keys.add(qkey)

def main():
    head=os.environ.get("BTC_VNEXT4R3_HEAD");action=os.environ.get("BTC_VNEXT4R3_ACTION")
    if head not in CONFIG or action not in ("forecast","outcome"):raise ValueError("invalid head/action")
    cfg=CONFIG[head]
    if action=="forecast":
        if not initialize(cfg,head):return False
        if utcnow()<START:return False
        mark_missed(cfg,head)
        return forecast(cfg,head)
    else:
        if utcnow()<START:return
        outcomes(cfg,head)

if __name__=="__main__":main()
