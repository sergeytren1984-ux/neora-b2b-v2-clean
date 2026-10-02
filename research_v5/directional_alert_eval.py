"""Research-only prospective candidate: symmetric 4h >1% directional alerts.

Uses training data through 2025, validation in H1 2026, late historical
diagnostics in Q3 2026. October is a seen, diagnostic stress episode.
"""
from pathlib import Path
import gzip, json, hashlib
exec(Path(__file__).with_name('evaluate_regime.py').read_text().split("print('samples'")[0])
from sklearn.metrics import roc_auc_score, brier_score_loss

by_time={c['close_time']:i for i,c in enumerate(cs)}
sc=StandardScaler().fit(X[train]); z=sc.transform(X)
models={}
for direction,sgn in [('rise',1),('fall',-1)]:
    y=np.array([100*sgn*(cs[by_time[d]+4]['close']/cs[by_time[d]]['close']-1)>1 for d in dates],dtype=int)
    m=LogisticRegression(C=0.03,max_iter=500).fit(z[train],y[train])
    scores=m.predict_proba(z)[:,1]
    models[direction]=(m,scores)
    for mask,name in [(valid,'validation'),(hold,'late_diagnostic')]:
        ix=np.flatnonzero(mask)
        ranks=np.array([float(np.mean(scores[max(0,i-720):i]<=scores[i])) for i in ix])
        truth=y[ix]; alert=ranks>=0.8
        print(direction,name,'n',len(ix),'prevalence',round(truth.mean(),4),
              'auc',round(roc_auc_score(truth,scores[ix]),4),
              'brier',round(brier_score_loss(truth,scores[ix]),4),
              'prior_brier',round(brier_score_loss(truth,np.full(len(ix),y[train].mean())),4),
              'alert_rate',round(alert.mean(),4),'precision',round(truth[alert].mean(),4),
              'recall',round(alert[truth==1].mean(),4),
              'false_alarm_rate',round(alert[truth==0].mean(),4))

live=json.loads(gzip.decompress(Path('research_v5/data/epoch5_20261002T080000Z.json.gz').read_bytes()))
bars=json.loads(live['captures'][0]['raw'])
additional=[]
for bar in bars:
    t=datetime.fromtimestamp(int(bar[0])/1000,timezone.utc)
    if t<datetime(2026,9,25,tzinfo=timezone.utc): continue
    if t>=datetime(2026,10,2,8,tzinfo=timezone.utc): continue
    additional.append({'open_time':t.isoformat(),'close_time':datetime.fromtimestamp(int(bar[0])/1000+3600,timezone.utc).isoformat(),
                       'open':float(bar[1]),'high':float(bar[2]),'low':float(bar[3]),'close':float(bar[4]),
                       'volume':float(bar[5]),'trades':int(bar[8]),'taker_buy_base':float(bar[9])})
full=cs+additional
seen=set()
full=[c for c in full if not (c['close_time'] in seen or seen.add(c['close_time']))]
full.sort(key=lambda c:c['close_time'])
diag={}
prospective_scores={direction:list(scores[-720:]) for direction,(_,scores) in models.items()}
for i in range(len(cs),len(full)):
    if i<168 or any((datetime.fromisoformat(full[j]['open_time'])-datetime.fromisoformat(full[j-1]['open_time'])).total_seconds()!=3600 for j in range(i-168,i+1)):
        continue
    f=forecast(full[i-168:i+1],pair,protocol)['features']
    v=np.array([float(f[k]) for k in keys]).reshape(1,-1)
    vals={}
    for direction,(model,scores) in models.items():
        p=float(model.predict_proba(sc.transform(v))[0,1])
        past=np.asarray(prospective_scores[direction][-720:])
        vals[direction]={'p':round(p,4),'rank':round(float(np.mean(past<=p)),4),'alert':bool(np.mean(past<=p)>=0.8)}
        prospective_scores[direction].append(p)
    diag[full[i]['close_time']]={'price':full[i]['close'],'signals':vals}
for when in ['2026-10-01T18:00:00+00:00','2026-10-02T08:00:00+00:00']:
    print('diagnostic',when,diag.get(when))
