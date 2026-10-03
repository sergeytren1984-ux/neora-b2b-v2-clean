import gzip,json,math,sys
from datetime import datetime,timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from alert import candidate,warn
root=Path(__file__).resolve().parents[1]
raw=json.loads(gzip.decompress((root/'research_v5/data/btc_1h_2024_to_sep24_2026.json.gz').read_bytes()))
artifact=json.loads((root/'directional_down_v1/artifact.json').read_bytes())
assert len(raw)==23952
cs=[]
for x in raw[-1000:]:
 t=datetime.fromtimestamp(int(x[0])/1000,timezone.utc)
 cs.append({'open_time':t.isoformat(),'close_time':datetime.fromtimestamp(int(x[0])/1000+3600,timezone.utc).isoformat(),
            'open':float(x[1]),'high':float(x[2]),'low':float(x[3]),'close':float(x[4]),
            'volume':float(x[5]),'trades':int(x[8]),'taker_buy_base':float(x[9])})
a=warn(cs,artifact)
p,_=candidate(cs[-169:],artifact)
assert len(cs)==1000 and a['past_scores_count']==720
assert 0<=a['rank_30d']<=1 and 0<p<1 and abs(p-a['candidate_estimate'])<1e-6
assert a['alert']==(a['rank_30d']>=.8)
assert a['excluded_from_numeric_model']
try: warn(cs[-888:],artifact)
except ValueError as e: assert '889' in str(e)
else: raise AssertionError('short history accepted')
assert artifact['raw_sha256']==__import__('hashlib').sha256(gzip.decompress((root/'research_v5/data/btc_1h_2024_to_sep24_2026.json.gz').read_bytes())).hexdigest()
print('directional-down-v1 selftest OK',a['candidate_estimate'],a['rank_30d'])
