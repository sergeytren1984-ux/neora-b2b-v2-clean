"""Independent prospective scorecard for BTC Predictive vNext4R3.

All admission statistics are computed on the preregistered fixed-phase
non-overlapping subset. Overlapping forecasts are descriptive only.
"""
from __future__ import annotations

import hashlib
import json
import math
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

UTC=timezone.utc
ROOT=Path(__file__).resolve().parents[1]
START=datetime(2026,10,5,12,0,tzinfo=UTC)
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

def event_files(root,events_dir):
    d=Path(root)/events_dir
    return sorted(p for p in d.glob("*.json") if len(p.stem)==8 and p.stem.isdigit())

def bundle_time(bundle):
    b=json.loads(Path(bundle).read_bytes())
    entries=b.get("verificationMaterial",{}).get("tlogEntries",[])
    if not entries: raise ValueError("Rekor entry missing")
    for e in entries:
        proof=e.get("inclusionProof")
        if not isinstance(proof,dict) or not proof.get("checkpoint") or "hashes" not in proof:
            raise ValueError("Rekor inclusion proof missing")
    return min(datetime.fromtimestamp(int(e["integratedTime"]),UTC) for e in entries)

def expected_workflow(event_type,fw,ow):
    return ow if event_type in ("OUTCOME_RECORDED","OPERATIONAL_OUTCOME_RECORDED") else fw

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

def verify_signature(path,event,fw,ow):
    wf=expected_workflow(event.get("type"),fw,ow)
    bundle=path.with_suffix(".sigstore.json")
    subprocess.run([
        "cosign","verify-blob",str(path),"--bundle",str(bundle),
        "--certificate-identity",identity(wf),"--certificate-oidc-issuer",ISSUER,
        *signature_claim_args(event),
    ],check=True,capture_output=True,text=True,timeout=180)
    return bundle_time(bundle)

def load_chain(root,events_dir,fw,ow):
    out=[];prev=None;keys=set();rekor={}
    for i,p in enumerate(event_files(root,events_dir),1):
        raw=p.read_bytes();e=json.loads(raw)
        if raw!=canonical(e) or e.get("sequence")!=i or e.get("previous_hash")!=prev:
            raise ValueError("event chain invalid at "+str(p))
        if e.get("idempotency_key") in keys: raise ValueError("duplicate idempotency key")
        integrated=verify_signature(p,e,fw,ow)
        rekor[i]=integrated
        keys.add(e["idempotency_key"]);prev=digest(raw);out.append(e)
    return out,rekor

def git_blob(repo_root,commit,path):
    return subprocess.run(["git","-C",str(repo_root),"show",f"{commit}:{path}"],
                          check=True,capture_output=True,timeout=180).stdout

