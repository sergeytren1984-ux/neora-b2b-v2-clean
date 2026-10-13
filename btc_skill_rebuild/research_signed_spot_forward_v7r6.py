"""Research-only BTC v7R6 already-frozen softmax on NEW as-of signed spot.

Two mathematically distinct steps:
  freeze -- source historical closed 5m ending Oct 11, fit existing v7R6
       3-way softmax on TRAIN before Oct 4 and choose shrink on Oct 4-11
       matured VALIDATION only; frozen weights are saved before forecasting.
  forecast -- takes genuine as-of fixed R5 signed snapshot 5m OHLCV
       receipt but does NOT authenticate Cosign bundle; no outcome data
       past snapshot anchor is ever accepted. Produces probabilities for
       1h/4h/24h with target anchored at last source 5m close.
No prices/execution OTC asserted; NO live trading or production edits.
"""
from __future__ import annotations
import argparse,datetime as dt,gzip,hashlib,json,math,pathlib,statistics
from btc_skill_rebuild.research_execution_drift_v7r6 import examples,STEP,FEATURES
from btc_skill_rebuild.research_endpoint_24h_v7r6 import fit,predict,brier
from btc_skill_rebuild.research_competing_barriers_v7r6 import SHRINK
from btc_skill_rebuild.research_unified_endpoint_v7r6 import HORIZONS,endpoint_class
UTC=dt.timezone.utc
VALID_BEGIN=int(dt.datetime(2026,10,4,tzinfo=UTC).timestamp()*1000)
VALID_END=int(dt.datetime(2026,10,11,19,tzinfo=UTC).timestamp()*1000)

def sha(path):return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()

def asof_last_feature(rows):
    """Identical existing examples() feature equation at LAST closed bar."""
    i=len(rows)-1
    if i<289:raise ValueError("not enough closed history")
    if any(int(rows[k][0])-int(rows[k-1][0])!=STEP for k in range(1,len(rows))):
        raise ValueError("not a continuous 5m candle record")
    if any(int(x[6])+1!=int(x[0])+STEP for x in rows):
        raise ValueError("unclosed spot bar")
    c=[float(z[4]) for z in rows];lg=[math.log(z) for z in c]
    vol=[float(z[5]) for z in rows];buy=[float(z[9]) for z in rows]
    trades=[float(z[8]) for z in rows]
    for bar,v,b,z in zip(rows,vol,buy,trades):
        o,h,l,close=[float(bar[k]) for k in (1,2,3,4)]
        if not all(math.isfinite(a) for a in (o,h,l,close,v,b,z)) or not (
              0<l<=min(o,close)<=max(o,close)<=h and 0<=b<=v and z>=0):
            raise ValueError("bad signed spot OHLCV")
    def ratio(n):
        return sum(buy[i-n+1:i+1])/max(sum(vol[i-n+1:i+1]),1e-8)
    def mom(n):return lg[i]-lg[i-n]
    fr5=ratio(1);fr15=ratio(3);fr60=ratio(12)
    v15=sum(vol[i-2:i+1]);t15=sum(trades[i-2:i+1])
    vprior=sum(vol[i-14:i-2]);tprior=sum(trades[i-14:i-2])
    sq=sum((lg[j]-lg[j-1])**2 for j in range(i-11,i+1))
    sq4=sum((lg[j]-lg[j-1])**2 for j in range(i-47,i+1))
    t=int(rows[i][0])+STEP
    at=dt.datetime.fromtimestamp(t/1000,UTC)
    angle=2*math.pi*(at.hour*60+at.minute)/1440
    x=(mom(3),mom(12),mom(48),mom(144),2*mom(12)-mom(24),
       2*fr5-1,2*fr15-1,2*fr60-1,2*(fr15-fr60),
       math.log((v15+1)/(vprior/4+1)),
       math.log((t15+1)/(tprior/4+1)),math.sqrt(max(0.,sq)),
       math.sqrt(max(0.,sq4)),
       (c[i]-max(float(rows[j][2]) for j in range(i-12,i)))/c[i],
       (c[i]-min(float(rows[j][3]) for j in range(i-12,i)))/c[i],
       math.sin(angle),math.cos(angle))
    assert len(x)==len(FEATURES)
    return (t,tuple(x),c[i])

