"""Independent prospective source -> signed CUSUM numerical replay.

This runs on a SEPARATE verification GitHub workflow. It never changes
frozen v7R4 source/evidence, never re-signs existing outcomes and never
claims predictive skill. It checks the exact source revision, Sigstore
identity/Rekor of each input, raw Binance/OKX factor rederivation and
reproduces the exact emitted CUSUM state/diagnostic on eligible real slots.

A chain break is FAIL, not a silent reset. Recovery epochs are explicitly
reported as NOT VERIFIED until their own numerical replay is supported.
"""
from __future__ import annotations
import argparse,concurrent.futures,datetime as dt,hashlib,json,math,os,pathlib,subprocess
from btc_demand_v7.source_integrity_v5 import rederive
from btc_demand_v7.demand_change_v2 import advance,state_zero,source_hash,timestamp
from btc_demand_v7.shadow_contract_v3 import digest,canonical,slot_id,accept_slot
from btc_demand_v7.release_guard import certificate_source_sha
from btc_demand_v7.prospective_core import when

REPO="sergeytren1984-ux/neora-b2b-v2-clean"
FROZEN_R4_SHA="46baa51edbbffc328c747be5d365bcba34ea3d00"
EVIDENCE_BRANCH="btc-v7r4-direct-evidence-20261013"
REG_PATH="btc_v7r3_evidence/registration.json"
IDENTITY=f"https://github.com/{REPO}/.github/workflows/btc-v7r3-signed-demand-shadow.yml@refs/heads/btc-v7r4-hardening-20261012"
ISSUER="https://token.actions.githubusercontent.com"

def verify_signed(path):
    path=pathlib.Path(path)
    bundle=pathlib.Path(str(path)+".sigstore.json")
    if not (path.is_file() and bundle.is_file()):
        raise RuntimeError("unsigned/missing signed raw evidence: "+str(path))
    args=["cosign","verify-blob",str(path),"--bundle",str(bundle),
          "--certificate-identity",IDENTITY,
          "--certificate-oidc-issuer",ISSUER]
    process=subprocess.run(args,capture_output=True,text=True,timeout=45)
    if process.returncode:
        raise RuntimeError("Cosign/Rekor rejected "+str(path)+": "+process.stderr[-250:])
    if certificate_source_sha(str(bundle))!=FROZEN_R4_SHA:
        raise RuntimeError("unexpected source SHA inside original OIDC attestation")
    value=json.loads(bundle.read_text())
    if not any(t.get("inclusionProof") for t in value["verificationMaterial"]["tlogEntries"]):
        raise RuntimeError("Rekor inclusion proof absent")

def price_reference(event):
    item=event["reference_1m_raw"]
    raw=item["row"]
    if int(raw[6])+1!=int(raw[0])+60000:
        raise RuntimeError("forecast used unclosed or shifted 1m price")
    t=dt.datetime.fromtimestamp((int(raw[6])+1)/1000,dt.timezone.utc)
    if when(item["minute_close_utc"])!=t:
        raise RuntimeError("forecast closed price bar timestamp inconsistent")
    op,hi,lo,close=map(float,(raw[1],raw[2],raw[3],raw[4]))
    if not all(map(math.isfinite,(op,hi,lo,close))) or not(0<lo<=min(op,close)<=max(op,close)<=hi):
        raise RuntimeError("forecast market reference invalid")
    if not math.isclose(close,float(event["reference_spot"]),abs_tol=1e-8,rel_tol=0):
        raise RuntimeError("forecast reference price differs from its 1m source")
    issued=when(event["issued_at_utc"])
    got=when(item["received_at_utc"])
    if not(t<=got<=issued<=t+dt.timedelta(minutes=2)):
        raise RuntimeError("publication inference used future/stale 1m reference")
    return close

def compare(actual,expected,name):
    if canonical(actual)!=canonical(expected):
        raise RuntimeError("published signed "+name+" differs from independent numerical source replay")

