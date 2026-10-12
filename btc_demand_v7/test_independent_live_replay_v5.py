"""Adversarial synthetic first clean R4 forecast input -> output numerical replay.

All signatures mocked ONLY for this unit test; GitHub workflow verifies
real Cosign/Rekor of genuine R4 journal and Binance/OKX raw separately.
"""
from __future__ import annotations
import copy,datetime as dt,json,pathlib,tempfile
from unittest.mock import patch
from btc_demand_v7 import independent_live_replay_v5 as v
from btc_demand_v7 import demand_change_v2 as numerical_test_fixture
from btc_demand_v7.test_demand_change_v2 import snap
from btc_demand_v7.shadow_contract_v3 import canonical,grid,slot_id,digest

UTC=dt.timezone.utc
SOURCE=v.FROZEN_R4_SHA

def put(folder,name,item):
    p=pathlib.Path(folder)/name
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_bytes(canonical(item))
    return p

def scenario(tamper=None):
    start=dt.datetime(2026,10,14,tzinfo=UTC)
    reg=grid(start,start-dt.timedelta(hours=4),SOURCE,days=7)
    ts=start+dt.timedelta(minutes=32*15)
    issue=ts+dt.timedelta(minutes=10,seconds=18)
    observations=[snap(i) for i in range(33)]
    for value in observations:value["observation"]["reference_spot"]=83000.
    baseline=observations[:32];live=observations[32]
    prior=numerical_test_fixture.state_zero()
    state,diagnostic=numerical_test_fixture.advance(
        prior,baseline,live,issued_utc=issue,live_change_since_anchor_pct=0.)
    minute_end=issue.replace(second=0,microsecond=0)
    m=int(minute_end.timestamp()*1000)
    receipt=issue-dt.timedelta(seconds=1)
    event={
        "schema":"btc-v7r3-signed-pressure-event-v1",
        "slot_id":slot_id(ts),"anchor_utc":ts.isoformat(),
        "status":"SIGNED_STATE_PUBLISHED","recovery":None,
        "issued_at_utc":issue.isoformat(),
        "snapshot_received_at_utc":live["retrieved_at_utc"],
        "reference_spot":83000.,"market_move_during_information_latency_pct":0.,
        "reference_1m_raw":{
          "source":"Binance BTCUSDT closed 1m spot",
          "spot":83000.,"row":[m-60000,"83000","83001","82999","83000","1",m-1],
          "minute_close_utc":minute_end.isoformat(),
          "received_at_utc":receipt.isoformat()},
        "upstream_r2_snapshot_canonical_sha256":numerical_test_fixture.source_hash(live),
        "registered_grid_sha256":digest(reg),
        "model_source_sha":SOURCE,
        "state":state,"diagnostic":diagnostic,
        "calibrated_probability":False,"trading_authority":False}
    with tempfile.TemporaryDirectory() as tmp:
        root=pathlib.Path(tmp)/"btc_v7r3_evidence"
        put(root,"registration.json",reg)
        put(root,"frozen_config.json",{
            "model_source_sha":SOURCE,"grid_sha256":digest(reg)})
        # Apply the malicious mutation BEFORE writing the fake source
        # bytes, otherwise only the in-memory object changes and the test
        # does not actually exercise the independent on-disk replayer.
        if tamper:tamper(event,live,root)
        for sample in observations:
            p=ts if sample is live else dt.datetime.fromisoformat(sample["anchor_utc"])
            put(root/"slots"/slot_id(p),"snapshot.json",sample)
        put(root/"slots"/slot_id(ts),"signal.json",event)
        with (patch.object(v,"verify_signed",lambda *_:None),
              patch.object(v,"rederive",lambda _:{"pressure_factor_ready":True}),
              patch.object(v,"frozen_numerics",lambda _:numerical_test_fixture)):
            return v.run(tmp,"only-synthetic-unit",3)

def must_fail(mutation,label):
    try:scenario(mutation)
    except (RuntimeError,ValueError) as ex:
        print("NUMERIC_REPLAY_REJECTED",label,type(ex).__name__)
        return
    raise AssertionError("forged signed model state accepted "+label)

def run():
    clean=scenario()
    assert clean["latest_numerically_verified_published_states"]==1,clean
    assert clean["published_model_states_available"]==1
    must_fail(lambda event,*rest:event["diagnostic"].__setitem__(
        "alert",not event["diagnostic"]["alert"]),
        "signed claimed warning differs from genuine CUSUM")
    must_fail(lambda event,*rest:event["state"].__setitem__(
        "up_cusum",event["state"]["up_cusum"]+100.),
        "fabricated signed CUSUM evidence")
    must_fail(lambda event,*rest:event.__setitem__("reference_spot",84950.),
        "fabricated reference spot after source")
    must_fail(lambda event,*rest:event.__setitem__("registered_grid_sha256","0"*64),
        "wrong signed registered due grid")
    must_fail(lambda event,live,*rest:live["observation"].__setitem__(
        "15m_taker_buy_fraction",.99),
        "changed previously signed source referenced by the forecast")
    print("BTC_V7R5_CAUSAL_R4_SIGNED_STATE_REPLAY_SYNTHETIC_NEGATIVE_TESTS_PASS")

if __name__=="__main__":run()
