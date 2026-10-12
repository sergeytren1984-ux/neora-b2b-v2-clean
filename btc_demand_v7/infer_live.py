"""Point-in-time deployment of source-compatible spot-only v7 SHADOW model.

Never inject contemporaneous OKX OI/funding into offline-trained Binance OI
slots. OI/book remain explicit context, until same-source causal training exists.
"""
from __future__ import annotations
import argparse,datetime as dt,json,math,hashlib,pathlib
import numpy as np
from joblib import load
from btc_skill_rebuild.evaluate import features,build_arrays,STEP,UTC
from btc_skill_rebuild.evaluate_microstructure import micro_features
from btc_demand_v7.otc_decision import compare

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
    if (issued-anchor).total_seconds()<0 or (issued-anchor).total_seconds()>15*60:
        raise RuntimeError("snapshot exceeds 15-minute active window; no live forecast")
    if received>issued:raise RuntimeError("future snapshot receipt")
    times,a=build_arrays(snapshot["five_min_rows"])
    if len(times)<600:raise ValueError("insufficient 5m history")
    idx,base=features(times,a)
    m_idx,m_feat=micro_features(snapshot["one_min_rows"],times,idx)
    if not len(m_idx) or idx[m_idx[-1]]!=len(times)-1:
        raise ValueError("latest 1m and 5m anchors do not match")
    x=np.hstack([base[m_idx[-1]],m_feat[-1]]).reshape(1,-1)
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
        alert[label]={"estimate":prob,"historical_validation_threshold":float(threshold),
                      "watch":bool(prob>=threshold),
                      "status":"EXPERIMENTAL_NOT_CALIBRATED_FOR_TRADING"}
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
        "price_test_mae":{h:audit["spot_1m_only_deployable_shadow"]["price_metrics"][h]["model_mae_usdt"] for h in preds},
        "forecast_target_offset_warning":"OTC price comparisons are invalidated unless exact forecast target_at matches each execution due timestamp.",
        "large_move_probabilities":alert,
        "spot_demand_watch":snapshot["observation"]["demand_watch"],
        "positioning_context":snapshot["observation"]["positioning_context"],
        "oi_not_used_numerically":True,
        "otc_comparison":decision,
        "operator_quote_is_executable":False,
        "no_auto_trade":True,
        "model_skill_status":"NOT_PROVEN",
    }

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--snapshot",required=True)
    p.add_argument("--candidate",required=True)
    p.add_argument("--paired",required=True)
    p.add_argument("--audit",required=True)
    p.add_argument("--output",required=True)
    args=p.parse_args()
    snapshot=json.loads(pathlib.Path(args.snapshot).read_text())
    model=load(args.candidate)
    errors=json.loads(pathlib.Path(args.paired).read_text())
    audit=json.loads(pathlib.Path(args.audit).read_text())
    result=issue(snapshot,model,errors,audit)
    out=pathlib.Path(args.output);out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2)+"\n")
    print("BTC_V7_SHADOW_PRICE_OTC",json.dumps({
        "anchor":result["reference_anchor_utc"],
        "computed":result["computed_at_utc"],
        "spot":result["spot"],
        "prices":result["price_point_forecasts"],
        "otc_status":result["otc_comparison"]["status"],
        "positioning":result["positioning_context"],
        "skill":result["model_skill_status"]},ensure_ascii=False),flush=True)

if __name__=="__main__":main()
