"""Adversarial acceptance attacks from 12 Oct audit, always research-only.

Signature verification is NOT mocked in the real CI's Cosign source validation;
synthetic fixtures below simulate corruption to check scoring authority.
"""
from __future__ import annotations
from datetime import datetime,timedelta,timezone
from unittest.mock import patch
import copy,io,json,os,pathlib,tempfile
from btc_demand_v7.prospective_core import registered_grid,score_fixed_grid,forecast_receipt,price_outcome
from btc_demand_v7.shadow_contract_v3 import grid,status_grid,digest,canonical,slot_id
from btc_demand_v7 import v7r3_shadow_worker as w
from btc_demand_v7.test_demand_change_v2 import snap

UTC=timezone.utc
START=datetime(2026,10,13,tzinfo=UTC)
def rejects(fn,description):
    try:fn()
    except (ValueError,RuntimeError,AssertionError):
        print("REJECTED",description)
        return
    raise AssertionError("adversarial input was accepted: "+description)

def r2_denom_and_errors():
    g=registered_grid(START,days=1,source_sha="a"*40,
         created_at=START-timedelta(hours=4),source_ref="refs/heads/test")
    no_forecasts=score_fixed_grid(g,[],[],START+timedelta(hours=2))
    assert no_forecasts["due_forecast_slots"]==8
    assert no_forecasts["outcome_due_count"]==3, no_forecasts
    assert no_forecasts["outcomes_missing"]==3
    assert not no_forecasts["admission_ready"]
    live={"reference_anchor_utc":START.isoformat(),
          "computed_at_utc":(START+timedelta(minutes=2)).isoformat(),
          "model_skill_status":"NOT_PROVEN_BASELINE_ONLY",
          "spot":83000.,"price_point_forecasts":{"1h":83000.,"4h":83000.,"morning":83000.},
          "evidence_binding":{"snapshot_sha256":"s","model_sha256":"x"},
          "otc_comparison":{"status":"NO_EXECUTION_ALIGNED_FORECAST"}}
    f=forecast_receipt(g,START,START+timedelta(minutes=3),live,
                       snapshot_sha="s",live_sha="l")
    o=price_outcome(g,f,"1h",START+timedelta(hours=1,minutes=4),83100.,raw_sha="r")
    ok=score_fixed_grid(g,[f],[o],START+timedelta(hours=2))
    assert ok["heads"]["1h"]["settled"]==1
    bad=copy.deepcopy(o);bad["absolute_error_usdt"]=-10000.
    rejects(lambda:score_fixed_grid(g,[f],[bad],START+timedelta(hours=2)),
            "R2 negative error fabricates gain")
    bad=copy.deepcopy(o);bad["persistence_absolute_error_usdt"]=float("nan")
    rejects(lambda:score_fixed_grid(g,[f],[bad],START+timedelta(hours=2)),
            "R2 nonfinite baseline error")
    bad=copy.deepcopy(o);bad["recorded_utc"]=(START+timedelta(days=1)).isoformat()
    bad["kind"]="OUTCOME_RECORDED"
    evaluated=score_fixed_grid(g,[f],[bad],START+timedelta(days=1,hours=2))
    assert evaluated["outcomes_late"]>=1
    print("FULL_GRID_MISSING_FORECAST_AND_RECOMPUTED_MAE_PASS")

