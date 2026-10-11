"""Single BTC demand/price/OTC numerical challenger; strictly RESEARCH ONLY.

Frozen pre-split data. No lookahead, labels from future closed candles, no
automatic relabeling. Historical Binance futures snapshots have uncertain
publication timing and MUST NOT be treated as signed prospective truth.
"""
from __future__ import annotations
import argparse,datetime as dt,gzip,hashlib,json,math,pathlib
import numpy as np
from joblib import dump
from sklearn.ensemble import HistGradientBoostingRegressor,HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from btc_skill_rebuild.evaluate import (
 UTC,STEP,SEED,VAL_START,TEST_START,END,features,build_arrays,build_targets,
 classification_metrics,regression_metrics,future_morning_bars
)
from btc_skill_rebuild.evaluate_microstructure import micro_features
from btc_skill_rebuild.evaluate_derivatives import aligned_derivatives
from btc_demand_v7.otc_decision import compare

BARS_PER_HOUR=12
PRICE_TARGETS={"1h":12,"2h":24,"4h":48,"5h":60,"morning":None,"morning_plus_1h":None}
EVENT_TARGETS={"up_30m":(6,.0045,1),"down_30m":(6,.0045,-1),
               "up_1h":(12,.007,1),"down_1h":(12,.007,-1),
               "up_4h":(48,.012,1),"down_4h":(48,.012,-1)}

def read_gzip_json(path):
    with gzip.open(path,"rt") as f:return json.load(f)

def label_arrays(times,a,idx):
    last=len(times);c=a[:,3];high=a[:,1];low=a[:,2]
    out={}
    for name,step in PRICE_TARGETS.items():
        if step is None:
            steps=np.asarray([future_morning_bars(times[i])+(12 if name=="morning_plus_1h" else 0) for i in idx],dtype=int)
        else:
            steps=np.full(len(idx),step,dtype=int)
        y=np.full(len(idx),np.nan)
        ok=(idx+steps<last)
        y[ok]=np.log(c[idx[ok]+steps[ok]]/c[idx[ok]])
        out[name]=y
    for name,(h,threshold,sign) in EVENT_TARGETS.items():
        y=np.full(len(idx),np.nan)
        for j,i in enumerate(idx):
            if i+h>=last:continue
            future_up=max(high[i+1:i+h+1])/c[i]-1
            future_down=min(low[i+1:i+h+1])/c[i]-1
            y[j]=float(future_up>=threshold) if sign==1 else float(future_down<=-threshold)
        out[name]=y
    return out

def splits(anchors):
    v=int(VAL_START.timestamp()*1000)
    t=int(TEST_START.timestamp()*1000)
    # 24h embargo is longer than the largest price/event horizon.
    tr=np.where(anchors+86_400_000<v)[0]
    va=np.where((anchors>=v)&(anchors+86_400_000<t))[0]
    te=np.where(anchors>=t)[0]
    if min(len(tr),len(va),len(te))<400:raise ValueError("not enough split examples")
    return tr,va,te

def train_price(x,y,close,tr,va,te):
    tr=tr[np.isfinite(y[tr])];va=va[np.isfinite(y[va])];te=te[np.isfinite(y[te])]
    model=HistGradientBoostingRegressor(
        loss="squared_error",learning_rate=.035,max_iter=135,max_leaf_nodes=12,
        min_samples_leaf=105,l2_regularization=7,random_state=SEED)
    model.fit(x[tr],y[tr])
    pred_val=model.predict(x[va])
    truth_val=close[va]*np.exp(y[va])
    shrink=min((0,.25,.5,.75,1),key=lambda a:np.mean(np.abs(close[va]*np.exp(a*pred_val)-truth_val)))
    test_return=model.predict(x[te])*shrink
    predicted=close[te]*np.exp(test_return)
    actual=close[te]*np.exp(y[te])
    metrics=regression_metrics(actual,predicted,close[te])
    metrics["validation_shrinkage"]=shrink
    metrics["heldout_bias_usdt"]=float(np.mean(predicted-actual))
    # The empirical "uncertainty" is validation-only residual sensitivity, not a calibrated interval.
    val_resid=np.asarray(y[va]-shrink*pred_val)
    return model,float(shrink),metrics,val_resid.tolist(),te