def verify_governance(repo_root,events,rekor,fw,ow,protocol_path):
    freezes=[e for e in events if e.get("type")=="CONFIG_FROZEN_PRESTART"]
    if len(freezes)!=1:return {"ok":False,"reason":"freeze_count_not_one"}
    freeze=freezes[0];m=freeze.get("manifest")
    if not isinstance(m,dict) or digest(canonical(m))!=freeze.get("manifest_sha256"):
        return {"ok":False,"reason":"signed_manifest_hash_invalid"}
    integrated=rekor.get(int(freeze["sequence"]))
    if integrated is None or integrated>=START:
        return {"ok":False,"reason":"freeze_rekor_time_not_prestart"}
    source=m.get("source_commit_sha");paths=m.get("paths_sha256",{})
    rejected=[]
    try:
        protocol=json.loads(git_blob(repo_root,source,protocol_path))
        deadline_minutes=int(protocol["issuance_deadline_minutes"])
    except Exception:
        return {"ok":False,"reason":"frozen_protocol_unreadable"}

    for p,h in paths.items():
        if p.startswith(".github/workflows/"):continue
        try: got=digest(git_blob(repo_root,source,p))
        except Exception:
            rejected.append({"path":p,"reason":"immutable_source_blob_unreadable"});continue
        if got!=h:rejected.append({"path":p,"reason":"immutable_source_hash_not_frozen"})

    for e in events:
        seq=int(e.get("sequence",0));etype=e.get("type")
        wf=expected_workflow(etype,fw,ow)
        try: got=digest(git_blob(repo_root,e["workflow_commit"],wf))
        except Exception:
            rejected.append({"sequence":seq,"reason":"workflow_commit_unreadable"});continue
        if got!=paths.get(wf):
            rejected.append({"sequence":seq,"reason":"workflow_hash_not_frozen"})
        it=rekor.get(seq)
        if it is None:
            rejected.append({"sequence":seq,"reason":"rekor_time_missing"})
            continue
        if etype=="FORECAST_ISSUED":
            anchor=parse(e["anchor_utc"]);deadline=anchor+timedelta(minutes=deadline_minutes)
            if it<anchor or it>=deadline:
                rejected.append({"sequence":seq,"reason":"forecast_rekor_time_outside_slot",
                                 "integrated":it.isoformat(),"anchor":anchor.isoformat(),
                                 "deadline":deadline.isoformat()})
        elif etype in ("OUTCOME_RECORDED","OPERATIONAL_OUTCOME_RECORDED"):
            due=parse(e["due_utc"])
            if it<due:
                rejected.append({"sequence":seq,"reason":"outcome_rekor_time_before_due",
                                 "integrated":it.isoformat(),"due":due.isoformat()})
        if etype in ("FORECAST_ISSUED","OUTCOME_RECORDED","OPERATIONAL_OUTCOME_RECORDED"):
            raw_path=e.get("raw_path");raw_sha=e.get("raw_sha256")
            if not raw_path or not raw_sha:
                rejected.append({"sequence":seq,"reason":"raw_reference_missing"})
            else:
                rp=Path(repo_root)/raw_path
                if not rp.exists():
                    rejected.append({"sequence":seq,"reason":"raw_file_missing","path":raw_path})
                elif digest(rp.read_bytes())!=raw_sha:
                    rejected.append({"sequence":seq,"reason":"raw_hash_mismatch","path":raw_path})
    # Every forecast must have exactly one signed DELIVERY_CONFIRMED receipt.
    # The receipt is created only after git push + ls-remote saw the forecast
    # commit on the remote evidence branch. Its Rekor integration must itself
    # occur before the frozen issuance deadline.
    receipts={}
    for e in events:
        if e.get("type")=="DELIVERY_CONFIRMED":
            receipts.setdefault(int(e.get("target_sequence",-1)),[]).append(e)
    forecast_count=0
    receipt_count=0
    for f in events:
        if f.get("type")!="FORECAST_ISSUED":
            continue
        forecast_count+=1
        seq=int(f["sequence"])
        rs=receipts.get(seq,[])
        if len(rs)!=1:
            rejected.append({"sequence":seq,"reason":"forecast_delivery_receipt_count","count":len(rs)})
            continue
        r=rs[0];receipt_count+=1
        rseq=int(r["sequence"])
        deadline=parse(f["anchor_utc"])+timedelta(minutes=deadline_minutes)
        if r.get("slot")!=f.get("slot") or r.get("target_event_hash")!=digest(canonical(f)):
            rejected.append({"sequence":rseq,"reason":"delivery_receipt_target_mismatch"})
        rit=rekor.get(rseq)
        if rit is None or rit>=deadline:
            rejected.append({"sequence":rseq,"reason":"delivery_receipt_rekor_not_before_deadline",
                             "deadline":deadline.isoformat(),
                             "integrated":None if rit is None else rit.isoformat()})
        try:
            remote_commit=r["remote_commit_sha"]
            # The referenced remote commit must contain the exact forecast event
            # at the ledger sequence path. Search the commit tree because the
            # event directory differs between heads.
            paths=subprocess.run(
                ["git","-C",str(repo_root),"ls-tree","-r","--name-only",remote_commit],
                check=True,capture_output=True,text=True,timeout=180
            ).stdout.splitlines()
            candidates=[p for p in paths if p.endswith(f"/{seq:08d}.json") and "predictive_vnext4r3_" in p and "_events/" in p]
            if len(candidates)!=1 or git_blob(repo_root,remote_commit,candidates[0])!=canonical(f):
                rejected.append({"sequence":rseq,"reason":"delivery_remote_commit_does_not_contain_forecast"})
        except Exception:
            rejected.append({"sequence":rseq,"reason":"delivery_remote_commit_unverifiable"})
    return {
        "ok":not rejected,"rejected":rejected,
        "manifest_sha256":freeze.get("manifest_sha256"),
        "source_commit_sha":source,
        "freeze_rekor_integrated_utc":integrated.isoformat(),
        "cosign_rekor_verified_events":len(events),
        "raw_integrity_and_due_time_checked":True,
        "forecast_delivery_receipts_checked":forecast_count,
        "valid_delivery_receipt_count":receipt_count,
    }

