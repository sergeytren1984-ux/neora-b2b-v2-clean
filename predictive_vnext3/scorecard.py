"""Independent-style prospective scorecard for vNext3.

The scorecard is deliberately stricter than the runtime worker:
- every event signature is independently verified with Cosign/Rekor;
- the signed pre-start manifest is the only freeze authority;
- every event's recorded workflow commit is checked against the frozen workflow hash;
- admission uses future data only, fixed non-overlapping windows, 14/28-day block
  uncertainty and family-wise correction across the three preregistered contenders.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

UTC=timezone.utc
ROOT=Path(__file__).resolve().parents[1]
START=datetime(2026,10,5,0,0,tzinfo=UTC)
ISSUER="https://token.actions.githubusercontent.com"
CLASSES=("LOWER_FIRST","UPPER_FIRST","NEITHER","AMBIGUOUS_SAME_BAR")
CLASS_TO_ID={x:i for i,x in enumerate(CLASSES)}
CONTENDERS=("logistic","gbdt","competing_risks")


def canonical(obj): return (json.dumps(obj,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False)+"\n").encode()
def digest(data): return hashlib.sha256(data).hexdigest()
def parse(s):
    x=s[:-1]+"+00:00" if s.endswith("Z") else s
    d=datetime.fromisoformat(x)
    return d if d.tzinfo else d.replace(tzinfo=UTC)

def identity(path):
    return f"https://github.com/sergeytren1984-ux/neora-b2b-v2-clean/{path}@refs/heads/main"

def event_files(events_dir):
    d=ROOT/events_dir
    return sorted(p for p in d.glob("*.json") if len(p.stem)==8 and p.stem.isdigit())

def bundle_time(bundle):
    b=json.loads(Path(bundle).read_bytes())
    entries=b.get("verificationMaterial",{}).get("tlogEntries",[])
    if not entries:raise ValueError("Rekor entry missing")
    for e in entries:
        proof=e.get("inclusionProof")
        if not isinstance(proof,dict) or not proof.get("checkpoint") or "hashes" not in proof:
            raise ValueError("Rekor inclusion proof missing")
    return min(datetime.fromtimestamp(int(e["integratedTime"]),UTC) for e in entries)

def expected_workflow(event_type,forecast_workflow,outcome_workflow):
    return outcome_workflow if event_type in ("OUTCOME_RECORDED","OPERATIONAL_OUTCOME_RECORDED") else forecast_workflow

def verify_signature(path,event,forecast_workflow,outcome_workflow):
    wf=expected_workflow(event.get("type"),forecast_workflow,outcome_workflow)
    bundle=path.with_suffix(".sigstore.json")
    subprocess.run([
        "cosign","verify-blob",str(path),"--bundle",str(bundle),
        "--certificate-identity",identity(wf),
        "--certificate-oidc-issuer",ISSUER
    ],check=True,capture_output=True,text=True,timeout=180)
    return bundle_time(bundle)

def load_chain(events_dir,forecast_workflow,outcome_workflow):
    out=[];prev=None;keys=set();rekor={}
    for i,p in enumerate(event_files(events_dir),1):
        raw=p.read_bytes();e=json.loads(raw)
        if raw!=canonical(e) or e.get("sequence")!=i or e.get("previous_hash")!=prev:
            raise ValueError("event chain invalid at "+str(p))
        if e.get("idempotency_key") in keys:raise ValueError("duplicate idempotency key")
        integrated=verify_signature(p,e,forecast_workflow,outcome_workflow)
        rekor[i]=integrated
        keys.add(e["idempotency_key"]);prev=digest(raw);out.append(e)
    return out,rekor

def workflow_blob(commit,path):
    subprocess.run(["git","fetch","origin","main"],check=True,capture_output=True,timeout=180)
    return subprocess.run(["git","show",f"{commit}:{path}"],check=True,capture_output=True,timeout=180).stdout

def source_blob(commit,path):
    subprocess.run(["git","fetch","origin",commit],check=False,capture_output=True,timeout=180)
    return subprocess.run(["git","show",f"{commit}:{path}"],check=True,capture_output=True,timeout=180).stdout

def verify_governance(events,rekor,forecast_workflow,outcome_workflow):
    freezes=[e for e in events if e.get("type")=="CONFIG_FROZEN_PRESTART"]
    if len(freezes)!=1:return {"ok":False,"reason":"freeze_count_not_one"}
    freeze=freezes[0];m=freeze.get("manifest")
    if not isinstance(m,dict) or digest(canonical(m))!=freeze.get("manifest_sha256"):
        return {"ok":False,"reason":"signed_manifest_hash_invalid"}
    freeze_integrated=rekor.get(int(freeze["sequence"]))
    if freeze_integrated is None or freeze_integrated>=START:
        return {"ok":False,"reason":"freeze_rekor_time_not_prestart"}
    source=m.get("source_commit_sha")
    paths=m.get("paths_sha256",{})
    rejected=[]
    # Verify that all static source blobs are exactly those committed at the immutable source SHA.
    for p,h in paths.items():
        if p.startswith(".github/workflows/"):
            continue
        try:
            got=digest(source_blob(source,p))
        except Exception:
            rejected.append({"path":p,"reason":"source_blob_unreadable"})
            continue
        if got!=h:
            rejected.append({"path":p,"reason":"source_blob_hash_not_frozen"})
    # Verify every signed event came from a workflow commit whose workflow content is frozen.
    for e in events:
        wf=expected_workflow(e.get("type"),forecast_workflow,outcome_workflow)
        try:
            got=digest(workflow_blob(e["workflow_commit"],wf))
        except Exception:
            rejected.append({"sequence":e.get("sequence"),"reason":"workflow_commit_unreadable"})
            continue
        if got!=paths.get(wf):
            rejected.append({"sequence":e.get("sequence"),"reason":"workflow_hash_not_frozen"})
    return {
        "ok":not rejected,
        "rejected":rejected,
        "manifest_sha256":freeze.get("manifest_sha256"),
        "source_commit_sha":source,
        "freeze_rekor_integrated_utc":freeze_integrated.isoformat(),
        "cosign_rekor_verified_events":len(events),
    }

def dist(e):
    return np.asarray([e["lower_first"],e["upper_first"],e["neither"],e["ambiguous_same_bar"]],dtype=float)

def metrics(p,y):
    one=np.eye(4)[y];eps=1e-12
    brier=float(np.mean(np.sum((p-one)**2,axis=1)))
    ll=float(-np.mean(np.log(np.clip(p[np.arange(len(y)),y],eps,1))))
    conf=p.max(axis=1);correct=p.argmax(axis=1)==y
    ece=0.0
    for a,b in zip(np.linspace(0,1,11)[:-1],np.linspace(0,1,11)[1:]):
        m=(conf>=a)&(conf<(b if b<1 else 1.000001))
        if np.any(m):
            ece+=float(np.mean(m))*abs(float(np.mean(correct[m]))-float(np.mean(conf[m])))
    return {"brier":brier,"log_loss":ll,"ece10":ece}

def block_lower(gain,dates,block_days,alpha=.05/3,n_boot=1200):
    dates=np.asarray(dates,dtype="datetime64[s]")
    origin=dates.min().astype("datetime64[D]")
    block=((dates.astype("datetime64[D]")-origin)/np.timedelta64(block_days,"D")).astype(int)
    groups=[np.flatnonzero(block==x) for x in np.unique(block)]
    if len(groups)<3:return None
    rng=np.random.default_rng(20261005+block_days)
    vals=[]
    for _ in range(n_boot):
        ids=np.concatenate([groups[i] for i in rng.integers(len(groups),size=len(groups))])
        vals.append(float(np.mean(gain[ids])))
    return float(np.quantile(vals,alpha))

def nonoverlap_mask(anchors,horizon_hours):
    step=int(horizon_hours*3600)
    sec=np.asarray([(a-START).total_seconds() for a in anchors],dtype=np.int64)
    return np.mod(sec,step)==0

def episode_count(vol_bins):
    if not len(vol_bins):return 0
    return 1+int(np.sum(np.asarray(vol_bins[1:])!=np.asarray(vol_bins[:-1])))

def early_warning(forecast_map,outcome_map,model):
    rows=[]
    for slot,f in forecast_map.items():
        o=outcome_map.get(slot)
        if not o:continue
        actual=CLASS_TO_ID[o["outcome_class"]]
        b=int(f["control"]["volatility_bin"])
        alerts=f["contenders"][model]["alerts_at_calibration_fpr20"]
        rows.append((b,actual,bool(alerts["lower_first"]),bool(alerts["upper_first"])))
    result={}
    for b in (0,1,2):
        rr=[x for x in rows if x[0]==b]
        if not rr:continue
        d={}
        for cls,name,idx in ((0,"lower",2),(1,"upper",3)):
            y=np.asarray([x[1]==cls for x in rr],dtype=bool)
            a=np.asarray([x[idx] for x in rr],dtype=bool)
            tp=int(np.sum(a&y));fp=int(np.sum(a&~y));fn=int(np.sum(~a&y));tn=int(np.sum(~a&~y))
            d[name]={
                "n":len(rr),
                "recall":None if tp+fn==0 else tp/(tp+fn),
                "fpr":None if fp+tn==0 else fp/(fp+tn),
                "precision":None if tp+fp==0 else tp/(tp+fp),
            }
        result[str(b)]=d
    return result

def score(events,head,horizon_hours,min_calendar_days,min_nonoverlap,min_episodes):
    forecasts={e["slot"]:e for e in events if e.get("type")=="FORECAST_ISSUED"}
    outcomes={e["slot"]:e for e in events if e.get("type")=="OUTCOME_RECORDED"}
    slots=sorted(set(forecasts)&set(outcomes),key=lambda s:parse(forecasts[s]["anchor_utc"]))
    if not slots:return {"status":"PENDING_NO_CLOSED_OUTCOMES"}
    anchors=[parse(forecasts[s]["anchor_utc"]) for s in slots]
    y=np.asarray([CLASS_TO_ID[outcomes[s]["outcome_class"]] for s in slots],dtype=int)
    primary=np.vstack([dist(forecasts[s]["control"]["primary_distribution"]) for s in slots])
    secondary=np.vstack([dist(forecasts[s]["control"]["secondary_distribution"]) for s in slots])
    candidate={m:np.vstack([dist(forecasts[s]["contenders"][m]["class_distribution"]) for s in slots]) for m in CONTENDERS}
    non=nonoverlap_mask(anchors,horizon_hours)
    cal_days=(max(anchors)-min(anchors)).total_seconds()/86400 if len(anchors)>1 else 0.0
    bins=[int(forecasts[s]["control"]["volatility_bin"]) for s in slots]
    episodes=episode_count(bins)
    base_full=metrics(primary,y);base_non=metrics(primary[non],y[non]) if np.any(non) else None
    result={
        "closed_forecasts":len(slots),"calendar_days":cal_days,
        "nonoverlap_count":int(np.sum(non)),"volatility_episode_count":episodes,
        "volatility_bins_seen":sorted(set(bins)),
        "primary_baseline_full":base_full,"primary_baseline_nonoverlap":base_non,
        "secondary_baseline_full":metrics(secondary,y),
        "contenders":{},"admission_ready":False,
        "multiple_comparison_control":{
            "familywise_alpha":.05,"contenders":3,
            "one_sided_quantile":.05/3,
            "block_lengths_days":[14,28]
        }
    }
    one=np.eye(4)[y];eps=1e-12
    for m,p in candidate.items():
        pm=metrics(p,y);pn=metrics(p[non],y[non]) if np.any(non) else None
        bg=np.sum((primary-one)**2,axis=1)-np.sum((p-one)**2,axis=1)
        lg=-np.log(np.clip(primary[np.arange(len(y)),y],eps,1))+np.log(np.clip(p[np.arange(len(y)),y],eps,1))
        ci={}
        for days in (14,28):
            ci[f"brier_gain_lower_{days}d"]=block_lower(bg,anchors,days)
            ci[f"logloss_gain_lower_{days}d"]=block_lower(lg,anchors,days)
        gates={
            "calendar":cal_days>=min_calendar_days,
            "nonoverlap":int(np.sum(non))>=min_nonoverlap,
            "episodes":episodes>=min_episodes and len(set(bins))==3,
            "brier_logloss_mean":pm["brier"]<base_full["brier"] and pm["log_loss"]<base_full["log_loss"],
            "familywise_block_ci":all(v is not None and v>0 for v in ci.values()),
            "calibration":pm["ece10"]<=base_full["ece10"]+.02,
        }
        result["contenders"][m]={
            "full":pm,"nonoverlap":pn,"uncertainty":ci,
            "gates":gates,"passes_all":all(gates.values())
        }
        if head=="early15m":
            result["contenders"][m]["early_warning_by_volatility_bin"]=early_warning(forecasts,outcomes,m)
    passing=[m for m,x in result["contenders"].items() if x["passes_all"]]
    result["admission_ready"]=bool(passing)
    if passing:
        passing.sort(key=lambda m:(result["contenders"][m]["full"]["brier"],
                                   result["contenders"][m]["full"]["log_loss"]))
        result["prospective_winner"]=passing[0]
    else:
        result["prospective_winner"]=None
    return result

def operational_summary(events):
    qs=[e for e in events if e.get("type")=="OPERATIONAL_OUTCOME_RECORDED"]
    out={}
    for e in qs:
        q=e["question_id"];out.setdefault(q,{"closed":0,"classes":{c:0 for c in CLASSES}})
        out[q]["closed"]+=1;out[q]["classes"][e["outcome_class"]]+=1
    return out

def main():
    import argparse
    ap=argparse.ArgumentParser();ap.add_argument("--head",choices=("hourly","early15m"),required=True)
    args=ap.parse_args()
    if args.head=="hourly":
        events_dir="predictive_vnext3_hourly_events"
        fw=".github/workflows/btc-predictive-vnext3-hourly.yml"
        ow=".github/workflows/btc-predictive-vnext3-hourly-outcome.yml"
        params=(72,90,30,12)
    else:
        events_dir="predictive_vnext3_early15m_events"
        fw=".github/workflows/btc-predictive-vnext3-early15m.yml"
        ow=".github/workflows/btc-predictive-vnext3-early15m-outcome.yml"
        params=(4,42,150,12)
    events,rekor=load_chain(events_dir,fw,ow)
    governance=verify_governance(events,rekor,fw,ow)
    result={
        "schema":"btc-predictive-vnext3-scorecard-v1","head":args.head,
        "governance":governance,"score":None,
        "operational":operational_summary(events)
    }
    if governance["ok"]:
        result["score"]=score(events,args.head,*params)
    print(json.dumps(result,ensure_ascii=False,indent=2,sort_keys=True))

if __name__=="__main__":
    main()
