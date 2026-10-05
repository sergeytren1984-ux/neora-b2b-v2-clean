"""Long-lived self-chained scheduler for BTC Predictive vNext4R3.

One workflow per head owns both forecast and outcome writes, eliminating branch
write races between separate workers. A successor workflow is queued by the
current workflow before this scheduler starts; GitHub concurrency keeps it
pending until the current session exits. If the current session crashes, the
queued successor can start and recover any still-open slot. Missed deadlines are
recorded as SLOT_MISSED; no backfill is allowed.
"""
from __future__ import annotations

import os
import sys
import time
from datetime import datetime,timedelta,timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))

from predictive_vnext4r3.worker import CONFIG,START,slot_floor,slot_text,utcnow,main as worker_main

UTC=timezone.utc
FORECAST_DATA_DELAY={"early15m":timedelta(seconds=75),"hourly":timedelta(seconds=90)}
ACTIVE_SESSION_RUNTIME=timedelta(hours=4)
PRESTART_SESSION_RUNTIME=timedelta(hours=5)
MAX_SLEEP_CHUNK=30.0
DEADLINE_SAFETY=timedelta(minutes=2)
RETRY_INTERVAL={"early15m":timedelta(seconds=45),"hourly":timedelta(minutes=2)}


def sleep_until(target):
    while True:
        now=utcnow()
        remain=(target-now).total_seconds()
        if remain<=0:
            return
        time.sleep(min(remain,MAX_SLEEP_CHUNK))


def next_anchor_after(now,cadence):
    if now<START:
        return START
    floor=slot_floor(now,cadence)
    # If the current anchor is still near its data-close delay, use it;
    # otherwise advance to the next anchor. The worker itself enforces deadline.
    return floor


def invoke(head,action):
    os.environ["BTC_VNEXT4R3_HEAD"]=head
    os.environ["BTC_VNEXT4R3_ACTION"]=action
    return worker_main()


def forecast_attempt_targets(head,anchor):
    """Deterministic retry grid strictly inside the frozen issuance deadline."""
    cfg=CONFIG[head]
    first=anchor+FORECAST_DATA_DELAY[head]
    cutoff=anchor+cfg["deadline"]-DEADLINE_SAFETY
    step=RETRY_INTERVAL[head]
    out=[];target=first
    while target<cutoff:
        out.append(target)
        target+=step
    return out


def run_slot(head,anchor,session_deadline=None):
    cfg=CONFIG[head]
    cutoff=anchor+cfg["deadline"]-DEADLINE_SAFETY
    for attempt,target in enumerate(forecast_attempt_targets(head,anchor),1):
        if session_deadline is not None and target>=session_deadline:
            break
        sleep_until(target)
        if utcnow()>=cutoff:
            break
        print(
            f"R3_SLOT_WAKE head={head} anchor={anchor.isoformat()} "
            f"attempt={attempt} at={utcnow().isoformat()}",
            flush=True,
        )
        issued=bool(invoke(head,"forecast"))
        # Outcomes remain due-only and idempotent; calling them after an
        # unsuccessful forecast attempt cannot create a future outcome.
        invoke(head,"outcome")
        if issued:
            print(
                f"R3_SLOT_FORECAST_CONFIRMED head={head} anchor={anchor.isoformat()} "
                f"attempt={attempt} at={utcnow().isoformat()}",
                flush=True,
            )
            return True
    print(
        f"R3_SLOT_NO_CONFIRMED_FORECAST head={head} anchor={anchor.isoformat()} "
        f"at={utcnow().isoformat()}",
        flush=True,
    )
    return False


def session(head):
    if head not in CONFIG:
        raise ValueError("invalid head")
    cfg=CONFIG[head]

    started=utcnow()
    runtime=PRESTART_SESSION_RUNTIME if started<START else ACTIVE_SESSION_RUNTIME
    session_deadline=started+runtime

    # Pre-start registration/freeze, or immediate recovery attempt if restarted
    # during an already-open slot.
    invoke(head,"forecast")
    if utcnow()>=START:
        invoke(head,"outcome")

    now=utcnow()
    anchor=START if now<START else slot_floor(now,cfg["cadence"])

    # If startup occurs after the nominal data delay, attempt this current slot
    # immediately. The worker either issues it within deadline or records it
    # missed when appropriate.
    if now>=anchor+FORECAST_DATA_DELAY[head]:
        print(f"R3_RECOVERY_ATTEMPT head={head} anchor={anchor.isoformat()} at={now.isoformat()}",flush=True)
        run_slot(head,anchor,session_deadline=session_deadline)
        anchor=anchor+cfg["cadence"]

    completed=0
    while True:
        target=anchor+FORECAST_DATA_DELAY[head]
        if target>=session_deadline:
            sleep_until(session_deadline)
            break
        run_slot(head,anchor,session_deadline=session_deadline)
        completed+=1
        anchor=anchor+cfg["cadence"]

    print(f"R3_SESSION_COMPLETE head={head} slots={completed} next_anchor={anchor.isoformat()} at={utcnow().isoformat()}",flush=True)


def preflight():
    head=os.environ.get("BTC_VNEXT4R3_HEAD")
    if head not in CONFIG:
        raise ValueError("invalid head")
    cfg=CONFIG[head]
    assert cfg["forecast_workflow"]==cfg["outcome_workflow"],"unified writer invariant"
    assert ACTIVE_SESSION_RUNTIME==timedelta(hours=4)
    assert PRESTART_SESSION_RUNTIME<timedelta(hours=5,minutes=30)
    print(f"R3_PREFLIGHT_OK head={head} start={START.isoformat()} active_runtime={ACTIVE_SESSION_RUNTIME}",flush=True)


def main():
    if os.environ.get("BTC_VNEXT4R3_PREFLIGHT")=="1":
        preflight()
        return
    head=os.environ.get("BTC_VNEXT4R3_HEAD")
    session(head)


if __name__=="__main__":
    main()