def dist(x):
    return np.asarray([x["lower_first"],x["upper_first"],x["neither"],x["ambiguous_same_bar"]],dtype=float)

def metrics(p,y):
    one=np.eye(4)[y];eps=1e-12
    brier=float(np.mean(np.sum((p-one)**2,axis=1)))
    ll=float(-np.mean(np.log(np.clip(p[np.arange(len(y)),y],eps,1))))
    conf=p.max(axis=1);correct=p.argmax(axis=1)==y
    ece=0.0
    for a,b in zip(np.linspace(0,1,11)[:-1],np.linspace(0,1,11)[1:]):
        m=(conf>=a)&(conf<(b if b<1 else 1.000001))
        if np.any(m): ece+=float(np.mean(m))*abs(float(np.mean(correct[m]))-float(np.mean(conf[m])))
    return {"brier":brier,"log_loss":ll,"ece10":ece}

def fixed_phase_nonoverlap(anchors,horizon_hours):
    step=int(horizon_hours*3600)
    sec=np.asarray([(a-START).total_seconds() for a in anchors],dtype=np.int64)
    return np.mod(sec,step)==0

def independent_episode_count(bins_non):
    # bins_non are already one full horizon apart. Each run therefore represents
    # at least one independent horizon-length regime observation.
    if not len(bins_non):return 0
    return 1+int(np.sum(np.asarray(bins_non[1:])!=np.asarray(bins_non[:-1])))

def block_lower(gain,anchors,block_days,alpha=.05/3,n_boot=1500):
    if len(gain)<3:return None
    dates=np.asarray([np.datetime64(a.replace(tzinfo=None),"s") for a in anchors])
    origin=dates.min().astype("datetime64[D]")
    block=((dates.astype("datetime64[D]")-origin)/np.timedelta64(block_days,"D")).astype(int)
    groups=[np.flatnonzero(block==b) for b in np.unique(block)]
    if len(groups)<3:return None
    rng=np.random.default_rng(20261005+block_days)
    vals=[]
    for _ in range(n_boot):
        ids=np.concatenate([groups[i] for i in rng.integers(len(groups),size=len(groups))])
        vals.append(float(np.mean(gain[ids])))
    return float(np.quantile(vals,alpha))

def wilson(k,n,z=1.959963984540054):
    if n<=0:return None
    p=k/n;den=1+z*z/n
    centre=(p+z*z/(2*n))/den
    half=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/den
    return [max(0.0,centre-half),min(1.0,centre+half)]

def binary_stats(actual,alert):
    actual=np.asarray(actual,dtype=bool);alert=np.asarray(alert,dtype=bool)
    tp=int(np.sum(alert&actual));fp=int(np.sum(alert&~actual))
    fn=int(np.sum(~alert&actual));tn=int(np.sum(~alert&~actual))
    rec_n=tp+fn;fpr_n=fp+tn;prec_n=tp+fp
    return {
        "tp":tp,"fp":fp,"fn":fn,"tn":tn,
        "recall":None if rec_n==0 else tp/rec_n,"recall_ci95":wilson(tp,rec_n),
        "fpr":None if fpr_n==0 else fp/fpr_n,"fpr_ci95":wilson(fp,fpr_n),
        "precision":None if prec_n==0 else tp/prec_n,"precision_ci95":wilson(tp,prec_n),
    }

