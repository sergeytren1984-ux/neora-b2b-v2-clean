"""Negative test of future 4h signed-source OTC wealth evaluator and full due grid."""
import datetime as dt,copy,json,pathlib,tempfile
from unittest.mock import patch
from btc_demand_v7.otc_signed_counterfactual_audit_v5 import run,MODEL_SHA,CURRENT_PRODUCER
from btc_demand_v7.otc_prospective_policy_v5 import commitment,digest
from btc_demand_v7.test_otc_prospective_policy_v5 import setup,source_minutes

UTC=dt.timezone.utc
START=dt.datetime(2026,10,13,tzinfo=UTC)
def put(p,obj):
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(obj,sort_keys=True,allow_nan=False,separators=(",",":"))+"\n")

def scenario(mutator=None,missing=False):
    with tempfile.TemporaryDirectory() as tmp:
        root=pathlib.Path(tmp)
        policy=commitment()
        policy.update(policy_producer_sha=CURRENT_PRODUCER,
                      registered_before_future_epoch_utc=(START-dt.timedelta(hours=2)).isoformat(),
                      source_precommitted=True)
        pre=root/"policy.json";put(pre,policy)
        grid=[]
        for index in range(672):
            anchor=START+dt.timedelta(minutes=index*15)
            grid.append({"slot_id":anchor.strftime("%Y%m%dT%H%M%SZ"),
                         "anchor_utc":anchor.isoformat(),
                         "first_32_signed_slots_are_warmup":index<32})
        base=root/"ledger"/"btc_v7r3_evidence"
        put(base/"registration.json",{
            "model_source_sha":MODEL_SHA,"start_utc":START.isoformat(),
            "end_utc":(START+dt.timedelta(days=7)).isoformat(),
            "due_slots":grid})
        event,delivery,raw=setup("UP")
        target=dt.datetime(2026,10,14,12,tzinfo=UTC)
        folder=base/"slots"/target.strftime("%Y%m%dT%H%M%SZ")
        public=dt.datetime.fromisoformat(delivery["public_delivery_utc"])
        end=public.replace(second=0,microsecond=0)+dt.timedelta(minutes=1,hours=4)
        outcome={"kind":"OUTCOME_RECORDED",
                 "slot_id":event["slot_id"],
                 "horizon":"4h",
                 "source_signal_sha256":digest(event),
                 "source_raw_sha256":digest(raw),
                 "source_github_run_id":event.get("github_run_id"),
                 "public_delivery_utc":delivery["public_delivery_utc"],
                 "due_utc":end.isoformat(),
                 "recorded_at_utc":(end+dt.timedelta(minutes=12)).isoformat()}
        if mutator:mutator(event,delivery,raw,outcome)
        if not missing:
            for name,payload in (("signal",event),("delivery",delivery),
                                 ("raw_4h",raw),("outcome_4h",outcome)):
                put(folder/(name+".json"),payload)
        with patch("btc_demand_v7.otc_signed_counterfactual_audit_v5.cosign",
                   lambda *_:None):
            return run(root/"ledger",pre,dt.datetime(2026,10,15,8,tzinfo=UTC),
                       head="fake-synthetic-evidence-head")

def rejects(mutation,label):
    try:scenario(mutation)
    except (RuntimeError,ValueError) as e:
        print("REJECTED_OTC_FUTURE_MANIPULATION",label,type(e).__name__)
        return
    raise AssertionError("forged prospective OTC outcome accepted "+label)

def test():
    value=scenario()
    assert value["preregistered_15m_due_count"]==672
    assert value["4h_matured_total_due_grid"]>100
    assert value["verified_fully_paired_4h"]==1
    assert value["forecast_or_outcome_missing"]>0
    assert value["scenarios"]["300_300"]["paired_outcomes"]==1
    assert value["scenarios"]["300_300"]["actual_accepted_operator_quotes"]==0
    assert value["scenarios"]["300_300"]["blocked_daily_ci95_vs_buy"] is None
    assert value["trading_authority"] is False
    no= scenario(missing=True)
    assert no["verified_fully_paired_4h"]==0
    assert no["forecast_or_outcome_missing"]>=value["forecast_or_outcome_missing"]+1
    rejects(lambda e,d,r,o:o.__setitem__("source_raw_sha256","0"*64),
            "substituted exact future-minute raw")
    rejects(lambda e,d,r,o:o.__setitem__("due_utc",(START+dt.timedelta(days=100)).isoformat()),
            "backdated signed target shifted 100 days to hide failure")
    rejects(lambda e,d,r,o:d.__setitem__("source_signal_sha256","0"*64),
            "signed delivery detached from signed decision")
    rejects(lambda e,d,r,o:e.__setitem__("model_source_sha","0"*40),
            "model source drift")
    print("BTC_V7R5_OTC_FUTURE_CASHFLOW_EVALUATOR_STRICT_ALL_DUE_AND_NEGATIVE_TESTS_PASS")

if __name__=="__main__":test()
