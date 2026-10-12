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
import subprocess,tempfile,urllib.parse,urllib.request,concurrent.futures,time
from btc_demand_v7.shadow_contract_v3 import (
    grid,accept_slot,slot_id,digest,canonical,
    future_anchor,future_due,HORIZONS,status_grid,
    BRANCH,EVIDENCE,SCHEDULER_BLOB_SHA)
from btc_demand_v7.demand_change_v2 import (
    advance,state_zero,source_hash,BASELINE_COUNT)
from btc_demand_v7.event_semantics import first_passage
from btc_demand_v7.prospective_core import when
from btc_demand_v7.live_snapshot import collect as market_collect, strict_closed, spot_state
from btc_demand_v7.release_guard import certificate_source_sha

REPO="sergeytren1984-ux/neora-b2b-v2-clean"
ISSUER="https://token.actions.githubusercontent.com"
SELF_ID=f"https://github.com/{REPO}/.github/workflows/btc-v7r3-signed-demand-shadow.yml@refs/heads/{BRANCH}"

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
    # Independent forecast/outcome workflows can write unrelated signed
    # paths concurrently. Never force push and never overwrite evidence.
    for retry in range(4):
        try:
            run("git","pull","--quiet","--rebase","origin",EVIDENCE,cwd=ledger)
            run("git","push","--quiet","origin","HEAD:refs/heads/"+EVIDENCE,cwd=ledger)
            return
        except RuntimeError:
            if retry==3:raise
            time.sleep(2**retry)


def scheduler_blob_sha():
    return run("gh","api",
        f"repos/{REPO}/contents/.github/workflows/btc-v7r3-forward-clock.yml?ref=main",
        "--jq",".sha")