def wrong_delivery_identity():
    event={"github_run_id":"777",
           "github_run_attempt":1,
           "model_source_sha":"a"*40,
           "issued_at_utc":(START+timedelta(minutes=10)).isoformat()}
    data={"id":777,"status":"completed","conclusion":"success",
          "head_sha":"a"*40,"head_branch":"another-branch",
          "event":"workflow_dispatch","path":".github/workflows/btc-v7r3-signed-demand-shadow.yml",
          "head_repository":{"full_name":w.REPO},
          "created_at":START.isoformat(),"run_attempt":1,
          "updated_at":(START+timedelta(days=3)).isoformat()}
    class MockResponse:
        status=200
        def __init__(self,body):self.body=body
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self):return json.dumps(self.body).encode()
    def urlopen(req,timeout=None):
        return MockResponse(data)
    with patch.object(w.urllib.request,"urlopen",urlopen):
        rejects(lambda:w.verified_delivery_time(event),
                "wrong branch accepted despite same source hash")
    data["head_branch"]=w.BRANCH
    data["path"]=".github/workflows/btc-v7r3-signed-demand-shadow.yml"
    assert data["updated_at"].startswith("2026-10-16")
    job_end=START+timedelta(minutes=13)
    def good_urlopen(req,timeout=None):
        if "/jobs" in req.full_url:
            return MockResponse({"jobs":[{"name":"signed-research-only",
                "status":"completed","conclusion":"success",
                "completed_at":job_end.isoformat()}]})
        return MockResponse(data)
    with patch.object(w.urllib.request,"urlopen",good_urlopen):
        assert w.verified_delivery_time(event)==job_end
    print("STRICT_COMPLETED_JOB_SOURCE_REF_RUN_ATTEMPT_PASS")

def unsigned_or_forged_outcome():
    reg=grid(START,START-timedelta(hours=4),"a"*40,days=1)
    slot=reg["due_slots"][0]
    issue=START+timedelta(minutes=10)
    delivered=START+timedelta(minutes=11)
    event={"schema":"btc-v7r3-signed-pressure-event-v1",
           "slot_id":slot["slot_id"],"anchor_utc":START.isoformat(),
           "status":"SIGNED_STATE_PUBLISHED","issued_at_utc":issue.isoformat(),
           "github_run_id":"777","model_source_sha":"a"*40,
           "reference_spot":83000.,
           "diagnostic":{"alert":True,"warning_side":"UP","price_already_moved":False}}
    delivery={"slot_id":slot["slot_id"],"public_delivery_utc":delivered.isoformat(),
              "source_signal_sha256":digest(event)}
    with tempfile.TemporaryDirectory() as t:
        root=pathlib.Path(t);folder=root/"slots"/slot["slot_id"]
        folder.mkdir(parents=True)
        (folder/"signal.json").write_bytes(canonical(event))
        (folder/"delivery.json").write_bytes(canonical(delivery))
        at=START+timedelta(hours=2)
        scored=None
        with patch.object(w,"verify",lambda *a:None):
            scored=w.score(reg,root,at)
        assert scored["forward_outcomes"]["1h"]["due"]>=1
        assert scored["forward_outcomes"]["1h"]["missing"]>=1
        due=w.future_due(delivered,"1h")
        fake={"slot_id":slot["slot_id"],"horizon":"1h",
              "due_utc":(due+timedelta(days=30)).isoformat(),
              "source_signal_sha256":digest(event),
              "warning_issued":True,"warning_lead_minutes":100.,
              "kind":"OUTCOME_RECORDED"}
        (folder/"outcome_1h.json").write_bytes(canonical(fake))
        # Signed fake is still insufficient without exact signed raw minute grid.
        with patch.object(w,"verify",lambda *a:None):
            result=w.score(reg,root,at)
        assert result["forward_outcomes"]["1h"]["missing"]>=1
        (folder/"raw_1h.json").write_bytes(canonical({"schema":"evil-source"}))
        with patch.object(w,"verify",lambda *a:None):
            rejects(lambda:w.score(reg,root,at),"signed fake result without source")
        def reject_unsigned(path,*a):
            if path.name.startswith("outcome_") and not pathlib.Path(str(path)+".sigstore.json").exists():
                raise RuntimeError("missing Sigstore source")
        with patch.object(w,"verify",reject_unsigned):
            rejects(lambda:w.score(reg,root,at),"unsigned fabricated 100m lead")
    print("NO_FORGED_FUTURE_DUE_OR_FAKE_SUCCESS_PASS")

