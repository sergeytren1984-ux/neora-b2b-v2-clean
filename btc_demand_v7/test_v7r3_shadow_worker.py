"""Source-authenticated research worker replay and frozen-before-outcome discipline.

All signatures are mocked ONLY in this synthetic unit test. The GitHub
workflow separately calls real Cosign verify on the upstream evidence.
"""
import datetime as dt
import hashlib,json,pathlib,tempfile
from unittest.mock import patch
from btc_demand_v7.test_demand_change_v2 import snap
from btc_demand_v7 import v7r3_shadow_worker as worker
from btc_demand_v7.shadow_contract_v3 import grid,canonical,slot_id
from btc_demand_v7.demand_change_v2 import source_hash
from btc_demand_v7.prospective_core import when

UTC=dt.timezone.utc

def test():
    base=dt.datetime(2026,10,14,tzinfo=UTC)
    reg=grid(base,base-dt.timedelta(hours=3),"a"*40,days=1)
    samples=[snap(i,direction=1 if i>=32 else 0) for i in range(35)]
    for sample in samples:
        sample["observation"]["reference_spot"]=83000.
    with tempfile.TemporaryDirectory() as temp:
        root=pathlib.Path(temp)/"r3"
        # No R2 tree exists: prove forecast no longer depends on R2 release
        # or R2 outcome/forecast processing liveness.
        def mock_signed(folder,name,value):
            dest=pathlib.Path(folder)/name
            dest.parent.mkdir(parents=True,exist_ok=True)
            dest.write_bytes(canonical(value))
            return dest
        def mock_direct_collect(anchor_ms):
            i=int((anchor_ms/1000-base.timestamp())//(15*60))
            return samples[i]
        def mock_prior_signed_history(root,slot):
            i=int((slot.timestamp()-base.timestamp())//(15*60))
            return samples[i-32:i]
        def mock_close():
            return {"source":"Binance BTCUSDT closed 1m spot","spot":83000.,
                    "minute_close_utc":received.replace(second=0,microsecond=0).isoformat(),
                    "received_at_utc":received.isoformat(),
                    "row":[1,"83000","83001","82999","83000","1",2]}
        first=base+dt.timedelta(minutes=15*32)
        received=first+dt.timedelta(minutes=10,seconds=15)
        with patch.object(worker,"verify",lambda *x:None),patch.object(worker,"write",mock_signed),patch.object(worker,"last_close_before_issuance",mock_close),patch.object(worker,"utcnow",lambda:received),patch.object(worker,"market_collect",mock_direct_collect),patch.object(worker,"historic_snapshots",mock_prior_signed_history):
            status=worker.current_slot_signal(root,reg,received)
        assert status=="SIGNED_STATE_PUBLISHED",status
        firstevent=json.loads((root/"slots"/slot_id(first)/"signal.json").read_text())
        assert firstevent["diagnostic"]["alert"] is False or firstevent["diagnostic"]["warning_side"]=="UP"
        assert firstevent["state"]["sequence"]==1
        assert firstevent["target_utc"]["1h"]==(first+dt.timedelta(hours=1,minutes=11)).isoformat()
        assert firstevent["reference_spot"]==83000.
        received=first+dt.timedelta(minutes=25,seconds=15)
        second=first+dt.timedelta(minutes=15)
        with patch.object(worker,"verify",lambda *x:None),patch.object(worker,"write",mock_signed),patch.object(worker,"last_close_before_issuance",mock_close),patch.object(worker,"utcnow",lambda:received),patch.object(worker,"market_collect",mock_direct_collect),patch.object(worker,"historic_snapshots",mock_prior_signed_history):
            status=worker.current_slot_signal(root,reg,received)
        assert status=="SIGNED_STATE_PUBLISHED",status
        nextstate=json.loads((root/"slots"/slot_id(second)/"signal.json").read_text())
        assert nextstate["state"]["sequence"]==2
        assert nextstate["state"]["up_cusum"]>firstevent["state"]["up_cusum"]
        assert nextstate["state"]["last_snapshot_sha256"]==source_hash(samples[33])
        assert nextstate["diagnostic"]["calibrated_probability"] is False
        assert nextstate["trading_authority"] is False
        assert nextstate["market_move_during_information_latency_pct"]==0.
        # Third slot: the model source remains bullish, but BTC has already
        # risen >0.3% before publication. Must NOT count an "early" alert.
        received=first+dt.timedelta(minutes=40,seconds=15)
        third=first+dt.timedelta(minutes=30)
        def moved_close():
            result=mock_close()
            return {**result,"spot":84000.}
        with patch.object(worker,"verify",lambda *x:None),patch.object(worker,"write",mock_signed),patch.object(worker,"last_close_before_issuance",moved_close),patch.object(worker,"utcnow",lambda:received),patch.object(worker,"market_collect",mock_direct_collect),patch.object(worker,"historic_snapshots",mock_prior_signed_history):
            third_status=worker.current_slot_signal(root,reg,received)
        assert third_status=="SIGNED_STATE_PUBLISHED"
        third_event=json.loads((root/"slots"/slot_id(third)/"signal.json").read_text())
        assert third_event["diagnostic"]["price_already_moved"]
        assert third_event["diagnostic"]["alert"] is False
        assert third_event["state"]["up_cusum"]==0.
        # An earlier UTC slot must never generate an alert after the deadline.
        received=second+dt.timedelta(minutes=14)
        with patch.object(worker,"write",mock_signed):
            status=worker.current_slot_signal(root,reg,received)
        assert status=="DUPLICATE_NO_MUTATION"
        with patch.object(worker,"verify",lambda *x:None):
            assessed=worker.score(reg,root,second+dt.timedelta(hours=1))
        assert assessed["coverage"]["missing_slots"]>0
        assert assessed["trading_authority"] is False

        # Actual future outcomes are computed only from complete CLOSED
        # minute bars collected post-due; never use source-time inference.
        recorded={}
        completed=when(firstevent["issued_at_utc"])+dt.timedelta(seconds=25)
        ref_end=int(completed.timestamp()*1000)//60000*60000
        recorded[ref_end]=[ref_end-60000,"83000","83800","82999","83800","1",ref_end-1]
        start=worker.future_anchor(completed)
        for i in range(1,300):
            end=start+dt.timedelta(minutes=i)
            ms=int(end.timestamp()*1000)
            recorded[ms]=[ms-60000,"83800",str(85000 if i==20 else 83900),"83700","83830","1",ms-1]
        def closed_bars(pending,now):return recorded
        at=first+dt.timedelta(hours=4,minutes=55)
        with patch.object(worker,"verify",lambda *x:None),patch.object(worker,"write",mock_signed),patch.object(worker,"get_future_raw",closed_bars),patch.object(worker,"verified_delivery_time",lambda e:when(e["issued_at_utc"])+dt.timedelta(seconds=25)):
            n=worker.resolve_outcomes(root,at)
        assert n>=2,n
        outcomes=list((root/"slots"/slot_id(first)).glob("outcome_*.json"))
        assert any(json.loads(p.read_text())["barrier_result"]["direction"]=="UP_FIRST" for p in outcomes)
        assert all(json.loads(p.read_text())["public_delivery_utc"]==completed.isoformat() for p in outcomes)
        assert all(json.loads(p.read_text())["reference_price_after_delivery_not_model_feature"] is True for p in outcomes)
        # The model saw 83000, the public learned it only after 83800.
        # Never credit the prior +800 dollars as an "early" warning.
        first_outcomes=[json.loads(p.read_text()) for p in outcomes]
        assert all(x["early_warning_eligible"] is False for x in first_outcomes)
        assert all(x["already_moved_before_publication"] is True for x in first_outcomes)
        for x in first_outcomes:
            if x["first_touch_minute_open_utc"] is not None:
                assert x["warning_lead_upper_minutes"]-x["warning_lead_lower_minutes"]==1.0
        with patch.object(worker,"verify",lambda *x:None):
            scored=worker.score(reg,root,at+dt.timedelta(hours=1))
        assert scored["forward_outcomes"]["1h"]["due"]>=1
        assert scored["coverage"]["missing_slots"]>0
        print("BTC_V7R3_END_TO_END_SIGNED_JOURNAL_ALGORITHM_SYNTHETIC_PASS",
              {"future_outcomes":n,"seq":nextstate["state"]["sequence"],
               "missing":scored["coverage"]["missing_slots"]})

if __name__=="__main__":
    test()
