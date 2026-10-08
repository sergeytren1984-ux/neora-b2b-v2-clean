"""Long-lived self-chained scheduler for BTC Predictive vNext4R7.1."""
from __future__ import annotations

import os
import sys
import time
import json
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from predictive_vnext4r71.worker import (
    CONFIG,
    START,
    DELIVERY_SAFETY,
    slot_floor,
    utcnow,
    main as worker_main,
)

FORECAST_DATA_DELAY = {
    "1h": timedelta(seconds=75),
    "4h": timedelta(seconds=75),
    "24h": timedelta(seconds=90),
}
RETRY_INTERVAL = {
    "1h": timedelta(seconds=45),
    "4h": timedelta(seconds=45),
    "24h": timedelta(minutes=2),
}
ACTIVE_SESSION_RUNTIME = timedelta(hours=4)
PRESTART_SESSION_RUNTIME = timedelta(hours=5)
MAX_SLEEP_CHUNK = 30.0
DEADLINE_SAFETY = DELIVERY_SAFETY


def sleep_until(target):
    while True:
        remain = (target - utcnow()).total_seconds()
        if remain <= 0:
            return
        time.sleep(min(remain, MAX_SLEEP_CHUNK))


def invoke(head, action):
    os.environ["BTC_VNEXT4R71_HEAD"] = head
    os.environ["BTC_VNEXT4R71_ACTION"] = action
    return worker_main()


def forecast_attempt_targets(head, anchor):
    cfg = CONFIG[head]
    first = anchor + FORECAST_DATA_DELAY[head]
    cutoff = anchor + cfg["deadline"] - DEADLINE_SAFETY
    step = RETRY_INTERVAL[head]
    out = []
    target = first
    while target < cutoff:
        out.append(target)
        target += step
    return out


def run_slot(head, anchor, session_deadline=None):
    cfg = CONFIG[head]
    cutoff = anchor + cfg["deadline"] - DEADLINE_SAFETY
    for attempt, target in enumerate(forecast_attempt_targets(head, anchor), 1):
        if session_deadline is not None and target >= session_deadline:
            break
        sleep_until(target)
        if utcnow() >= cutoff:
            break
        print(
            f"R71_SLOT_WAKE head={head} anchor={anchor.isoformat()} "
            f"attempt={attempt} at={utcnow().isoformat()}",
            flush=True,
        )
        issued = bool(invoke(head, "forecast"))
        invoke(head, "outcome")
        if issued:
            print(
                f"R71_SLOT_FORECAST_CONFIRMED head={head} "
                f"anchor={anchor.isoformat()} attempt={attempt} "
                f"at={utcnow().isoformat()}",
                flush=True,
            )
            return True
    print(
        f"R71_SLOT_NO_CONFIRMED_FORECAST head={head} "
        f"anchor={anchor.isoformat()} at={utcnow().isoformat()}",
        flush=True,
    )
    return False


def session(head):
    if head not in CONFIG:
        raise ValueError("invalid head")
    cfg = CONFIG[head]

    started = utcnow()
    runtime = (
        PRESTART_SESSION_RUNTIME
        if started < START
        else ACTIVE_SESSION_RUNTIME
    )
    session_deadline = started + runtime
    initial_anchor = START if started < START else slot_floor(started, cfg["cadence"])
    initial_cutoff = initial_anchor + cfg["deadline"] - DEADLINE_SAFETY
    print(
        "R76_SESSION_READY " + json.dumps(
            {
                "head": head,
                "started_at": started.isoformat(),
                "session_deadline": session_deadline.isoformat(),
                "initial_anchor": initial_anchor.isoformat(),
                "initial_cutoff": initial_cutoff.isoformat(),
                "seconds_to_initial_cutoff": (initial_cutoff-started).total_seconds(),
                "zero_restart_lag_claimed": False,
            },
            sort_keys=True,
            separators=(",", ":"),
        ),
        flush=True,
    )

    invoke(head, "forecast")
    if utcnow() >= START:
        invoke(head, "outcome")

    now = utcnow()
    anchor = START if now < START else slot_floor(now, cfg["cadence"])

    if now >= anchor + FORECAST_DATA_DELAY[head]:
        print(
            f"R71_RECOVERY_ATTEMPT head={head} "
            f"anchor={anchor.isoformat()} at={now.isoformat()}",
            flush=True,
        )
        run_slot(head, anchor, session_deadline=session_deadline)
        anchor += cfg["cadence"]

    completed = 0
    while True:
        target = anchor + FORECAST_DATA_DELAY[head]
        if target >= session_deadline:
            sleep_until(session_deadline)
            break
        run_slot(head, anchor, session_deadline=session_deadline)
        completed += 1
        anchor += cfg["cadence"]

    print(
        f"R71_SESSION_COMPLETE head={head} slots={completed} "
        f"next_anchor={anchor.isoformat()} at={utcnow().isoformat()}",
        flush=True,
    )


def preflight():
    head = os.environ.get("BTC_VNEXT4R71_HEAD")
    if head not in CONFIG:
        raise ValueError("invalid head")
    cfg = CONFIG[head]
    if not os.environ.get("BTC_VNEXT4R71_SOURCE_SHA"):
        raise ValueError("immutable source SHA missing")
    if "2099-" in START.isoformat():
        raise ValueError("prospective start is not frozen")
    assert cfg["forecast_workflow"] == cfg["outcome_workflow"]
    assert ACTIVE_SESSION_RUNTIME == timedelta(hours=4)
    assert PRESTART_SESSION_RUNTIME < timedelta(hours=5, minutes=30)
    assert FORECAST_DATA_DELAY[head] < cfg["deadline"]
    print(
        f"R71_PREFLIGHT_OK head={head} start={START.isoformat()} "
        f"active_runtime={ACTIVE_SESSION_RUNTIME}",
        flush=True,
    )


def main():
    if os.environ.get("BTC_VNEXT4R71_PREFLIGHT") == "1":
        preflight()
        return
    session(os.environ.get("BTC_VNEXT4R71_HEAD"))


if __name__ == "__main__":
    main()
