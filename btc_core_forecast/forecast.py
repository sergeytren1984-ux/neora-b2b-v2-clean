"""Joint BTC path research candidate. No trade authority or prospective claim."""
from __future__ import annotations
import argparse, datetime as dt, gzip, hashlib, json, pathlib
import numpy as np

STEP=300000
HOURS=72
RIDGE=100.
TRAIN_END='2026-09-28T00:00:00+00:00'
CAL_END='2026-10-05T00:00:00+00:00'
MIN_DAYS=28
UTC=dt.timezone.utc

def stamp(s):
    v=dt.datetime.fromisoformat(s.replace('Z','+00:00'))
    if v.tzinfo is None: raise ValueError('timezone required')
    return int(v.timestamp()*1000)

def iso(t): return dt.datetime.fromtimestamp(int(t)/1000,UTC).isoformat()

def write(path,obj):
    pathlib.Path(path).write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False)+'\n')

def read(path,asof=None):
    p=pathlib.Path(path)
    with gzip.open(p,'rt') if p.suffix=='.gz' else p.open() as stream:
        rows=json.load(stream)
    if not isinstance(rows,list) or not rows: raise ValueError('nonempty kline array required')
    if asof is not None: rows=[r for r in rows if int(r[6])+1<=asof]
    if len(rows)<290: raise ValueError('24h closed history required')
    a=np.asarray([[float(r[k]) for k in (0,1,2,3,4,5,6,8,9)] for r in rows])
    if not np.all(np.isfinite(a)): raise ValueError('nonfinite raw value')
    t=a[:,0].astype(np.int64)+STEP
    if not np.all(np.diff(t)==STEP): raise ValueError('missing or duplicated candles')
    if not np.all(a[:,6]+1==t): raise ValueError('invalid close boundary')
    o,h,l,c=a[:,1],a[:,2],a[:,3],a[:,4]
    if np.any(l<=0) or np.any(l>np.minimum(o,c)) or np.any(h<np.maximum(o,c)):
        raise ValueError('invalid OHLC')
    if np.any(a[:,5]<0) or np.any(a[:,7]<0) or np.any(a[:,8]<0) or np.any(a[:,8]>a[:,5]):
        raise ValueError('invalid volume/taker count')
    return t,a

