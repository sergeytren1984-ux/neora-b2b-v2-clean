"""GitHub-only v7R2 signed prospective registry and slot/outcome pipeline.

All durable evidence lives in a separate Git branch; signed before push.
Missing scheduled slots are NEVER backfilled. Historical v7 is BASELINE_ONLY.
"""
from __future__ import annotations
import argparse,datetime as dt,hashlib,json,os,pathlib,subprocess,tempfile,urllib.parse,urllib.request
from btc_demand_v7.prospective_core import (
 UTC,HORIZONS,registered_grid,find_slot,forecast_receipt,price_outcome,
 score_fixed_grid,sha256,canonical,when
)
from btc_demand_v7.release_guard import check as check_release,certificate_source_sha
from btc_demand_v7.event_semantics import first_passage,BARRIERS
from btc_demand_v7.demand_change import estimate as estimate_demand

REPO="sergeytren1984-ux/neora-b2b-v2-clean"
SOURCE_BRANCH="btc-v7r2-prospective-contour-20261012"
EVIDENCE_BRANCH="btc-v7r2-prospective-evidence-20261013"
IDENTITY=f"https://github.com/{REPO}/.github/workflows/btc-v7r2-prospective.yml@refs/heads/{SOURCE_BRANCH}"

def run(*cmd,cwd=None):
    result=subprocess.run(cmd,check=True,cwd=cwd,text=True,
                          stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    return result.stdout.strip()

def now():return dt.datetime.now(UTC)

def sign(path):
    path=pathlib.Path(path)
    run("cosign","sign-blob","--yes","--bundle",str(path)+".sigstore.json",str(path))

def verify(path,source_sha):
    path=pathlib.Path(path)
    run("cosign","verify-blob",str(path),"--bundle",str(path)+".sigstore.json",
        "--certificate-identity",IDENTITY,
        "--certificate-oidc-issuer","https://token.actions.githubusercontent.com")
    if certificate_source_sha(str(path)+".sigstore.json")!=source_sha:
        raise RuntimeError("certificate source SHA mismatch")

def signed(root,name,obj):
    path=pathlib.Path(root)/name
    if path.exists():raise RuntimeError("immutable evidence collision "+str(path))
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(canonical(obj))
    sign(path)
    return path

def fetch_repo(base,create=False):
    run("gh","auth","setup-git")
    remote=f"https://github.com/{REPO}.git"
    if create:
        run("git","clone","--quiet","--no-checkout",remote,str(base))
        run("git","checkout","--quiet","--detach",os.environ["GITHUB_SHA"],cwd=base)
        run("git","switch","--quiet","-c",EVIDENCE_BRANCH,cwd=base)
    else:
        run("git","clone","--quiet","--depth","1","--branch",EVIDENCE_BRANCH,remote,str(base))
    run("git","config","user.name","btc-v7r2-evidence-bot",cwd=base)
    run("git","config","user.email","btc-v7r2-evidence-bot@users.noreply.github.com",cwd=base)

def publish(base,message):
    run("git","add","btc_v7r2_evidence",cwd=base)
    if not run("git","status","--porcelain",cwd=base):raise RuntimeError("nothing to publish")
    run("git","commit","--quiet","-m",message,cwd=base)
    run("git","push","--quiet","origin","HEAD:refs/heads/"+EVIDENCE_BRANCH,cwd=base)

def register(args):
    timestamp=now()
    grid=registered_grid(args.start_utc,days=args.days,
        source_sha=os.environ["GITHUB_SHA"],created_at=timestamp,
        source_ref="refs/heads/"+SOURCE_BRANCH)
    with tempfile.TemporaryDirectory() as temp:
        repo=pathlib.Path(temp)/"repository";fetch_repo(repo,create=True)
        root=repo/"btc_v7r2_evidence"
        signed(root,"schedule.json",grid)
        signed(root,"frozen_config.json",{
            "schema":"btc-v7r2-frozen-prestart-v1",
            "source_commit_sha":grid["model_source_sha"],
            "source_ref":grid["model_source_ref"],
            "start_utc":grid["start_utc"],
            "register_at_utc":timestamp.isoformat(),
            "grid_sha256":sha256(grid),"trading_authority":False,
            "training_source_run":38169934478,
            "prospective_skill_proven":False})
        publish(repo,"Sign v7R2 fixed future grid and frozen source before start")
    print("V7R2_REGISTERED",json.dumps({
        "start_utc":grid["start_utc"],"slots":len(grid["slots"]),
        "grid_sha256":sha256(grid),"source_sha":grid["model_source_sha"]}))

def raw_closes(pending,ts):
    """Retrieve closed 1m vendor bars. Payload kept for signed audit."""
    if not pending:return {},[]
    last_closed=(int(ts.timestamp()*1000)//60000)*60000
    first_target=min(
        int(when(x[0]["slot_utc"]).timestamp()*1000)
        if x[1].startswith("barrier_") else int(x[2].timestamp()*1000)
        for x in pending)
    by={}
    cursor=last_closed-1
    for page in range(5):
        query=urllib.parse.urlencode({
            "symbol":"BTCUSDT","interval":"1m","endTime":cursor,"limit":1000})
        req=urllib.request.Request(
            "https://data-api.binance.vision/api/v3/klines?"+query,
            headers={"User-Agent":"btc-v7r2-signed-prospective-outcome"})
        with urllib.request.urlopen(req,timeout=25) as resp:
            if resp.status!=200:raise RuntimeError("outcome market HTTP error")
            rows=json.load(resp)
        if not rows:break
        for row in rows:
            t=int(row[6])+1
            if t<=last_closed and int(row[0])+60000==t:by[t]=row
        cursor=int(rows[0][0])-1
        if cursor<first_target:break
    targets=set()
    for f,head,due,path in pending:
        end=int(due.timestamp()*1000)
        if head.startswith("barrier_"):
            start=int(when(f["slot_utc"]).timestamp()*1000)
            targets.update(range(start+60000,end+60000,60000))
        else:
            targets.add(end)
    return by,[by[t] for t in sorted(targets) if t in by]

def outcomes(root,grid,ts):
    pending=[]
    folders=root/"slots"
    if not folders.exists():return 0
    for fpath in folders.glob("*/forecast.json"):
        f=json.loads(fpath.read_text())
        if f.get("kind")!="FORECAST_ISSUED":continue
        for head in HORIZONS:
            path=fpath.parent/("outcome_"+head+".json")
            due=when(f["heads"][head]["target_utc"])
            if path.exists() or ts<due+dt.timedelta(minutes=2):continue
            pending.append((f,head,due,path))
        for horizon,(minutes,fraction) in BARRIERS.items():
            path=fpath.parent/("barrier_"+horizon+".json")
            due=when(f["slot_utc"])+dt.timedelta(minutes=minutes)
            if path.exists() or ts<due+dt.timedelta(minutes=2):continue
            pending.append((f,"barrier_"+horizon,due,path))
    if not pending:return 0
    bars,selected=raw_closes(pending,ts)
    if not selected:return 0
    payload={"schema":"btc-v7r2-vendor-raw-close-v1",
             "source":"Binance data-api BTCUSDT 1m","captured_utc":ts.isoformat(),
             "rows":selected}
    signed(root/"outcome_raw",os.environ["GITHUB_RUN_ID"]+".json",payload)
    digest=sha256(payload)
    completed=0
    verified=set()
    for f,head,due,path in pending:
        target=int(due.timestamp()*1000)
        fpath=path.parent/"forecast.json"
        if head.startswith("barrier_"):
            horizon=head.removeprefix("barrier_")
            minutes,threshold=BARRIERS[horizon]
            start=int(when(f["slot_utc"]).timestamp()*1000)
            stamps=range(start+60000,start+(minutes+1)*60000,60000)
            if not all(t in bars for t in stamps):
                continue
            if fpath not in verified:
                verify(fpath,grid["model_source_sha"]);verified.add(fpath)
            result=first_passage(f["slot_utc"],f["spot_reference"],
                                 [bars[t] for t in stamps],horizon)
            event={"schema":"btc-v7r2-barrier-outcome-v1",
                   "kind":"BARRIER_OUTCOME_RECORDED" if ts<=due+dt.timedelta(minutes=30)
                          else "BARRIER_OUTCOME_LATE",
                   "slot_id":f["slot_id"],"period":horizon,
                   "due_utc":due.isoformat(),"recorded_utc":ts.isoformat(),
                   "raw_market_sha256":digest,"forecast_sha256":sha256(f),
                   "frozen_grid_sha256":sha256(grid),
                   "result":result,"trading_authority":False}
            signed(path.parent,path.name,event)
            completed+=1
        else:
            if target not in bars:continue
            row=bars[target];o,hi,lo,c=map(float,[row[1],row[2],row[3],row[4]])
            if not(0<lo<=min(o,c)<=max(o,c)<=hi):
                raise RuntimeError("invalid vendor future OHLC")
            if fpath not in verified:
                verify(fpath,grid["model_source_sha"]);verified.add(fpath)
            signed(path.parent,path.name,price_outcome(
                grid,f,head,ts,c,raw_sha=digest))
            completed+=1
    return completed

def tick(args):
    with tempfile.TemporaryDirectory() as temp:
        repo=pathlib.Path(temp)/"repository";fetch_repo(repo)
        root=repo/"btc_v7r2_evidence"
        grid=json.loads((root/"schedule.json").read_text())
        verify(root/"schedule.json",grid["model_source_sha"])
        verify(root/"frozen_config.json",grid["model_source_sha"])
        freeze=json.loads((root/"frozen_config.json").read_text())
        if freeze["grid_sha256"]!=sha256(grid) or freeze["source_commit_sha"]!=grid["model_source_sha"]:
            raise RuntimeError("frozen registration integrity failure")
        if grid["model_source_sha"]!=os.environ["GITHUB_SHA"] or grid["model_source_ref"]!="refs/heads/"+SOURCE_BRANCH:
            raise RuntimeError("workflow source changed after freeze")
        current=now()
        slot=current.replace(minute=(current.minute//15)*15,second=0,microsecond=0)
        start=when(grid["start_utc"]);end=start+dt.timedelta(days=grid["days"])
        forecast=None
        if start<=slot<end:
            item=find_slot(grid,slot)
            folder=root/"slots"/item["id"]
            if not (folder/"forecast.json").exists():
                from btc_demand_v7.prospective_core import acceptance_at
                if acceptance_at(grid,slot,current)=="SLOT_MISSED":
                    forecast=forecast_receipt(grid,slot,current,None,
                                              snapshot_sha="",live_sha="")
                else:
                    raw=pathlib.Path(temp)/"market"
                    frozen=pathlib.Path(args.model_dir)
                    check_release(frozen,args.trusted_release)
                    run("python","-m","btc_demand_v7.live_snapshot","--out",str(raw))
                    snapshot=json.loads((raw/"snapshot.json").read_text())
                    if when(snapshot["anchor_utc"])!=slot:
                        raise RuntimeError("wrong source anchor: NO BACKFILL")
                    run("python","-m","btc_demand_v7.infer_live",
                        "--snapshot",str(raw/"snapshot.json"),
                        "--candidate",str(frozen/"candidate.joblib"),
                        "--audit",str(frozen/"audit.json"),
                        "--paired",str(frozen/"spot_paired_validation_errors.json"),
                        "--trusted-release",args.trusted_release,
                        "--output",str(raw/"live_forecast.json"))
                    live=json.loads((raw/"live_forecast.json").read_text())
                    issued=now()
                    snapshot_sha=hashlib.sha256((raw/"snapshot.json").read_bytes()).hexdigest()
                    live_sha=hashlib.sha256((raw/"live_forecast.json").read_bytes()).hexdigest()
                    forecast=forecast_receipt(grid,slot,issued,live,
                        snapshot_sha=snapshot_sha,live_sha=live_sha)
                    if forecast["kind"]=="FORECAST_ISSUED":
                        # Compare only with prior signed snapshots, never
                        # invented or backfilled OI/order-book observations.
                        prior=sorted((root/"slots").glob("*/snapshot.json")) if (root/"slots").exists() else []
                        historical=[]
                        for previous in prior[-32:]:
                            verify(previous,grid["model_source_sha"])
                            historical.append(json.loads(previous.read_text()))
                        forecast["demand_position_change"]=estimate_demand(historical+[snapshot])
                        for name in ("snapshot.json","observation.json","live_forecast.json"):
                            dest=folder/name
                            dest.parent.mkdir(parents=True,exist_ok=True)
                            dest.write_bytes((raw/name).read_bytes())
                            sign(dest)
                signed(folder,"forecast.json",forecast)
        timestamp=now()
        new_outcomes=outcomes(root,grid,timestamp)
        events=[json.loads(x.read_text()) for x in (root/"slots").glob("*/forecast.json")] if (root/"slots").exists() else []
        resolved=[json.loads(x.read_text()) for x in (root/"slots").glob("*/outcome_*.json")] if (root/"slots").exists() else []
        barrier_events=[json.loads(x.read_text()) for x in (root/"slots").glob("*/barrier_*.json")] if (root/"slots").exists() else []
        scored=score_fixed_grid(grid,events,resolved,timestamp,barrier_events)
        scored["github_run_id"]=os.environ["GITHUB_RUN_ID"]
        scored["model_source_sha"]=grid["model_source_sha"]
        signed(root/"scorecards",os.environ["GITHUB_RUN_ID"]+".json",scored)
        publish(repo,"Append signed v7R2 forecast/outcomes and full-denominator scorecard")
    print("V7R2_TICK",json.dumps({
        "slot":slot.isoformat(),
        "forecast":forecast["kind"] if forecast else "NOT_DUE_OR_ALREADY_RECORDED",
        "new_outcomes":new_outcomes,"due_slots":scored["due_forecast_slots"],
        "missing_forecasts":scored["missing_forecasts"],
        "missing_outcomes":scored["outcomes_missing"],
        "admission_ready":scored["admission_ready"]},sort_keys=True))

def main():
    p=argparse.ArgumentParser();p.add_argument("action",choices=["register","tick"])
    p.add_argument("--start-utc",default="");p.add_argument("--days",type=int,default=7)
    p.add_argument("--model-dir",default="/tmp/frozen-training")
    p.add_argument("--trusted-release",default="btc_demand_v7/trusted_release.json")
    args=p.parse_args()
    if args.action=="register":register(args)
    else:tick(args)

if __name__=="__main__":main()
