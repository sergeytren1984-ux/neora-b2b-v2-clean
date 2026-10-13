"""v7R6 forecast mathematics: dynamic causal climatology benchmark.

A 1h/4h/24h 3-way endpoint model is only useful if it beats a plausible
NO-SKILL competitor. In addition to its own frozen TRAIN prior, compare
against trailing 7d or 14d class frequencies (with Laplace smoothing).
All reference labels must be MATURE strictly BEFORE current issue time;
rolling class rates use only horizon-spaced UTC due slots, not overlapping
15m endpoint labels.
Which baseline is used is selected ONLY from the prior validation set.
No frozen production modification. Already-seen historical replay !=
prospective forecast evidence.
"""
from __future__ import annotations
import argparse,bisect,datetime as dt,gzip,hashlib,json,math,pathlib,statistics
from btc_skill_rebuild.research_execution_drift_v7r6 import examples,STEP
from btc_skill_rebuild.research_endpoint_24h_v7r6 import fit,predict,brier
from btc_skill_rebuild.research_competing_barriers_v7r6 import SHRINK
from btc_skill_rebuild.research_walkforward_barriers_v7r6 import FOLDS,UTC

HORIZONS={'1h':(12,.007),'4h':(48,.012),'24h':(288,.02)}
DAY=86400000
BASELINES=('frozen_training_prior','matured_rolling_7day','matured_rolling_14day')

def endpoint_class(reference,forward,threshold):
    if not all(math.isfinite(z) for z in (reference,forward,threshold)):
        raise ValueError('nonfinite future price')
    if min(reference,forward)<=0 or threshold<=0:
        raise ValueError('invalid future price or threshold')
    if forward>=reference*(1+threshold):return 0
    if forward<=reference*(1-threshold):return 1
    return 2

class CausalClimatology:
    def __init__(self,population):
        # Four-tuples: (issue_ms, future_maturity_ms, features, class).
        if any(a[0]>=b[0] for a,b in zip(population,population[1:])):
            raise ValueError('duplicate or reversed historical time')
        self.issued=[r[0] for r in population]
        self.mature=[r[1] for r in population]
        if any(a>b for a,b in zip(self.mature,self.mature[1:])):
            raise ValueError('future labels are not monotonic')
        self.prefix=[[0] for _ in range(3)]
        for _,_,_,y in population:
            if y not in (0,1,2):raise ValueError('unknown future class')
            for k in range(3):
                self.prefix[k].append(self.prefix[k][-1]+int(y==k))

    def probability(self,issue,days):
        if days not in (7,14):raise ValueError('unregistered lookback')
        lo=bisect.bisect_left(self.issued,issue-days*DAY)
        # If all rows issued within the window are still immature,
        # hi can precede lo. This is an EMPTY matured window, not a
        # negative class count. Never admit any older-than-window row.
        hi=max(lo,bisect.bisect_left(self.mature,issue))
        n=hi-lo
        counts=[self.prefix[k][hi]-self.prefix[k][lo] for k in range(3)]
        if n!=sum(counts):raise ValueError('historical label maturity mismatch')
        return [(c+1)/(n+3) for c in counts]

def independent_due_climatology_population(population,horizon_steps):
    """Estimate rolling class frequencies on SAME nonoverlapping due grid.

    A 24h horizon sampled at 15m has up to 96 strongly overlapping
    labels per day, but only one independent 24h endpoint.  Treating
    96 labels as independent gives an unjustifiably concentrated prior.
    Only issue times on the predetermined UTC horizon grid may enter
    the causal 7/14d climatology; every label still needs strict
    maturity BEFORE the query timestamp.
    """
    if not isinstance(horizon_steps,int) or horizon_steps<=0:
        raise ValueError('invalid independent horizon step')
    grid=horizon_steps*STEP
    return [r for r in population if r[0]%grid==0]


