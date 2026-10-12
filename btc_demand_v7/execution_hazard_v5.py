"""Single historical spot-flow classifier for *actionable >=60m lead* risk.

Research-only: Oct 5-11 had already been inspected; not untouched. No
as-of book/OI history; NOT the registered 15m v7R4 model. Reuses signed
Binance 1m source. Model and threshold never see test labels, but experiment
family has seen test dates, so no inferential claim of skill is allowed.

A first $500 barrier reached BEFORE 60m lead is a non-actionable class,
not a win under the one-hour OTC execution constraint. Globally at most
one alert per UTC day, selected ONLINE by crossing a single validation-only
threshold (never retroactive daily top-k). Two minute hypothetical public
delivery cannot be claimed to have occurred historically.
"""
from __future__ import annotations
import argparse,datetime as dt,gzip,hashlib,json,math,pathlib
import numpy as np
from sklearn.linear_model import LogisticRegression

UTC=dt.timezone.utc
V_START=dt.datetime(2026,9,28,tzinfo=UTC)
T_START=dt.datetime(2026,10,5,tzinfo=UTC)
LAST_CLOSED=dt.datetime(2026,10,11,18,55,tzinfo=UTC)
CADENCE=3
PREHISTORY=60
LATENCY=2
BARRIER_DOLLARS=500.
TARGET_MINUTES=120
MIN_USEFUL_LEAD=60
EMBARGO_MINUTES=240
BUDGET_PER_UTC_DAY=1
RIDGE_C=.20
SHRINK_GRID=(0.,.25,.50,.75,1.)
CODE_SCHEMA="btc-v7r5-single-spot-flow-actionable-2h-hazard-v1"

def stamp(x):return dt.datetime.fromtimestamp(int(x)/1000,UTC)
def strict(raw):
    if not isinstance(raw,list) or len(raw)<30000:
        raise ValueError("incomplete verified signed minute archive")
    prior=None
    for r in raw:
        t=int(r[0])
        if int(r[6])+1!=t+60000 or (prior is not None and t-prior!=60000):
            raise ValueError("future/gapped minute source")
        prior=t
        op,hi,lo,cl,volume,trades,buy=[float(r[k]) for k in (1,2,3,4,5,8,9)]
        if not all(map(math.isfinite,(op,hi,lo,cl,volume,trades,buy))):
            raise ValueError("nonfinite signed raw")
        if not(0<lo<=min(op,cl)<=max(op,cl)<=hi
               and 0<=buy<=volume and trades>=0 and trades.is_integer()):
            raise ValueError("invalid raw minute mechanics")

def feat(raw,i):
    """Everything is <= closed source candle i; no labels and no +2m price."""
    close=lambda k:float(raw[k][4])
    vol=lambda lo,hi:sum(float(raw[t][5]) for t in range(lo,hi))
    buy=lambda lo,hi:sum(float(raw[t][9]) for t in range(lo,hi))
    amount3=vol(i-2,i+1)
    amountprev3=vol(i-5,i-2)
    amount15=vol(i-14,i+1)
    amountprev15=vol(i-29,i-14)
    frac3=buy(i-2,i+1)/max(amount3,1e-9)
    frac15=buy(i-14,i+1)/max(amount15,1e-9)
    price3=math.log(close(i)/close(i-3))
    price15=math.log(close(i)/close(i-15))
    price60=math.log(close(i)/close(i-60))
    amplitude15=max(float(x[2]) for x in raw[i-14:i+1])-min(float(x[3]) for x in raw[i-14:i+1])
    minute_var=sum(math.log(close(j)/close(j-1))**2 for j in range(i-14,i+1))
    lasttrades=float(raw[i][8])
    prevtrades=sum(float(raw[j][8]) for j in range(i-15,i))/15
    calendar=stamp(int(raw[i][6])+1)
    minute=calendar.hour*60+calendar.minute
    values=[
       frac3-.5, frac15-.5, frac3-frac15,
       math.log(max(amount3,1e-9)/max(amountprev3,1e-9)),
       math.log(max(amount15,1e-9)/max(amountprev15,1e-9)),
       price3,price15,price60,
       amplitude15/close(i), math.sqrt(minute_var),
       math.log((lasttrades+1)/(prevtrades+1)),
       math.sin(2*math.pi*minute/1440),math.cos(2*math.pi*minute/1440),
       int(calendar.weekday()>=5)]
    if not all(map(math.isfinite,values)):raise ValueError("nonfinite derived features")
    return values

