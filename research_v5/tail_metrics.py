from pathlib import Path
exec(Path(__file__).with_name('evaluate_regime.py').read_text().split("print('samples'")[0])
from sklearn.metrics import roc_auc_score,average_precision_score,brier_score_loss
from datetime import datetime,timezone
by_time={c['close_time']:i for i,c in enumerate(cs)}
h=4;threshold=1.0
y=np.array([100*(cs[by_time[d]+h]['close']/cs[by_time[d]]['close']-1)>threshold for d in dates],dtype=int)
sc=StandardScaler().fit(X[train]);z=sc.transform(X);m=LogisticRegression(C=0.03,max_iter=500).fit(z[train],y[train]);pred=m.predict_proba(z)[:,1]
cut=np.quantile(pred[train],0.9)
for mask,name in ((train,'train'),(valid,'valid'),(hold,'historical_holdout')):
 truth=y[mask];p=pred[mask];sig=p>=cut
 print(name,'samples',len(p),'prevalence',round(truth.mean(),4),'Brier',round(brier_score_loss(truth,p),4),'prior Brier',round(brier_score_loss(truth,np.full(len(truth),y[train].mean())),4),'AUC',round(roc_auc_score(truth,p),4),'AP',round(average_precision_score(truth,p),4),'cut',round(cut,4),'signal_rate',round(sig.mean(),4),'precision',round(truth[sig].mean(),4),'recall',round(sig[truth==1].mean(),4),'FPR',round(sig[truth==0].mean(),4))
 for q in range(5):
  lo,hi=np.quantile(p,[q/5,(q+1)/5]);s=(p>=lo)&(p<=hi)
  print('  bin',q,round(p[s].mean(),4),round(truth[s].mean(),4),sum(s))
import hashlib
bundle={'schema':'btc-tail-risk-4h-v1','source':'BINANCE_BTCUSDT_1H_CLOSED','raw_sha256':hashlib.sha256(__import__('gzip').decompress(Path('research_v5/data/btc_1h_2024_to_sep24_2026.json.gz').read_bytes())).hexdigest(),'raw_hours':len(raw),'training_start_utc':'2024-01-01T00:00:00Z','training_end_before_utc':'2026-01-01T00:00:00Z','validation':'2026-01-02 through 2026-06-30','historical_holdout':'2026-07-02 through 2026-09-24 (diagnostic, not independent after inspection)','target':'close[t+4h]/close[t]-1 > 0.01','reference':'closed 1h BTCUSDT Binance spot candle','features':keys,'standard_mean':sc.mean_.tolist(),'standard_scale':sc.scale_.tolist(),'coefficients':m.coef_[0].tolist(),'intercept':float(m.intercept_[0]),'signal_cutoff':float(cut),'regularization_C':0.03,'trading_authority':False}
Path('research_v5/tail_model.json').write_text(json.dumps(bundle,sort_keys=True,indent=2)+'\n')
print('saved',Path('research_v5/tail_model.json').stat().st_size)