def nonoverlap_training_prior(train,horizon_steps):
    """Causal TRAIN prior on exactly the same UTC due grid as scored slots.

    The model may fit on many overlapping 15m TRAIN labels, but its fitted
    class prior is NOT an independent nonoverlap-grid climatology. Use the
    independent grid for all competing baseline rates, including TRAIN.
    Never count one underlying 24h movement 96 times in this comparator.
    """
    if not isinstance(horizon_steps,int) or horizon_steps<=0:
        raise ValueError('invalid horizon steps')
    selected=[y for t,_,y in train if t%(horizon_steps*STEP)==0]
    if not selected:raise ValueError('no causally matured TRAIN grid labels')
    if any(y not in (0,1,2) for y in selected):
        raise ValueError('invalid TRAIN endpoint label')
    return [(sum(y==k for y in selected)+1)/(len(selected)+3)
            for k in range(3)]


def baseline_probability(name,issue,grid_training_prior,climatology):
    if name=='frozen_training_prior':return grid_training_prior
    if name=='matured_rolling_7day':return climatology.probability(issue,7)
    if name=='matured_rolling_14day':return climatology.probability(issue,14)
    raise ValueError('unknown baseline')

def matched_score(sample,model,alpha,name,climatology,grid_training_prior):
    changes=[];signed=[]
    days={}
    for t,x,y in sample:
        p=predict(model,x,alpha)
        q=baseline_probability(name,t,grid_training_prior,climatology)
        gain=brier(q,y)-brier(p,y)
        # Counterfactual uses the IDENTICAL P(UP or DOWN) as model,
        # but no model-specific sign; this is signed skill ALONE.
        risk=p[0]+p[1]
        if q[0]+q[1]<=0:raise ValueError('no directional prior')
        upshare=q[0]/(q[0]+q[1])
        nondir=[risk*upshare,risk*(1-upshare),p[2]]
        changes.append(gain);signed.append(brier(nondir,y)-brier(p,y))
        date=dt.datetime.fromtimestamp(t/1000,UTC).date().isoformat()
        days.setdefault(date,[]).append(gain)
    daily=[statistics.mean(v) for _,v in sorted(days.items())]
    low=(statistics.mean(daily)-1.96*statistics.stdev(daily)/math.sqrt(len(daily))
         if len(daily)>1 else None)
    return {'n_resolved':len(sample),'n_UTC_days':len(days),
      'model_minus_causal_baseline_mean_Brier_gain_positive_is_better':statistics.mean(changes),
      'conditional_signed_Brier_gain_above_identical_total_event_risk':statistics.mean(signed),
      'positive_calendar_days':sum(x>0 for x in daily),
      'descriptive_dayblock_lower95_not_prospective':low}

