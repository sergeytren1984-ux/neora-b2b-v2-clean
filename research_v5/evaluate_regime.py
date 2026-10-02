from datetime import datetime,timezone
from pathlib import Path
import gzip,json,sys,time
import numpy as np
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss
sys.path.insert(0,str(Path('regime_v4').resolve()))
from model import forecast
raw=json.loads(gzip.decompress(Path('research_v5/data/btc_1h_2024_to_sep24_2026.json.gz').read_bytes()))
features=[]; dates=[]; prices=[]; heuristic={h:[] for h in ('1h','4h','24h')}; labels={h:[] for h in ('1h','4h','24h')}
keys=['technical','structure','flow','transition','breakout','persistence','change_point','trend_quality','ema_alignment','exhaustion','confirmed_breakout','atr24_pct','ret_1h','ret_3h','ret_6h','ret_12h','ret_24h','taker_imbalance_1h','taker_imbalance_4h','stretch_from_ema24_atr']
protocol=json.loads(Path('regime_v4/protocol.json').read_text())
pair={'current':{'factors':{}},'previous':{'factors':{}},'elapsed_seconds':3600,'current_factor_status':{},'previous_factor_status':{}}
cs=[]
for x in raw:
 opened=datetime.fromtimestamp(int(x[0])/1000,timezone.utc)
 cs.append({'open_time':opened.isoformat(),'close_time':datetime.fromtimestamp((int(x[0])+3600000)/1000,timezone.utc).isoformat(),'open':float(x[1]),'high':float(x[2]),'low':float(x[3]),'close':float(x[4]),'volume':float(x[5]),'trades':int(x[8]),'taker_buy_base':float(x[9])})
start=time.monotonic()
for i in range(168,len(cs)-24):
 if i%4000==0: print('features',i,'seconds',round(time.monotonic()-start),flush=True)
 if any((datetime.fromisoformat(cs[j]['open_time'])-datetime.fromisoformat(cs[j-1]['open_time'])).total_seconds()!=3600 for j in range(i-168,i+25)):
  continue
 out=forecast(cs[i-168:i+1],pair,protocol);f=out['features'];p=cs[i]['close']
 dates.append(cs[i]['close_time']);prices.append(p);features.append([float(f[k]) for k in keys])
 for h,n in [('1h',1),('4h',4),('24h',24)]:
  z=out['horizons'][h];q=z['probabilities'];heuristic[h].append([q['downside'],q['range'],q['upside']])
  ret=100*(cs[i+n]['close']/p-1);th=z['threshold_pct']
  labels[h].append(2 if ret>th else 0 if ret< -th else 1)
X=np.array(features);dates=np.array(dates);prices=np.array(prices)
train=dates<'2026-01-01T00:00:00+00:00';valid=(dates>='2026-01-02T00:00:00+00:00')&(dates<'2026-07-01T00:00:00+00:00');hold=dates>='2026-07-02T00:00:00+00:00'
print('samples',len(X),'train',sum(train),'validation',sum(valid),'historical_holdout',sum(hold),flush=True)
models={}
for h in ('1h','4h','24h'):
 y=np.array(labels[h]);old=np.array(heuristic[h]);sc=StandardScaler().fit(X[train]);xs=sc.transform(X)
 for c in (0.03,0.3,3.0):
  m=LogisticRegression(C=c,max_iter=500).fit(xs[train],y[train]);pred=m.predict_proba(xs)
  def score(p,mask):
   yy=y[mask];pp=p[mask]
   one=np.eye(3)[yy]
   return [round(float(np.mean(np.sum((pp-one)**2,axis=1))),4),round(float(log_loss(yy,pp,labels=[0,1,2])),4),round(float(np.mean(pp.argmax(axis=1)==yy)),4),round(float(np.mean((pp.argmax(axis=1)==2)&(yy==1))),4)]
  print(h,'C',c,'valid',score(pred,valid),'historical_holdout',score(pred,hold),flush=True)
  if c==0.3:models[h]=(sc,m,pred)
 print(h,'HEURISTIC','valid',score(old,valid),'historical_holdout',score(old,hold),flush=True)
 yy=y[hold];idx=np.where(hold)[0];tr=(X[idx,keys.index('ret_24h')]<0.5)&(yy==2)
 for name,pp in [('RIDGE',models[h][2]),('HEURISTIC',old)]:
  print(h,name,'transition up N',int(sum(tr)),'recall',round(float(np.mean(pp[idx][tr].argmax(axis=1)==2)),4),'pred_up_rate',round(float(np.mean(pp[idx].argmax(axis=1)==2)),4),flush=True)
print('elapsed',round(time.monotonic()-start),flush=True)
