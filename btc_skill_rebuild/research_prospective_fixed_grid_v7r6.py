"""BTC v7R6 prospective research-only mathematical fixed-grid scorecard.

This module NEVER estimates new model weights or touches production. It
checks prepublished exact 1h/4h/24h ENDPOINT probabilities against outcomes
only after a later observed 5m source has closed. An empty/missing slot
remains in the due denominator; overlapping forecasts do not count as
independent events. Research began AFTER the frozen R5 epoch: its observed
first forecast cannot be misrepresented as a preregistered start.
"""
from __future__ import annotations
import datetime as dt,json,math,pathlib,statistics,sys

UTC=dt.timezone.utc
FROZEN_R5_EPOCH=dt.datetime(2026,10,13,tzinfo=UTC)
FIRST_OBSERVED_RESEARCH_SLOT=dt.datetime(2026,10,13,4,45,tzinfo=UTC)
FROZEN_R5_END=FROZEN_R5_EPOCH+dt.timedelta(days=7)
DURATIONS={"1h":60,"4h":240,"24h":1440}
THRESHOLDS={"1h":0.007,"4h":0.012,"24h":0.02}
DUE_CADENCE=dt.timedelta(minutes=15)

def utc(s):
    t=dt.datetime.fromisoformat(s.replace("Z","+00:00"))
    if t.tzinfo is None:raise ValueError("UTC offset required")
    return t.astimezone(UTC)

def brier(p,truth):
    if set(p)!={"UP","DOWN","RANGE"}:raise ValueError("not three classes")
    values=[float(p[k]) for k in ("UP","DOWN","RANGE")]
    if not all(math.isfinite(x) and 0<=x<=1 for x in values) or abs(sum(values)-1)>1e-9:
        raise ValueError("not valid probabilities")
    if truth not in p:raise ValueError("invalid true class")
    return sum((v-(k==truth))**2 for k,v in zip(("UP","DOWN","RANGE"),values))/3

def convert_original_one_hour_score(doc):
    """Source is existing 1h own-slot JSON, never retrospectively rewritten."""
    m=doc["original_public_research_forecast"]
    x=doc["endpoint_1h"]
    obs=doc["target_outcome_evidence"]
    if doc.get("trading_authority") is not False or m.get("signed_frozen_R6_model_forecast") is not False:
        raise ValueError("not a research-only original score")
    if obs.get("no_backfill") is not True or obs.get("cryptographic_Cosign_verification_performed") is not False:
        raise ValueError("provenance must not be exaggerated")
    return {
        "slot_utc":x["forecast_slot_utc"],"horizon":"1h",
        "published_utc":m["original_public_commit_time_utc"],
        "target_utc":x["precommitted_target_utc"],
        "source_original_forecast_sha":m["git_blob_sha1"],
        "source_original_forecast_commit":m["original_public_commit_sha"],
        "future_snapshot_sha":obs["R5_snapshot_git_blob_sha1"],
        "future_snapshot_anchor_utc":obs["R5_snapshot_anchor_utc"],
        "actual_class":x["actual_class"],
        "original_probabilities":x["precommitted_probabilities"],
        "original_frozen_prior":x["frozen_train_prior_probabilities"],
        "original_threshold":x["threshold_fraction"],
        "original_reference_spot_usdt":x["reference_spot_usdt"],
        "actual_closed_5m_spot_usdt":obs["exact_target_closed_5m_price_usdt"],
        "original_model_brier":x["strict_three_way_brier_divided_by_3"],
        "original_prior_brier":x["strict_three_way_train_prior_brier_divided_by_3"],
        "source_cosign_verified":False
    }

def validate_record(r,asof):
    h=r["horizon"]
    if h not in DURATIONS:raise ValueError("unsupported horizon")
    slot=utc(r["slot_utc"]);pub=utc(r["published_utc"])
    target=utc(r["target_utc"]);future=utc(r["future_snapshot_anchor_utc"])
    if slot<FROZEN_R5_EPOCH or slot>=FROZEN_R5_END or slot.minute%15:
        raise ValueError("invalid frozen 15m slot")
    if not slot<=pub<=slot+dt.timedelta(minutes=13) or pub>=target:
        raise ValueError("late or post-outcome forecast")
    if target!=slot+dt.timedelta(minutes=DURATIONS[h]):
        raise ValueError("post-hoc horizon shift")
    if not target<=future<=asof:raise ValueError("unmatured or future 5m price")
    if float(r["original_threshold"])!=THRESHOLDS[h]:
        raise ValueError("post-hoc threshold")
    price=float(r["original_reference_spot_usdt"])
    actual=float(r["actual_closed_5m_spot_usdt"])
    if not math.isfinite(price) or not math.isfinite(actual) or min(price,actual)<=0:
        raise ValueError("invalid reference or outcome spot")
    movement=(actual/price-1)
    label="UP" if movement>THRESHOLDS[h] else "DOWN" if movement<-THRESHOLDS[h] else "RANGE"
    if label!=r["actual_class"]:raise ValueError("changed outcome class")
    bmodel=brier(r["original_probabilities"],label)
    bprior=brier(r["original_frozen_prior"],label)
    if (abs(bmodel-float(r["original_model_brier"]))>1e-11
        or abs(bprior-float(r["original_prior_brier"]))>1e-11):
        raise ValueError("altered original proper Brier")
    if not r.get("source_original_forecast_sha") or not r.get("future_snapshot_sha"):
        raise ValueError("missing source identity")
    return bprior-bmodel