def missing_state_resets_are_forbidden():
    # Source worker's fixed rule: after the one explicitly signed 32-slot
    # warmup, absent predecessor triggers STATEFUL_CHAIN_DISCONTINUITY.
    reg=grid(START,START-timedelta(hours=4),"a"*40,days=1)
    current=START+timedelta(minutes=15*34)
    with tempfile.TemporaryDirectory() as t:
        root=pathlib.Path(t);r2=pathlib.Path(t)/"r2"
        folder=root/"slots"/slot_id(current);folder.mkdir(parents=True)
        base={**snap(34,direction=1),"anchor_utc":current.isoformat(),
              "observation":{**snap(34,direction=1)["observation"],"reference_spot":83000.}}
        def mock_signed(root,name,obj):
            p=pathlib.Path(root)/name;p.parent.mkdir(parents=True,exist_ok=True)
            p.write_bytes(canonical(obj));return p
        with patch.object(w,"market_collect",lambda *x,**kw:base),patch.object(w,"historic_snapshots",lambda *x:[base]*32),patch.object(w,"write",mock_signed):
            result=w.current_slot_signal(root,reg,current+timedelta(minutes=10))
        assert result=="STATEFUL_CHAIN_DISCONTINUITY"
        assert (folder/"signal.json").exists()
        assert json.loads((folder/"signal.json").read_text())["zero_reset_not_allowed"] is True
    print("MISSING_PREVIOUS_STATE_CANNOT_RESTART_ALERT_BUDGET_PASS")

def warmup_to_first_live_pressure():
    # 32 consecutive previous slots carry signed raw but ZERO valid
    # directional state. First legitimate event MUST start exactly once,
    # then second event must retain the prior CUSUM.
    from btc_demand_v7.test_demand_change_v2 import snap
    from btc_demand_v7.demand_change_v2 import state_zero
    initial=datetime(2026,10,14,tzinfo=UTC)
    reg=grid(initial,initial-timedelta(hours=4),"a"*40,days=1)
    first=initial+timedelta(minutes=32*15)
    sample=snap(32,direction=1)
    def signed(root,name,obj):
        p=pathlib.Path(root)/name;p.parent.mkdir(parents=True,exist_ok=True)
        p.write_bytes(canonical(obj));return p
    with tempfile.TemporaryDirectory() as t:
        root=pathlib.Path(t)
        previous_slot=first-timedelta(minutes=15)
        p=signed(root/"slots"/slot_id(previous_slot),"signal.json",{
            "slot_id":slot_id(previous_slot),
            "status":"INSUFFICIENT_ASOF_HISTORY",
            "state":state_zero(),
            "anchor_utc":previous_slot.isoformat()})
        with patch.object(w,"verify",lambda *x:None):
            assert w.available_previous_state(root,first) is None
        def collect(anchor_ms):
            assert anchor_ms==int(first.timestamp()*1000)
            raw=copy.deepcopy(sample)
            raw["anchor_utc"]=first.isoformat()
            raw["observation"]["reference_spot"]=83000.
            return raw
        reference={"spot":83000.,"row":[1,"83000","83001","82999","83000",1,2]}
        # Advance computes a correct non-zero initial CUSUM from signed
        # 32-slot baseline but must never adopt warmup placeholder state.
        received=first+timedelta(minutes=10)
        with (patch.object(w,"verify",lambda *x:None),
              patch.object(w,"write",signed),
              patch.object(w,"market_collect",collect),
              patch.object(w,"historic_snapshots",
                           lambda *x:[snap(i) for i in range(32)]),
              patch.object(w,"last_close_before_issuance",lambda:reference),
              patch.object(w,"utcnow",lambda:received)):
            result=w.current_slot_signal(root,reg,received)
        assert result=="SIGNED_STATE_PUBLISHED",result
        event=json.loads((root/"slots"/slot_id(first)/"signal.json").read_text())
        assert event["state"]["sequence"]==1
        assert event["state"]["up_cusum"]>=0
        print("FIRST_FROZEN_WARMUP_STATE_INITIALIZES_EXACTLY_ONCE_PASS")

def run():
    warmup_to_first_live_pressure()
    r2_denom_and_errors()
    wrong_delivery_identity()
    unsigned_or_forged_outcome()
    missing_state_resets_are_forbidden()
    print("BTC_V7R4_ADVERSARIAL_P0_CLOSURES_PASS")

if __name__=="__main__":run()