def early_warning(forecasts,outcomes,model,non_slots):
    all_slots=sorted(set(forecasts)&set(outcomes),key=lambda s:parse(forecasts[s]["anchor_utc"]))
    result={}
    for scope,slots in (("all_overlapping_descriptive",all_slots),("fixed_phase_nonoverlap",non_slots)):
        by_bin={}
        for b in (0,1,2):
            ss=[s for s in slots if int(forecasts[s]["control"]["volatility_bin"])==b]
            if not ss:continue
            block={}
            for cls,name in ((0,"lower"),(1,"upper")):
                actual=[CLASS_TO_ID[outcomes[s]["outcome_class"]]==cls for s in ss]
                alert=[bool(forecasts[s]["contenders"][model]["alerts_at_calibration_fpr20"][name+"_first"]) for s in ss]
                stat=binary_stats(actual,alert)
                leads=[]
                for s,a,al in zip(ss,actual,alert):
                    touch=outcomes[s].get("first_touch_time_utc")
                    if a and al and touch:
                        leads.append((parse(touch)-parse(forecasts[s]["anchor_utc"])).total_seconds()/60)
                stat["median_minutes_to_true_touch_after_alert"]=None if not leads else float(np.median(leads))
                block[name]=stat
            by_bin[str(b)]=block
        result[scope]=by_bin
    return result

def slot_text(anchor):
    return anchor.strftime("%Y%m%dT%H%M%SZ")

def expected_due_grid(as_of_utc,horizon_hours):
    step=timedelta(hours=horizon_hours)
    out=[];anchor=START
    while anchor+step<=as_of_utc:
        out.append(anchor);anchor+=step
    return out

