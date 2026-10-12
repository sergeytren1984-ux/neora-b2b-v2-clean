"""Point-in-time deployment of source-compatible spot-only v7 SHADOW model.

Never inject contemporaneous OKX OI/funding into offline-trained Binance OI
slots. OI/book remain explicit context, until same-source causal training exists.
"""
from __future__ import annotations
import argparse,datetime as dt,json,math,hashlib,pathlib,os
import numpy as np
from joblib import load
from btc_skill_rebuild.evaluate import features,build_arrays,STEP,UTC
from btc_skill_rebuild.evaluate_microstructure import micro_features
from btc_demand_v7.otc_decision import compare, prediction_target_times
from btc_demand_v7.live_snapshot import strict_closed, spot_state
from btc_demand_v7.release_guard import check as check_release

def issue(snapshot,model,paired,audit,now=None):
    if snapshot.get("schema")!="btc-v7-live-shadow-snapshot-v1":
        raise ValueError("untrusted live snapshot schema")
    if model.get("schema")!="btc-v7-candidate-not-production" or model.get("trading_authority") is not False:
        raise ValueError("model numerical/trading authority mismatch")
    if model.get("numeric_oi_input_authorized_on_github") is not False:
        raise ValueError("unexpected OI numerical input authorization")
    if audit.get("prospective_skill_proven") is not False:
        raise ValueError("shadow model must not claim proven skill")
    anchor=dt.datetime.fromisoformat(snapshot["anchor_utc"])
    received=dt.datetime.fromisoformat(snapshot["retrieved_at_utc"])
    issued=dt.datetime.now(UTC) if now is None else now
    if anchor.tzinfo is None or received.tzinfo is None or issued.tzinfo is None:raise ValueError("missing timezone")
    anchor=anchor.astimezone(UTC)
    received=received.astimezone(UTC)
    issued=issued.astimezone(UTC)
    if anchor.timestamp()%300!=0:
        raise ValueError("5m snapshot anchor not aligned")
    if not (anchor<=received<=issued) or (issued-anchor).total_seconds()>15*60:
        raise RuntimeError("snapshot anchor/receipt/issuance temporal contract violated")
    if snapshot.get("symbol")!="BTCUSDT" or snapshot.get("raw_source")!="Binance data-api closed 1m/5m":
        raise ValueError("wrong instrument or required source")
    anchor_ms=int(anchor.timestamp()*1000)
    one=strict_closed(snapshot["one_min_rows"],60000,anchor_ms,200)
    five=strict_closed(snapshot["five_min_rows"],300000,anchor_ms,600)
    if len(one)!=len(snapshot["one_min_rows"]) or len(five)!=len(snapshot["five_min_rows"]):
        raise ValueError("future/unclosed spot candle included")
    state=spot_state(one,anchor_ms)
    observation=snapshot.get("observation")
    if not isinstance(observation,dict):
        raise ValueError("missing independently reproducible observation")
    for field,expected in state.items():
        actual=float(observation.get(field,float("nan")))
        if not math.isfinite(actual) or not math.isclose(actual,expected,rel_tol=1e-11,abs_tol=1e-9):
            raise ValueError("signed spot observation inconsistent with raw: "+field)
    times,a=build_arrays(five)
    if len(times)<600:raise ValueError("insufficient 5m history")
    idx,base=features(times,a)
    m_idx,m_feat=micro_features(snapshot["one_min_rows"],times,idx)
    if not len(m_idx) or idx[m_idx[-1]]!=len(times)-1:
        raise ValueError("latest 1m and 5m anchors do not match")
    x=np.hstack([base[m_idx[-1]],m_feat[-1]]).reshape(1,-1)
    if not np.all(np.isfinite(x)):
        raise ValueError("nonfinite spot features before model prediction")
    if x.shape[1]!=model.get("spot_live_feature_count"):
        raise ValueError("feature schema does not match signed spot model")
    price=float(a[-1,3])
    preds={}
    for horizon,(fit,shrink) in model["spot_live_price_models"].items():
        ret=float(fit.predict(x)[0])*float(shrink)
        preds[horizon]=float(price*math.exp(ret))
    alert={}
    for label,bundle in model["spot_live_alert_models"].items():
        if bundle is None:
            alert[label]={"status":"NO_TRAINING_EVENTS"};continue
        fit,cal,threshold=bundle
        raw=float(np.clip(fit.predict_proba(x)[0,1],1e-6,1-1e-6))
        prob=float(cal.predict_proba([[math.log(raw/(1-raw))]])[0,1])
        scores=audit["spot_1m_only_deployable_shadow"]["event_metrics"].get(label,{})
        valid=(scores.get("passes_both") is True and
               (scores.get("alert_precision") or 0)>0 and
               (scores.get("recall_of_hourly_positive_windows") or 0)>0)
        alert[label]={"estimate":prob,"historical_validation_threshold":float(threshold),
                      "watch":bool(prob>=threshold) if valid else False,
                      "raw_threshold_crossed":bool(prob>=threshold),
                      "status":"EXPERIMENTAL_NOT_CALIBRATED_FOR_TRADING" if valid else "NOT_VALIDATED_NO_ACTIONABLE_WARNING"}
    # All action calculations use quote time, not the 5m anchor time.
    decision=compare(issued,preds,prediction_anchor=anchor,paired_errors=paired,demonstrated_price_skill=False)
    return {
        "schema":"btc-v7-frozen-shadow-inference-v1",
        "model_branch":"btc-predictive-vnext7-demand-price-otc-20261011",
        "trading_authority":False,"prospective_skill_proven":False,
        "reference_anchor_utc":anchor.isoformat(),
        "computed_at_utc":issued.isoformat(),
        "snapshot_age_seconds":(issued-anchor).total_seconds(),
        "spot":price,
        "price_point_forecasts":preds,
        "price_exact_target_utc":{k:v.isoformat() for k,v in prediction_target_times(anchor).items()},
        "price_test_mae":{h:audit["spot_1m_only_deployable_shadow"]["price_metrics"][h]["model_mae_usdt"] for h in preds},
        "forecast_target_offset_warning":"OTC price comparisons are invalidated unless exact forecast target_at matches each execution due timestamp.",
        "large_move_probabilities":alert,
        "spot_demand_watch":snapshot["observation"]["demand_watch"],
        "positioning_context":snapshot["observation"]["positioning_context"],
        "oi_not_used_numerically":True,
        "otc_comparison":decision,
        "operator_quote_is_executable":False,
        "no_auto_trade":True,
        "model_skill_status":"NOT_PROVEN_BASELINE_ONLY",
    }

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--snapshot",required=True)
    p.add_argument("--candidate",required=True)
    p.add_argument("--paired",required=True)
    p.add_argument("--audit",required=True)
    p.add_argument("--output",required=True)
    p.add_argument("--trusted-release",required=True)
    args=p.parse_args()
    # Before joblib.load (which is executable pickle!), bind EXACT loaded
    # file and path to signed release. Same-directory alternate files are NOT
    # authorized simply because a legitimate candidate.joblib also exists.
    candidate=pathlib.Path(args.candidate).resolve(strict=True)
    release_root=candidate.parent
    if candidate.name!="candidate.joblib" or candidate!=release_root.joinpath("candidate.joblib").resolve(strict=True):
        raise RuntimeError("untrusted alternative candidate filename")
    release=check_release(release_root,args.trusted_release)
    if hashlib.sha256(candidate.read_bytes()).hexdigest()!=release["model_sha256"]:
        raise RuntimeError("actual deserialized joblib hash differs from signed manifest")
    for path,key in ((args.audit,"audit_sha256"),(args.paired,"paired_sha256")):
        actual=hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()
        if release[key]!=actual:raise RuntimeError("forecast received mixed source: "+key)
    snapshot_raw=pathlib.Path(args.snapshot).read_bytes()
    snapshot=json.loads(snapshot_raw)
    model=load(candidate)
    errors=json.loads(pathlib.Path(args.paired).read_text())
    audit=json.loads(pathlib.Path(args.audit).read_text())
    result=issue(snapshot,model,errors,audit)
    result["evidence_binding"]={
        "snapshot_sha256":hashlib.sha256(snapshot_raw).hexdigest(),
        "model_sha256":release["model_sha256"],
        "audit_sha256":release["audit_sha256"],
        "paired_sha256":release["paired_sha256"],
        "training_source_commit_sha":release["source_commit_sha"],
        "training_source_run_id":release["source_run_id"],
        "trusted_release_manifest_sha256":release["release_manifest_sha256"],
        "inference_source_commit_sha":os.environ.get("GITHUB_SHA"),
        "inference_run_id":os.environ.get("GITHUB_RUN_ID"),
        "forecast_target_utc":result["price_exact_target_utc"],
    }
    out=pathlib.Path(args.output);out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+"\n")
    print("BTC_V7_SHADOW_PRICE_OTC",json.dumps({
        "anchor":result["reference_anchor_utc"],
        "computed":result["computed_at_utc"],
        "spot":result["spot"],
        "prices":result["price_point_forecasts"],
        "otc_status":result["otc_comparison"]["status"],
        "positioning":result["positioning_context"],
        "skill":result["model_skill_status"]},ensure_ascii=False),flush=True)

if __name__=="__main__":main()
