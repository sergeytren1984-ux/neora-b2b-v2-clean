from __future__ import annotations
import hashlib,json,math,subprocess,tempfile,urllib.request
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

def verify_signed_snapshot(snapshot_bytes,bundle_bytes,anchor,protocol,expected_at=None,max_offset_seconds=None):
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
    expected_at=expected_at or anchor
    max_offset_seconds=int(max_offset_seconds if max_offset_seconds is not None else pol["snapshot_max_age_seconds"])
    offset=(expected_at-captured).total_seconds()
    if abs(offset)>max_offset_seconds or captured>anchor+skew:
        raise ValueError("context snapshot outside its comparison window")
    if integrated<captured-skew:
        raise ValueError("context signed before capture")
    return obj,{"captured_at_utc":captured.isoformat(),"rekor_integrated_utc":integrated.isoformat(),
                "snapshot_age_seconds":(anchor-captured).total_seconds(),"target_offset_seconds":offset}

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
    if name != "etf_flows" and ts is None:
        return {"available":False,"reason":"MISSING_SOURCE_TIMESTAMP"}
    age=(anchor-ts).total_seconds() if ts else None
    max_age=f.get("max_age_seconds")
    if age is not None and (age < -skew or not isinstance(max_age,(int,float)) or age>max_age):
        return {"available":False,"reason":"SOURCE_OUTSIDE_FRESHNESS_WINDOW","age_seconds_at_anchor":age}
    if name=="etf_flows":
        day=f.get("flow_date_utc")
        try: flow_day=datetime.strptime(day,"%Y-%m-%d").date()
        except (TypeError,ValueError): return {"available":False,"reason":"MISSING_FLOW_DATE"}
        if flow_day>=anchor.date() or (anchor.date()-flow_day).days>f.get("max_age_days",0):
            return {"available":False,"reason":"ETF_SESSION_NOT_AVAILABLE"}
        if not isinstance(f.get("numeric_value"),(int,float)):
            return {"available":False,"reason":"MISSING_ETF_NUMERIC_VALUE"}
    elif not isinstance(f.get("value_btc" if name=="open_interest" else "value"),(int,float)):
        return {"available":False,"reason":"MISSING_NUMERIC_VALUE"}
    value=f.get("numeric_value" if name=="etf_flows" else "value_btc" if name=="open_interest" else "value")
    if not math.isfinite(value) or (name=="open_interest" and value<=0):
        return {"available":False,"reason":"INVALID_NUMERIC_VALUE"}
    meta={"available":True,"freshness_status":fresh}
    if ts: meta["source_timestamp_utc"]=ts.isoformat()
    if age is not None: meta["age_seconds_at_anchor"]=age
    return meta

def context_pair(repo,anchor,protocol,token=None):
    api=f"https://api.github.com/repos/{repo}/git/trees/btc-context?recursive=1"
    listing=json.loads(_get(api,token))
    if listing.get("truncated") or not isinstance(listing.get("tree"),list):
        raise ValueError("context tree incomplete")
    names=sorted(x["path"].rsplit("/",1)[-1] for x in listing["tree"]
                 if x.get("type")=="blob" and x.get("path","").startswith("context_live/")
                 and x["path"].endswith("Z.json"))
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
    for n,expected,limit in ((now_name,anchor,int(protocol["external_context"]["snapshot_max_age_seconds"])),
                             (prev_name,target,tol)):
        base=f"https://raw.githubusercontent.com/{repo}/btc-context/context_live/{n}"
        sb=_get(base,token); bb=_get(base+".sigstore.json",token)
        obj,proof=verify_signed_snapshot(sb,bb,anchor,protocol,expected,limit)
        # Freshness belongs to each observation time, not the final forecast anchor.
        # A valid 07:00 factor is not stale merely because the forecast is at 08:00.
        captured=_dt(obj["captured_at_utc"])
        factors={k:factor_status(obj,k,captured,protocol) for k in FACTOR_KEYS}
        proof["snapshot_sha256"]=hashlib.sha256(sb).hexdigest()
        proof["bundle_sha256"]=hashlib.sha256(bb).hexdigest()
        out.append((obj,proof,factors,n))
    elapsed=(_dt(out[0][0]["captured_at_utc"])-_dt(out[1][0]["captured_at_utc"])).total_seconds()
    if abs(elapsed-int(protocol["external_context"]["comparison_window_seconds"]))>tol+int(protocol["external_context"]["snapshot_max_age_seconds"]):
        raise ValueError("context comparison elapsed time invalid")
    return {
      "current":out[0][0],"previous":out[1][0],"current_proof":out[0][1],"previous_proof":out[1][1],
      "current_factor_status":out[0][2],"previous_factor_status":out[1][2],
      "snapshot_names":[out[0][3],out[1][3]],"elapsed_seconds":elapsed,
      "legacy_numeric_challenger_authorized":bool((out[0][0].get("admission") or {}).get("numeric_challenger_authorized",False))
    }