def score(events,head,horizon_hours,min_calendar_days,min_nonoverlap,min_episodes,as_of_utc=None):
    as_of_utc=as_of_utc or datetime.now(UTC)
    forecasts={e["slot"]:e for e in events if e.get("type")=="FORECAST_ISSUED"}
    outcomes={e["slot"]:e for e in events if e.get("type")=="OUTCOME_RECORDED"}
    overlap_slots=sorted(set(forecasts)&set(outcomes),key=lambda s:parse(forecasts[s]["anchor_utc"]))

    expected_anchors=expected_due_grid(as_of_utc,horizon_hours)
    expected_slots=[slot_text(a) for a in expected_anchors]
    missing_forecast=[];missing_outcome=[];malformed=[];complete_slots=[]
    step=timedelta(hours=horizon_hours)
    for anchor,slot in zip(expected_anchors,expected_slots):
        due=anchor+step
        f=forecasts.get(slot)
        if f is None:
            missing_forecast.append(slot);continue
        try:
            if parse(f["anchor_utc"])!=anchor or parse(f["due_utc"])!=due:
                malformed.append({"slot":slot,"reason":"forecast_anchor_or_due_mismatch"});continue
        except Exception:
            malformed.append({"slot":slot,"reason":"forecast_time_unreadable"});continue
        o=outcomes.get(slot)
        if o is None:
            missing_outcome.append(slot);continue
        try:
            if o.get("outcome_class") not in CLASS_TO_ID:
                malformed.append({"slot":slot,"reason":"outcome_class_invalid"});continue
            if parse(o["anchor_utc"])!=anchor or parse(o["due_utc"])!=due:
                malformed.append({"slot":slot,"reason":"outcome_anchor_or_due_mismatch"});continue
            if "published_at_utc" in o and parse(o["published_at_utc"])<due:
                malformed.append({"slot":slot,"reason":"outcome_published_before_due"});continue
        except Exception:
            malformed.append({"slot":slot,"reason":"outcome_time_unreadable"});continue
        complete_slots.append(slot)

    expected_n=len(expected_slots);complete_n=len(complete_slots)
    completeness={
        "as_of_utc":as_of_utc.isoformat(),
        "required_fraction":1.0,
        "expected_due_independent_slots":expected_n,
        "complete_due_independent_slots":complete_n,
        "fraction":None if expected_n==0 else complete_n/expected_n,
        "missing_forecast_count":len(missing_forecast),
        "missing_outcome_count":len(missing_outcome),
        "malformed_count":len(malformed),
        "missing_forecast_slots":missing_forecast,
        "missing_outcome_slots":missing_outcome,
        "malformed_slots":malformed,
        "complete":bool(expected_n>0 and complete_n==expected_n and
                        not missing_forecast and not missing_outcome and not malformed),
    }
    if expected_n==0:
        return {"status":"PENDING_NO_DUE_INDEPENDENT_WINDOWS",
                "outcome_completeness":completeness,"admission_ready":False}

    result={
        "status":"EVALUATED_PARTIAL" if not completeness["complete"] else "EVALUATED_COMPLETE",
        "outcome_completeness":completeness,
        "calendar_days":max(0.0,(as_of_utc-START).total_seconds()/86400),
        "expected_fixed_phase_nonoverlap_count":expected_n,
        "fixed_phase_nonoverlap_count":complete_n,
        "closed_forecasts_overlapping":len(overlap_slots),
        "contenders":{},"admission_ready":False,
        "admission_statistics_scope":"PREDECLARED_DUE_FIXED_PHASE_GRID_ONLY",
        "overlapping_forecasts":"DESCRIPTIVE_ONLY",
        "multiple_comparison_control":{"familywise_alpha":.05,"contenders":3,
                                       "one_sided_quantile":.05/3,
                                       "block_lengths_days":[14,28]},
    }

    if overlap_slots:
        oy=np.asarray([CLASS_TO_ID[outcomes[s]["outcome_class"]] for s in overlap_slots],dtype=int)
        op=np.vstack([dist(forecasts[s]["control"]["primary_distribution"]) for s in overlap_slots])
        result["descriptive_overlapping_primary"]=metrics(op,oy)

    if not complete_slots:
        result["independent_volatility_episode_count"]=0
        result["volatility_bins_seen_nonoverlap"]=[]
        result["prospective_winner"]=None
        return result

    anchors=[parse(forecasts[s]["anchor_utc"]) for s in complete_slots]
    y=np.asarray([CLASS_TO_ID[outcomes[s]["outcome_class"]] for s in complete_slots],dtype=int)
    primary=np.vstack([dist(forecasts[s]["control"]["primary_distribution"]) for s in complete_slots])
    secondary=np.vstack([dist(forecasts[s]["control"]["secondary_distribution"]) for s in complete_slots])
    candidates={m:np.vstack([dist(forecasts[s]["contenders"][m]["class_distribution"]) for s in complete_slots])
                for m in CONTENDERS}
    bins=[int(forecasts[s]["control"]["volatility_bin"]) for s in complete_slots]
    episodes=independent_episode_count(bins)
    base=metrics(primary,y)
    result.update({
        "independent_volatility_episode_count":episodes,
        "volatility_bins_seen_nonoverlap":sorted(set(bins)),
        "primary_baseline_nonoverlap":base,
        "secondary_baseline_nonoverlap":metrics(secondary,y),
    })
    one=np.eye(4)[y];eps=1e-12
    for m,p in candidates.items():
        pm=metrics(p,y)
        bg=np.sum((primary-one)**2,axis=1)-np.sum((p-one)**2,axis=1)
        lg=-np.log(np.clip(primary[np.arange(len(y)),y],eps,1))+np.log(np.clip(p[np.arange(len(y)),y],eps,1))
        ci={}
        for days in (14,28):
            ci[f"brier_gain_lower_{days}d"]=block_lower(bg,anchors,days)
            ci[f"logloss_gain_lower_{days}d"]=block_lower(lg,anchors,days)
        gates={
            "complete_due_grid":completeness["complete"],
            "calendar":result["calendar_days"]>=min_calendar_days,
            "nonoverlap_expected_grid":expected_n>=min_nonoverlap and complete_n==expected_n,
            "independent_episodes":episodes>=min_episodes and len(set(bins))==3,
            "brier_logloss_nonoverlap":pm["brier"]<base["brier"] and pm["log_loss"]<base["log_loss"],
            "familywise_block_ci_nonoverlap":all(v is not None and v>0 for v in ci.values()),
            "calibration_nonoverlap":pm["ece10"]<=base["ece10"]+.02,
        }
        result["contenders"][m]={
            "nonoverlap":pm,"uncertainty_nonoverlap":ci,"gates":gates,
            "passes_all":all(gates.values()),
        }
        if overlap_slots:
            pall=np.vstack([dist(forecasts[s]["contenders"][m]["class_distribution"]) for s in overlap_slots])
            oy=np.asarray([CLASS_TO_ID[outcomes[s]["outcome_class"]] for s in overlap_slots],dtype=int)
            result["contenders"][m]["overlapping_descriptive"]=metrics(pall,oy)
        if head=="early15m":
            result["contenders"][m]["early_warning"]=early_warning(forecasts,outcomes,m,complete_slots)
    passing=[m for m,x in result["contenders"].items() if x["passes_all"]]
    result["admission_ready"]=bool(passing)
    if passing:
        passing.sort(key=lambda m:(result["contenders"][m]["nonoverlap"]["brier"],
                                   result["contenders"][m]["nonoverlap"]["log_loss"]))
        result["prospective_winner"]=passing[0]
    else:
        result["prospective_winner"]=None
    return result