def label(raw,i):
    """First +/-$500 after *assumed* later public reference, not current spot."""
    delivery=i+LATENCY
    ref=float(raw[delivery][4])
    source_ref=float(raw[i][4])
    if abs(ref/source_ref-1)>=.003:
        # Already moved >0.3% before publication. Not an early signal.
        return 0,False,None
    boundary_up=ref+BARRIER_DOLLARS
    boundary_down=ref-BARRIER_DOLLARS
    for j in range(delivery+1,delivery+TARGET_MINUTES+1):
        up=float(raw[j][2])>=boundary_up
        down=float(raw[j][3])<=boundary_down
        if up or down:
            lead=j-delivery-1 # minute OPEN lower-bound, not minute close
            if up and not down and lead>=MIN_USEFUL_LEAD:return 1,True,lead
            if down and not up and lead>=MIN_USEFUL_LEAD:return 2,True,lead
            return 0,True,lead # earlier event is not actionable for 1h OTC
    return 0,True,None

def phase(anchor,mins):
    end=anchor+dt.timedelta(minutes=mins+EMBARGO_MINUTES)
    if end<V_START:return "TRAIN"
    if V_START<=anchor and end<T_START:return "VALIDATION"
    if anchor>=T_START:return "SEEN_TEST"
    return "GAP"

def multiclass_brier(y,probs):
    truth=np.eye(3)[np.asarray(y,dtype=int)]
    return float(np.mean(np.sum((probs-truth)**2,axis=1)))

