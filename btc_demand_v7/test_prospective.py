"""Negative tests for prospective grid, no-backfill, scorecard and correct outcomes."""
import copy,datetime as dt,math
from btc_demand_v7.prospective_core import *
UTC=dt.timezone.utc
SHA="b"*40

def err(fn,why):
    try:fn()
    except (ValueError,RuntimeError):return
    raise AssertionError("accepted invalid "+why)

def test():
    registered=dt.datetime(2026,10,12,4,0,tzinfo=UTC)
    start=dt.datetime(2026,10,13,0,0,tzinfo=UTC)
    g=registered_grid(start,days=1,source_sha=SHA,created_at=registered,
                      source_ref="refs/heads/btc-v7r2-prospective-contour-20261012")
    assert len(g["slots"])==96
    assert len({s["id"] for s in g["slots"]})==96
    assert target(start,"1h")==start+dt.timedelta(hours=1)
    assert target(start,"4h")==start+dt.timedelta(hours=4)
    assert target(start,"24h")==start+dt.timedelta(days=1)
    assert target(start,"morning_08msk")==dt.datetime(2026,10,13,5,tzinfo=UTC)
    assert target(dt.datetime(2026,10,13,5,tzinfo=UTC),"morning_08msk")==dt.datetime(2026,10,14,5,tzinfo=UTC)
    err(lambda:registered_grid(start,source_sha=SHA,created_at=start-dt.timedelta(minutes=3),
                                source_ref="none"),"post-hoc registration")
    err(lambda:registered_grid(start+dt.timedelta(minutes=1),source_sha=SHA,created_at=registered,
                                source_ref="none"),"unaligned grid")

    issued=start+dt.timedelta(minutes=3)
    live={"reference_anchor_utc":start.isoformat(),
          "computed_at_utc":(start+dt.timedelta(minutes=2)).isoformat(),
          "spot":83000.,"model_skill_status":"NOT_PROVEN_BASELINE_ONLY",
          "price_point_forecasts":{"1h":83100,"4h":83500,"morning":83090},
          "evidence_binding":{"snapshot_sha256":"a"*64,"model_sha256":"f"*64},
          "otc_comparison":{"status":"NO_EXECUTION_ALIGNED_FORECAST"}}
    f=forecast_receipt(g,start,issued,live,snapshot_sha="a"*64,live_sha="e"*64)
    assert f["kind"]=="FORECAST_ISSUED"
    assert f["heads"]["24h"]["method"]=="PERSISTENCE_BASELINE_ONLY"
    assert f["heads"]["1h"]["forecast_spot"]==83100
    assert f["heads"]["4h"]["forecast_spot"]==83500
    assert f["otc_calculation_is_executable"] is False
    err(lambda:forecast_receipt(g,start,issued,{**live,"reference_anchor_utc":(start+dt.timedelta(minutes=5)).isoformat()},
                                snapshot_sha="a"*64,live_sha="e"*64),"wrong underlying candle")
    assert acceptance_at(g,start,start-dt.timedelta(seconds=1))=="FORECAST_EARLY"
    assert acceptance_at(g,start,start+dt.timedelta(minutes=11))=="SLOT_MISSED"
    missed=forecast_receipt(g,start,start+dt.timedelta(minutes=11),None,snapshot_sha="",live_sha="")
    assert missed["kind"]=="SLOT_MISSED"
    err(lambda:price_outcome(g,f,"1h",start+dt.timedelta(minutes=55),83102,raw_sha="d"*64),"early outcome")
    o=price_outcome(g,f,"1h",start+dt.timedelta(hours=1,minutes=3),83102,raw_sha="d"*64)
    assert o["kind"]=="OUTCOME_RECORDED"
    assert o["absolute_error_usdt"]==2 and o["persistence_absolute_error_usdt"]==102
    late=price_outcome(g,f,"4h",start+dt.timedelta(hours=5),84000,raw_sha="d"*64)
    assert late["kind"]=="OUTCOME_LATE"
    s=score_fixed_grid(g,[f],[o],start+dt.timedelta(hours=2))
    assert s["due_forecast_slots"]==8
    assert s["issued_on_time"]==1
    assert s["missing_forecasts"]==7
    assert s["heads"]["1h"]["settled"]==1 and s["heads"]["1h"]["mae_gain_usdt"]==100.
    assert not s["admission_ready"]
    assert s["missing_slots_block_admission"]
    err(lambda:score_fixed_grid(g,[f,f],[o],start+dt.timedelta(hours=2)),"duplicate forecast")
    spoof=copy.deepcopy(o);spoof["forecast_sha256"]="0"*64
    err(lambda:score_fixed_grid(g,[f],[spoof],start+dt.timedelta(hours=2)),"wrong forecast hash")
    print("V7R2_REGISTERED_DUE_GRID_AND_CAUSAL_OUTCOMES_PASS")

if __name__=="__main__":test()
