"""UTC times and safe watchdog dispatch without backfill or fake successes."""
import datetime as dt
from btc_v7r5_watchdog import START,END,SOURCE_SHA,SOURCE_REF,plan,anchor_for
UTC=dt.timezone.utc

def t(mins):return START+dt.timedelta(minutes=mins)

def run():
    assert anchor_for(t(22))==t(15)
    pre=plan(START-dt.timedelta(hours=1),[],{})
    assert pre["status"]=="OUTSIDE_FROZEN_EPOCH"
    assert plan(t(5),[],{})["rescue"] is False
    assert plan(t(8),[],{})["rescue"] is True
    assert plan(t(10),[],{})["rescue"] is False
    existing=[{"headSha":SOURCE_SHA,"headBranch":SOURCE_REF,"event":"workflow_dispatch",
              "createdAt":t(3).isoformat()}]
    assert plan(t(8),existing,{})["rescue"] is False
    wrong=[{**existing[0],"headSha":"0"*40}]
    assert plan(t(8),wrong,{})["rescue"] is True
    assert plan(t(8),[],{t(0).isoformat():(True,True)})["rescue"] is False
    # Successful GitHub job without actual signed event + Sigstore is missed.
    miss=plan(t(16),existing,{t(0).isoformat():(False,False)})
    assert miss["missed"]==[t(0).isoformat()]
    assert miss["rescue"] is False
    # A signed JSON without attached transparency bundle is still missing.
    unsigned=plan(t(16),existing,{t(0).isoformat():(True,False)})
    assert unsigned["missed"]==[t(0).isoformat()]
    genuine=plan(t(16),existing,{t(0).isoformat():(True,True)})
    assert genuine["missed"]==[]
    # Past expiry: never resurrect previous frozen grid.
    late=plan(END+dt.timedelta(days=1),[],{})
    assert late["status"]=="OUTSIDE_FROZEN_EPOCH" and not late["rescue"]
    print("BTC_R5_WATCHDOG_13_REGRESSION_ASSERTIONS_PASS")

if __name__=="__main__":run()
