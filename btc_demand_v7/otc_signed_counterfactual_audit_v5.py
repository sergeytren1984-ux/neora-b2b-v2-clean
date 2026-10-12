"""Independent forward BTC OTC policy audit: only signed first-party R5 results.

Immutable pre-event policy SHA and original R5 signed source are checked by
GitHub runner BEFORE this program is allowed to consume any JSON. No trading
authority; Binance spot outcome is a hypothetical OTC execution proxy, not
an actual operator quote/partial-fill receipt.

Each eligible 15m due is counted even without forecast/outcome, so missing
inputs cannot vanish from the denominator. 4h signed minute raw must contain
first full future minute through +4h and be bound to signed forecast/outcome.
"""
from __future__ import annotations
import argparse,datetime as dt,hashlib,json,math,pathlib,random,statistics,subprocess
from btc_demand_v7.otc_prospective_policy_v5 import (
    MODEL_SHA,SCHEMA,commitment,compare_pair,digest,when,GUARDS,PREMIUMS)

UTC=dt.timezone.utc
STREAK_FLOOR_DAYS=20
BLOCK_BOOTSTRAPS=1000
SEED=51291
SOURCE_EPOCH_START=dt.datetime(2026,10,13,tzinfo=UTC)
SOURCE_EPOCH_END=dt.datetime(2026,10,20,tzinfo=UTC)
CURRENT_PRODUCER="d233d93baa02ee2b184bddb02afbd06d46cd9dce"
PRECOMMITTED_POLICY_SOURCE_BLOB="4b3302dd3c06a8c136c3ba12234aeecaddac960f"

def source_file(path):
    return json.loads(path.read_text())

def verify_immutable_policy(path):
    data=source_file(path)
    src=commitment()
    for k,v in src.items():
        if k in data and data[k]!=v:
            raise ValueError("frozen pre-event OTC strategy was retuned: "+k)
    if (data.get("policy_producer_sha")!=CURRENT_PRODUCER
        or data.get("registered_before_future_epoch_utc") is None
        or when(data["registered_before_future_epoch_utc"])>=SOURCE_EPOCH_START
        or data.get("source_precommitted") is not True):
        raise ValueError("not the original signed pre-event OTC policy")
    return data

def cosign(path):
    identity=("https://github.com/sergeytren1984-ux/neora-b2b-v2-clean/"
              ".github/workflows/btc-v7r3-signed-demand-shadow.yml"
              "@refs/heads/btc-v7r5-live-cadence-reliability-20261012")
    bundle=pathlib.Path(str(path)+".sigstore.json")
    if not path.is_file() or not bundle.is_file():
        raise RuntimeError("missing signed evidence or transparency bundle: "+str(path))
    result=subprocess.run(
        ["cosign","verify-blob",str(path),"--bundle",str(bundle),
         "--certificate-identity",identity,
         "--certificate-oidc-issuer","https://token.actions.githubusercontent.com"],
        capture_output=True,text=True,timeout=50)
    if result.returncode:
        raise RuntimeError("cannot verify signed R5 source: "+path.name+" "+result.stderr[-220:])
    proof=json.loads(bundle.read_text())
    if not any(x.get("inclusionProof") for x in proof["verificationMaterial"]["tlogEntries"]):
        raise RuntimeError("no Rekor inclusion proof "+path.name)

def block_ci_by_days(paired_gains,days,seed=SEED):
    keyed={}
    for value,date in zip(paired_gains,days):
        keyed.setdefault(date,[]).append(float(value))
    if len(keyed)<STREAK_FLOOR_DAYS:
        return None
    daily=[statistics.mean(v) for _,v in sorted(keyed.items())]
    rng=random.Random(seed)
    means=[statistics.mean(rng.choices(daily,k=len(daily)))
           for _ in range(BLOCK_BOOTSTRAPS)]
    means.sort()
    return [means[int(.025*BLOCK_BOOTSTRAPS)],
            means[int(.975*BLOCK_BOOTSTRAPS)]]

