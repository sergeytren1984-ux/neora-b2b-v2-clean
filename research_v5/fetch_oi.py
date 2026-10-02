import concurrent.futures,datetime,hashlib,io,zipfile,urllib.request,csv,json,gzip,time
from pathlib import Path
start=datetime.date(2026,1,1);end=datetime.date(2026,9,24)
days=[start+datetime.timedelta(days=i) for i in range((end-start).days+1)]
def fetch(day):
 u=f'https://data.binance.vision/data/futures/um/daily/metrics/BTCUSDT/BTCUSDT-metrics-{day}.zip'
 for k in range(3):
  try:
   with urllib.request.urlopen(urllib.request.Request(u,headers={'User-Agent':'btc-regime-research'}),timeout=35) as f:b=f.read()
   with zipfile.ZipFile(io.BytesIO(b)) as z:rows=list(csv.DictReader(io.StringIO(z.read(z.namelist()[0]).decode())))
   return str(day),hashlib.sha256(b).hexdigest(),rows
  except Exception as e:
   if k==2:return str(day),None,str(e)
   time.sleep(1+k)
out=[]
with concurrent.futures.ThreadPoolExecutor(max_workers=12) as ex:
 for i,result in enumerate(ex.map(fetch,days),1):
  out.append(result)
  if i%40==0:print('downloaded',i,'of',len(days),flush=True)
p=Path('research_v5/data/oi_2026_asof_research.json.gz')
with p.open('wb') as f:
 with gzip.GzipFile(fileobj=f,mode='wb',mtime=0,filename='') as z:z.write(json.dumps(out,separators=(',',':')).encode())
print('days',len(out),'failures',[(x[0],x[2]) for x in out if x[1] is None][:12],'bytes',p.stat().st_size)
