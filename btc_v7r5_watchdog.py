"""Read-only prospective signed due-grid watchdog for BTC v7R5.

Does not mutate frozen source/evidence. Can dispatch ONE rescue if an original
worker run is entirely absent before the frozen issuance deadline. Signed
forecast plus signed Sigstore bundle required after the deadline. GitHub
workflow-run success alone does NOT count as a forecast.
"""
from __future__ import annotations
import datetime as dt,json,os,base64,urllib.error,urllib.request

UTC=dt.timezone.utc
REPO="sergeytren1984-ux/neora-b2b-v2-clean"
SOURCE_REF="btc-v7r5-live-cadence-reliability-20261012"
SOURCE_SHA="d6acb83d45ea484d2f2c88b725faedf3de97775d"
EVIDENCE_REF="btc-v7r5-corrected-signed-evidence-20261013"
WORKFLOW="btc-v7r3-signed-demand-shadow.yml"
START=dt.datetime(2026,10,13,tzinfo=UTC)
END=dt.datetime(2026,10,20,tzinfo=UTC)
CADENCE=dt.timedelta(minutes=15)

def when(s):
    x=dt.datetime.fromisoformat(s.replace("Z","+00:00"))
    if not x.tzinfo:raise ValueError("UTC offset missing")
    return x.astimezone(UTC)

def anchor_for(t):
    t=t.astimezone(UTC)
    return t.replace(minute=t.minute//15*15,second=0,microsecond=0)

def plan(t,runs,signed):
    anchor=anchor_for(t)
    out={"anchor":anchor.isoformat(),"rescue":False,"missed":[]}
    if t<START or t>=END+dt.timedelta(minutes=15):
        out["status"]="OUTSIDE_FROZEN_EPOCH";return out
    prev=anchor-CADENCE
    if START<=prev<END and t>=prev+dt.timedelta(minutes=14):
        if signed.get(prev.isoformat())!=(True,True):
            out["missed"].append(prev.isoformat())
    if not START<=anchor<END:
        out["status"]="DRAINING";return out
    receipt=signed.get(anchor.isoformat(),(False,False))
    if receipt==(True,True):
        out["status"]="SIGNED_SLOT_FOUND";return out
    age=(t-anchor).total_seconds()/60
    already_dispatched=any(
        r.get("headSha")==SOURCE_SHA and r.get("headBranch")==SOURCE_REF
        and r.get("event")=="workflow_dispatch"
        and anchor+dt.timedelta(minutes=1)<=when(r["createdAt"])<=anchor+dt.timedelta(minutes=13)
        for r in runs)
    out["observed_worker_dispatch"]=already_dispatched
    out["rescue"]=(7<=age<=9 and not already_dispatched)
    out["status"]=("MISSING_DISPATCH_RESCUE" if out["rescue"] else
                   "DISPATCH_OBSERVED" if already_dispatched else
                   "FROZEN_DEADLINE_PASSED" if age>13 else "BEFORE_RESCUE_WINDOW")
    return out

def github(path,method="GET",body=None):
    token=os.environ.get("GH_TOKEN")
    if not token:raise RuntimeError("Missing GitHub action token")
    headers={"Authorization":"Bearer "+token,"Accept":"application/vnd.github+json",
             "X-GitHub-Api-Version":"2022-11-28","User-Agent":"BTC-R5-watchdog"}
    if body is not None:headers["Content-Type"]="application/json"
    request=urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/{path}",
        data=json.dumps(body).encode() if body is not None else None,
        headers=headers,method=method)
    with urllib.request.urlopen(request,timeout=20) as resp:
        blob=resp.read()
        return json.loads(blob) if blob else None

def exists(path):
    try:
        result=github(f"contents/{path}?ref={EVIDENCE_REF}")
        return bool(result and result.get("sha") and result.get("type")=="file")
    except urllib.error.HTTPError as e:
        if e.code==404:return False
        raise

def slot_signed(anchor):
    key=anchor.strftime("%Y%m%dT%H%MZ")
    path=f"btc_v7r3_evidence/slots/{key}/signal.json"
    return exists(path),exists(path+".sigstore.json")

def check_frozen():
    file=github(f"contents/btc_v7r3_evidence/registration.json?ref={EVIDENCE_REF}")
    if not file or file.get("type")!="file":raise RuntimeError("Missing registration")
    reg=json.loads(base64.b64decode(file["content"]))
    if (reg.get("model_source_sha")!=SOURCE_SHA or when(reg["start_utc"])!=START
        or when(reg["end_utc"])!=END or len(reg.get("due_slots",[]))!=672
        or not exists("btc_v7r3_evidence/registration.json.sigstore.json")):
        raise RuntimeError("Mismatched/unsigned original prospective registration")
    return reg

def main():
    now=dt.datetime.now(UTC)
    if now<START:
        print("BTC_R5_WATCHDOG_PRESTART",now.isoformat());return
    check_frozen()
    runs=github(f"actions/workflows/{WORKFLOW}/runs?branch={SOURCE_REF}&event=workflow_dispatch&per_page=100")
    recent=[{"headSha":r.get("head_sha"),"headBranch":r.get("head_branch"),
             "event":r.get("event"),"createdAt":r["created_at"]}
            for r in runs.get("workflow_runs",[])]
    current=anchor_for(now)
    signed={}
    for anchor in (current-CADENCE,current):
        if START<=anchor<END:
            signed[anchor.isoformat()]=slot_signed(anchor)
    decision=plan(now,recent,signed)
    if decision["rescue"]:
        fresh=dt.datetime.now(UTC)
        if anchor_for(fresh)==current and fresh<=current+dt.timedelta(minutes=9):
            github(f"actions/workflows/{WORKFLOW}/dispatches",
                   method="POST",body={"ref":SOURCE_REF,"inputs":{"action":"forecast","days":"7"}})
            decision["rescue_accepted_utc"]=fresh.isoformat()
            print("::warning::R5 frozen slot rescue dispatched while still timely")
        else:
            decision["rescue"]=False
            decision["status"]="RESCUE_ABORTED_TOO_LATE"
    result={"timestamp_utc":now.isoformat(),"source_sha":SOURCE_SHA,
            "model_skill_proven":False,"trading_authority":False,**decision}
    print("BTC_R5_SIGNED_DUE_GRID_WATCHDOG",json.dumps(result,sort_keys=True))
    if decision["missed"]:
        print("::error::Signed forecast missing after frozen deadline: "+str(decision["missed"]))
        raise SystemExit(2)

if __name__=="__main__":main()
