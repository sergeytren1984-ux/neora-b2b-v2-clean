from datetime import datetime,timezone
from pathlib import Path
import json,sys
import numpy as np
sys.path.insert(0,str(Path('regime_v4').resolve()))
from model import forecast
raw=json.loads(__import__('gzip').decompress(Path('research_v5/data/btc_1h_2024_to_sep24_2026.json.gz').read_bytes()))
cs=[]
for x in raw:
 t=datetime.fromtimestamp(x[0]/1000,timezone.utc)
 cs.append(dict(close_time=datetime.fromtimestamp((x[0]+3600000)/1000,timezone.utc).isoformat(),open_time=t.isoformat(),open=float(x[1]),high=float(x[2]),low=float(x[3]),close=float(x[4]),volume=float(x[5]),trades=int(x[8]),taker_buy_base=float(x[9])))
p=json.loads(Path('regime_v4/protocol.json').read_text());pair={'current':{'factors':{}},'previous':{'factors':{}},'elapsed_seconds':3600,'current_factor_status':{},'previous_factor_status':{}}
records=[]
for i in range(168,len(cs)-24):
 if i%4000==0:print(i,flush=True)
 out=forecast(cs[i-168:i+1],pair,p);ref=cs[i]['close'];records.append((cs[i]['close_time'],out['regime_state'],out['features']['confirmed_breakout'],out['features']['breakout_memory']['age_hours'],*(100*(cs[i+h]['close']/ref-1)>out['horizons'][f'{h}h']['threshold_pct'] for h in (1,4,24))))
rows=[r for r in records if r[0]>='2026-07-02T00:00:00+00:00']
for state in ['UP_TRANSITION','UP_CONTINUATION','UP_EXHAUSTION','RANGE','DOWN_TRANSITION']:
 sub=[r for r in rows if r[1]==state]
 print(state,'N',len(sub),'rate',round(len(sub)/len(rows),3),'up1/4/24',[round(sum(r[k] for r in sub)/len(sub),3) if sub else None for k in (4,5,6)])
print('base',len(rows),[round(sum(r[k] for r in rows)/len(rows),3) for k in (4,5,6)])