def train_alert(x,y,anchors,tr,va,te):
    tr=tr[np.isfinite(y[tr])];va=va[np.isfinite(y[va])];te=te[np.isfinite(y[te])]
    if len(np.unique(y[va]))<2 or np.sum(y[tr])<25:
        return None,{"status":"INSUFFICIENT_HISTORICAL_POSITIVES"}
    m=HistGradientBoostingClassifier(
        learning_rate=.035,max_iter=130,max_leaf_nodes=10,min_samples_leaf=120,
        l2_regularization=10,random_state=SEED)
    m.fit(x[tr],y[tr])
    pv=np.clip(m.predict_proba(x[va])[:,1],1e-6,1-1e-6)
    pt=np.clip(m.predict_proba(x[te])[:,1],1e-6,1-1e-6)
    cal=LogisticRegression(C=.25,random_state=SEED)
    cal.fit(np.log(pv/(1-pv)).reshape(-1,1),y[va])
    qv=cal.predict_proba(np.log(pv/(1-pv)).reshape(-1,1))[:,1]
    qt=cal.predict_proba(np.log(pt/(1-pt)).reshape(-1,1))[:,1]
    d=classification_metrics(y[te],qt)
    # Pre-registered candidate threshold: top one candidate per day, validation ONLY.
    hourly_val=(anchors[va]%(3600*1000))==0
    hourly_test=(anchors[te]%(3600*1000))==0
    hourly_v=qv[hourly_val];hourly_t=qt[hourly_test]; hourly_y=y[te][hourly_test]
    threshold=float(np.quantile(hourly_v,23/24)) if len(hourly_v)>24 else 1.0
    flags=hourly_t>=threshold
    positives=int(np.sum(hourly_y))
    d["alert_threshold"]=threshold
    d["alerts_per_day"]=float(np.sum(flags)/(len(hourly_y)/24)) if len(hourly_y) else None
    d["alert_precision"]=float(np.mean(hourly_y[flags])) if np.any(flags) else None
    d["recall_of_hourly_positive_windows"]=float(np.sum(hourly_y[flags])/positives) if positives else None
    d["passes_constant_brier"]=bool(d["brier"]<d["baseline_brier"])
    d["passes_constant_pr_auc"]=bool(d.get("pr_auc",0)>d["prevalence"])
    d["passes_both"]=d["passes_constant_brier"] and d["passes_constant_pr_auc"]
    return (m,cal,threshold),d

def otc_realized_backtest(times,idx,closes,te,labels,budget=147600.,markup=350.):
    # ONLY rows with all delayed execution outcomes are evaluated.
    j=te[np.isfinite(labels["1h"][te])&np.isfinite(labels["2h"][te])&
         np.isfinite(labels["5h"][te])&np.isfinite(labels["morning_plus_1h"][te])]
    base_price=closes[idx[j]]*np.exp(labels["1h"][j])
    buy_units=budget/(base_price+markup)
    outcomes={}
    for h in ("2h","5h","morning_plus_1h"):
        waited_price=closes[idx[j]]*np.exp(labels[h][j])
        change=budget/(waited_price+markup)-buy_units
        outcomes[h]={"n":int(len(change)),"mean_more_btc_from_wait":float(np.mean(change)),
                     "median_more_btc_from_wait":float(np.median(change)),
                     "fraction_wait_bought_more":float(np.mean(change>0)),
                     "p05_delta_btc":float(np.quantile(change,.05)),
                     "p95_delta_btc":float(np.quantile(change,.95))}
    return {"schema":"btc-otc-holdout-actual-purchase-units-v1",
            "assumption":"historical spot reference + fixed OTC markup, exactly 1h order latency; no guaranteed operator quote",
            "outcomes":outcomes}