def evaluate(raw):
    feat=examples(raw);results={}
    for h,(n,threshold) in HORIZONS.items():
        population=[]
        for i,t,x,close,lg in feat:
            if t%(15*60000) or i+n>=len(raw):continue
            maturity=int(raw[i+n][0])+STEP
            y=endpoint_class(close[i],float(raw[i+n][4]),threshold)
            population.append((t,maturity,x,y))
        climate=CausalClimatology(independent_due_climatology_population(population,n))
        weekly=[]
        for fold in FOLDS:
            start=int(fold.timestamp()*1000);end=start+7*DAY
            vstart=start-8*DAY;vend=start-DAY
            train=[(t,x,y) for t,d,x,y in population if d<vstart]
            # Choose BOTH shrink and climatology baseline on the SAME
            # nonoverlapping due-grid used for prospective scoring. Using
            # overlapping 15m validation overweights one future BTC move
            # as many independent-looking labels and can reverse selection.
            valid_overlap=[(t,x,y) for t,d,x,y in population
                           if vstart<=t and d<vend]
            valid=[(t,x,y) for t,x,y in valid_overlap if t%(n*STEP)==0]
            test=[(t,x,y) for t,d,x,y in population
                  if start<=t<end and t%(n*STEP)==0]
            due=7*24*60//(n*5)
            absent=due-len(test)
            if absent<0 or min(len(train),len(valid),len(test))<6:
                raise ValueError('invalid fixed-fold due grid')
            model=fit(train)
            grid_prior=nonoverlap_training_prior(train,n)
            alpha=min(SHRINK,key=lambda a:statistics.mean(
                brier(predict(model,x,a),y) for t,x,y in valid))
            # Baseline selection happens on PREVIOUS validation ONLY.
            chosen=min(BASELINES,key=lambda z:statistics.mean(
                brier(baseline_probability(z,t,grid_prior,climate),y)
                for t,x,y in valid))
            test_score=matched_score(test,model,alpha,chosen,climate,grid_prior)
            weekly.append({
                'week_start_utc':fold.isoformat(),'validation_n':len(valid),
                'validation_overlapping_15m_slots_not_used_for_selection':len(valid_overlap),
                'validation_and_forward_identical_nonoverlap_UTC_grid':True,
                'training_n':len(train),
                'training_nonoverlap_prior':grid_prior,
                'training_nonoverlap_due_count':sum(t%(n*STEP)==0 for t,_,_ in train),
                'fixed_due_expected':due,
                'fixed_due_resolved':len(test),'missing_or_not_yet_mature':absent,
                'entire_fixed_due_grid_complete':absent==0,
                'model_shrink_previous_validation_only':alpha,
                'baseline_selected_previous_validation_only':chosen,
                'nonoverlapping_identical_UTC_forecast_scores':test_score})
            print('ADAPTIVE_REFERENCE',h,str(fold.date()),'baseline',chosen,
                  'alpha',alpha,'n',len(test),'missing',absent,
                  'gain',round(test_score['model_minus_causal_baseline_mean_Brier_gain_positive_is_better'],8),flush=True)
        complete=[w for w in weekly if w['entire_fixed_due_grid_complete']]
        results[h]={
          'weeks':weekly,'complete_forward_weeks':len(complete),
          'weeks_winning_over_selected_matured_baseline':sum(
              w['nonoverlapping_identical_UTC_forecast_scores']['model_minus_causal_baseline_mean_Brier_gain_positive_is_better']>0
              for w in complete),
          'weeks_with_positive_signed_value':sum(
              w['nonoverlapping_identical_UTC_forecast_scores']['conditional_signed_Brier_gain_above_identical_total_event_risk']>0
              for w in complete),
          'missing_fixed_due_total':sum(w['missing_or_not_yet_mature'] for w in weekly)}
    return {'schema':'btc-v7r6-three-horizon-causal-adaptive-climatology-benchmark-v1',
      'all_forward_blocks_already_known_historical':True,
      'competing_baselines':'frozen train prior or prior 7/14 calendar-day matured rolling class frequencies',
      'source_asof_maturity_enforced':True,
      'same_timestamp_maturity_excluded':True,
      'rolling_climatology_uses_nonoverlapping_horizon_UTC_grid':True,
      'training_climatology_uses_same_nonoverlap_UTC_grid':True,
      'model_fit_may_use_overlapping_training_rows':True,
      'no_production_changes':True,'trading_authority':False,'horizons':results}

def run(raw_path,out):
    with gzip.open(raw_path,'rt') as f:raw=json.load(f)
    result=evaluate(raw)
    result['raw_gzip_sha256']=hashlib.sha256(pathlib.Path(raw_path).read_bytes()).hexdigest()
    pathlib.Path(out).write_text(json.dumps(result,sort_keys=True,indent=2,allow_nan=False)+'\n')
    for h,r in result['horizons'].items():
        print('ADAPTIVE_REFERENCE_SUMMARY',h,r['weeks_winning_over_selected_matured_baseline'],
              'wins of',r['complete_forward_weeks'],'fully mature weeks',flush=True)
    return result

if __name__=='__main__':
    cli=argparse.ArgumentParser();cli.add_argument('--raw',required=True);cli.add_argument('--out',required=True)
    args=cli.parse_args();run(args.raw,args.out)