def operational_summary(events):
    out={}
    for e in events:
        if e.get("type")!="OPERATIONAL_OUTCOME_RECORDED":continue
        q=e["question_id"];out.setdefault(q,{"closed":0,"classes":{c:0 for c in CLASSES}})
        out[q]["closed"]+=1;out[q]["classes"][e["outcome_class"]]+=1
    return out

def main():
    import argparse,os
    ap=argparse.ArgumentParser();ap.add_argument("--head",choices=("hourly","early15m"),required=True)
    ap.add_argument("--repo-root",default=os.environ.get("BTC_VNEXT4R3_EVIDENCE_ROOT",str(ROOT)))
    ap.add_argument("--as-of-utc",default=None,
                    help="ISO-8601 evaluation cutoff; defaults to current UTC")
    args=ap.parse_args()
    repo_root=Path(args.repo_root)
    if args.head=="hourly":
        events_dir="predictive_vnext4r3_hourly_events"
        fw=".github/workflows/btc-predictive-vnext4r3-hourly.yml"
        ow=".github/workflows/btc-predictive-vnext4r3-hourly.yml"
        protocol_path="predictive_vnext4r3/protocol_hourly.json"
        params=(72,90,30,12)
    else:
        events_dir="predictive_vnext4r3_early15m_events"
        fw=".github/workflows/btc-predictive-vnext4r3-early15m.yml"
        ow=".github/workflows/btc-predictive-vnext4r3-early15m.yml"
        protocol_path="predictive_vnext4r3/protocol_early15m.json"
        params=(4,42,150,12)
    events,rekor=load_chain(repo_root,events_dir,fw,ow)
    governance=verify_governance(repo_root,events,rekor,fw,ow,protocol_path)
    result={"schema":"btc-predictive-vnext4r3-scorecard-v1","head":args.head,
            "governance":governance,"score":None,"operational":operational_summary(events)}
    as_of=parse(args.as_of_utc) if args.as_of_utc else datetime.now(UTC)
    if governance["ok"]:result["score"]=score(events,args.head,*params,as_of_utc=as_of)
    print(json.dumps(result,ensure_ascii=False,indent=2,sort_keys=True))

if __name__=="__main__":main()
