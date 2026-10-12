"""Symmetric first-passage, intra-minute ambiguity, clustering and alert budget."""
import datetime as dt
from btc_demand_v7.event_semantics import first_passage,clustered_episodes,warning_lead_minutes,validate_alert_budget

UTC=dt.timezone.utc
def candle(t,open_,high,low,close):
    ms=int(t.timestamp()*1000)
    return [ms,str(open_),str(high),str(low),str(close),"1",ms+59999]

def run():
    start=dt.datetime(2026,10,13,0,0,tzinfo=UTC);spot=100000
    rows=[candle(start+dt.timedelta(minutes=i),100000,100050,99950,100000) for i in range(60)]
    up=[r[:] for r in rows];up[12][2]="100800"
    u=first_passage(start,spot,up,"1h")
    assert u["direction"]=="UP_FIRST"
    down=[r[:] for r in rows];down[12][3]="99200"
    d=first_passage(start,spot,down,"1h")
    assert d["direction"]=="DOWN_FIRST"
    double=[r[:] for r in rows]
    double[12][2]="100800";double[12][3]="99200"
    result=first_passage(start,spot,double,"1h")
    assert result["direction"]=="AMBIGUOUS_SAME_MINUTE"
    assert first_passage(start,spot,rows,"1h")["direction"]=="NEITHER"
    try:first_passage(start,spot,rows[:59],"1h")
    except ValueError:pass
    else:raise AssertionError("truncated minute outcomes accepted")
    assert warning_lead_minutes(u["first_barrier_touch_utc"],start)==13
    assert warning_lead_minutes(u["first_barrier_touch_utc"],start+dt.timedelta(minutes=15)) is None
    records=[u,{**d,"first_barrier_touch_utc":(start+dt.timedelta(minutes=14)).isoformat()},
             {**u,"first_barrier_touch_utc":(start+dt.timedelta(hours=5)).isoformat()}]
    clusters=clustered_episodes(records)
    assert len(clusters)==2 and clusters[0]["episode_member_count"]==2
    assert validate_alert_budget([{"alert_id":"one","issued_utc":start.isoformat()}])["within_budget"]
    assert not validate_alert_budget([{"alert_id":"one","issued_utc":start.isoformat()},
        {"alert_id":"two","issued_utc":(start+dt.timedelta(minutes=15)).isoformat()}])["within_budget"]
    print("BTC_V7R2_SYMMETRIC_FIRST_PASSAGE_CAUSAL_TEST_PASS")
if __name__=="__main__":run()