def run(ledger,policy_json,at,head=None,max_verify=None):
    checked_policy=verify_immutable_policy(pathlib.Path(policy_json))
    root=pathlib.Path(ledger)/"btc_v7r3_evidence"
    regpath=root/"registration.json"
    cosign(regpath)
    reg=source_file(regpath)
    if (reg["model_source_sha"]!=MODEL_SHA
        or len(reg.get("due_slots",[]))!=672
        or when(reg["start_utc"])!=SOURCE_EPOCH_START
        or when(reg["end_utc"])!=SOURCE_EPOCH_END):
        raise RuntimeError("source registration differs from pre-event OTC policy")
    due=0;warmup=0;missing=0;late=0;resolved=0;skipped=[]
    paired=[];rows=[]
    for ordinal,slot in enumerate(reg["due_slots"]):
        anchor=when(slot["anchor_utc"])
        # Last issuance + 4h + 35m, signed PRIOR to data existence.
        maturity=anchor+dt.timedelta(minutes=13+240+35)
        if at<maturity:continue
        due+=1
        if slot.get("first_32_signed_slots_are_warmup",False):
            warmup+=1
            continue
        sid=slot["slot_id"]
        base=root/"slots"/sid
        files=[base/(name+".json") for name in
               ("signal","delivery","raw_4h","outcome_4h")]
        if not all(x.is_file() for x in files):
            missing+=1;skipped.append({"slot":sid,"reason":"MISSING_SIGNED_FORECAST_OR_OUTCOME"})
            continue
        for path in files:
            cosign(path)
        event,delivery,raw,outcome=map(source_file,files)
        if event.get("slot_id")!=sid or event.get("status")!="SIGNED_STATE_PUBLISHED":
            missing+=1;skipped.append({"slot":sid,"reason":"NO_ELIGIBLE_PUBLISHED_MODEL_STATE"})
            continue
        if (outcome.get("slot_id")!=sid
            or outcome.get("horizon")!="4h"
            or outcome.get("source_signal_sha256")!=digest(event)
            or outcome.get("source_raw_sha256")!=digest(raw)
            or outcome.get("source_github_run_id")!=event.get("github_run_id")
            or when(outcome.get("public_delivery_utc"))!=when(delivery["public_delivery_utc"])):
            raise RuntimeError("counterfeit signed 4h outcome/source dependency")
        claimed_due=when(outcome["due_utc"])
        expected_delivery=when(delivery["public_delivery_utc"])
        # The target must be exactly 4h from the first full minute after
        # GitHub publication, NOT a mutable outcome-supplied future horizon.
        minute_zero=expected_delivery.replace(second=0,microsecond=0)
        if minute_zero<=expected_delivery:
            minute_zero+=dt.timedelta(minutes=1)
        expected_due=minute_zero+dt.timedelta(hours=4)
        if claimed_due!=expected_due:
            raise RuntimeError("4h outcome maturity was manipulated")
        if when(outcome["recorded_at_utc"])>expected_due+dt.timedelta(minutes=35):
            late+=1;continue
        if outcome.get("kind")!="OUTCOME_RECORDED":
            late+=1;continue
        if when(event["issued_at_utc"])>anchor+dt.timedelta(minutes=13):
            missing+=1;continue
        choice=compare_pair(event,delivery,raw)
        day=expected_delivery.date().isoformat()
        rows.append({"slot_id":sid,"day_utc":day,
                     "action":choice["precommitted_action"],
                     "public_spot":choice["public_reference_spot"],
                     "fill_buy1h_spot":choice["buy_now_execution_spot_after1h"],
                     "fill_wait2h_spot":choice["wait_execution_spot_after2h"],
                     "mark4h_spot":choice["terminal_spot_after4h"],
                     "scenarios":choice["scenarios"]})
        resolved+=1
    if max_verify is not None and due>max_verify:
        raise RuntimeError("partial score is not admissible as a full due grid")
    scenario_stats={}
    for guard in GUARDS:
        for premium in PREMIUMS:
            key=str(int(guard))+"_"+str(int(premium))
            vs_buy=[r["scenarios"][key]["policy_gain_vs_always_buy_usdt"] for r in rows]
            vs_wait=[r["scenarios"][key]["policy_gain_vs_always_wait_usdt"] for r in rows]
            dates=[r["day_utc"] for r in rows]
            ci_buy=block_ci_by_days(vs_buy,dates)
            ci_wait=block_ci_by_days(vs_wait,dates)
            scenario_stats[key]={
                "guard_usdt":guard,"premium_usdt":premium,
                "paired_outcomes":len(vs_buy),
                "model_policy_vs_buy_mean_usdt":(statistics.mean(vs_buy) if vs_buy else None),
                "model_policy_vs_wait_mean_usdt":(statistics.mean(vs_wait) if vs_wait else None),
                "positive_fraction_vs_buy":(sum(x>0 for x in vs_buy)/len(vs_buy) if vs_buy else None),
                "positive_fraction_vs_wait":(sum(x>0 for x in vs_wait)/len(vs_wait) if vs_wait else None),
                "blocked_daily_ci95_vs_buy":ci_buy,
                "blocked_daily_ci95_vs_wait":ci_wait,
                "robust_positive_lower_bound":
                    bool(ci_buy and ci_wait and ci_buy[0]>0 and ci_wait[0]>0),
                "actual_accepted_operator_quotes":0,
                "actual_partial_full_fills":0,
                "reality_of_OTC_execution_proven":False,
            }
    dates=sorted({r["day_utc"] for r in rows})
    asof=(at.isoformat() if at.tzinfo else None)
    return {
        "schema":"btc-v7r5-frozen-otc-paired-prospective-scorecard-v1",
        "scored_utc":asof,"frozen_policy_source_sha":CURRENT_PRODUCER,
        "registered_r5_source_sha":MODEL_SHA,
        "evidence_head_sha":head,
        "preregistered_15m_due_count":672,
        "4h_matured_total_due_grid":due,
        "explicit_warmup_due":warmup,
        "forecast_eligible_4h_matured_due":due-warmup,
        "forecast_or_outcome_missing":missing,
        "outcomes_late":late,"verified_fully_paired_4h":resolved,
        "distinct_utc_days":len(dates),
        "full_matured_grid_counted_even_when_missing":True,
        "published_only_at_original_signed_time":True,
        "current_USDT_budget_not_discarded_if_OTC_declines":True,
        "hypothetical_operator_guards_not_actual_quoted_deals":True,
        "scenarios":scenario_stats,
        "missing_examples":skipped[:15],
        "selection_bias_warning":"15m overlapping windows not independent; per-UTC-day block bootstrap",
        "requires_20_prospective_days":True,
        "requires_actual_operator_quotes_and_fills_for_trade_admission":True,
        "all_original_receipts_verified_with_cosign":True,
        "prospective_skill_proven":False,
        "trading_authority":False
    }

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--ledger",required=True)
    parser.add_argument("--precommitted-policy",required=True)
    parser.add_argument("--out",required=True)
    parser.add_argument("--evidence-head-sha",required=True)
    a=parser.parse_args()
    out=run(a.ledger,a.precommitted_policy,dt.datetime.now(UTC),a.evidence_head_sha)
    p=pathlib.Path(a.out);p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(out,sort_keys=True,indent=2,allow_nan=False)+"\n")
    print("BTC_V7R5_REAL_OTC_DUE_GRID_ECONOMIC_EVIDENCE",json.dumps({
        "eligible":out["forecast_eligible_4h_matured_due"],
        "resolved":out["verified_fully_paired_4h"],
        "missing":out["forecast_or_outcome_missing"],
        "late":out["outcomes_late"],
        "days":out["distinct_utc_days"],
        "trading_authority":False},sort_keys=True))

if __name__=="__main__":main()
