"""Source-authenticated research worker replay and frozen-before-outcome discipline.

All signatures are mocked ONLY in this synthetic unit test. The GitHub
workflow separately calls real Cosign verify on the upstream evidence.
"""
import datetime as dt
import hashlib,json,pathlib,tempfile
from unittest.mock import patch
from btc_demand_v7.test_demand_change_v2 import snap
from btc_demand_v7 import v7r3_shadow_worker as worker
from btc_demand_v7.shadow_contract_v3 import grid,canonical,slot_id,source_hash
from btc_demand_v7.prospective_core import when

UTC=dt.timezone.utc

def test():
    base=dt.datetime(2026,10,14,tzinfo=UTC)
    reg=grid(base,base-dt.timedelta(hours=3),"a"*40,days=1)
    samples=[snap(i,direction=1 if i>=32 else 0) for i in range(35)]
    with tempfile.TemporaryDirectory() as temp:
        root=pathlib.Path(temp)/"r3"; r2=pathlib.Path(temp)/"r2"
        for s in samples:
            t=when(s["anchor_utc"])
            d=r2/"slots"/slot_id(t)
            d.mkdir(parents=True,exist_ok=True)
            raw=canonical(s)
            (d/"snapshot.json").write_bytes(raw)
            (d/"forecast.json").write_bytes(canonical({
                "schema":"btc-v7r2-slot-event-v1",
                "kind":"FORECAST_ISSUED",
                "slot_utc":s["anchor_utc"],
                "snapshot_sha256":hashlib.sha256(raw).hexdigest(),
                "frozen_grid_sha256":worker.SOURCE_R2_GRID_SHA,
            }))
        def mock_signed(folder,name,value):
            dest=pathlib.Path(folder)/name
            dest.parent.mkdir(parents=True,exist_ok=True)
            dest.write_bytes(canonical(value))
            return dest
        def mock_close():
            return {"source":"Binance BTCUSDT closed 1m spot","spot":83000.,
                    "minute_close_utc":received.replace(second=0,microsecond=0).isoformat(),
                    "received_at_utc":received.isoformat(),
                    "row":[1,"83000","83001","82999","83000","1",2]}
        first=base+dt.timedelta(minutes=15*32)
        received=first+dt.timedelta(minutes=10,seconds=15)
        with patch.object(worker,"verify",lambda *x:None),patch.object(worker,"write",mock_signed),patch.object(worker,"last_close_before_issuance",mock_close),patch.object(worker,"utcnow",lambda:received):
            status=worker.current_slot_signal(root,r2,reg,received)
        assert status=="SIGNED_STATE_PUBLISHED",status
        firstevent=json.loads((root/"slots"/slot_id(first)/"signal.json").read_text())
        assert firstevent["diagnostic"]["alert"] is False or firstevent["diagnostic"]["warning_side"]=="UP"
        assert firstevent["state"]["sequence"]==1
        assert firstevent["target_utc"]["1h"]==(first+dt.timedelta(hours=1,minutes=11)).isoformat()
        assert firstevent["reference_spot"]==83000.
        received=first+dt.timedelta(minutes=25,seconds=15)
        second=first+dt.timedelta(minutes=15)
        with patch.object(worker,"verify",lambda *x:None),patch.object(worker,"write",mock_signed),patch.object(worker,"last_close_before_issuance",mock_close),patch.object(worker,"utcnow",lambda:received):
            status=worker.current_slot_signal(root,r2,reg,received)
        assert status=="SIGNED_STATE_PUBLISHED",status
        nextstate=json.loads((root/"slots"/slot_id(second)/"signal.json").read_text())
        assert nextstate["state"]["sequence"]==2
        assert nextstate["state"]["up_cusum"]>firstevent["state"]["up_cusum"]
        assert nextstate["state"]["last_snapshot_sha256"]==source_hash(samples[33])
        assert nextstate["diagnostic"]["calibrated_probability"] is False
        assert nextstate["trading_authority"] is False
        # An earlier UTC slot must never generate an alert after the deadline.
        received=second+dt.timedelta(minutes=14)
        with patch.object(worker,"write",mock_signed):
            status=worker.current_slot_signal(root,r2,reg,received)
        assert status=="DUPLICATE_NO_MUTATION"
        assessed=worker.score(reg,root,second+dt.timedelta(hours=1))
        assert assessed["coverage"]["missing_slots"]>0
        assert assessed["trading_authority"] is False

        # Actual future outcomes are computed only from complete CLOSED
        # minute bars collected post-due; never use source-time inference.
        recorded={}
        start=when(firstevent["exact_future_first_full_minute_utc"])
        for i in range(1,300):
            end=start+dt.timedelta(minutes=i)
            ms=int(end.timestamp()*1000)
            recorded[ms]=[ms-60000,"83000",str(84000 if i==20 else 83100),"82900","83030","1",ms-1]
        def closed_bars(pending,now):return recorded
        at=first+dt.timedelta(hours=4,minutes=55)
        with patch.object(worker,"verify",lambda *x:None),patch.object(worker,"write",mock_signed),patch.object(worker,"get_future_raw",closed_bars):
            n=worker.resolve_outcomes(root,at)
        assert n>=2,n
        outcomes=list((root/"slots"/slot_id(first)).glob("outcome_*.json"))
        assert any(json.loads(p.read_text())["barrier_result"]["direction"]=="UP_FIRST" for p in outcomes)
        scored=worker.score(reg,root,at+dt.timedelta(hours=1))
        assert scored["forward_outcomes"]["1h"]["due"]>=1
        assert scored["coverage"]["missing_slots"]>0
        print("BTC_V7R3_END_TO_END_SIGNED_JOURNAL_ALGORITHM_SYNTHETIC_PASS",
              {"future_outcomes":n,"seq":nextstate["state"]["sequence"],
               "missing":scored["coverage"]["missing_slots"]})

if __name__=="__main__":
    test()
