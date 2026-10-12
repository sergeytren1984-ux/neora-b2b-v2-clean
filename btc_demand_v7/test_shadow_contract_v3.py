"""Test R3 prospective source receipt, actual issuance, censoring, due grid."""
from __future__ import annotations
from datetime import datetime,timedelta,timezone
from btc_demand_v7.shadow_contract_v3 import (
    grid,accept_slot,future_anchor,future_due,status_grid,early_lead_report,digest)
UTC=timezone.utc

def nope(fn):
    try:fn()
    except (ValueError,RuntimeError):return
    raise AssertionError("invalid prospective action accepted")

def main():
    start=datetime(2026,10,13,tzinfo=UTC)
    g=grid(start,start-timedelta(hours=3),"a"*40,days=1)
    assert len(g["due_slots"])==96 and len(set(x["slot_id"] for x in g["due_slots"]))==96
    assert accept_slot(g,start,start+timedelta(minutes=2))=="NOT_YET_DUE"
    assert accept_slot(g,start,start+timedelta(minutes=10))=="ON_TIME"
    assert accept_slot(g,start,start+timedelta(minutes=14))=="MISSED_DEADLINE"
    nope(lambda:grid(start,start-timedelta(minutes=2),"a"*40))
    nope(lambda:grid(start+timedelta(minutes=1),start-timedelta(hours=3),"a"*40))
    issue=start+timedelta(minutes=10,seconds=28)
    assert future_anchor(issue)==start+timedelta(minutes=11)
    assert future_due(issue,"1h")==start+timedelta(hours=1,minutes=11)
    assert future_due(issue,"4h")==start+timedelta(hours=4,minutes=11)
    assert future_due(start+timedelta(minutes=10),"1h")==start+timedelta(hours=1,minutes=10)
    nope(lambda:future_due(issue,"24h"))
    from btc_demand_v7.shadow_contract_v3 import digest as hash_signed
    active=start+timedelta(minutes=32*15)
    issue=active+timedelta(minutes=10,seconds=28)
    warmups=[{"slot_id":v["slot_id"],
              "status":"INSUFFICIENT_ASOF_HISTORY"} for v in g["due_slots"][:32]]
    event={"slot_id":g["due_slots"][32]["slot_id"],
           "anchor_utc":active.isoformat(),
           "status":"SIGNED_STATE_PUBLISHED",
           "issued_at_utc":issue.isoformat(),
           "diagnostic":{"alert":True,"status":"UNCALIBRATED_PRE_MOVE_UP_PRESSURE"}}
    delivery={"slot_id":event["slot_id"],
              "source_signal_sha256":hash_signed(event),
              "public_delivery_utc":(issue+timedelta(seconds=20)).isoformat()}
    status=status_grid(g,warmups+[event],active+timedelta(minutes=58),[delivery])
    assert status["due"]==36
    assert status["explicit_warmup_due"]==32
    assert status["eligible_signal_due"]==4
    assert status["missing_slots"]==3
    assert status["signed_pre_move_alerts"]==1
    assert status["admission_ready"] is False
    assert status["grid_sha256"]==digest(g)
    late_delivery={**delivery,"public_delivery_utc":(active+timedelta(minutes=45)).isoformat()}
    delayed=status_grid(g,warmups+[event],active+timedelta(minutes=58),[late_delivery])
    assert delayed["late_public_deliveries"]==1 and delayed["on_time_signed_model_state"]==0
    missing=status_grid(g,warmups+[event],active+timedelta(minutes=58))
    assert missing["delivery_unconfirmed"]==1 and missing["on_time_signed_model_state"]==0
    report=early_lead_report([
        {"alert":True,"warning_side":"UP_FIRST",
         "actual_side":"UP_FIRST","issued_utc":start.isoformat(),
         "first_touch_utc":(start+timedelta(minutes=15)).isoformat()},
        {"alert":True,"warning_side":"DOWN_FIRST",
         "actual_side":"UP_FIRST","issued_utc":start.isoformat(),
         "first_touch_utc":(start+timedelta(minutes=75)).isoformat()},
    ])
    assert report["lead_levels_minutes"][10]=={"correct_earlier":1,"false_alert":1}
    assert report["lead_levels_minutes"][30]=={"correct_earlier":0,"false_alert":2}
    assert report["lead_levels_minutes"][60]=={"correct_earlier":0,"false_alert":2}
    print("BTC_V7R3_PUBLICATION_UTC_FIRST_COMPLETE_MINUTE_AND_MISSING_GRID_PASS")

if __name__=="__main__":main()
