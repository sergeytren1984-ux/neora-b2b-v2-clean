from __future__ import annotations
import json,subprocess,tempfile,urllib.request
from datetime import datetime,timezone,timedelta
from pathlib import Path

UTC=timezone.utc
CTX_IDENTITY="https://github.com/sergeytren1984-ux/neora-b2b-v2-clean/.github/workflows/btc-context-evidence.yml@refs/heads/main"
ISSUER="https://token.actions.githubusercontent.com"
FACTOR_KEYS=("open_interest","funding","dxy","nasdaq_futures","us10y","etf_flows")

def _dt(v):
    if not v: return None
    d=datetime.fromisoformat(str(v).replace("Z","+00:00"))
    if d.tzinfo is None: raise ValueError("timezone required")
    return d.astimezone(UTC)

def _run(*args):
    return subprocess.run(args,check=True,capture_output=True,text=True,timeout=90).stdout

def _get(url,token=None):
    h={"User-Agent":"btc-regime-v2-audit"}
    if token: h["Authorization"]="Bearer "+token
    with urllib.request.urlopen(urllib.request.Request(url,headers=h),timeout=20) as r:
        if r.status!=200: raise RuntimeError(f"HTTP {r.status}: {url}")
        return r.read()

def verify_signed_snapshot(snapshot_bytes,bundle_bytes,anchor,protocol):
    pol=protocol["external_context"]; skew=timedelta(seconds=int(pol["clock_skew_tolerance_seconds"]))
    with tempfile.TemporaryDirectory() as td:
        p=Path(td)/"snapshot.json"; b=Path(td)/"snapshot.sigstore.json"
        p.write_bytes(snapshot_bytes); b.write_bytes(bundle_bytes)
        _run("cosign","verify-blob",str(p),"--bundle",str(b),
             "--certificate-identity",pol["identity"],"--certificate-oidc-issuer",pol["oidc_issuer"])
    bundle=json.loads(bundle_bytes)
    entries=bundle.get("verificationMaterial",{}).get("tlogEntries",[])
    if not entries: raise ValueError("context has no Rekor entry")
    integrated=min(datetime.fromtimestamp(int(e["integratedTime"]),UTC) for e in entries)
    for e in entries:
        pr=e.get("inclusionProof")
        if not isinstance(pr,dict) or not pr.get("checkpoint") or "hashes" not in pr:
            raise ValueError("context missing Rekor inclusion proof")
    if integrated>anchor+skew: raise ValueError("context Rekor time is after anchor")
    obj=json.loads(snapshot_bytes)
    captured=_dt(obj.get("captured_at_utc"))
    if captured is None or captured>anchor+skew: raise ValueError("context captured after anchor")
    age=(anchor-captured).total_seconds()
    if age< -pol["clock_skew_tolerance_seconds"] or age>pol["snapshot_max_age_seconds"]:
        raise ValueError("context snapshot outside allowed age")
    return obj,{"captured_at_utc":captured.isoformat(),"rekor_integrated_utc":integrated.isoformat(),"snapshot_age_seconds":age}

def factor_status(ctx,name,anchor,protocol):
    f=(ctx.get("factors") or {}).get(name)
    if not isinstance(f,dict) or f.get("status")!="VALID":
        return {"available":False,"reason":"MISSING_OR_INVALID"}
    allowed=set(protocol["factor_policy"].get(name,{}).get("freshness",[]))
    fresh=f.get("freshness_status")
    if allowed and fresh not in allowed:
        return {"available":False,"reason":"STALE_OR_DISALLOWED_FRESHNESS","freshness_status":fresh}
    ts=_dt(f.get("source_timestamp_utc"))
    skew=float(protocol["external_context"]["clock_skew_tolerance_seconds"])
    if ts and (ts-anchor).total_seconds()>skew:
        return {"available":False,"reason":"FUTURE_SOURCE_TIMESTAMP","source_timestamp_utc":ts.isoformat()}
    age=f.get("age_seconds")
    if isinstance(age,(int,float)) and age < -skew:
        return {"available":False,"reason":"NEGATIVE_AGE_EXCEEDS_TOLERANCE","age_seconds":age}
    meta={"available":True,"freshness_status":fresh}
    if ts: meta["source_timestamp_utc"]=ts.isoformat()
    if isinstance(age,(int,float)): meta["age_seconds"]=age
    return meta

def context_pair(repo,anchor,protocol,token=None):
    api=f"https://api.github.com/repos/{repo}/contents/context_live?ref=btc-context"
    arr=json.loads(_get(api,token))
    names=sorted(x["name"] for x in arr if x["name"].endswith("Z.json"))
    parsed=[]
    for n in names:
        try: t=datetime.strptime(n[:15],"%Y%m%dT%H%M%S").replace(tzinfo=UTC)
        except Exception: continue
        if t<=anchor: parsed.append((t,n))
    if not parsed: raise ValueError("no context snapshot before anchor")
    now_name=parsed[-1][1]
    target=anchor-timedelta(seconds=int(protocol["external_context"]["comparison_window_seconds"]))
    tol=int(protocol["external_context"]["comparison_tolerance_seconds"])
    eligible=[x for x in parsed if abs((x[0]-target).total_seconds())<=tol]
    if not eligible: raise ValueError("no context snapshot in fixed comparison window")
    prev_name=min(eligible,key=lambda x:abs((x[0]-target).total_seconds()))[1]
    out=[]
    for n in (now_name,prev_name):
        base=f"https://raw.githubusercontent.com/{repo}/btc-context/context_live/{n}"
        sb=_get(base,token); bb=_get(base+".sigstore.json",token)
        obj,proof=verify_signed_snapshot(sb,bb,anchor,protocol)
        factors={k:factor_status(obj,k,anchor,protocol) for k in FACTOR_KEYS}
        out.append((obj,proof,factors,n))
    elapsed=(_dt(out[0][0]["captured_at_utc"])-_dt(out[1][0]["captured_at_utc"])).total_seconds()
    if elapsed<=0: raise ValueError("context comparison elapsed time invalid")
    return {
      "current":out[0][0],"previous":out[1][0],"current_proof":out[0][1],"previous_proof":out[1][1],
      "current_factor_status":out[0][2],"previous_factor_status":out[1][2],
      "snapshot_names":[out[0][3],out[1][3]],"elapsed_seconds":elapsed,
      "legacy_numeric_challenger_authorized":bool((out[0][0].get("admission") or {}).get("numeric_challenger_authorized",False))
    }
