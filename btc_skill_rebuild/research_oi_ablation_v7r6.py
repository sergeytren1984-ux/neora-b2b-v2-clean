"""Causal historical OI ablation in the SAME v7R6 competing-barrier model.

Strict identical horizon, samples, TRAIN/VALIDATION/test, scoring and bias
across SPOT versus SPOT+lagged futures. Historical derivatives' vendor
publication time is NOT independently proven: exploratory, never prospect.
No production or GitHub Actions changes.
"""
from __future__ import annotations
import argparse,bisect,datetime as dt,gzip,json,hashlib,math,pathlib,statistics
from btc_skill_rebuild.research_competing_barriers_v7r6 import (
    fit,metrics,labels,SHRINK,classify_threshold,alert_score,prob)
from btc_skill_rebuild.research_execution_drift_v7r6 import examples,STEP
from btc_skill_rebuild.research_distribution_v7r6 import UTC,TRAIN_CUTOFF,VALIDATION_CUTOFF

FEATURES=('oi_um_15m_log_change','oi_um_1h_log_change',
          'oi_coinm_15m_log_change_optional','funding_last_settled',
          'coinm_missing','coinm_staleness_0to1')
LAG_MS=300000

def load_hist(path):
    with gzip.open(path,'rt') as f:r=json.load(f)
    if r['schema']!='btc-vnext6-historical-futures-mac-collector-v1':
        raise ValueError('unknown futures collector provenance')
    um={int(k):float(v) for k,v in r['um'].items()}
    cm={int(k):float(v) for k,v in r['cm'].items()}
    funding={int(k):float(v) for k,v in r['funding'].items()}
    if not all(math.isfinite(x) for v in (um,cm,funding) for x in v.values()):
        raise ValueError('nonfinite historical futures')
    return um,cm,funding

def extra_asof(decision,um,cm,fs,cm_keys,fund_keys):
    """All historical observations must be timestamped BEFORE decision-5m.

    Historical vendor timestamp <= t-5m is conservative but is NOT a
    proof of original HTTP publication time, which the archive lacks.
    """
    before=decision-LAG_MS
    ts=(before,before-3*STEP,before-12*STEP)
    if not all(k in um and um[k]>0 for k in ts):return None
    k=bisect.bisect_right(fund_keys,before)-1
    if k<0 or before-fund_keys[k]>9*3600000:return None
    coin=[];ages=[]
    for target in ts[:2]:
        j=bisect.bisect_right(cm_keys,target)-1
        if j<0 or target-cm_keys[j]>15*60000:
            coin=[];break
        val=cm[cm_keys[j]]
        if val<=0:raise ValueError('nonpositive vendor futures')
        coin.append(val);ages.append(target-cm_keys[j])
    cm_ok=len(coin)==2
    return (
        math.log(um[ts[0]]/um[ts[1]]),
        math.log(um[ts[0]]/um[ts[2]]),
        math.log(coin[0]/coin[1]) if cm_ok else 0.,
        fs[fund_keys[k]],
        0. if cm_ok else 1.,
        (ages[0]/(15*60000)) if cm_ok else 1.)

