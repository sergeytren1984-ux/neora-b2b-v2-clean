"""Test immutable TRAIN benchmark, fixed-phase windows, paired day uncertainty."""
import json,datetime as dt
from btc_demand_v7.skill_metrics import fixed_phase,day_block_ci,prospective_skill
from btc_demand_v7.prospective_core import registered_grid
UTC=dt.timezone.utc

def test():
    s=dt.datetime(2026,10,13,tzinfo=UTC)
    assert fixed_phase(s,"1h")
    assert not fixed_phase(s+dt.timedelta(minutes=15),"1h")
    assert fixed_phase(s,"4h")
    assert not fixed_phase(s+dt.timedelta(hours=1),"4h")
    assert fixed_phase(s,"24h") and fixed_phase(s,"morning_08msk")
    assert not fixed_phase(s+dt.timedelta(hours=4),"24h")
    r=[{"slot_utc":(s+dt.timedelta(days=i)).isoformat(),
        "baseline_abs_error":100.,"model_abs_error":80.} for i in range(20)]
    ci=day_block_ci(r)
    assert ci["model_beats_persistence_at_95pct"] is True
    assert ci["lower_95_mae_gain_usdt"]==20
    assert day_block_ci(r[:10]) is None
    with open("btc_demand_v7/frozen_train_priors.json") as f:priors=json.load(f)
    frozen=registered_grid(s,days=1,
        source_sha="a"*40,created_at=s-dt.timedelta(hours=3),
        source_ref="refs/heads/btc-v7r2-prospective-contour-20261012")
    report=prospective_skill(frozen,[],[],[],priors)
    assert report["trading_authority"] is False
    assert report["first_passage"]["1h"]["frozen_train_first_passage_prior"]["UP_FIRST"]==priors["event_priors"]["1h"]["p_up_first_train"]
    assert report["first_passage"]["1h"]["n_fixed_phase_independent_windows"]==0
    print("BTC_V7R2_TRAIN_PRIOR_NO_ORACLE_FIXED_PHASE_DAY_BOOTSTRAP_PASS")
if __name__=="__main__":test()
