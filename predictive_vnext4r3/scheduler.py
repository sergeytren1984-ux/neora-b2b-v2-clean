"""Self-chained scheduler for BTC Predictive vNext4R3.

The workflow itself is started by push once and then by explicit workflow_dispatch
from the preceding run. This script sleeps until the next evidence action and
executes the frozen worker. GitHub cron is not used as the primary clock.

A delayed chain can still catch the current slot if it is inside the preregistered
deadline. If it is too late, the worker records SLOT_MISSED; there is no backfill.
"""
from __future__ import annotations

import os
import time
from datetime import datetime,timedelta,timezone

from predictive_vnext4r3.worker import (
    CONFIG, START, prior_events, slot_floor, slot_text, utcnow, main as worker_main
)

UTC=timezone.utc
RETRY_DELAY=timedelta(minutes=2)
FORECAST_DATA_DELAY={"early15m":timedelta(seconds=75),"hourly":timedelta(seconds=90)}
OUTCOME_DELAY={"early15m":timedelta(minutes=4),"hourly":timedelta(minutes=8)}
SAFETY=timedelta(minutes=2)


def finalized_forecast(events,anchor):
    slot=slot_text(anchor)
    keys={e["idempotency_key"] for e,_ in events}
    return ("forecast:"+slot in keys) or ("missed:"+slot in keys)


def next_forecast_wake(head,now,events):
    cfg=CONFIG[head]
    if now<START:
        return START+FORECAST_DATA_DELAY[head]
    anchor=max(START,slot_floor(now,cfg["cadence"]))
    if finalized_forecast(events,anchor):
        target=anchor+cfg["cadence"]+FORECAST_DATA_DELAY[head]
        return target if target>now else now+RETRY_DELAY
    deadline=anchor+cfg["deadline"]
    if now<deadline-SAFETY:
        return min(now+RETRY_DELAY,deadline-SAFETY)
    # Current slot is no longer admissible. Next worker invocation will mark it
    # missed; wake for the next slot after its data-close delay.
    target=anchor+cfg["cadence"]+FORECAST_DATA_DELAY[head]
    return target if target>now else now+RETRY_DELAY


def next_boundary(now,cadence):
    floor=slot_floor(now,cadence)
    return floor+cadence


def next_outcome_wake(head,now):
    cfg=CONFIG[head]
    if now<START:
        return START+OUTCOME_DELAY[head]
    target=next_boundary(now,cfg["cadence"])+OUTCOME_DELAY[head]
    return target


def sleep_until(target):
    while True:
        now=utcnow()
        remain=(target-now).total_seconds()
        if remain<=0:
            return
        time.sleep(min(remain,30.0))


def run_cycle(head,action):
    if head not in CONFIG or action not in ("forecast","outcome"):
        raise ValueError("invalid head/action")
    os.environ["BTC_VNEXT4R3_HEAD"]=head
    os.environ["BTC_VNEXT4R3_ACTION"]=action

    # Immediate attempt: catches a still-open delayed slot or resolves any due outcomes.
    worker_main()
    now=utcnow()

    if action=="forecast":
        events=prior_events(CONFIG[head]) if now>=START or (CONFIG[head]["events"]) else []
        target=next_forecast_wake(head,now,events)
    else:
        target=next_outcome_wake(head,now)

    print(f"SCHEDULER_WAIT head={head} action={action} now={now.isoformat()} target={target.isoformat()}",flush=True)
    sleep_until(target)
    print(f"SCHEDULER_WAKE head={head} action={action} at={utcnow().isoformat()}",flush=True)
    worker_main()


def main():
    head=os.environ.get("BTC_VNEXT4R3_HEAD")
    action=os.environ.get("BTC_VNEXT4R3_ACTION")
    run_cycle(head,action)


if __name__=="__main__":
    main()