def freeze(history_path,out):
    with gzip.open(history_path,"rt") as f:raw=json.load(f)
    feat=examples(raw)
    n=len(raw)
    runs={}
    for h,(duration,threshold) in HORIZONS.items():
        population=[]
        for i,t,x,cl,lg in feat:
            if t%(15*60000) or i+duration>=n:continue
            mature=int(raw[i+duration][0])+STEP
            y=endpoint_class(cl[i],float(raw[i+duration][4]),threshold)
            population.append((t,mature,x,y))
        training=[(t,x,y) for t,d,x,y in population if d<VALID_BEGIN]
        valid=[(t,x,y) for t,d,x,y in population
               if VALID_BEGIN<=t and d<VALID_END]
        if len(training)<1500 or len(valid)<250:
            # Longer 24h endpoint can have as many as six days of validation.
            raise ValueError("insufficient matured hist/validation rows")
        model=fit(training)
        alpha=min(SHRINK,key=lambda a:statistics.mean(
            brier(predict(model,x,a),y) for t,x,y in valid))
        runs[h]={"duration_5m_steps":duration,"threshold":threshold,
                 "validation_selected_shrink":alpha,
                 "historical_training_observations":len(training),
                 "historical_validation_observations":len(valid),
                 "model_parameters":[list(model[0]),list(model[1]),model[2],model[3]]}
        print("FROZEN_FORWARD_MATH",h,"alpha",alpha,"train",len(training),"val",len(valid),flush=True)
    payload={"schema":"btc-v7r6-same-math-three-heads-locked-historical-weights-v1",
             "source_gzip_sha256":sha(history_path),
             "train_label_maturity_before_utc":dt.datetime.fromtimestamp(VALID_BEGIN/1000,UTC).isoformat(),
             "validation_labels_mature_before_utc":dt.datetime.fromtimestamp(VALID_END/1000,UTC).isoformat(),
             "model_features":list(FEATURES),
             "thresholds_predeclared":True,"training_archive_already_seen_historical":True,
             "signing_and_prospective_quality_not_claimed":True,
             "no_operator_quote_data":True,"trading_authority":False,"heads":runs}
    pathlib.Path(out).write_text(json.dumps(payload,sort_keys=True,separators=(",",":"),allow_nan=False)+"\n")
    return payload

def forecast(frozen_path,historical_path,appended_path,out):
    frozen=json.load(open(frozen_path))
    with gzip.open(historical_path,"rt") as f:rows=json.load(f)
    append=json.load(open(appended_path))
    if frozen["source_gzip_sha256"]!=sha(historical_path):
        raise ValueError("not the historical pre-epoch source")
    last=int(rows[-1][0])
    new=append["new_closed_5m_rows_after_archive"]
    if not new or any(int(r[0])<=last for r in new):
        raise ValueError("overlapping or reversed already-closed forecast inputs")
    rows+=new
    slot,x,price=asof_last_feature(rows)
    if dt.datetime.fromtimestamp(slot/1000,UTC).isoformat()!=append["frozen_source_anchor_utc"]:
        raise ValueError("signed anchor does not equal final closed spot feature timestamp")
    probs={}
    for h,entry in frozen["heads"].items():
        p=predict(entry["model_parameters"],x,entry["validation_selected_shrink"])
        probs[h]={"up":p[0],"down":p[1],"range":p[2],"source_anchor_utc":append["frozen_source_anchor_utc"],
                  "horizon_target_utc":(dt.datetime.fromtimestamp(slot/1000,UTC)+
                          dt.timedelta(minutes=5*entry["duration_5m_steps"])).isoformat(),
                  "reference_spot_usdt":price,"endpoint_threshold_fraction":entry["threshold"],
                  "estimated_probabilities_sum_to_one":True}
    obj={"schema":"btc-v7r6-unpromoted-ex-ante-research-spot-probabilities-v1",
         "clock_anchor_utc":append["frozen_source_anchor_utc"],
         "input_R5_spot_source_blob_GitHub_sha1":append["source_blob"],
         "input_R5_spot_source_path":append["source_path"],
         "source_retrieved_at_utc":append["source_retrieved_at_utc"],
         "generated_utc":dt.datetime.now(UTC).isoformat(),
         "training_weights_sha256":sha(frozen_path),
         "evidence_signature_not_independently_verified":True,
         "not_GitHub_signed_prospective_v7r6":True,
         "publication_must_be_committed_BEFORE_outcome_and_within_13m_for_slot_admission":True,
         "has_real_operator_OTC_quotes":False,
         "trading_authority":False,"three_way":probs}
    pathlib.Path(out).write_text(json.dumps(obj,sort_keys=True,indent=2,allow_nan=False)+"\n")
    return obj

if __name__=="__main__":
    a=argparse.ArgumentParser();a.add_argument("action",choices=("freeze","forecast"))
    a.add_argument("--historical",required=True);a.add_argument("--weights")
    a.add_argument("--append");a.add_argument("--out",required=True)
    args=a.parse_args()
    if args.action=="freeze":freeze(args.historical,args.out)
    else:forecast(args.weights,args.historical,args.append,args.out)