def run(repo_dir,max_recent=5):
    root=pathlib.Path(repo_dir)/"btc_v7r3_evidence"
    regfile=root/"registration.json"
    freeze=root/"frozen_config.json"
    for p in (regfile,freeze):verify_signed(p)
    reg=json.loads(regfile.read_text())
    config=json.loads(freeze.read_text())
    if reg["model_source_sha"]!=FROZEN_R4_SHA or config["model_source_sha"]!=FROZEN_R4_SHA:
        raise RuntimeError("wrong frozen registered v7R4 numerical source")
    if digest(reg)!=config["grid_sha256"]:
        raise RuntimeError("prestart frozen registered grid hash mismatch")
    slots=reg["due_slots"]
    if len(slots)!=672 or sum(bool(x["first_32_signed_slots_are_warmup"]) for x in slots)!=32:
        raise RuntimeError("registered due grid/warmup unexpectedly changed")
    base=root/"slots"
    issued_candidates=[]
    seen=0
    for index,entry in enumerate(slots):
        sid=entry["slot_id"]
        ep=base/sid/"signal.json"
        if not ep.exists():continue
        event=json.loads(ep.read_text())
        if event.get("slot_id")!=sid or when(event["anchor_utc"])!=when(entry["anchor_utc"]):
            raise RuntimeError("signed event is in wrong future slot")
        if event.get("status")=="SIGNED_STATE_PUBLISHED":
            if index<32:
                raise RuntimeError("model signal during preregistered warmup")
            issued_candidates.append((index,entry,event,ep))
        seen+=1
    selected=issued_candidates[-max_recent:]
    targets=[]
    for index,entry,event,ep in selected:
        wanted=[(j,base/slots[j]["slot_id"]/"snapshot.json") for j in range(index-32,index+1)]
        targets += [p for _,p in wanted]+[ep]
        if index>32:
            targets.append(base/slots[index-1]["slot_id"]/"signal.json")
    # Register and config were already verified; no raw cache trusting
    # unsigned mutable evidence. Exact SHA+OIDC+Rekor each individual file.
    targets=sorted(set(targets))
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
        list(pool.map(verify_signed,targets))
    checked=0
    r4_replay_events=[]
    for index,entry,event,ep in selected:
        if event.get("recovery") is not None:
            raise RuntimeError("signed recovery epoch must be independently reviewed, not silently accepted")
        baseline=[]
        for j in range(index-32,index):
            signed=root/"slots"/slots[j]["slot_id"]/"snapshot.json"
            x=json.loads(signed.read_text())
            verified=rederive(x)
            if verified["pressure_factor_ready"] is not True:
                raise RuntimeError("history contains missing OI/book or invalid pressure factors")
            if when(x["anchor_utc"])!=when(slots[j]["anchor_utc"]):
                raise RuntimeError("raw history swapped 15m source anchor")
            baseline.append(x)
        snapshot=json.loads((base/entry["slot_id"]/"snapshot.json").read_text())
        verified=rederive(snapshot)
        if when(snapshot["anchor_utc"])!=when(entry["anchor_utc"]):
            raise RuntimeError("signed recent source has wrong 15m anchor")
        if when(event["snapshot_received_at_utc"])!=when(snapshot["retrieved_at_utc"]):
            raise RuntimeError("published claim of snapshot receipt differs from raw")
        if event.get("upstream_r2_snapshot_canonical_sha256")!=source_hash(snapshot):
            raise RuntimeError("signed state not bound to actual market raw snapshot")
        if event.get("registered_grid_sha256")!=digest(reg) or event["model_source_sha"]!=FROZEN_R4_SHA:
            raise RuntimeError("model release/source grid not exact")
        if accept_slot(reg,when(entry["anchor_utc"]),when(event["issued_at_utc"]))!="ON_TIME":
            raise RuntimeError("forecast outside original preregistered window")
        if index==32:prior=state_zero()
        else:
            previous=base/slots[index-1]["slot_id"]/"signal.json"
            if not previous.exists():raise RuntimeError("missing signed predecessor")
            prior_event=json.loads(previous.read_text())
            if prior_event.get("status")!="SIGNED_STATE_PUBLISHED":
                raise RuntimeError("previous model state absent, cannot claim continuous replay")
            prior=prior_event["state"]
        reference=price_reference(event)
        anchor_price=float(snapshot["observation"]["reference_spot"])
        gap=100*(reference/anchor_price-1)
        if not math.isclose(gap,float(event["market_move_during_information_latency_pct"]),rel_tol=0,abs_tol=1e-9):
            raise RuntimeError("unsigned fabricated movement during information latency")
        state,diagnostic=advance(
            prior,baseline,snapshot,
            issued_utc=when(event["issued_at_utc"]),
            live_change_since_anchor_pct=gap)
        compare(event["state"],state,"CUSUM state")
        compare(event["diagnostic"],diagnostic,"CUSUM diagnostic")
        checked+=1
        r4_replay_events.append({
            "slot_id":entry["slot_id"],
            "state_sequence":state["sequence"],
            "actual_source_anchor":snapshot["anchor_utc"],
            "source_received_at_utc":snapshot["retrieved_at_utc"],
            "model_issued_utc":event["issued_at_utc"],
            "raw_snapshot_SHA256":source_hash(snapshot),
            "exact_signed_numerical_state_replay":True,
            "real_public_delivery_verified_here":False,
            "trading_authority":False})
    return {
        "schema":"btc-v7r5-independent-signed-r4-live-numerical-replay-v1",
        "original_model_sha":FROZEN_R4_SHA,
        "registered_source_sha":reg["model_source_sha"],
        "grid_sha256":digest(reg),
        "preregistered_due_slots":len(slots),
        "observed_signed_slot_events":seen,
        "published_model_states_available":len(issued_candidates),
        "latest_numerically_verified_published_states":checked,
        "latest_checked":r4_replay_events,
        "source_raw_and_signatures_recomputed":True,
        "status":"VERIFIED_NONZERO_REAL_STATES" if checked else "NO_REAL_FORECASTS_YET",
        "prospective_predictive_skill_proven":False,
        "trading_authority":False,
    }

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--evidence-root",required=True)
    ap.add_argument("--out",required=True)
    ap.add_argument("--latest",type=int,default=3)
    a=ap.parse_args()
    report=run(a.evidence_root,a.latest)
    p=pathlib.Path(a.out)
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(report,sort_keys=True,indent=2,allow_nan=False)+"\n")
    print("BTC_V7R5_INDEPENDENT_REAL_PROSPECTIVE_STATE_REPLAY",
          json.dumps({k:report[k] for k in (
            "status","observed_signed_slot_events","published_model_states_available",
            "latest_numerically_verified_published_states","prospective_predictive_skill_proven")},
            sort_keys=True))

if __name__=="__main__":main()
