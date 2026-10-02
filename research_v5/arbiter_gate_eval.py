"""Diagnostic only: evaluate a single arbiter gate on pre-October data."""
from pathlib import Path
import os
os.chdir(Path(__file__).resolve().parents[1])
exec(Path('research_v5/evaluate_regime.py').read_text().split("print('samples'")[0])
from sklearn.metrics import brier_score_loss

by_time={c['close_time']:i for i,c in enumerate(cs)}
yup=np.array([100*(cs[by_time[d]+4]['close']/cs[by_time[d]]['close']-1)>1 for d in dates],dtype=bool)
ydn=np.array([100*(cs[by_time[d]+4]['close']/cs[by_time[d]]['close']-1)<-1 for d in dates],dtype=bool)
sc=StandardScaler().fit(X[train]);z=sc.transform(X)
pup=LogisticRegression(C=.03,max_iter=500).fit(z[train],yup[train]).predict_proba(z)[:,1]
pdn=LogisticRegression(C=.03,max_iter=500).fit(z[train],ydn[train]).predict_proba(z)[:,1]
hr=np.asarray(heuristic['4h'])
for mask,name in ((valid,'validation'),(hold,'late_diagnostic')):
    ix=np.flatnonzero(mask)
    ru=np.array([np.mean(pup[i-720:i]<=pup[i]) for i in ix])
    rd=np.array([np.mean(pdn[i-720:i]<=pdn[i]) for i in ix])
    regimes=hr[ix].argmax(axis=1)
    gates={
      'up_tail':ru>=.8,
      'up_tail_regime_range':(ru>=.8)&(regimes==1),
      'up_tail_regime_down':(ru>=.8)&(regimes==0),
      'up_tail_regime_up':(ru>=.8)&(regimes==2),
      'up_only':(ru>=.8)&(rd<.8),
      'up_only_regime_up':(ru>=.8)&(rd<.8)&(regimes==2),
      'up_only_regime_non_down':(ru>=.8)&(rd<.8)&(regimes!=0),
      'regime_up':regimes==2,
    }
    print(name,'n',len(ix),'prevalence',yup[ix].mean(),flush=True)
    for k,g in gates.items():
        n=g.sum(); positives=np.sum(yup[ix]&g)
        print(k,'n',n,'precision',round(positives/n,4) if n else None,
              'recall',round(positives/yup[ix].sum(),4),
              'false_alarm_rate',round(np.mean(g[~yup[ix]]),4),flush=True)
    # Resample complete calendar weeks so overlapping 4h labels are not iid.
    weeks=np.array([datetime.fromisoformat(dates[i]).strftime('%G-W%V') for i in ix])
    groups=[np.flatnonzero(weeks==w) for w in np.unique(weeks)]
    rng=np.random.default_rng(42)
    for k in ('up_tail','up_tail_regime_up'):
        draws=[]
        for _ in range(2000):
            sel=np.concatenate([groups[j] for j in rng.integers(0,len(groups),len(groups))])
            g=gates[k][sel]
            if g.sum()==0:continue
            yy=yup[ix][sel]
            draws.append(yy[g].mean()-yy.mean())
        print('weekly_bootstrap',k,'lift_precision_minus_prevalence',
              np.round(np.quantile(draws,[.025,.5,.975]),4).tolist(),flush=True)
