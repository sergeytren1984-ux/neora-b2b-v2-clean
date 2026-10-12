"""v7R3: independent signed prospective demand research, no trade permissions.

The only source of OI/depth/taker features is the PREVIOUSLY signed v7R2
prospective raw. Release and all future recorded decisions are signed using
GitHub OIDC Cosign/Rekor. No retroactive early warning is ever permitted.

Modes:
  register --start-utc ..., future >=2h -> frozen 672-slot schedule and SHA.
  tick -> only CURRENT UTC window, then resolves matured first-touch outcomes.
"""
from __future__ import annotations
import argparse, datetime as dt, hashlib, json, math, os, pathlib
import subprocess,tempfile,urllib.parse,urllib.request,concurrent.futures
from btc_demand_v7.shadow_contract_v3 import (
    grid,accept_slot,slot_id,digest,canonical,
    future_anchor,future_due,HORIZONS,status_grid,
    BRANCH,EVIDENCE,R2_EVIDENCE,SOURCE_R2_SHA,SOURCE_R2_GRID_SHA)
from btc_demand_v7.demand_change_v2 import (
    advance,state_zero,source_hash,BASELINE_COUNT)
from btc_demand_v7.event_semantics import first_passage
from btc_demand_v7.prospective_core import when
from btc_demand_v7.release_guard import certificate_source_sha

REPO="sergeytren1984-ux/neora-b2b-v2-clean"
ISSUER="https://token.actions.githubusercontent.com"
SELF_ID=f"https://github.com/{REPO}/.github/workflows/btc-v7r3-signed-demand-shadow.yml@refs/heads/{BRANCH}"
R2_ID=f"https://github.com/{REPO}/.github/workflows/btc-v7r2-prospective.yml@refs/heads/btc-v7r2-prospective-contour-20261012"

def utcnow():return dt.datetime.now(dt.timezone.utc)

def run(*args,cwd=None):
    p=subprocess.run(args,cwd=cwd,capture_output=True,text=True)
    if p.returncode:
        raise RuntimeError("command failed: "+" ".join(str(x) for x in args[:2])+": "+p.stderr[-600:])
    return p.stdout.strip()

def clone(target,branch,create=False):
    run("gh","auth","setup-git")
    remote="https://github.com/"+REPO+".git"
    if create:
        run("git","clone","--quiet","--no-checkout",remote,str(target))
        run("git","checkout","--quiet","--detach",os.environ["GITHUB_SHA"],cwd=target)
        run("git","switch","--quiet","-c",branch,cwd=target)
    else:
        run("git","clone","--quiet","--depth","1","--branch",branch,remote,str(target))
    run("git","config","user.name","btc-v7r3-signed-shadow-bot",cwd=target)
    run("git","config","user.email","btc-v7r3-signed-shadow-bot@users.noreply.github.com",cwd=target)

def sign(path):
    path=pathlib.Path(path)
    run("cosign","sign-blob","--yes","--bundle",str(path)+".sigstore.json",str(path))

def verify(path,identity,sha):
    p=pathlib.Path(path)
    run("cosign","verify-blob",str(p),"--bundle",str(p)+".sigstore.json",
        "--certificate-identity",identity,"--certificate-oidc-issuer",ISSUER)
    if certificate_source_sha(str(p)+".sigstore.json")!=sha:
        raise RuntimeError("Sigstore source commit is not the frozen signer")

def write(root,name,obj):
    path=pathlib.Path(root)/name
    if path.exists():raise RuntimeError("immutable signed evidence collision")
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(canonical(obj))
    sign(path)
    return path

def publish(ledger,message):
    run("git","add","btc_v7r3_evidence",cwd=ledger)
    if not run("git","status","--porcelain",cwd=ledger):
        raise RuntimeError("no new signed evidence")
    run("git","commit","--quiet","-m",message,cwd=ledger)
    run("git","push","--quiet","origin","HEAD:refs/heads/"+EVIDENCE,cwd=ledger)

