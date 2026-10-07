"""Liveness guard for the vNext4R7.1 self-chained GitHub Actions runner.

This module never writes forecasts, outcomes, evidence, or model state. It only
decides whether a workflow successor is missing and, when invoked from an
authorized workflow, dispatches one replacement run.
"""
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.request

LIVE_STATUSES={"queued","pending","waiting","requested","in_progress"}


def _run_id(run):
    try:
        return int(run.get("id"))
    except Exception:
        return None


def assess_runs(runs,current_run_id=None):
    current=int(current_run_id) if current_run_id not in (None,"") else None
    live=[r for r in runs if str(r.get("status","")).lower() in LIVE_STATUSES]
    in_progress=[
        r for r in live
        if str(r.get("status","")).lower()=="in_progress"
    ]
    queued=[
        r for r in live
        if str(r.get("status","")).lower()
        in {"queued","pending","waiting","requested"}
    ]

    if current is not None:
        others=[r for r in live if _run_id(r)!=current]
        return {
            "need_dispatch":len(others)==0,
            "reason":(
                "NO_SUCCESSOR_FOR_CURRENT_RUN"
                if not others else "SUCCESSOR_ALREADY_PRESENT"
            ),
            "live_count":len(live),
            "other_live_count":len(others),
        }

    if in_progress:
        need=len(queued)==0
        reason=(
            "RUNNING_WITHOUT_SUCCESSOR"
            if need else "RUNNING_WITH_SUCCESSOR"
        )
    else:
        need=len(live)==0
        reason="NO_LIVE_RUN" if need else "QUEUED_RUN_PRESENT"
    return {
        "need_dispatch":need,
        "reason":reason,
        "live_count":len(live),
        "in_progress_count":len(in_progress),
        "queued_count":len(queued),
    }


def _request_json(url,token,method="GET",body=None,timeout=20):
    data=None if body is None else json.dumps(
        body,separators=(",",":")
    ).encode()
    req=urllib.request.Request(
        url,data=data,method=method,
        headers={
            "Authorization":"Bearer "+token,
            "Accept":"application/vnd.github+json",
            "X-GitHub-Api-Version":"2022-11-28",
            "User-Agent":"btc-predictive-vnext4r71-liveness",
            "Content-Type":"application/json",
        },
    )
    with urllib.request.urlopen(req,timeout=timeout) as response:
        raw=response.read()
        if method=="POST" and response.status!=204:
            raise RuntimeError(f"dispatch HTTP {response.status}")
        return {} if not raw else json.loads(raw)


def list_runs(repo,workflow,token):
    url=(
        f"https://api.github.com/repos/{repo}/actions/workflows/"
        f"{workflow}/runs?per_page=30"
    )
    obj=_request_json(url,token)
    runs=obj.get("workflow_runs")
    if not isinstance(runs,list):
        raise RuntimeError("workflow_runs missing")
    return runs


def dispatch(repo,workflow,token,ref="main",attempts=5,sleep_base=2):
    url=(
        f"https://api.github.com/repos/{repo}/actions/workflows/"
        f"{workflow}/dispatches"
    )
    last=None
    for attempt in range(1,attempts+1):
        try:
            _request_json(
                url,token,method="POST",body={"ref":ref}
            )
            return {"ok":True,"attempt":attempt}
        except Exception as ex:
            last=f"{type(ex).__name__}: {ex}"
            if attempt<attempts:
                time.sleep(sleep_base*attempt)
    return {"ok":False,"attempt":attempts,"error":last}


def ensure(repo,workflow,token,current_run_id=None,ref="main"):
    runs=list_runs(repo,workflow,token)
    assessment=assess_runs(runs,current_run_id=current_run_id)
    result={"workflow":workflow,**assessment}
    if not assessment["need_dispatch"]:
        result["dispatch"]={"ok":True,"skipped":True}
        return result
    result["dispatch"]=dispatch(repo,workflow,token,ref=ref)
    return result


def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument("--repo",required=True)
    p.add_argument("--workflow",required=True)
    p.add_argument("--ref",default="main")
    p.add_argument("--current-run-id")
    args=p.parse_args(argv)
    token=os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        raise SystemExit("GitHub token missing")
    result=ensure(
        args.repo,args.workflow,token,args.current_run_id,args.ref
    )
    print(json.dumps(result,sort_keys=True,separators=(",",":")))
    if not result["dispatch"].get("ok"):
        raise SystemExit(2)


if __name__=="__main__":
    main()