def run(spot_raw,minute_raw,futures_raw,outdir):
    spot=read_gzip_json(spot_raw); minute=read_gzip_json(minute_raw);futures=read_gzip_json(futures_raw)
    if futures.get("schema")!="btc-vnext6-historical-futures-mac-collector-v1":
        raise ValueError("unknown OI provenance")
    times,a=build_arrays(spot); idx,base=features(times,a)
    m_ix,m_feat=micro_features(minute,times,idx)
    d_ix,d_feat=aligned_derivatives(times,idx,
        {int(k):v for k,v in futures["um"].items()},
        {int(k):v for k,v in futures["cm"].items()},
        {int(k):v for k,v in futures["funding"].items()})
    d_map={int(k):j for j,k in enumerate(d_ix)}
    matched=[(j,d_map[int(p)]) for j,p in enumerate(m_ix) if int(p) in d_map]
    full_indices=np.asarray([int(m_ix[i]) for i,_ in matched],dtype=int)
    minute_indices=np.asarray([i for i,_ in matched],dtype=int)
    deriv_indices=np.asarray([j for _,j in matched],dtype=int)
    close=a[idx[full_indices],3]
    x_spot=np.hstack([base[full_indices],m_feat[minute_indices]])
    x=np.hstack([x_spot,d_feat[deriv_indices]])
    if not np.all(np.isfinite(x)) or not np.all(np.isfinite(x_spot)):
        raise ValueError("invalid feature data")
    anchors=times[idx[full_indices]]+STEP
    labels=label_arrays(times,a,idx[full_indices])
    tr,va,te=splits(anchors)
    price_fits={};metrics={};residual={}
    for horizon in PRICE_TARGETS:
        m,shrink,score,resid,valid_test=train_price(x,labels[horizon],close,tr,va,te)
        price_fits[horizon]=(m,shrink)
        metrics[horizon]=score
        residual[horizon]=resid
    alert_fits={};alert_scores={}
    for event in EVENT_TARGETS:
        fit,d=train_alert(x,labels[event],anchors,tr,va,te)
        alert_fits[event]=fit
        alert_scores[event]=d
    # A separate deployable spot+1m numerical variant preserves exact source
    # parity on GitHub when Binance Futures endpoints return HTTP 451.
    # OKX positioning is reported separately, NEVER inserted into Binance OI slots.
    spot_price_fits={};spot_price_scores={};spot_alert_fits={};spot_alert_scores={}
    for horizon in PRICE_TARGETS:
        m,shrink,score,_,_=train_price(x_spot,labels[horizon],close,tr,va,te)
        spot_price_fits[horizon]=(m,shrink)
        spot_price_scores[horizon]=score
    for event in EVENT_TARGETS:
        fit,score=train_alert(x_spot,labels[event],anchors,tr,va,te)
        spot_alert_fits[event]=fit
        spot_alert_scores[event]=score
    # paired residuals require a common validation anchor across 6 horizons:
    val_all=va[np.all(np.column_stack([np.isfinite(labels[h][va]) for h in PRICE_TARGETS]),axis=1)]
    paired={h:(labels[h][val_all] - price_fits[h][1]*price_fits[h][0].predict(x[val_all])).tolist()
            for h in PRICE_TARGETS}
    spot_paired={h:(labels[h][val_all] - spot_price_fits[h][1]*spot_price_fits[h][0].predict(x_spot[val_all])).tolist()
            for h in PRICE_TARGETS}
    episode={}
    for hm in ("15:30","15:45","16:00"):
        t=int(dt.datetime.fromisoformat("2026-10-11T"+hm+":00+00:00").timestamp()*1000)
        k=np.where(anchors==t)[0]
        if len(k)==0:continue
        j=int(k[0]);now=dt.datetime.fromtimestamp(t/1000,UTC)
        prices={h:float(close[j]*np.exp(sh*mod.predict(x[j:j+1])[0]))
                for h,(mod,sh) in price_fits.items()}
        event_prob={}
        for ev,fit in alert_fits.items():
            if fit is None:continue
            model,cal,threshold=fit
            raw=float(np.clip(model.predict_proba(x[j:j+1])[0,1],1e-6,1-1e-6))
            p=float(cal.predict_proba([[math.log(raw/(1-raw))]])[0,1])
            event_prob[ev]={"probability":p,"validation_alert_threshold":threshold,
                            "watch_triggered":bool(p>=threshold),
                            "observed":float(labels[ev][j]) if np.isfinite(labels[ev][j]) else None}
        episode[hm]={"anchor_utc":now.isoformat(),"reference_price":float(close[j]),
                     "prices":prices,"alerts":event_prob,
                     "otc_sensitivity":compare(now,prices,paired_errors=paired)}
    report={
        "schema":"btc-demand-price-otc-v7-chronological-evaluation-v1",
        "status":"EXPERIMENTAL_REJECT_UNLESS_PROSPECTIVE_PROVEN",
        "trading_authority":False,
        "prospective_skill_proven":False,
        "policy":"No auto-order and no numerical macro influence absent historical point-in-time macro archive.",
        "source_provenance":{"spot":"Binance closed 5m+1m",
            "futures":"Mac-fetched historical Binance USDT-M/COIN-M OI and funding",
            "point_in_time_futures_publication_proven":False},
        "holdout_start_utc":TEST_START.isoformat(),
        "embargo_hours":24,"train_n":len(tr),"valid_n":len(va),"test_n":len(te),
        "features_count":int(x.shape[1]),
        "spot_live_feature_count":int(x_spot.shape[1]),
        "price_metrics":metrics,"event_metrics":alert_scores,
        "spot_1m_only_deployable_shadow":{"price_metrics":spot_price_scores,"event_metrics":spot_alert_scores,
             "trading_authority":False,"source":"closed Binance spot 5m+1m ONLY"},
        "otc_holdout":otc_realized_backtest(times,idx[full_indices],a[:,3],te,labels),
        "oct11_incident_diagnostic_only":episode,
    }
    outdir=pathlib.Path(outdir);outdir.mkdir(parents=True,exist_ok=True)
    (outdir/"audit.json").write_text(json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2)+"\n")
    dump({"price_models":price_fits,"alert_models":alert_fits,
          "features_count":int(x.shape[1]),
          "spot_live_price_models":spot_price_fits,
          "spot_live_alert_models":spot_alert_fits,
          "spot_live_feature_count":int(x_spot.shape[1]),
          "schema":"btc-v7-candidate-not-production",
          "trading_authority":False,
          "numeric_oi_input_authorized_on_github":False},
          outdir/"candidate.joblib",compress=3)
    (outdir/"paired_validation_errors.json").write_text(json.dumps(paired,sort_keys=True)+"\n")
    (outdir/"spot_paired_validation_errors.json").write_text(json.dumps(spot_paired,sort_keys=True)+"\n")
    print("BTC_V7_AUDIT_RESULT",json.dumps({
        "price_mae_gain":{k:round(v["model_mae_gain_usdt"],3) for k,v in metrics.items()},
        "spot_live_mae_gain":{k:round(v["model_mae_gain_usdt"],3) for k,v in spot_price_scores.items()},
        "event":{k:{"brier":v.get("brier"),"baseline_brier":v.get("baseline_brier"),
                    "pr_auc":v.get("pr_auc"),"precision":v.get("alert_precision"),
                    "alarms_per_day":v.get("alerts_per_day")} for k,v in alert_scores.items()},
        "oct11":episode.get("15:45",{})},ensure_ascii=False),flush=True)
    return report

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--spot-raw",required=True)
    ap.add_argument("--minute-raw",required=True)
    ap.add_argument("--futures-raw",required=True)
    ap.add_argument("--output",required=True)
    a=ap.parse_args()
    run(a.spot_raw,a.minute_raw,a.futures_raw,a.output)

if __name__=="__main__":main()