def source_r2(r2_root):
    p=r2_root/"schedule.json"
    assert p.exists()
    registered=json.loads(p.read_text())
    if registered["model_source_sha"]!=SOURCE_R2_SHA or digest(registered)!=SOURCE_R2_GRID_SHA:
        raise RuntimeError("R2 upstream epoch not frozen at authorized source")
    verify(p,R2_ID,SOURCE_R2_SHA)
    freeze=r2_root/"frozen_config.json"
    verify(freeze,R2_ID,SOURCE_R2_SHA)
    if json.loads(freeze.read_text())["grid_sha256"]!=SOURCE_R2_GRID_SHA:
        raise RuntimeError("R2 prospective freeze inconsistency")
    return registered

def register(args):
    start=when(args.start_utc)
    timestamp=utcnow()
    with tempfile.TemporaryDirectory() as temp:
        tmp=pathlib.Path(temp);r2=tmp/"r2";ledger=tmp/"ledger"
        clone(r2,R2_EVIDENCE)
        source_r2(r2/"btc_v7r2_evidence")
        reg=grid(start,timestamp,os.environ["GITHUB_SHA"],days=args.days)
        clone(ledger,EVIDENCE,create=True)
        root=ledger/"btc_v7r3_evidence"
        write(root,"registration.json",reg)
        write(root,"frozen_config.json",{
            "schema":"btc-v7r3-signed-prestart-freeze-v1",
            "registered_at_utc":timestamp.isoformat(),
            "model_source_sha":os.environ["GITHUB_SHA"],
            "grid_sha256":digest(reg),
            "r2_source_sha":SOURCE_R2_SHA,
            "r2_grid_sha256":SOURCE_R2_GRID_SHA,
            "signed_upstream_r2":True,
            "trading_authority":False,"prospective_skill_proven":False})
        publish(ledger,"Freeze v7R3 stateful source, future decision deadlines and source lineage")
    print("BTC_V7R3_REGISTERED",json.dumps({
        "model_sha":reg["model_source_sha"],
        "upstream_r2_sha":SOURCE_R2_SHA,
        "grid_sha":digest(reg),"slots":len(reg["due_slots"]),
        "first_due":reg["due_slots"][0]["anchor_utc"]},sort_keys=True))

