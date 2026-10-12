"""Adversarial independent episode scoring; no model skill claims."""
from datetime import datetime,timedelta,timezone
from btc_demand_v7.episode_quality_v4 import report,episodes_from_verified_barriers

UTC=timezone.utc
def iso(x):return x.isoformat()
def must_reject(fn):
    try:fn()
    except ValueError:return
    raise AssertionError("illegal episode admitted")

def main():
    origin=datetime(2026,10,14,12,tzinfo=UTC)
    observed=[
        {"slot_id":"s1","direction":"UP_FIRST","touch_open_utc":iso(origin+timedelta(minutes=61))},
        {"slot_id":"s2","direction":"UP_FIRST","touch_open_utc":iso(origin+timedelta(minutes=62))},
        {"slot_id":"s3","direction":"UP_FIRST","touch_open_utc":iso(origin+timedelta(minutes=63))},
        {"slot_id":"s4","direction":"DOWN_FIRST","touch_open_utc":iso(origin+timedelta(minutes=111))},
        {"slot_id":"s5","direction":"NEITHER","touch_open_utc":None},
        {"slot_id":"s6","direction":"UP_FIRST","touch_open_utc":iso(origin+timedelta(minutes=301))},
    ]
    ep=episodes_from_verified_barriers(observed)
    assert len(ep)==3,ep
    assert ep[0]["member_windows"]==3
    assert ep[1]["side"]=="DOWN_FIRST"
    eligible=[
        {"slot_id":"a1","side":"UP_FIRST","eligible":True,
         "public_delivery_utc":iso(origin+timedelta(minutes=1,seconds=30))},
        {"slot_id":"a2","side":"DOWN_FIRST","eligible":False,
         "public_delivery_utc":iso(origin+timedelta(minutes=10))},
    ]
    scored=report("1h",observed,eligible,full_due_count=42,missing_or_late_count=5)
    assert scored["n_verified_nonoverlapping_episodes"]==3
    assert scored["n_verified_public_alerts"]==2
    assert scored["partial_coverage"] is True
    assert scored["prospective_skill_proven"] is False
    assert scored["conservative_lead_minutes"]["10"]["verified_alerts_matched"]==1
    assert scored["conservative_lead_minutes"]["30"]["verified_alerts_matched"]==1
    # Conservative minute-open lead 59.5m; does NOT qualify as >=60m.
    assert scored["conservative_lead_minutes"]["60"]["verified_alerts_matched"]==0
    assert scored["conservative_lead_minutes"]["10"]["verified_distinct_episodes_matched"]==1
    must_reject(lambda:report("1h",observed,eligible+eligible[:1],
                               full_due_count=42,missing_or_late_count=5))
    must_reject(lambda:episodes_from_verified_barriers(observed+observed[:1]))
    no_alert=report("4h",observed,[],full_due_count=10,missing_or_late_count=0)
    assert no_alert["conservative_lead_minutes"]["30"]["observed_alert_precision"] is None
    assert no_alert["conservative_lead_minutes"]["30"]["observed_episode_recall"]==0
    print("BTC_V7R4_VERIFIED_NONOVERLAPPING_EVENT_PRECISION_RECALL_AND_MINUTE_LEAD_TEST_PASS")

if __name__=="__main__":main()
