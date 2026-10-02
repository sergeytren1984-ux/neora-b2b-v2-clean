from pathlib import Path
exec(Path(__file__).with_name('evaluate_regime.py').read_text().split("print('samples'")[0])
import gzip,bisect,datetime
archive=json.loads(gzip.decompress(Path('research_v5/data/oi_2026_asof_research.json.gz').read_bytes()))
obs=[]
for day,checksum,rows in archive:
 for row in rows:
  try:
   t=datetime.datetime.strptime(row['create_time'],'%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)+datetime.timedelta(minutes=5)
   vals=[float(row[k]) for k in ['sum_open_interest','count_toptrader_long_short_ratio','sum_toptrader_long_short_ratio','count_long_short_ratio','sum_taker_long_short_vol_ratio']]
   if np.isfinite(vals).all() and vals[0]>0:obs.append((t.timestamp(),vals))
  except Exception:pass
obs.sort(key=lambda x:x[0]);times=[x[0] for x in obs]
def at(t):
 j=bisect.bisect_right(times,t)-1
 if j<0 or t-times[j]>900:return None
 return obs[j][1]
idx=[];additional=[]
for i,s in enumerate(dates):
 t=datetime.datetime.fromisoformat(s).timestamp();n=at(t);one=at(t-3600);four=at(t-14400)
 if n is None or one is None or four is None:continue
 add=[100*(n[0]/one[0]-1),100*(n[0]/four[0]-1),*n[1:]]
 if np.isfinite(add).all():idx.append(i);additional.append(add)
idx=np.array(idx);extra=np.array(additional);x=X[idx];allx=np.column_stack([x,extra]);d=dates[idx]
train=(d>='2026-01-08T00:00:00+00:00')&(d<'2026-06-15T00:00:00+00:00');valid=(d>='2026-06-17T00:00:00+00:00')&(d<'2026-09-01T00:00:00+00:00');hold=(d>='2026-09-02T00:00:00+00:00')&(d<'2026-09-23T00:00:00+00:00')
print('coverage',len(idx),'train/valid/hold',sum(train),sum(valid),sum(hold))
from sklearn.metrics import roc_auc_score,brier_score_loss
by_time={c['close_time']:i for i,c in enumerate(cs)}
for task in ('4h_up','4h_tail'):
 if task=='4h_up':y=np.array(labels['4h'])[idx]
 else:y=np.array([100*(cs[by_time[dates[i]]+4]['close']/cs[by_time[dates[i]]]['close']-1)>1 for i in idx],dtype=int)
 for name,z in (('spot',x),('spot_oi',allx)):
  sc=StandardScaler().fit(z[train]);zz=sc.transform(z);m=LogisticRegression(C=0.03,max_iter=500).fit(zz[train],y[train]);p=m.predict_proba(zz)
  for mask,label in ((valid,'valid'),(hold,'hold')):
   if task=='4h_up':
    one=np.eye(3)[y[mask]];score=np.mean(np.sum((p[mask]-one)**2,axis=1));auc=roc_auc_score(y[mask]==2,p[mask,2])
   else:score=brier_score_loss(y[mask],p[mask,1]);auc=roc_auc_score(y[mask],p[mask,1])
   print(task,name,label,'brier',round(score,4),'auc',round(auc,3))
