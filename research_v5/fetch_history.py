import concurrent.futures,datetime,gzip,hashlib,json,time,urllib.request
from pathlib import Path
end=int(datetime.datetime(2026,9,25,tzinfo=datetime.timezone.utc).timestamp()*1000)-1
start=int(datetime.datetime(2024,1,1,tzinfo=datetime.timezone.utc).timestamp()*1000)
parts=[]
for i in range(25):
 e=end-i*1000*3600000
 if e<start:break
 parts.append((i,e))
def fetch(item):
 i,e=item
 u=f'https://data-api.binance.vision/api/v3/klines?symbol=BTCUSDT&interval=1h&limit=1000&endTime={e}'
 for attempt in range(3):
  try:
   req=urllib.request.Request(u,headers={'User-Agent':'btc-regime-evaluation'})
   with urllib.request.urlopen(req,timeout=30) as f:d=json.load(f)
   return i,d
  except Exception:
   if attempt==2:raise
   time.sleep(2*(attempt+1))
with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
 rows=sorted(ex.map(fetch,parts))
flat={int(c[0]):c for _,part in rows for c in part if int(c[0])>=start and int(c[0])<end}
rows=[flat[k] for k in sorted(flat)]
p=Path('research_v5/data/btc_1h_2024_to_sep24_2026.json.gz')
p.parent.mkdir(exist_ok=True)
payload=json.dumps(rows,separators=(',',':')).encode()
assert hashlib.sha256(payload).hexdigest()=='3e78a339e60fec957dea2c0884c6840d66a92351ac04b4198623f1da10165fc9', 'source revision: historical results must be rerun'
with p.open('wb') as f:
 with gzip.GzipFile(fileobj=f,mode='wb',mtime=0,filename='') as z:z.write(payload)
print('saved',len(rows),'first',datetime.datetime.fromtimestamp(rows[0][0]/1000,datetime.timezone.utc),'last',datetime.datetime.fromtimestamp(rows[-1][0]/1000,datetime.timezone.utc),'bytes',p.stat().st_size)