def run(spot_raw,futures_raw,out):
    with gzip.open(spot_raw,'rt') as f:raw=json.load(f)
    um,cm,fs=load_hist(futures_raw)
    cm_keys=sorted(cm);fund_keys=sorted(fs)
    input=examples(raw)
    a=int(TRAIN_CUTOFF.timestamp()*1000);b=int(VALIDATION_CUTOFF.timestamp()*1000)
    results={}
    for head,(n,band) in {'1h':(12,.007),'4h':(48,.012)}.items():
        paired={key:[] for key in ('train','validation','test')}
        missing=0;checked=0
        for i,at,features,prices,logs in input:
            if i+n>=len(raw):continue
            if at<int(dt.datetime(2026,9,14,tzinfo=UTC).timestamp()*1000):continue
            end=int(raw[i+n][0])+STEP
            if end<a:part='train'
            elif a<=at and end<b:part='validation'
            elif at>=b:part='test'
            else:continue
            # Sparse available OI history leaves only ~14 train days.
            # Use every CLOSED 5m anchor in TRAIN, and sparse 15m anchors
            # in VALIDATION/TEST for a fair same-row comparison, with no
            # future labels or new indicators. Fold independence remains
            # measured by days, NEVER by the apparent row count.
            if part!='train' and at%(15*60000):continue
            checked+=1
            extras=extra_asof(at,um,cm,fs,cm_keys,fund_keys)
            if extras is None:
                missing+=1;continue
            side,touch=labels(raw,i,n,band)
            actual_first_touch=int(raw[touch][0])+STEP if touch is not None else None
            paired[part].append((at,features,features+extras,side,actual_first_touch))
        if min(map(len,paired.values()))<450:
            raise RuntimeError('not enough completely matched historical futures for '+head)
        results[head]={
            'same_matched_rows_both_models':True,
            'missing_futures_removed_from_both':missing,
            'total_candidate_rows':checked,
            'asof_timestamp_at_least_5m_before_decision':True,
            'original_vendor_http_publication_time_proven':False,
            'mathematical_incremental_performance':{},
        }
        paired_frozen={}
        for candidate in ('spot','spot_with_lagged_OI_funding'):
            where=1 if candidate=='spot' else 2
            subset={phase:[(at,spot if candidate=='spot' else augmented,y,touch)
                           for at,spot,augmented,y,touch in vals]
                    for phase,vals in paired.items()}
            model=fit(subset['train'])
            shrink=min(SHRINK,key=lambda z:metrics(subset['validation'],model,z)['four_class_brier'])
            threshold=classify_threshold(subset['validation'],model,shrink)
            paired_frozen[candidate]=(model,shrink)
            results[head]['mathematical_incremental_performance'][candidate]={
                'train_rows':len(subset['train']),
                'validation_rows':len(subset['validation']),
                'historical_test_rows':len(subset['test']),
                'validation_selected_shrink':shrink,
                'train_prior':model[3],
                'validation':metrics(subset['validation'],model,shrink),
                'historical_test_already_seen':metrics(subset['test'],model,shrink),
                'validation_alert':alert_score(subset['validation'],model,shrink,threshold),
                'historical_test_alert':alert_score(subset['test'],model,shrink,threshold)}
        c=results[head]['mathematical_incremental_performance']
        v0=c['spot']['historical_test_already_seen'];v1=c['spot_with_lagged_OI_funding']['historical_test_already_seen']
        results[head]['delta_test_brier_spot_minus_with_derivatives']=v0['four_class_brier']-v1['four_class_brier']
        results[head]['delta_test_directional_gain_with_derivatives_minus_spot']=(
            v1['directional_incremental_brier_gain_vs_same_conditional_volatility']-
            v0['directional_incremental_brier_gain_vs_same_conditional_volatility'])
        # Paired DAILY sample differences, not 648 overlapping windows
        # incorrectly counted as 648 statistically independent trials.
        day={}
        def brier(p,y):return sum((v-(j==y))**2 for j,v in enumerate(p))/4
        def conditional_directed(p,base):
            total=p[0]+p[1]
            up=base[0]/(base[0]+base[1])
            return [total*up,total*(1-up),p[2],p[3]]
        for at,spot_x,full_x,y,touch in paired['test']:
            first_model,sh0=paired_frozen['spot']
            second_model,sh1=paired_frozen['spot_with_lagged_OI_funding']
            a0=prob(first_model,spot_x,sh0);a1=prob(second_model,full_x,sh1)
            score=brier(a0,y)-brier(a1,y)
            directional=(brier(conditional_directed(a1,second_model[3]),y)-brier(a1,y)
                - brier(conditional_directed(a0,first_model[3]),y)+brier(a0,y))
            key=dt.datetime.fromtimestamp(at/1000,UTC).date().isoformat()
            day.setdefault(key,[]).append((score,directional))
        daily=[]
        for day_id,items in sorted(day.items()):
            daily.append({'day':day_id,
                          'brier_spot_minus_with_OI':statistics.mean(t[0] for t in items),
                          'directional_OI_increment':statistics.mean(t[1] for t in items),
                          'n_slots_correlated':len(items)})
        scores=[v['brier_spot_minus_with_OI'] for v in daily]
        los=statistics.mean(scores)-1.96*statistics.stdev(scores)/math.sqrt(len(scores))
        results[head]['paired_day_block_incremental']={
            'days':daily,'n_days':len(daily),
            'days_OI_improved_Brier':sum(v>0 for v in scores),
            'mean_daily_Brier_gain':statistics.mean(scores),
            'descriptive_lower95_not_prospective':los,
            'at_least_20_independent_days':len(daily)>=20}
        print('OI_DAYBLOCK',head,'days',len(daily),'win_days',sum(v>0 for v in scores),
              'mean',round(statistics.mean(scores),7),'lower95',round(los,7),flush=True)
        print('HISTORICAL_OI_ABLATION',head,
              'matched',len(paired['test']),
              'spot_brier',round(v0['four_class_brier'],7),
              'with_OI_brier',round(v1['four_class_brier'],7),
              'OI_BRIER_GAIN',round(results[head]['delta_test_brier_spot_minus_with_derivatives'],7),
              'OI_DIRECTION_GAIN',round(results[head]['delta_test_directional_gain_with_derivatives_minus_spot'],7),flush=True)
    payload={'schema':'btc-v7r6-oi-ablation-historical-math-only-v1',
       'spot_source_sha256':hashlib.sha256(pathlib.Path(spot_raw).read_bytes()).hexdigest(),
       'futures_source_sha256':hashlib.sha256(pathlib.Path(futures_raw).read_bytes()).hexdigest(),
       'historical_vendor_availability_not_independently_proven':True,
       'existing_v7r6_competing_model_with_optional_OI_features':True,
       'not_a_new_live_model':True,'model_promoted':False,
       'prospective_skill_proven':False,'trading_authority':False,
       'derivatives_feature_names':FEATURES,'results':results}
    pathlib.Path(out).write_text(json.dumps(payload,sort_keys=True,indent=2,allow_nan=False)+'\n')
    return payload
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--spot-raw',required=True);p.add_argument('--futures-raw',required=True);p.add_argument('--out',required=True)
    a=p.parse_args();run(a.spot_raw,a.futures_raw,a.out)
