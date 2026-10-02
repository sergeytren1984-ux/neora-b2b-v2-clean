from datetime import datetime, timezone
from copy import deepcopy
from rules import decide

a=datetime(2026,10,2,15,tzinfo=timezone.utc);s="20261002T150000Z";due="2026-10-02T19:00:00+00:00"
d={"type":"DIRECTIONAL_4H_ALERT_ISSUED","slot":s,"idempotency_key":"alert:"+s,"due_utc":due,"reference_price":85686.93,
   "output":{"rank_30d":0.943056,"candidate_estimate":0.129219,"cutoff_rank":0.8,"past_scores_count":720,"alert":True}}
v={"type":"REGIME_FORECAST_ISSUED","slot":s,"idempotency_key":"regime:"+s,"reference_price":85686.93,
   "output":{"horizons":{"4h":{"due_utc":due,"shadow_class_scores":{"upside":0.17158,"range":0.60897,"downside":0.21945},
                              "probabilities":None,"probability_status":"UNCALIBRATED_SHADOW_SCORE","regime_state":"RANGE"}}}}
assert decide(d,v,anchor=a)["status"]=="UPSIDE_TAIL_RISK_WITH_REGIME_DISAGREEMENT"
assert decide(d,v,anchor=a)["action_status"]=="WATCH_ONLY_NO_TRADE_AUTHORITY"
u=deepcopy(v);u['output']['horizons']['4h']['shadow_class_scores']={'upside':0.6,'range':0.3,'downside':0.1};u['output']['horizons']['4h']['regime_state']='UP_CONTINUATION'
assert decide(d,u,anchor=a)['status']=='UPSIDE_TAIL_RISK_CONCORDANT'
n=deepcopy(d);n['output']['alert']=False;n['output']['rank_30d']=0.4
assert decide(n,u,anchor=a)['status']=='UP_REGIME_UNCONFIRMED'
for bad in (lambda x:x.update(reference_price=85687.5),
            lambda x:x['output'].update(alert=False),
            lambda x:x.update(slot='20261002T140000Z')):
    z=deepcopy(d);bad(z)
    try:decide(z,v,anchor=a)
    except ValueError:pass
    else:raise AssertionError('invalid evidence accepted')
print('arbiter v2 selftest OK')
