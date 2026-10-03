"""Operational wakeups only; frozen v3 worker verifies the signed source content.

Source events are observed by exact slot, type and idempotency key.  At +15m
the frozen arbiter may issue its documented missing-regime fallback.  No past
slot is dispatched and no event is manufactured by this transport.
"""
from __future__ import annotations

import datetime as dt
import base64
import json
import os
import subprocess
import time
import urllib.request

UTC = dt.timezone.utc
DEADLINE_MINUTE = 41  # leave signing/push time before the frozen +45m deadline
SOURCES = (
    ("btc-directional-v1", "directional_v1_events", "DIRECTIONAL_4H_ALERT_ISSUED", "alert:"),
    ("btc-regime-v4-hardened", "regime_v4_events", "REGIME_FORECAST_ISSUED", "regime:"),
)


def run(*args: str) -> str:
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=45).stdout


def dispatch(workflow: str) -> None:
    repo = os.environ["REPO_NAME"]
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/actions/workflows/{workflow}/dispatches",
        data=json.dumps({"ref": "main"}).encode(),
        headers={"Authorization": "Bearer " + os.environ["GH_TOKEN"],
                 "Accept": "application/vnd.github+json",
                 "User-Agent": "btc-arbitration-v3-source-sequencer"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=25) as result:
        if result.status != 204:
            raise RuntimeError(f"{workflow}: HTTP {result.status}")
    print("DISPATCHED", workflow, dt.datetime.now(UTC).isoformat(), flush=True)


def receipt(slot: str, ready: list[bool], mode: str) -> None:
    repo = os.environ["REPO_NAME"]
    run_id = os.environ["RUN_ID"]
    path = f"arbiter_v3_sequencer_receipts/{run_id}.json"
    data = {"schema": "btc-arbiter-v3-source-sequencer-receipt",
            "run_id": run_id, "slot": slot, "source_candidates_present":
            {"directional": ready[0], "regime": ready[1]},
            "dispatch_mode": mode, "arbiter_dispatch_status": 204,
            "dispatched_at_utc": dt.datetime.now(UTC).isoformat()}
    body = {"message": "Record ordered BTC arbitration dispatch " + slot,
            "branch": "main", "content": base64.b64encode(
                (json.dumps(data, sort_keys=True) + "\n").encode()).decode()}
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/contents/{path}",
        data=json.dumps(body).encode(),
        headers={"Authorization": "Bearer " + os.environ["GH_TOKEN"],
                 "Accept": "application/vnd.github+json",
                 "User-Agent": "btc-arbitration-v3-source-sequencer"},
        method="PUT")
    with urllib.request.urlopen(req, timeout=25) as result:
        if result.status != 201:
            raise RuntimeError(f"sequencer receipt HTTP {result.status}")


def event_present(branch: str, directory: str, kind: str, prefix: str, slot: str) -> bool:
    ref = "refs/remotes/origin/" + branch
    paths = run("git", "ls-tree", "-r", "--name-only", ref, directory).splitlines()
    for path in paths:
        name = path.rsplit("/", 1)[-1]
        if len(name) != 13 or not name[:8].isdigit() or not name.endswith(".json"):
            continue
        event = json.loads(run("git", "show", ref + ":" + path))
        if (event.get("slot") == slot and event.get("type") == kind and
                event.get("idempotency_key") == prefix + slot):
            # The immutable worker performs the full Cosign/Rekor and raw check.
            return path[:-5] + ".sigstore.json" in paths
    return False


def main() -> None:
    current = dt.datetime.now(UTC)
    anchor = current.replace(minute=0, second=0, microsecond=0)
    slot = anchor.strftime("%Y%m%dT%H%M%SZ")
    if current.minute >= DEADLINE_MINUTE:
        print("TOO_LATE_FOR_CURRENT_SLOT", slot, flush=True)
        return
    # Wake source workflows before looking for any source events.  The calls
    # are idempotent with the frozen workers' per-slot keys.
    for workflow in ("btc-directional-v1.yml", "btc-regime-v4-hardened.yml"):
        dispatch(workflow)
    while dt.datetime.now(UTC) < anchor + dt.timedelta(minutes=DEADLINE_MINUTE):
        run("git", "fetch", "--quiet", "origin", *(
            "+refs/heads/" + source[0] + ":refs/remotes/origin/" + source[0]
            for source in SOURCES))
        ready = [event_present(*source, slot) for source in SOURCES]
        current = dt.datetime.now(UTC)
        if all(ready):
            dispatch("btc-arbitration-v3.yml")
            receipt(slot, ready, "BOTH_SOURCE_EVENTS_OBSERVED")
            print("BOTH_SOURCE_EVENTS_OBSERVED", slot, flush=True)
            return
        if ready[0] and current >= anchor + dt.timedelta(minutes=15):
            dispatch("btc-arbitration-v3.yml")
            receipt(slot, ready, "DIRECTIONAL_ONLY_FALLBACK_AFTER_15M")
            print("DIRECTIONAL_PRESENT_REGIME_FALLBACK_ELIGIBLE", slot, flush=True)
            return
        time.sleep(20)
    print("SOURCES_NOT_READY_BEFORE_SAFETY_MARGIN", slot, flush=True)
    # An explicit later guard invocation records SLOT_MISSED at +45m; do not
    # dispatch a too-late inference that could be mistaken for timely issuance.


if __name__ == "__main__":
    main()
