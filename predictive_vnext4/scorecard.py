"""Independent prospective scorecard for BTC Predictive vNext4.

All admission statistics are computed on the preregistered fixed-phase
non-overlapping subset. Overlapping forecasts are descriptive only.
"""
from __future__ import annotations

import hashlib
import json
import math
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

def verify_signature(path,event,fw,ow):
    wf=expected_workflow(event.get("type"),fw,ow)
    bundle=path.with_suffix(".sigstore.json")
    subprocess.run([
        "cosign","verify-blob",str(path),"--bundle",str(bundle),
        "--certificate-identity",identity(wf),"--certificate-oidc-issuer",ISSUER
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

def verify_governance(repo_root,events,rekor,fw,ow):
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
    for p,h in paths.items():
        if p.startswith(".github/workflows/"):continue
        try: got=digest(git_blob(repo_root,source,p))
        except Exception:
            rejected.append({"path":p,"reason":"immutable_source_blob_unreadable"});continue
        if got!=h:rejected.append({"path":p,"reason":"immutable_source_hash_not_frozen"})
    for e in events:
        wf=expected_workflow(e.get("type"),fw,ow)
        try: got=digest(git_blob(repo_root,e["workflow_commit"],wf))
        except Exception:
            rejected.append({"sequence":e.get("sequence"),"reason":"workflow_commit_unreadable"});continue
        if got!=paths.get(wf):
            rejected.append({"sequence":e.get("sequence"),"reason":"workflow_hash_not_frozen"})
    return {
        "ok":not rejected,"rejected":rejected,
        "manifest_sha256":freeze.get("manifest_sha256"),
        "source_commit_sha":source,
        "freeze_rekor_integrated_utc":integrated.isoformat(),
        "cosign_rekor_verified_events":len(events),
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

def score(events,head,horizon_hours,min_calendar_days,min_nonoverlap,min_episodes):
    forecasts={e["slot"]:e for e in events if e.get("type")=="FORECAST_ISSUED"}
    outcomes={e["slot"]:e for e in events if e.get("type")=="OUTCOME_RECORDED"}
    slots=sorted(set(forecasts)&set(outcomes),key=lambda s:parse(forecasts[s]["anchor_utc"]))
    if not slots:return {"status":"PENDING_NO_CLOSED_OUTCOMES"}
    anchors=[parse(forecasts[s]["anchor_utc"]) for s in slots]
    non_mask=fixed_phase_nonoverlap(anchors,horizon_hours)
    non_slots=[s for s,m in zip(slots,non_mask) if m]
    y=np.asarray([CLASS_TO_ID[outcomes[s]["outcome_class"]] for s in slots],dtype=int)
    y_non=y[non_mask]
    primary=np.vstack([dist(forecasts[s]["control"]["primary_distribution"]) for s in slots])
    secondary=np.vstack([dist(forecasts[s]["control"]["secondary_distribution"]) for s in slots])
    candidates={m:np.vstack([dist(forecasts[s]["contenders"][m]["class_distribution"]) for s in slots]) for m in CONTENDERS}
    primary_non=primary[non_mask];secondary_non=secondary[non_mask]
    anchors_non=[a for a,m in zip(anchors,non_mask) if m]
    bins_all=[int(forecasts[s]["control"]["volatility_bin"]) for s in slots]
    bins_non=[int(forecasts[s]["control"]["volatility_bin"]) for s in non_slots]
    cal_days=(max(anchors)-min(anchors)).total_seconds()/86400 if len(anchors)>1 else 0.0
    episodes=independent_episode_count(bins_non)
    base_non=metrics(primary_non,y_non) if len(y_non) else None
    result={
        "closed_forecasts_overlapping":len(slots),
        "calendar_days":cal_days,
        "fixed_phase_nonoverlap_count":len(non_slots),
        "independent_volatility_episode_count":episodes,
        "volatility_bins_seen_nonoverlap":sorted(set(bins_non)),
        "descriptive_overlapping_primary":metrics(primary,y),
        "primary_baseline_nonoverlap":base_non,
        "secondary_baseline_nonoverlap":metrics(secondary_non,y_non) if len(y_non) else None,
        "contenders":{},"admission_ready":False,
        "admission_statistics_scope":"FIXED_PHASE_NONOVERLAP_ONLY",
        "multiple_comparison_control":{"familywise_alpha":.05,"contenders":3,
                                       "one_sided_quantile":.05/3,
                                       "block_lengths_days":[14,28]},
    }
    if not len(y_non):return result
    one=np.eye(4)[y_non];eps=1e-12
    for m,p_all in candidates.items():
        p=p_all[non_mask]
        pm=metrics(p,y_non)
        bg=np.sum((primary_non-one)**2,axis=1)-np.sum((p-one)**2,axis=1)
        lg=-np.log(np.clip(primary_non[np.arange(len(y_non)),y_non],eps,1))+np.log(np.clip(p[np.arange(len(y_non)),y_non],eps,1))
        ci={}
        for days in (14,28):
            ci[f"brier_gain_lower_{days}d"]=block_lower(bg,anchors_non,days)
            ci[f"logloss_gain_lower_{days}d"]=block_lower(lg,anchors_non,days)
        gates={
            "calendar":cal_days>=min_calendar_days,
            "nonoverlap":len(non_slots)>=min_nonoverlap,
            "independent_episodes":episodes>=min_episodes and len(set(bins_non))==3,
            "brier_logloss_nonoverlap":pm["brier"]<base_non["brier"] and pm["log_loss"]<base_non["log_loss"],
            "familywise_block_ci_nonoverlap":all(v is not None and v>0 for v in ci.values()),
            "calibration_nonoverlap":pm["ece10"]<=base_non["ece10"]+.02,
        }
        result["contenders"][m]={
            "nonoverlap":pm,"uncertainty_nonoverlap":ci,"gates":gates,
            "passes_all":all(gates.values()),
            "overlapping_descriptive":metrics(p_all,y),
        }
        if head=="early15m":
            result["contenders"][m]["early_warning"]=early_warning(forecasts,outcomes,m,non_slots)
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
    ap.add_argument("--repo-root",default=os.environ.get("BTC_VNEXT4_EVIDENCE_ROOT",str(ROOT)))
    args=ap.parse_args()
    repo_root=Path(args.repo_root)
    if args.head=="hourly":
        events_dir="predictive_vnext4_hourly_events"
        fw=".github/workflows/btc-predictive-vnext4-hourly.yml"
        ow=".github/workflows/btc-predictive-vnext4-hourly-outcome.yml"
        params=(72,90,30,12)
    else:
        events_dir="predictive_vnext4_early15m_events"
        fw=".github/workflows/btc-predictive-vnext4-early15m.yml"
        ow=".github/workflows/btc-predictive-vnext4-early15m-outcome.yml"
        params=(4,42,150,12)
    events,rekor=load_chain(repo_root,events_dir,fw,ow)
    governance=verify_governance(repo_root,events,rekor,fw,ow)
    result={"schema":"btc-predictive-vnext4-scorecard-v1","head":args.head,
            "governance":governance,"score":None,"operational":operational_summary(events)}
    if governance["ok"]:result["score"]=score(events,args.head,*params)
    print(json.dumps(result,ensure_ascii=False,indent=2,sort_keys=True))

if __name__=="__main__":main()
