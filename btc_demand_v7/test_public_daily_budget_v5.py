"""Adversarial UTC-publication-day alert budget across late GitHub delivery.

The signed CUSUM alert time is source receipt time. GitHub completion
can occur up to its registered T+13m deadline. Under old 3h cooldown, a
late Sunday alert at 23:58 with public Monday 00:10, followed by Monday
morning source at 08:03 with Monday 08:10 public would create *two
Monday UTC PUBLIC warnings* even though source UTC days differ.
"""
from __future__ import annotations
from datetime import datetime,timedelta,timezone
from btc_demand_v7.test_demand_change_v2 import snap
from btc_demand_v7.demand_change_v2 import (
    BASELINE_COUNT,advance,replay,source_hash,
    GLOBAL_PUBLIC_DAILY_ALERT_SAFETY_MINUTES)
UTC=timezone.utc

def run():
    history=[snap(i) for i in range(BASELINE_COUNT)]
    state,_=replay(history)
    current=snap(BASELINE_COUNT,direction=1)
    assert current["anchor_utc"].startswith("2026-10-14T08:00")
    # Previously issued just before midnight; arrived to public after 00:00.
    last=datetime(2026,10,13,23,58,tzinfo=UTC)
    state["last_alert_utc"]=last.isoformat()
    state["last_alert_side"]="UP"
    nextstate,detail=advance(state,history,current)
    assert detail["alert"] is False
    assert detail["status"]=="SUPPRESSED_IN_COOLDOWN",detail
    assert nextstate["last_alert_utc"]==last.isoformat()
    assert GLOBAL_PUBLIC_DAILY_ALERT_SAFETY_MINUTES==1453
    # A source genuinely 48h ago cannot indefinitely suppress alerts.
    older=datetime(2026,10,12,23,58,tzinfo=UTC)
    state2={**state,"last_alert_utc":older.isoformat()}
    nextstate2,detail2=advance(state2,history,current)
    assert detail2["alert"] and detail2["warning_side"]=="UP",detail2
    assert nextstate2["last_alert_utc"]==current["retrieved_at_utc"]
    # Tampered future alert must not make model silently wait forever.
    state3={**state,"last_alert_utc":(datetime(2026,10,15,tzinfo=UTC)).isoformat()}
    try:advance(state3,history,current)
    except ValueError:pass
    else:raise AssertionError("untrusted future signed prior alert accepted")
    print("BTC_V7R5_PUBLIC_UTC_DAY_GLOBAL_ALERT_BUDGET_MIDNIGHT_PROVEN_PASS")

if __name__=="__main__":run()