def register(args):
    if scheduler_blob_sha()!=SCHEDULER_BLOB_SHA:
        raise RuntimeError("unregistered operational GitHub scheduler modification")
    start=when(args.start_utc)
    timestamp=utcnow()
    with tempfile.TemporaryDirectory() as temp:
        tmp=pathlib.Path(temp);ledger=tmp/"ledger"
        # No R2 forecast/outcome worker on the critical collection path.
        reg=grid(start,timestamp,os.environ["GITHUB_SHA"],days=args.days)
        clone(ledger,EVIDENCE,create=True)
        root=ledger/"btc_v7r3_evidence"
        write(root,"registration.json",reg)
        write(root,"frozen_config.json",{
            "schema":"btc-v7r3-signed-prestart-freeze-v1",
            "registered_at_utc":timestamp.isoformat(),
            "model_source_sha":os.environ["GITHUB_SHA"],
            "grid_sha256":digest(reg),
            "spot_and_derivatives_input":"signed direct Binance/OKX point-in-time as-of",
            "signed_upstream_r2":False,
            "trading_authority":False,"prospective_skill_proven":False})
        publish(ledger,"Freeze v7R3 stateful source, future decision deadlines and source lineage")
    print("BTC_V7R3_REGISTERED",json.dumps({
        "model_sha":reg["model_source_sha"],
        "direct_market_source":"Binance BTCUSDT spot1m/5m plus OKX OI/book; independent R4",
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

def validated_snapshot(root,slot,unused=None):
    """Only accept previously signed R4 direct raw from exact due anchor."""
    path=root/"slots"/slot_id(slot)/"snapshot.json"
    if not path.is_file():return None
    verify(path,SELF_ID,os.environ["GITHUB_SHA"])
    snapshot=json.loads(path.read_text())
    if when(snapshot["anchor_utc"])!=slot:
        raise RuntimeError("wrong signed self-collected candle anchor")
    anchor_ms=int(slot.timestamp()*1000)
    one=strict_closed(snapshot["one_min_rows"],60000,anchor_ms,200)
    five=strict_closed(snapshot["five_min_rows"],300000,anchor_ms,600)
    if len(one)!=len(snapshot["one_min_rows"]) or len(five)!=len(snapshot["five_min_rows"]):
        raise RuntimeError("signed source includes future/unclosed candle")
    derived=spot_state(one,anchor_ms)
    for k,expected in derived.items():
        actual=float(snapshot["observation"][k])
        if not(math.isfinite(actual) and math.isclose(actual,expected,rel_tol=1e-11,abs_tol=1e-8)):
            raise RuntimeError("signed source spot features differ from actual 1m raw")
    return snapshot

def historic_snapshots(root,slot):
    anchors=[slot-dt.timedelta(minutes=15*i)
             for i in reversed(range(1,BASELINE_COUNT+1))]
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
        history=list(pool.map(lambda anchor:validated_snapshot(root,anchor),anchors))
    return None if any(x is None for x in history) else history


def available_previous_state(root,slot):
    previous=slot-dt.timedelta(minutes=15)
    path=root/"slots"/slot_id(previous)/"signal.json"
    if not path.exists():return None
    verify(path,SELF_ID,os.environ["GITHUB_SHA"])
    prior=json.loads(path.read_text())
    # Warmup records may contain a placeholder zero state for bookkeeping.
    # It is NOT a valid prior directional state. Exactly at the 33rd reading
    # the first legitimate CUSUM must initialize once with state_zero().
    if prior.get("status")!="SIGNED_STATE_PUBLISHED":
        return None
    state=prior.get("state")
    if not isinstance(state,dict):
        raise RuntimeError("signed published event lacks its running state")
    return state

def current_slot_signal(root,reg,ts):
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
    # Fetch fresh direct market observations IN THIS SOURCE JOB. Waiting
    # for an R2 outcome backlog cannot prevent a time-critical signal.
    snapshot=market_collect(anchor_ms=int(slot.timestamp()*1000))
    if when(snapshot["anchor_utc"])!=slot:
        raise RuntimeError("collector shifted preregistered anchor")
    write(path.parent,"snapshot.json",snapshot)
    history=historic_snapshots(root,slot)
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
    # GitHub REST workflow-runs.path contains JUST the workflow file,
    # while head_branch independently carries the exact ref.
    expected_path=".github/workflows/btc-v7r3-signed-demand-shadow.yml"
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
    """Score ONLY signed, independently revalidated future evidence.

    Denominators depend on the immutable registered grid, NEVER on whether
    any forecast or outcome JSON happens to exist. This runs on the lower
    priority outcome worker, not in the forecast critical path.
    """
    current=when(at)
    slots_dir=root/"slots"
    signal_paths=list(slots_dir.glob("*/signal.json")) if slots_dir.exists() else []
    delivery_paths=list(slots_dir.glob("*/delivery.json")) if slots_dir.exists() else []
    # Verify signed input bytes before trusting any scorecard numerical fields.
    signed_inputs=signal_paths+delivery_paths
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:
        list(pool.map(lambda path: verify(path,SELF_ID,os.environ["GITHUB_SHA"]),signed_inputs))
    events=[json.loads(p.read_text()) for p in signal_paths]
    deliveries=[json.loads(p.read_text()) for p in delivery_paths]
    index={e["slot_id"]:e for e in events}
    delivery_index={d["slot_id"]:d for d in deliveries}
    if len(index)!=len(events) or len(delivery_index)!=len(deliveries):
        raise ValueError("duplicate signed signal or delivery")
    coverage=status_grid(reg,events,current,deliveries)
    if coverage["global_daily_budget_violated"]:
        raise RuntimeError("more than one signed public alert in a UTC day")
    metrics={}
    for horizon,minutes in HORIZONS.items():
        count={"due":0,"resolved":0,"missing":0,"late":0,
               "no_valid_forecast":0,"warning_count":0,
               "wrong_side":0,"no_touch":0,
               "true_warning_at_least_minutes":{k:0 for k in (10,30,60)},
               "false_or_insufficient_lead":{k:0 for k in (10,30,60)}}
        for slot in reg["due_slots"]:
            sid=slot["slot_id"]
            anchor=when(slot["anchor_utc"])
            event=index.get(sid)
            delivery=delivery_index.get(sid)
            # The frozen latest issuance bound controls a missing due.
            # Outcome-provided due_utc has ZERO authority over eligibility.
            latest=anchor+dt.timedelta(minutes=13+minutes)
            if event is not None and delivery is not None:
                if delivery.get("source_signal_sha256")!=digest(event):
                    raise ValueError("delivery receipt not bound to event")
                published=when(delivery["public_delivery_utc"])
                due=future_due(published,horizon)
                if due>latest+dt.timedelta(minutes=1):
                    # A late signal is invalid, but it cannot erase due
                    # evidence by inventing arbitrary future target dates.
                    due=latest
            else:
                due=latest
            if current<due+dt.timedelta(minutes=35):
                continue
            count["due"]+=1
            if (event is None or event.get("status")!="SIGNED_STATE_PUBLISHED"
                or delivery is None):
                count["no_valid_forecast"]+=1
                count["missing"]+=1
                continue
            dtime=when(delivery["public_delivery_utc"])
            if (not when(slot["decision_window_open_utc"])<=when(event["issued_at_utc"])<=when(slot["decision_window_close_utc"])
                or dtime>when(slot["decision_window_close_utc"])
                or dtime<when(event["issued_at_utc"])):
                count["no_valid_forecast"]+=1
                count["missing"]+=1
                continue
            location=slots_dir/sid
            opath=location/("outcome_"+horizon+".json")
            rawpath=location/("raw_"+horizon+".json")
            if not opath.exists() or not rawpath.exists():
                count["missing"]+=1
                continue
            verify(opath,SELF_ID,os.environ["GITHUB_SHA"])
            verify(rawpath,SELF_ID,os.environ["GITHUB_SHA"])
            outcome=json.loads(opath.read_text())
            raw=json.loads(rawpath.read_text())
            if (outcome.get("source_signal_sha256")!=digest(event)
                or outcome.get("source_raw_sha256")!=digest(raw)
                or outcome.get("source_github_run_id")!=event.get("github_run_id")
                or outcome.get("horizon")!=horizon
                or outcome.get("slot_id")!=sid
                or raw.get("schema")!="btc-v7r3-closed-1m-forward-source-v2"
                or raw.get("symbol")!="BTCUSDT"):
                raise ValueError("unsigned/substituted result or orphaned source")
            if (when(outcome["due_utc"])!=due
                or when(outcome["public_delivery_utc"])!=dtime
                or when(raw["actual_publication_utc"])!=dtime):
                raise ValueError("mutable outcome maturity/date")
            refms=int(dtime.timestamp()*1000)//60000*60000
            rr=raw["reference_row"]
            if (int(rr[0])+60000!=refms or int(rr[6])+1!=refms
                or when(raw["reference_minute_close_utc"])!=dt.datetime.fromtimestamp(refms/1000,dt.timezone.utc)):
                raise ValueError("wrong reference spot-minute at GitHub public delivery")
            ref=float(rr[4])
            if not (math.isfinite(ref) and ref>0
                    and math.isclose(ref,float(outcome["reference_spot_at_public_delivery"]),rel_tol=0,abs_tol=1e-8)):
                raise ValueError("reference close differs from outcome claim")
            anchor_time=future_anchor(dtime)
            if when(raw["first_complete_minute_anchor_utc"])!=anchor_time:
                raise ValueError("forward minute starts before publication")
            recomputed=first_passage(anchor_time,ref,raw["rows"],horizon)
            if digest(recomputed)!=digest(outcome["barrier_result"]):
                raise ValueError("barrier direction/first-touch cannot be reproduced")
            touch=recomputed["first_barrier_touch_utc"]
            lower=((when(touch)-dt.timedelta(minutes=1)-dtime).total_seconds()/60
                   if touch else None)
            upper=((when(touch)-dtime).total_seconds()/60 if touch else None)
            warning=bool(event["diagnostic"].get("alert"))
            side=event["diagnostic"].get("warning_side")
            mapped={"UP":"UP_FIRST","DOWN":"DOWN_FIRST",None:None}
            if side not in mapped:raise ValueError("unknown signed pressure side")
            warning_side=mapped[side]
            market_gap=100*(ref/float(event["reference_spot"])-1)
            truly_early=(not event["diagnostic"].get("price_already_moved",True)
                          and abs(market_gap)<.30
                          and dtime<=when(slot["decision_window_close_utc"]))
            claimed_lead=(lower if warning_side==recomputed["direction"] else None)
            observed_lead=outcome.get("warning_lead_minutes")
            if (outcome.get("warning_issued") is not warning
                or outcome.get("warning_side")!=warning_side
                or outcome.get("actual_first_touch_side")!=recomputed["direction"]
                or outcome.get("early_warning_eligible") is not truly_early
                or outcome.get("already_moved_before_publication") is not (abs(market_gap)>=.30)
                or abs(float(outcome["price_move_between_compute_and_publication_pct"])-market_gap)>1e-9
                or (observed_lead is None)!=(claimed_lead is None)
                or (claimed_lead is not None and abs(float(observed_lead)-claimed_lead)>1e-7)
                or (lower is not None and abs(float(outcome["warning_lead_lower_minutes"])-lower)>1e-7)
                or (upper is not None and abs(float(outcome["warning_lead_upper_minutes"])-upper)>1e-7)):
                raise ValueError("invented label, success, intra-minute lead, or postcompute-veto")
            recorded=when(outcome["recorded_at_utc"])
            if recorded<due:raise ValueError("outcome recorded before maturity")
            if recorded>due+dt.timedelta(minutes=35):
                count["late"]+=1
                continue
            if outcome.get("kind")!="OUTCOME_RECORDED":
                raise ValueError("status kind inconsistent with actual completion")
            count["resolved"]+=1
            if recomputed["direction"]=="NEITHER":count["no_touch"]+=1
            if warning:
                count["warning_count"]+=1
                if warning_side!=recomputed["direction"]:count["wrong_side"]+=1
                for threshold in (10,30,60):
                    if (truly_early and warning_side==recomputed["direction"]
                        and lower is not None and lower>=threshold):
                        count["true_warning_at_least_minutes"][threshold]+=1
                    else:
                        count["false_or_insufficient_lead"][threshold]+=1
        metrics[horizon]=count
    return {
        "schema":"btc-v7r4-strict-full-grid-signed-recomputed-quality-v1",
        "registered_grid_sha256":digest(reg),
        "coverage":coverage,
        "forward_outcomes":metrics,
        "score_verification":"each signed outcome and raw rechecked, all first passage/lead/due recalculated",
        "missing_forecast_does_not_reduce_outcome_denominator":True,
        "skill_verified":False,"admission_ready":False,
        "trading_authority":False}


def tick(args):
    with tempfile.TemporaryDirectory() as temp:
        tmp=pathlib.Path(temp);ledger=tmp/"ledger"
        clone(ledger,EVIDENCE)
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
        if (reg.get("github_prestart_scheduler_blob_sha")!=SCHEDULER_BLOB_SHA
            or scheduler_blob_sha()!=SCHEDULER_BLOB_SHA):
            raise RuntimeError("live operational scheduler diverged from frozen registration")
        ts=utcnow()
        if args.action=="forecast":
            status=current_slot_signal(root,reg,ts)
            outcomes=0
            # Do NOT wait for 672-slot audit/cosign replay in critical path.
            # A no-op due to missing R2 source is not a successful forecast.
            if status in ("WAITING_R2_SIGNED_SNAPSHOT","NOT_YET_DUE","OUTSIDE_FUTURE_EPOCH",
                          "DUPLICATE_NO_MUTATION"):
                print("R4_NO_NEW_FORECAST",status,flush=True)
                return
            publish(ledger,"Append signed R4 time-critical forecast only")
            print("R4_FORECAST_PUBLISHED",status,flush=True)
            return
        if args.action!="outcome":
            raise ValueError("invalid work action")
        status="OUTCOME_ONLY_NO_FORECAST_CRITICAL_PATH"
        outcomes=resolve_outcomes(root,utcnow())
        scored=score(reg,root,utcnow())
        scored["github_run_id"]=os.environ["GITHUB_RUN_ID"]
        write(root/"scorecards",os.environ["GITHUB_RUN_ID"]+".json",scored)
        publish(ledger,"Append signed R4 matured outcomes and strict score")
    print("BTC_V7R4_SIGNED_TICK",json.dumps({
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