def eval_archive(path,out):
    packed=pathlib.Path(path).read_bytes()
    with gzip.open(path,"rt") as fh:raw=json.load(fh)
    strict(raw)
    ix=[];xs=[];ys=[];eras=[];published=[];leads=[]
    for i in range(PREHISTORY,len(raw)-TARGET_MINUTES-LATENCY,CADENCE):
        t=stamp(int(raw[i][6])+1)
        p=phase(t,TARGET_MINUTES+LATENCY)
        if p=="GAP":continue
        x=feat(raw,i)
        y,eligible,lead=label(raw,i)
        ix.append(t.isoformat());xs.append(x);ys.append(y)
        eras.append(p);published.append(eligible)
        leads.append(lead)
    x=np.asarray(xs,float);y=np.asarray(ys,int)
    pub=np.asarray(published,bool);phasearr=np.asarray(eras)
    tr=np.flatnonzero(phasearr=="TRAIN")
    va=np.flatnonzero(phasearr=="VALIDATION")
    te=np.flatnonzero(phasearr=="SEEN_TEST")
    if min(len(tr),len(va),len(te))<500:
        raise ValueError("insufficient temporally separated event cohort")
    med=np.median(x[tr],axis=0)
    mad=np.maximum(1e-5,1.4826*np.median(np.abs(x[tr]-med),axis=0))
    z=np.clip((x-med)/mad,-5,5)
    if set(y[tr])!={0,1,2}:
        raise ValueError("insufficient TRAIN 3-way first-touch classes")
    model=LogisticRegression(C=RIDGE_C,solver="lbfgs",max_iter=600)
    model.fit(z[tr],y[tr])
    qva=model.predict_proba(z[va]);qt=model.predict_proba(z[te])
    prior=np.bincount(y[tr],minlength=3)/len(tr)
    blend=lambda q,sh:sh*q+(1-sh)*prior
    shrink=min(SHRINK_GRID,key=lambda sh:multiclass_brier(y[va],blend(qva,sh)))
    qvalid=blend(qva,shrink);qtest=blend(qt,shrink)
    train_rate=prior.tolist()
    m_brier=multiclass_brier(y[te],qtest)
    p_brier=multiclass_brier(y[te],np.repeat(prior[None,:],len(te),axis=0))
    # Validate single alert/day budget on the EXACT preknown validation cohort:
    # ~480 as-of 3m observations/day; threshold is a validation-only quantile,
    # and *first crossing* online in test wins, never daily retrospective max.
    score_va=np.max(qvalid[:,1:],axis=1)
    threshold=float(np.quantile(score_va,1-1/480))
    day_stamped={};alerts=[]
    for row,prob in zip(te,qtest):
        day=ix[row][:10]
        if day in day_stamped or not pub[row]:continue
        side=int(np.argmax(prob[1:])+1)
        confidence=float(np.max(prob[1:]))
        if confidence<threshold:continue
        day_stamped[day]=True
        alerts.append({
          "utc_published_source_at":ix[row],
          "day_utc":day,
          "direction":"UP" if side==1 else "DOWN",
          "confidence_is_not_calibrated_in_future":confidence,
          "signed_label_for_research_only":int(y[row]),
          "correct_with_at_least_60m_lead":bool(int(y[row])==side),
          "conservative_touch_lead_minutes":leads[row],
        })
    n_correct=sum(a["correct_with_at_least_60m_lead"] for a in alerts)
    days=sorted(set(ix[i][:10] for i in te))
    incidence={d:int(np.any((y[te]==1)|(y[te]==2))) for d in days
               for te_mask in [np.asarray([ix[i][:10]==d for i in te])]}
    # Correct day recall uses same-day labels, not overlap count.
    # Daily events definition requires a separate episode denominator;
    # do NOT interpret it as event-level recall.
    day_hit={day:bool(any(a["day_utc"]==day and a["correct_with_at_least_60m_lead"]
                          for a in alerts)) for day in days}
    detail={
      "schema":CODE_SCHEMA,
      "research_only_not_prospective":True,
      "test_date_known_to_prior_experiments":True,
      "unsigned_OI_or_book_not_used":True,
      "signed_minute_raw_bytes_sha256":hashlib.sha256(packed).hexdigest(),
      "signed_archive_producer_run":38167948896,
      "train_validation_test_rows":[len(tr),len(va),len(te)],
      "train_cutoff_utc":V_START.isoformat(),
      "test_start_utc":T_START.isoformat(),
      "embargo_minutes":EMBARGO_MINUTES,
      "source_close_to_publication_latency_minutes_is_hypothetical":LATENCY,
      "global_alert_budget_per_UTC_day":BUDGET_PER_UTC_DAY,
      "early_actionable_barrier_dollars":BARRIER_DOLLARS,
      "minimum_lead_lower_bound_minutes":MIN_USEFUL_LEAD,
      "event_horizon_minutes":TARGET_MINUTES,
      "one_single_model":"three-class multinomial regularized logistic hazard",
      "prior_probability_train_only":train_rate,
      "validation_blend_to_train_prior":shrink,
      "validation_only_alert_confidence_threshold":threshold,
      "classifier_coef":model.coef_.tolist(),
      "classifier_intercept":model.intercept_.tolist(),
      "train_only_feature_centers":med.tolist(),
      "train_only_feature_MAD":mad.tolist(),
      "test_multiclass_brier":m_brier,
      "test_train_prior_brier":p_brier,
      "gain_vs_prior_brier":p_brier-m_brier,
      "test_class_counts":np.bincount(y[te],minlength=3).tolist(),
      "alerts":alerts,
      "n_utc_days":len(days),
      "n_alerts":len(alerts),
      "n_true_actionable_alerts":n_correct,
      "n_utc_days_with_true_alert":sum(day_hit.values()),
      "n_days_with_no_alert":len(days)-len(set(a["day_utc"] for a in alerts)),
      "n_true_alerts_with_at_least60m_lead":n_correct,
      "daily_event_recall_NOT_CLAIMED":True,
      "retrained_or_tuned_on_known_test":False,
      "test_set_known_from_prior_evaluations":True,
      "shadow_release_authorized":False,
      "prospective_skill_proven":False,
      "trading_authority":False,
    }
    outfile=pathlib.Path(out);outfile.parent.mkdir(parents=True,exist_ok=True)
    outfile.write_text(json.dumps(detail,sort_keys=True,indent=2,allow_nan=False)+"\n")
    print("BTC_V7R5_EXECUTION_ACTIONABLE_HAZARD_DIAGNOSTIC",json.dumps({
      "test_rows":len(te),"days":len(days),"brier":m_brier,"prior_brier":p_brier,
      "gain":p_brier-m_brier,"selection_blend":shrink,
      "daily_threshold":threshold,"alerts":len(alerts),
      "correct_60min_actionable":n_correct,
      "early_before_11Oct":next((a for a in alerts if a["day_utc"]=="2026-10-11"),None),
      "not_prospective":True},sort_keys=True))

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--signed-minutes",required=True)
    p.add_argument("--out",required=True)
    args=p.parse_args()
    eval_archive(args.signed_minutes,args.out)
if __name__=="__main__":main()