def anchors(start,end):
    if end<start:return []
    n=int((end-start).total_seconds()//900)
    return [start+i*DUE_CADENCE for i in range(n+1)]

def audit(records,asof_snapshot_anchor):
    asof=utc(asof_snapshot_anchor)
    if asof<FIRST_OBSERVED_RESEARCH_SLOT:raise ValueError("not live research")
    if asof>dt.datetime.now(UTC)+dt.timedelta(minutes=5):
        raise ValueError("future cutoff")
    accepted={}
    for r in records:
        gain=validate_record(r,asof)
        key=(r["horizon"],utc(r["slot_utc"]))
        if key in accepted:raise ValueError("duplicate scored slot")
        accepted[key]=(r,gain)
    result={}
    for h,duration in DURATIONS.items():
        maturity=dt.timedelta(minutes=duration)
        full_grid=anchors(FROZEN_R5_EPOCH,min(asof-maturity,FROZEN_R5_END-DUE_CADENCE))
        research_grid=[a for a in full_grid if a>=FIRST_OBSERVED_RESEARCH_SLOT]
        nonoverlap=[a for a in research_grid
                    if int((a-FROZEN_R5_EPOCH).total_seconds()/60)%duration==0]
        all_hits=[(a,*accepted[(h,a)]) for a in research_grid if (h,a) in accepted]
        independent_hits=[(a,*accepted[(h,a)]) for a in nonoverlap if (h,a) in accepted]
        all_gains=[x[2] for x in all_hits]
        independent_gains=[x[2] for x in independent_hits]
        days={a.date().isoformat() for a,_,_ in independent_hits}
        independent_directional=sum(r["actual_class"] in ("UP","DOWN") for _,r,_ in independent_hits)
        result[h]={
            "duration_minutes":duration,
            "frozen_R5_epoch_due_grid_matured_slots":len(full_grid),
            "research_only_observed_start_matured_due_slots":len(research_grid),
            "research_only_forecasts_with_valid_matured_outcomes":len(all_hits),
            "research_only_missing_slots_not_removed":len(research_grid)-len(all_hits),
            "UTC_midnight_anchored_nonoverlap_due":len(nonoverlap),
            "UTC_midnight_anchored_nonoverlap_resolved":len(independent_hits),
            "UTC_midnight_anchored_nonoverlap_missing":len(nonoverlap)-len(independent_hits),
            "nonoverlap_independent_UTC_days_with_resolved_forecast":len(days),
            "nonoverlap_directional_endpoint_labels_not_independent_events":independent_directional,
            "unique_first_touch_events":None,
            "mean_paired_Brier_gain_all_overlapping":statistics.mean(all_gains) if all_gains else None,
            "mean_paired_Brier_gain_nonoverlap":statistics.mean(independent_gains) if independent_gains else None,
            "confidence_interval_nonoverlap_by_independent_day":None,
            "positive_skill_statistically_proven":False,
            "nonoverlap_resolved_slots":[a.isoformat() for a,_,_ in independent_hits],
            "nonoverlap_missing_slots":[a.isoformat() for a in nonoverlap if (h,a) not in accepted]
        }
    return {
        "schema":"btc-v7r6-fixed-UTC-nonoverlap-prospective-math-audit-v1",
        "asof_later_R5_snapshot_anchor_utc":asof.isoformat(),
        "R5_frozen_epoch_start_utc":FROZEN_R5_EPOCH.isoformat(),
        "research_first_observed_slot_utc":FIRST_OBSERVED_RESEARCH_SLOT.isoformat(),
        "research_first_observed_start_is_NOT_preregistered":True,
        "research_15m_missing_slots_retained":True,
        "UTC_midnight_nonoverlap_origin_prevents_choice_after_outcome":True,
        "only_public_research_not_signed_R6":True,
        "source_Cosign_cryptography_not_independently_verified":True,
        "actual_firm_OTC_quotes":0,"actual_operator_fills":0,
        "minimum_independent_prospective_days_required":20,
        "trading_authority":False,
        "horizons":result}

def main():
    if len(sys.argv)<4:
        raise SystemExit("usage: python research_prospective_fixed_grid_v7r6.py <asof UTC> <out.json> <original_1h_score.json>...")
    cutoff=sys.argv[1];out=pathlib.Path(sys.argv[2])
    scores=[convert_original_one_hour_score(json.loads(pathlib.Path(x).read_text())) for x in sys.argv[3:]]
    result=audit(scores,cutoff)
    out.write_text(json.dumps(result,indent=2,sort_keys=True,allow_nan=False)+"\n")
    for h,v in result["horizons"].items():
        print("MATHEMATICAL_PROSPECTIVE_FIXED_GRID",h,
              "matured_due",v["research_only_observed_start_matured_due_slots"],
              "resolved",v["research_only_forecasts_with_valid_matured_outcomes"],
              "nonoverlap",v["UTC_midnight_anchored_nonoverlap_resolved"],
              "trading_authority",False)

if __name__=="__main__":main()