def last_close_before_issuance():
    """Read raw *closed* spot 1m price. Never extrapolate from old 5m anchor."""
    received=utcnow()
    cutoff=(int(received.timestamp()*1000)//60000)*60000
    query=urllib.parse.urlencode({"symbol":"BTCUSDT","interval":"1m",
                                  "endTime":cutoff-1,"limit":2})
    req=urllib.request.Request(
        "https://data-api.binance.vision/api/v3/klines?"+query,
        headers={"User-Agent":"btc-v7r3-asof-price-reference"})
    with urllib.request.urlopen(req,timeout=20) as response:
        if response.status!=200:raise RuntimeError("spot reference HTTP error")
        rows=json.load(response)
    acquired=utcnow()
    if not isinstance(rows,list) or not rows:raise ValueError("no fresh minute spot")
    row=rows[-1]
    if int(row[6])+1!=cutoff or int(row[0])+60000!=cutoff:
        raise ValueError("last price reference does not close at exact minute")
    op,hi,lo,c=map(float,[row[1],row[2],row[3],row[4]])
    if not(0<lo<=min(op,c)<=max(op,c)<=hi):
        raise ValueError("invalid last 1m price")
    if (acquired-dt.datetime.fromtimestamp(cutoff/1000,dt.timezone.utc))>dt.timedelta(minutes=2):
        raise ValueError("spot reference is stale")
    return {"source":"Binance BTCUSDT closed 1m spot","row":row,
            "minute_close_utc":dt.datetime.fromtimestamp(cutoff/1000,dt.timezone.utc).isoformat(),
            "received_at_utc":acquired.isoformat(),"spot":c}

def validated_snapshot(r2root,slot,expected_r2):
    directory=r2root/"slots"/slot_id(slot)
    snapshot_file=directory/"snapshot.json"
    forecast_file=directory/"forecast.json"
    if not(snapshot_file.is_file() and forecast_file.is_file()):
        return None
    verify(snapshot_file,R2_ID,SOURCE_R2_SHA)
    verify(forecast_file,R2_ID,SOURCE_R2_SHA)
    snapshot_bytes=snapshot_file.read_bytes()
    snap=json.loads(snapshot_bytes)
    forecast=json.loads(forecast_file.read_text())
    if forecast["kind"]!="FORECAST_ISSUED" or when(forecast["slot_utc"])!=slot:
        raise RuntimeError("R2 signed source has wrong slot/status")
    if when(snap["anchor_utc"])!=slot or forecast["snapshot_sha256"]!=hashlib.sha256(snapshot_bytes).hexdigest():
        raise RuntimeError("R2 snapshot digest does not match its signed forecast")
    if forecast["frozen_grid_sha256"]!=SOURCE_R2_GRID_SHA:
        raise RuntimeError("R2 snapshot from wrong registered epoch")
    return snap

def historic_snapshots(r2root,slot):
    # Verify distinct source snapshots/forecasts in parallel; serial 64+
    # Cosign verifications can exhaust a five-minute issuance window.
    anchors=[slot-dt.timedelta(minutes=15*i)
             for i in reversed(range(1,BASELINE_COUNT+1))]
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
        history=list(pool.map(lambda anchor:validated_snapshot(r2root,anchor,None),anchors))
    return None if any(x is None for x in history) else history

def available_previous_state(root,slot):
    previous=slot-dt.timedelta(minutes=15)
    path=root/"slots"/slot_id(previous)/"signal.json"
    if not path.exists():return None
    verify(path,SELF_ID,os.environ["GITHUB_SHA"])
    prior=json.loads(path.read_text())
    return prior.get("state")

def current_slot_signal(root,r2root,reg,ts):
    slot=ts.replace(minute=ts.minute//15*15,second=0,microsecond=0)
    if not(when(reg["start_utc"])<=slot<when(reg["end_utc"])):
        return "OUTSIDE_FUTURE_EPOCH"
    path=root/"slots"/slot_id(slot)/"signal.json"
    if path.exists():return "DUPLICATE_NO_MUTATION"
    due=accept_slot(reg,slot,ts)
    if due=="NOT_YET_DUE":return due
    # An issue after deadline is explicitly counted MISSING, never backdated.
    if due=="MISSED_DEADLINE":
        write(path.parent,path.name,{
            "schema":"btc-v7r3-signed-pressure-event-v1",
            "slot_id":slot_id(slot),"anchor_utc":slot.isoformat(),
            "status":"MISSED_DEADLINE","published_utc":ts.isoformat(),
            "trading_authority":False})
        return due
    snapshot=validated_snapshot(r2root,slot,None)
    if snapshot is None:
        # Try again before deadline. Absent final evidence is still a missing slot.
        return "WAITING_R2_SIGNED_SNAPSHOT"
    history=historic_snapshots(r2root,slot)
    if history is None:
        write(path.parent,path.name,{
            "schema":"btc-v7r3-signed-pressure-event-v1",
            "slot_id":slot_id(slot),"anchor_utc":slot.isoformat(),
            "status":"INSUFFICIENT_ASOF_HISTORY","published_utc":utcnow().isoformat(),
            "state":state_zero(),"trading_authority":False})
        return "INSUFFICIENT_ASOF_HISTORY"
    # Exactly ONE clean initialization, after the first 32 signed slots.
    # Any later missing predecessor is a disqualifying continuity break,
    # NOT permission to reset the same-day alert budget or CUSUM.
    first_eligible=when(reg["start_utc"])+dt.timedelta(minutes=15*BASELINE_COUNT)
    previous_state=available_previous_state(root,slot)
    if previous_state is None and slot!=first_eligible:
        write(path.parent,path.name,{
            "schema":"btc-v7r3-signed-pressure-event-v1",
            "slot_id":slot_id(slot),"anchor_utc":slot.isoformat(),
            "status":"STATEFUL_CHAIN_DISCONTINUITY",
            "published_utc":utcnow().isoformat(),
            "zero_reset_not_allowed":True,"trading_authority":False})
        return "STATEFUL_CHAIN_DISCONTINUITY"
    if slot==first_eligible and previous_state is not None:
        raise RuntimeError("untrusted state before frozen warmup completed")
    state=state_zero() if previous_state is None else previous_state
    if previous_state is not None:
        previous_record=root/"slots"/slot_id(slot-dt.timedelta(minutes=15))/"signal.json"
        prior=json.loads(previous_record.read_text())
        if prior.get("status")!="SIGNED_STATE_PUBLISHED":
            raise RuntimeError("predecessor not a continuous signed model state")
        if previous_state["sequence"]<1:
            raise RuntimeError("improper signed state sequence")
        if previous_state.get("last_alert_utc") is not None:
            # The single alert/day policy stays bound to the signed state.
            prior_alert=when(previous_state["last_alert_utc"])
            if prior_alert>slot:raise RuntimeError("future last-alert state")
    reference=last_close_before_issuance()
    issued=utcnow()
    if accept_slot(reg,slot,issued)!="ON_TIME":
        raise RuntimeError("source validation exhausted decision window")
    anchor_spot=float(snapshot["observation"]["reference_spot"])
    actual_publication_spot=float(reference["spot"])
    if not(math.isfinite(anchor_spot) and anchor_spot>0
           and math.isfinite(actual_publication_spot) and actual_publication_spot>0):
        raise RuntimeError("invalid source/current spot for late warning veto")
    unobserved_move_pct=100*(actual_publication_spot/anchor_spot-1)
    state,diagnostic=advance(
        state,history,snapshot,issued_utc=issued,
        live_change_since_anchor_pct=unobserved_move_pct)
    # A missed predecessor with nonzero CUSUM is rejected by the raw hash
    # chain, rather than silently rebuilding a favorable history.
    event={"schema":"btc-v7r3-signed-pressure-event-v1",
           "slot_id":slot_id(slot),"anchor_utc":slot.isoformat(),
           "status":"SIGNED_STATE_PUBLISHED",
           "issued_at_utc":issued.isoformat(),
           "github_run_id":os.environ.get("GITHUB_RUN_ID","SYNTHETIC_TEST"),
           "github_run_attempt":int(os.environ.get("GITHUB_RUN_ATTEMPT","1")),
           "public_delivery_only_after_successful_GitHub_run":True,
           "snapshot_received_at_utc":snapshot["retrieved_at_utc"],
           "reference_spot":reference["spot"],
           "underlying_spot_at_orderflow_anchor":anchor_spot,
           "market_move_during_information_latency_pct":unobserved_move_pct,
           "reference_1m_raw":reference,
           "decision_price_not_stale_5m":True,
           "upstream_r2_snapshot_canonical_sha256":source_hash(snapshot),
           "model_source_sha":reg["model_source_sha"],
           "registered_grid_sha256":digest(reg),
           "state":state,"diagnostic":diagnostic,
           "exact_future_first_full_minute_utc":future_anchor(issued).isoformat(),
           "target_utc":{h:future_due(issued,h).isoformat() for h in HORIZONS},
           "calibrated_probability":False,"trading_authority":False}
    write(path.parent,path.name,event)
    return "SIGNED_STATE_PUBLISHED"

def get_future_raw(pending,now):
    if not pending:return {}
    cutoff=(int(now.timestamp()*1000)//60000)*60000
    end=cutoff-1
    query=urllib.parse.urlencode({"symbol":"BTCUSDT","interval":"1m",
                                  "endTime":end,"limit":1000})
    req=urllib.request.Request(
        "https://data-api.binance.vision/api/v3/klines?"+query,
        headers={"User-Agent":"btc-v7r3-signed-forward-outcomes"})
    with urllib.request.urlopen(req,timeout=25) as response:
        if response.status!=200:raise RuntimeError("vendor price history unavailable")
        rows=json.load(response)
    recorded={}
    for r in rows:
        last=int(r[6])+1
        if last<=cutoff and last==int(r[0])+60000:
            recorded[last]=r
    return recorded

def verified_delivery_time(event):
    """Conservative signed GitHub *JOB completion* bound, not mutable updated_at.

    Verify run attempt, exact workflow path/ref, repository and frozen SHA.
    This can only establish delivery was no later than job completion; it
    CANNOT prove an earlier user notification or exchange quote delivery.
    """
    runid=event.get("github_run_id")
    if not runid or not str(runid).isdigit():
        raise RuntimeError("forecast lacks verifiable source GitHub run")
    headers={"Accept":"application/vnd.github+json",
             "X-GitHub-Api-Version":"2022-11-28",
             "User-Agent":"btc-v7r4-strict-delivery"}
    token=os.environ.get("GH_TOKEN")
    if token:headers["Authorization"]="Bearer "+token

    def get(url):
        req=urllib.request.Request(url,headers=headers)
        with urllib.request.urlopen(req,timeout=20) as response:
            return json.load(response)
    runurl=f"https://api.github.com/repos/{REPO}/actions/runs/{runid}"
    data=get(runurl)
    if data.get("status")!="completed":return None
    if data.get("conclusion")!="success":
        raise RuntimeError("signal source job has no successful completion")
    expected_path=f".github/workflows/btc-v7r3-signed-demand-shadow.yml@refs/heads/{BRANCH}"
    if (data.get("head_sha")!=event["model_source_sha"]
        or data.get("head_branch")!=BRANCH
        or data.get("event")!="workflow_dispatch"
        or data.get("path")!=expected_path
        or data.get("head_repository",{}).get("full_name")!=REPO):
        raise RuntimeError("GitHub delivery has wrong workflow/ref/repository")
    attempt=int(data.get("run_attempt",0))
    if attempt<1 or attempt!=int(event.get("github_run_attempt",1)):
        raise RuntimeError("GitHub delivery attempt differs from signed event")
    jobs=get(runurl+f"/attempts/{attempt}/jobs?per_page=100")
    candidates=[j for j in jobs.get("jobs",[]) if j.get("name")=="signed-research-only"
                and j.get("conclusion")=="success"
                and j.get("status")=="completed"
                and j.get("completed_at")]
    if len(candidates)!=1:
        raise RuntimeError("no single matching successfully completed forecast job")
    completed=when(candidates[0]["completed_at"])
    computed=when(event["issued_at_utc"])
    if completed<computed:
        raise RuntimeError("signed forecast completed after purported job completion")
    if completed<when(data["created_at"]):
        raise RuntimeError("completion before GitHub dispatch")
    return completed


def resolve_outcomes(root,now):
    pending=[]
    for p in (root/"slots").glob("*/signal.json") if (root/"slots").exists() else []:
        event=json.loads(p.read_text())
        if event.get("status")!="SIGNED_STATE_PUBLISHED":continue
        delivery_file=p.parent/"delivery.json"
        verify(p,SELF_ID,os.environ["GITHUB_SHA"])
        if delivery_file.exists():
            verify(delivery_file,SELF_ID,os.environ["GITHUB_SHA"])
            entry=json.loads(delivery_file.read_text())
            if entry.get("source_signal_sha256")!=digest(event):
                raise RuntimeError("delivery proof does not bind signed signal")
            delivery=when(entry["public_delivery_utc"])
        else:
            delivery=verified_delivery_time(event)
            if delivery is None:continue
            write(p.parent,"delivery.json",{
                "schema":"btc-v7r4-publication-receipt-v1",
                "slot_id":event["slot_id"],
                "public_delivery_utc":delivery.isoformat(),
                "source_signal_sha256":digest(event),
                "github_run_id":event["github_run_id"],
                "github_run_attempt":event["github_run_attempt"],
                "model_source_sha":event["model_source_sha"],
                "evidence_context":"successful forecast GitHub job completion; conservative bound",
                "trading_authority":False})
        for horizon in HORIZONS:
            due=future_due(delivery,horizon)
            filename=p.parent/("outcome_"+horizon+".json")
            if filename.exists() or now<due+dt.timedelta(minutes=2):continue
            pending.append((event,horizon,due,filename,p,delivery))
    if not pending:return 0
    bars=get_future_raw(pending,now)
    completed=0
    for event,horizon,due,path,eventpath,delivery in pending:
        start=future_anchor(delivery)
        target_times=[int((start+dt.timedelta(minutes=i)).timestamp()*1000)
                      for i in range(1,HORIZONS[horizon]+1)]
        ref_end=int(delivery.timestamp()*1000)//60000*60000
        if ref_end not in bars or not all(t in bars for t in target_times):
            continue
        reference_bar=bars[ref_end]
        # The public-completion reference is determined AFTER the run
        # completed. It is never used to compute the earlier warning.
        ref=float(reference_bar[4])
        if not(math.isfinite(ref) and ref>0):
            raise ValueError("invalid public-completion price reference")
        verify(eventpath,SELF_ID,os.environ["GITHUB_SHA"])
        raw={"schema":"btc-v7r3-closed-1m-forward-source-v2",
             "symbol":"BTCUSDT","requested_post_due_utc":now.isoformat(),
             "actual_publication_utc":delivery.isoformat(),
             "reference_minute_close_utc":dt.datetime.fromtimestamp(ref_end/1000,dt.timezone.utc).isoformat(),
             "reference_row":reference_bar,
             "first_complete_minute_anchor_utc":start.isoformat(),
             "rows":[bars[t] for t in target_times]}
        write(path.parent,"raw_"+horizon+".json",raw)
        result=first_passage(start,ref,raw["rows"],horizon)
        warning_side=event["diagnostic"].get("warning_side")
        predicted=("UP_FIRST" if warning_side=="UP" else
                   "DOWN_FIRST" if warning_side=="DOWN" else None)
        touch=result["first_barrier_touch_utc"]
        # Intra-minute high/low order unknown: earliest touch is the
        # minute OPEN. Use the LOWER bound of actionable warning lead.
        touch_open=when(touch)-dt.timedelta(minutes=1) if touch else None
        lead_lower=((touch_open-delivery).total_seconds()/60 if touch_open else None)
        lead_upper=((when(touch)-delivery).total_seconds()/60 if touch else None)
        pre_delivery_spot=float(event["reference_spot"])
        move_since_compute=100*(ref/pre_delivery_spot-1)
        moved_before_publication=(abs(move_since_compute)>=0.30)
        # Do not relabel the already-realized move as successful early
        # warning merely by resetting a first-touch barrier at delivery.
        lead_eligible=(delivery<=when(event["anchor_utc"])+dt.timedelta(minutes=13)
                       and not moved_before_publication
                       and event["diagnostic"].get("price_already_moved") is False)
        write(path.parent,path.name,{
            "schema":"btc-v7r3-signed-pre-move-forward-outcome-v1",
            "slot_id":event["slot_id"],"horizon":horizon,
            "due_utc":due.isoformat(),"recorded_at_utc":now.isoformat(),
            "public_delivery_utc":delivery.isoformat(),
            "model_computed_at_utc":event["issued_at_utc"],
            "source_github_run_id":event["github_run_id"],
            "reference_spot_at_public_delivery":ref,
            "reference_price_after_delivery_not_model_feature":True,
            "kind":"OUTCOME_RECORDED" if now<=due+dt.timedelta(minutes=35) else "OUTCOME_LATE",
            "source_raw_sha256":digest(raw),
            "source_signal_sha256":digest(event),
            "barrier_result":result,
            "warning_issued":bool(event["diagnostic"].get("alert")),
            "warning_side":predicted,
            "actual_first_touch_side":result["direction"],
            "warning_lead_minutes":lead_lower if predicted==result["direction"] else None,
            "warning_lead_lower_minutes":lead_lower,
            "warning_lead_upper_minutes":lead_upper,
            "first_touch_minute_open_utc":touch_open.isoformat() if touch_open else None,
            "first_touch_minute_close_utc":touch,
            "price_move_between_compute_and_publication_pct":move_since_compute,
            "already_moved_before_publication":moved_before_publication,
            "early_warning_eligible":lead_eligible,
            "raw_independent_vendor_close_time_verified":True,
            "trading_authority":False})
        completed+=1
    return completed

def score(reg,root,at):
    events=[json.loads(p.read_text()) for p in (root/"slots").glob("*/signal.json")] if (root/"slots").exists() else []
    coverage=status_grid(reg,events,at)
    event_index={e["slot_id"]:e for e in events}
    metrics={}
    for h in HORIZONS:
        due=0;resolved=0;late=0;missing=0;alerts=0;true_by_lead={m:0 for m in (10,30,60)}
        false_by_lead={m:0 for m in (10,30,60)}
        for s in reg["due_slots"]:
            e=event_index.get(s["slot_id"])
            if not e or e.get("status")!="SIGNED_STATE_PUBLISHED":continue
            output=root/"slots"/s["slot_id"]/("outcome_"+h+".json")
            # The true target is measured from verified public delivery,
            # not the original model compute timestamp.
            if output.is_file():
                target=when(json.loads(output.read_text())["due_utc"])
            else:
                # Missing future outcomes count once the *latest* 13m
                # issuance deadline plus horizon plus 35m grace passes.
                target=when(e["anchor_utc"])+dt.timedelta(minutes=13+HORIZONS[h])
            if at<target+dt.timedelta(minutes=35):continue
            due+=1
            if not output.is_file():missing+=1;continue
            result=json.loads(output.read_text())
            if result.get("source_signal_sha256")!=digest(e):
                raise RuntimeError("outcome does not bind to signed warning")
            if result.get("kind")!="OUTCOME_RECORDED":
                late+=1;continue
            resolved+=1
            if result.get("warning_issued"):
                alerts+=1
                for k in true_by_lead:
                    lead=result.get("warning_lead_minutes")
                    if result.get("early_warning_eligible") is True and lead is not None and lead>=k:
                        true_by_lead[k]+=1
                    else:
                        false_by_lead[k]+=1
        metrics[h]={"due":due,"resolved":resolved,"missing":missing,"late":late,
                    "warning_count":alerts,"true_warning_at_least_minutes":true_by_lead,
                    "false_or_insufficient_lead":false_by_lead}
    return {"schema":"btc-v7r3-prospective-stateful-quality-grid-v1",
            "registered_grid_sha256":digest(reg),
            "coverage":coverage,"forward_outcomes":metrics,
            "skill_verified":False,"admission_ready":False,
            "trading_authority":False}

def tick(args):
    with tempfile.TemporaryDirectory() as temp:
        tmp=pathlib.Path(temp);ledger=tmp/"ledger";r2=tmp/"r2"
        clone(ledger,EVIDENCE);clone(r2,R2_EVIDENCE)
        root=ledger/"btc_v7r3_evidence"
        frozen_file=root/"registration.json"
        reg=json.loads(frozen_file.read_text())
        verify(frozen_file,SELF_ID,reg["model_source_sha"])
        freeze_path=root/"frozen_config.json"
        verify(freeze_path,SELF_ID,reg["model_source_sha"])
        if json.loads(freeze_path.read_text())["grid_sha256"]!=digest(reg):
            raise RuntimeError("R3 freeze tampered")
        if reg["model_source_sha"]!=os.environ["GITHUB_SHA"]:
            raise RuntimeError("source drift invalidates this prospective epoch")
        source_r2(r2/"btc_v7r2_evidence")
        ts=utcnow()
        if args.action=="forecast":
            status=current_slot_signal(root,r2/"btc_v7r2_evidence",reg,ts)
            outcomes=0
        elif args.action=="outcome":
            status="OUTCOME_ONLY_NO_FORECAST_CRITICAL_PATH"
            outcomes=resolve_outcomes(root,utcnow())
        else:
            raise ValueError("invalid work action")
        scored=score(reg,root,utcnow())
        scored["github_run_id"]=os.environ["GITHUB_RUN_ID"]
        write(root/"scorecards",os.environ["GITHUB_RUN_ID"]+".json",scored)
        publish(ledger,"Append signed R3 prospective warning, outcomes and full due grid")
    print("BTC_V7R3_SIGNED_TICK",json.dumps({
        "source_status":status,"new_outcomes":outcomes,
        "due_slots":scored["coverage"]["due"],
        "on_time":scored["coverage"]["on_time_signed_model_state"],
        "missing":scored["coverage"]["missing_slots"],
        "trading_authority":False},sort_keys=True))

def main():
    p=argparse.ArgumentParser()
    p.add_argument("action",choices=["register","forecast","outcome"])
    p.add_argument("--start-utc",default="")
    p.add_argument("--days",type=int,default=7)
    args=p.parse_args()
    if args.action=="register":register(args)
    else:tick(args)

if __name__=="__main__":main()
