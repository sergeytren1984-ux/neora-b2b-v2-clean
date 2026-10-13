"""Macro HTTP collection with explicit receipts and no proxy substitutions."""
import base64,concurrent.futures,datetime as dt,hashlib,json,urllib.parse,urllib.request
from macro_quote_adapter import replay,SYMBOLS
from calendar_ingest import parse

BLS='https://www.bls.gov/schedule/news_release/bls.ics'

def now():return dt.datetime.now(dt.timezone.utc)

def http(url):
    start=now();req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0 BTC-factor-evidence/1.0','Accept':'*/*'})
    with urllib.request.urlopen(req,timeout=20) as response:
        raw=response.read(2000001)
        if len(raw)>2000000:raise ValueError('publisher response too large')
        status=response.status;final=response.geturl()
    return raw,{'requested_url':url,'final_url':final,'http_status':status,'request_started_utc':start.isoformat(),
        'retrieved_at_utc':now().isoformat(),'sha256':hashlib.sha256(raw).hexdigest(),'raw_response_b64':base64.b64encode(raw).decode()}

def quote(name):
    symbol=SYMBOLS[name];span='5d' if name=='us10y' else '1d'
    url='https://query1.finance.yahoo.com/v8/finance/chart/'+urllib.parse.quote(symbol,safe='')+'?'+urllib.parse.urlencode({'interval':'5m','range':span,'includePrePost':'true'})
    raw,receipt=http(url);result=json.loads(raw)['chart']['result'][0]
    times=result.get('timestamp') or [];values=(result.get('indicators',{}).get('quote') or [{}])[0].get('close') or []
    points=[(t,v) for t,v in zip(times,values) if v is not None];meta=result['meta']
    t,v=points[-1] if points else (meta.get('regularMarketTime'),meta.get('regularMarketPrice'))
    if t is None or v is None:raise ValueError('no provider quote')
    factor={'status':'VALID','value':float(v),'source_timestamp_utc':dt.datetime.fromtimestamp(int(t),dt.timezone.utc).isoformat(),
        'receipt':receipt,'source':'YAHOO_'+symbol,'symbol':symbol,'unit':'publisher_quoted_index_or_futures_price',
        'not_a_DGS10_or_NASDAQ100_cash_substitution':True}
    replay(factor,symbol);return factor

def calendar():
    raw,receipt=http(BLS)
    if receipt['http_status']!=200 or urllib.parse.urlparse(receipt['final_url']).hostname not in ('www.bls.gov','bls.gov'):raise ValueError('official calendar source rejected')
    r={'source':BLS,'received_at_utc':receipt['retrieved_at_utc'],'sha256':receipt['sha256']}
    events=parse(raw,r)
    return {'status':'VALID','scope':'BLS official calendar only','receipt':receipt,'calendar_receipt':r,
        'events':events,'covers_all_required_macro_events':False,'consensus_available':False,'surprises_available':False}

def collect():
    start=now();factors={}
    calls={**{name:(lambda name=name:quote(name)) for name in SYMBOLS},'bls_calendar':calendar}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures={name:pool.submit(fn) for name,fn in calls.items()}
        for name,future in futures.items():
            try:factors[name]=future.result()
            except Exception as e:factors[name]={'status':'UNAVAILABLE','value':None,'error':type(e).__name__}
    return {'schema':'btc-pinned-macro-capture-v1','collection_started_utc':start.isoformat(),
        'inputs_received_at_utc':now().isoformat(),'factors':factors,'immutable_collector_checkout_required':True,
        'trading_authority':False,'full_system_ready':False,'predictive_skill_proven':False}