def feature(a,i,t):
    # Restrict computation to required as-of window, never scan the full dataset.
    a=a[i-288:i+1];i=288
    z=np.log(a[:,4]); v=a[:,5]; buy=a[:,8]
    f=[]
    for n in (3,12,48,288):
        w=np.diff(z[i-n:i+1]); total=v[i-n+1:i+1].sum()
        f.extend([z[i]-z[i-n],np.sqrt(np.mean(w*w)),
                  2*buy[i-n+1:i+1].sum()/max(total,1e-12)-1,
                  abs(w.sum())/max(np.abs(w).sum(),1e-12)])
    f.extend([np.log(max(v[i-11:i+1].sum(),1e-12)/max(v[i-47:i+1].sum()/4,1e-12)),
              np.log(a[i,4]/a[i-47:i+1,2].max()),
              np.log(a[i,4]/a[i-47:i+1,3].min())])
    hour=(int(t)//3600000)%24
    f.extend([np.sin(2*np.pi*hour/24),np.cos(2*np.pi*hour/24)])
    # 24h realized per-bar volatility; only known closed candles.
    sigma=max(float(np.sqrt(np.mean(np.diff(z[i-288:i+1])**2))),1e-6)
    return np.asarray(f),sigma

def arrays(t,a):
    idx=np.asarray([i for i in range(288,len(a)-HOURS*12) if t[i]%3600000==0])
    if not len(idx): raise ValueError('no complete 72h labels')
    x=[]; scales=[]; close=[]; high=[]; low=[]
    for i in idx:
        fx,s=feature(a,i,t[i]); x.append(fx);scales.append(s)
        close.append(np.log(a[i+np.arange(1,HOURS+1)*12,4]/a[i,4])/s)
        high.append([np.log(a[i+(h-1)*12+1:i+h*12+1,2].max()/a[i,4])/s for h in range(1,HOURS+1)])
        low.append([np.log(a[i+(h-1)*12+1:i+h*12+1,3].min()/a[i,4])/s for h in range(1,HOURS+1)])
    return idx,np.asarray(x),np.asarray(scales),np.asarray(close),np.asarray(high),np.asarray(low)

def fit(x,y):
    mu=x.mean(0);sd=np.maximum(x.std(0),1e-6)
    xx=np.column_stack([np.ones(len(x)),np.clip((x-mu)/sd,-6,6)])
    penalty=np.eye(xx.shape[1])*RIDGE;penalty[0,0]=0
    coef=np.linalg.solve(xx.T@xx+penalty,xx.T@y)
    return mu,sd,coef

def predict(model,x):
    return np.column_stack([np.ones(len(x)),np.clip((x-model['mu'])/model['sd'],-6,6)])@model['coef']

def paths(model,x,sigma,baseline=False):
    location=np.zeros(HOURS) if baseline else predict(model,x[None,:])[0]
    prefix='base_' if baseline else 'res_'
    return tuple(sigma*(model[prefix+k]+location) for k in ('close','high','low'))

def crps(samples,actual):
    s=np.sort(samples);n=len(s)
    return float(np.mean(np.abs(s-actual))-np.sum((2*np.arange(1,n+1)-n-1)*s)/(n*n))

def first_passage(high,low,lower=-.02,upper=.05,hours=72):
    if not (-1<lower<0<upper) or not 1<=hours<=HOURS: raise ValueError('invalid barriers/horizon')
    up=high[:,:hours]>=np.log1p(upper);down=low[:,:hours]<=np.log1p(lower)
    u=np.where(up.any(1),up.argmax(1),hours)
    d=np.where(down.any(1),down.argmax(1),hours)
    classes=np.where((u==hours)&(d==hours),2,np.where(u<d,0,np.where(d<u,1,3)))
    return classes

def economic(close,spot,budget,premium,delay_hours,wait_hours):
    if not (np.isfinite([spot,budget,premium]).all() and spot>0 and budget>0 and premium>=0):
        raise ValueError('invalid execution assumptions')
    if isinstance(delay_hours,bool) or isinstance(wait_hours,bool): raise ValueError('integer hours required')
    if int(delay_hours)!=delay_hours or int(wait_hours)!=wait_hours or delay_hours<1 or wait_hours<1 or delay_hours+wait_hours>HOURS:
        raise ValueError('execution hours outside path')
    now=spot*np.exp(close[:,int(delay_hours)-1])+premium
    later=spot*np.exp(close[:,int(delay_hours+wait_hours)-1])+premium
    delta=budget/later-budget/now
    return {'средняя_разница_БТК':float(delta.mean()),'вероятность_получить_больше_БТК':float((delta>0).mean()),
            'квантиль_05_разницы_БТК':float(np.quantile(delta,.05)),
            'квантиль_95_разницы_БТК':float(np.quantile(delta,.95)),
            'реальные_котировки_оператора':False,'решение':'НЕ ДОПУЩЕНО К ТОРГОВЛЕ'}

def summary(model,x,sigma,spot,anchor,budget=147600.,premium=350.):
    c,h,l=paths(model,x,sigma)
    out={'момент_закрытия_исходных_данных_МСК':dt.datetime.fromtimestamp(anchor/1000,UTC).astimezone(dt.timezone(dt.timedelta(hours=3))).isoformat(),
         'статус':'ИССЛЕДОВАТЕЛЬСКИЙ КАНДИДАТ','торговая_готовность':False,
         'вероятности_проверены_на_будущих_данных':False,'исходная_цена':float(spot),
         'число_зависимых_калибровочных_траекторий':len(c),'прогноз_цены':{},'возврат_ядра':{},'ожидание':{}}
    for hours,barrier in ((1,.007),(4,.012),(24,.02)):
        s=c[:,hours-1];p=spot*np.exp(s)
        out['прогноз_цены'][str(hours)+'ч']={'медиана':float(np.median(p)),
            'квантиль_10':float(np.quantile(p,.1)),'квантиль_90':float(np.quantile(p,.9)),
            'вероятность_роста_выше_порога':float((s>=np.log1p(barrier)).mean()),
            'вероятность_снижения_ниже_порога':float((s<=np.log1p(-barrier)).mean()),
            'вероятность_небольшого_изменения':float(((s>np.log1p(-barrier))&(s<np.log1p(barrier))).mean()),
            'порог_в_процентах':barrier*100}
    for hours in (24,48,72):
        cls=first_passage(h,l,hours=hours)
        draw=np.exp(l[:,:hours].min(1))-1
        out['возврат_ядра'][str(hours)+'ч']={'снижение_на_2проц_раньше_роста_на_5проц':float((cls==1).mean()),
            'рост_раньше_снижения':float((cls==0).mean()),'оба_уровня_не_достигнуты':float((cls==2).mean()),
            'порядок_внутри_часа_неизвестен':float((cls==3).mean()),
            'квантиль_10_минимальной_доходности':float(np.quantile(draw,.1))}
    for wait in (1,4,24):
        out['ожидание'][str(wait)+'ч']=economic(c,spot,budget,premium,1,wait)
    out['условия_исполнения']={'задержка_часы':1,'капитал_УСДТ':budget,'надбавка_УСДТ_за_БТК':premium,
        'надбавка_гипотетическая':True,'отказы_и_частичные_исполнения_не_оценены':True}
    out['цель_90000_100000']='Долгосрочная оценка не реализована в горизонте 72 часа'
    return out

def daily_stats(gain,anchors):
    keys=anchors//86400000;days=np.unique(keys)
    means=np.array([gain[keys==d].mean() for d in days])
    # Dependent day blocks: descriptive moving 3-day block bootstrap, no admission.
    rng=np.random.default_rng(60113);n=len(means)
    if n<3: bounds=None
    else:
        blocks=np.array([means[j:j+3] for j in range(n-2)])
        boot=np.array([blocks[rng.integers(len(blocks),size=int(np.ceil(n/3)))].ravel()[:n].mean() for _ in range(1000)])
        bounds=np.quantile(boot,[.025,.975]).tolist()
    return {'среднее_улучшение':float(gain.mean()),'число_суток':n,
        'интервал_по_зависимым_блокам_описательный':bounds,'независимое_доказательство':False}

def evaluate(model,x,scales,close,high,low,spot,anchors):
    report={};prices={h:[] for h in (1,4,24)};gains={h:[] for h in prices}
    brier=[];economic_gain=[];wait_count=0
    for j in range(len(x)):
        c,h,l=paths(model,x[j],scales[j]);bc,bh,bl=paths(model,x[j],scales[j],True)
        actual=close[j]*scales[j]
        for horizon in prices:
            truth=spot[j]*np.exp(actual[horizon-1]);s=spot[j]*np.exp(c[:,horizon-1]);bs=spot[j]*np.exp(bc[:,horizon-1])
            q=np.quantile(s,[.1,.5,.9]);err=abs(q[1]-truth)
            prices[horizon].append([err,abs(spot[j]-truth),crps(s,truth),crps(bs,truth),float(q[0]<=truth<=q[2])])
            gains[horizon].append(abs(spot[j]-truth)-err)
        cls=int(first_passage(high[j:j+1]*scales[j],low[j:j+1]*scales[j])[0])
        pred=first_passage(h,l);base=first_passage(bh,bl)
        pp=np.bincount(pred,minlength=4)/len(pred);bp=np.bincount(base,minlength=4)/len(base)
        yy=np.eye(4)[cls];brier.append(float(np.sum((bp-yy)**2)-np.sum((pp-yy)**2)))
        e=economic(c,spot[j],147600.,350.,1,24)
        # A research rule, never live authority. 5% scenario quantile must be positive.
        wait=e['квантиль_05_разницы_БТК']>0
        wait_count+=int(wait)
        actual_gain=147600./(spot[j]*np.exp(actual[24])+350.)-147600./(spot[j]*np.exp(actual[0])+350.)
        economic_gain.append(float(actual_gain if wait else 0.))
    for hours,values in prices.items():
        vals=np.array(values)
        report[str(hours)+'ч']={'МАО_модель':float(vals[:,0].mean()),'МАО_сохранение_цены':float(vals[:,1].mean()),
            'КРПС_модель':float(vals[:,2].mean()),'КРПС_волатильностная_база':float(vals[:,3].mean()),
            'покрытие_интервала_80проц':float(vals[:,4].mean()),
            'выигрыш_МАО':daily_stats(np.array(gains[hours]),anchors)}
    return {'прогноз_цены':report,'порядок_барьеров_выигрыш_Брайера':daily_stats(np.array(brier),anchors),
        'условное_ожидание_24ч':{'срабатываний':wait_count,'выигрыш_БТК':daily_stats(np.array(economic_gain),anchors)},
        'полнота_будущих_наблюдений':False,'торговая_готовность':False,
        'причины_недопуска':['Вся история уже использована прежними исследованиями',
            'Нет заранее опубликованных прогнозов нового кандидата',
            'Нет фактических котировок, отказов и исполнений оператора',
            'Нет исторических макрофакторов с доказанным временем доступности']}

def train(raw,outdir):
    out=pathlib.Path(outdir);out.mkdir(parents=True,exist_ok=True)
    t,a=read(raw);idx,x,scales,c,h,l=arrays(t,a);anchors=t[idx]
    end=anchors+HOURS*3600000;cut=stamp(TRAIN_END);calcut=stamp(CAL_END)
    tr=np.flatnonzero(end<cut);ca=np.flatnonzero((anchors>=cut)&(end<calcut));te=np.flatnonzero(anchors>=calcut)
    if min(len(tr),len(ca),len(te))<48: raise ValueError('insufficient separated labels')
    mu,sd,coef=fit(x[tr],c[tr]);model={'mu':mu,'sd':sd,'coef':coef}
    loc=predict(model,x[ca])
    for k,y in (('close',c),('high',h),('low',l)):
        model['res_'+k]=y[ca]-loc;model['base_'+k]=y[ca]
    np.savez_compressed(out/'candidate.npz',**model)
    results=evaluate(model,x[te],scales[te],c[te],h[te],l[te],a[idx[te],4],anchors[te])
    rawhash=hashlib.sha256(pathlib.Path(raw).read_bytes()).hexdigest()
    modelhash=hashlib.sha256((out/'candidate.npz').read_bytes()).hexdigest()
    manifest={'schema':'btc-core-joint-path-research-v1','training_end_exclusive':TRAIN_END,'calibration_end_exclusive':CAL_END,
        'last_train_label_end':iso(end[tr].max()),'last_calibration_label_end':iso(end[ca].max()),
        'source_sha256':rawhash,'model_sha256':modelhash,
        'code_sha256':hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest(),
        'train_n':len(tr),'calibration_n':len(ca),'diagnostic_n':len(te),
        'calibration_days':len(np.unique(anchors[ca]//86400000)),'test_days':len(np.unique(anchors[te]//86400000)),
        'horizon_hours':HOURS,'ridge':RIDGE,'features':'closed spot OHLCV and taker buy; no fabricated R6/OI/macro',
        'r6_used_as_feature':False,'history_already_seen':True,'min_future_calendar_days':MIN_DAYS,
        'trading_authority':False,'prospective_skill_proven':False,
        'price_grid_hourly':True,'intrahour_barrier_order_unknown':True}
    write(out/'manifest.json',manifest);write(out/'historical_diagnostic.json',results)
    f,s=feature(a,len(a)-1,t[-1]);write(out/'last_historical_forecast.json',summary(model,f,s,a[-1,4],int(t[-1])))
    print(json.dumps({'counts':[len(tr),len(ca),len(te)],'test_days':manifest['test_days'],
        'mae_gain':{k:v['выигрыш_МАО']['среднее_улучшение'] for k,v in results['прогноз_цены'].items()},'trade_ready':False},ensure_ascii=False))

def load_model(directory,asof=None):
    d=pathlib.Path(directory);meta=json.loads((d/'manifest.json').read_text())
    if hashlib.sha256((d/'candidate.npz').read_bytes()).hexdigest()!=meta['model_sha256']: raise ValueError('model hash mismatch')
    if hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest()!=meta['code_sha256']:raise ValueError('frozen code hash mismatch')
    if asof is not None and asof<stamp(meta['calibration_end_exclusive']):
        raise ValueError('model calibration was not available at requested time')
    return dict(np.load(d/'candidate.npz',allow_pickle=False))

def main():
    p=argparse.ArgumentParser();sub=p.add_subparsers(dest='action',required=True)
    tr=sub.add_parser('train');tr.add_argument('--raw',required=True);tr.add_argument('--output',required=True)
    fo=sub.add_parser('forecast');fo.add_argument('--raw',required=True);fo.add_argument('--model',required=True)
    fo.add_argument('--asof',required=True);fo.add_argument('--output',required=True)
    fo.add_argument('--budget',type=float,default=147600.);fo.add_argument('--premium',type=float,default=350.)
    args=p.parse_args()
    if args.action=='train':train(args.raw,args.output)
    else:
        boundary=stamp(args.asof);t,a=read(args.raw,boundary)
        if boundary-int(t[-1])>STEP:raise ValueError('stale closed candles')
        f,s=feature(a,len(a)-1,t[-1]);m=load_model(args.model,int(t[-1]))
        write(args.output,summary(m,f,s,a[-1,4],int(t[-1]),args.budget,args.premium))

if __name__=='__main__':main()
