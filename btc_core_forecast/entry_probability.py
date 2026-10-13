"""Fixed calibrated probability of obtaining more BTC after delayed execution.

One diagnostic specification, no threshold search, no prospective claim.
Isotonic calibration uses only the completed purged calibration period.
"""
import argparse,pathlib
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.isotonic import IsotonicRegression
import forecast as f
import walkforward as w

def realized_gain(close, scales, spot, wait, premium=350., budget=147600.):
    # Actions have DIFFERENT execution times; never use current spot as fill.
    buy=spot*np.exp(close[:,0]*scales)+premium
    later=spot*np.exp(close[:,wait]*scales)+premium
    return budget/later-budget/buy

def fit(x,gain,tr,ca):
    labels=(gain>0).astype(int)
    classifier=HistGradientBoostingClassifier(loss='log_loss',learning_rate=.035,
        max_iter=100,max_leaf_nodes=7,min_samples_leaf=150,l2_regularization=10,random_state=60113)
    classifier.fit(x[tr],labels[tr])
    p=classifier.predict_proba(x[ca])[:,1]
    calibrator=IsotonicRegression(out_of_bounds='clip',y_min=0.,y_max=1.)
    calibrator.fit(p,labels[ca])
    positive=gain[ca][labels[ca]==1];negative=gain[ca][labels[ca]==0]
    if not len(positive) or not len(negative):raise ValueError('both calibration outcome classes required')
    return classifier,calibrator,float(positive.mean()),float(negative.mean()),float(labels[ca].mean())

def run(array_file,out):
    a=dict(np.load(array_file,allow_pickle=False));out=pathlib.Path(out);out.mkdir(parents=True,exist_ok=True)
    result={'schema':'btc-fixed-entry-probability-diagnostic-v1','historical_only':True,
        'all_history_previously_seen':True,'trading_authority':False,'actual_OTC_quotes':False,
        'R6_and_macro_numeric_inputs':False,'rule':'calibrated probability >0.60 AND estimated BTC gain >0',
        'calibration':'purged isotonic; class magnitudes in BTC/USDT-normalized units', 'folds':{}}
    for start,end in w.FOLDS:
        tr,ca,te=w.split(a['anchors'],start,end);fold={}
        for wait in w.HORIZONS:
            # Normalizing by budget/anchor price avoids fitting changing BTC units.
            gain=realized_gain(a['close'],a['scales'],a['spot'],wait)
            units=147600/a['spot'];normalized=gain/units
            classifier,calibrator,pos,neg,base=fit(a['x'],normalized,tr,ca)
            p=calibrator.predict(classifier.predict_proba(a['x'][te])[:,1])
            expected=p*pos+(1-p)*neg
            signals=(p>.60)&(expected>0)
            chosen=np.where(signals,gain[te],0.)
            truth=(gain[te]>0).astype(float)
            aa=a['anchors'][te]
            brier_delta=(base-truth)**2-(p-truth)**2
            logloss=lambda q:-(truth*np.log(np.clip(q,1e-8,1-1e-8))+(1-truth)*np.log(np.clip(1-q,1e-8,1-1e-8)))
            fold[str(wait)]={'signals':int(signals.sum()),'p_min':float(p.min()),'p_max':float(p.max()),
                'accuracy_among_signals':float(truth[signals].mean()) if signals.any() else None,
                'brier_gain':f.daily_stats(brier_delta,aa),
                'logloss_gain':f.daily_stats(logloss(base)-logloss(p),aa),
                'vs_buy_now':f.daily_stats(chosen,aa),'vs_always_wait':f.daily_stats(chosen-gain[te],aa)}
            print('ENTRY_PROBABILITY',start[:10],wait,fold[str(wait)]['signals'],
                round(chosen.mean(),8),round((chosen-gain[te]).mean(),8),flush=True)
        result['folds'][start[:10]]=fold;f.write(out/'diagnostic.json',result)
    result['all_horizons_all_folds_positive_vs_both']=all(v['vs_buy_now']['среднее_улучшение']>0 and v['vs_always_wait']['среднее_улучшение']>0
        for fold in result['folds'].values() for v in fold.values())
    result['all_horizons_all_folds_brier_positive']=all(v['brier_gain']['среднее_улучшение']>0 for fold in result['folds'].values() for v in fold.values())
    f.write(out/'diagnostic.json',result)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--arrays',required=True);p.add_argument('--output',required=True)
    args=p.parse_args();run(args.arrays,args.output)
