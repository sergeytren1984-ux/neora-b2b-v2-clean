from copy import deepcopy
from datetime import datetime,timezone
from rules import decide

a=datetime(2026,10,3,9,tzinfo=timezone.utc);slot='20261003T090000Z';due='2026-10-03T13:00:00+00:00'
up={'type':'DIRECTIONAL_4H_ALERT_ISSUED','slot':slot,'idempotency_key':'alert:'+slot,
    'due_utc':due,'reference_price':84500,'output':{'rank_30d':.3,'candidate_estimate':.06,
    'cutoff_rank':.8,'past_scores_count':720,'alert':False}}
down={'type':'DIRECTIONAL_4H_DOWNSIDE_ALERT_ISSUED','slot':slot,
      'idempotency_key':'down-alert:'+slot,'due_utc':due,'reference_price':84500,
      'output':{'rank_30d':.9,'candidate_estimate':.12,'cutoff_rank':.8,
                'past_scores_count':720,'alert':True}}
regime={'type':'REGIME_FORECAST_ISSUED','slot':slot,'idempotency_key':'regime:'+slot,
        'reference_price':84500,'output':{'horizons':{'4h':{'due_utc':due,
        'shadow_class_scores':{'upside':.2,'range':.3,'downside':.5},
        'probabilities':None,'probability_status':'UNCALIBRATED_SHADOW_SCORE',
        'regime_state':'DOWN_TRANSITION'}}}}
x=decide(up,regime,down,anchor=a)
assert x['status']=='DOWNSIDE_TAIL_RISK_CONCORDANT'
assert x['action_status']=='WATCH_ONLY_NO_TRADE_AUTHORITY' and x['trading_authority'] is False
assert decide(up,None,down,anchor=a)['status']=='DOWNSIDE_TAIL_RISK_REGIME_UNAVAILABLE'
assert decide(up,regime,None,anchor=a)['status']=='DOWN_HEAD_UNAVAILABLE_NO_DIRECTIONAL_CONCLUSION'
up2=deepcopy(up);up2['output'].update(rank_30d=.9,alert=True)
assert decide(up2,regime,down,anchor=a)['status']=='BIDIRECTIONAL_TAIL_RISK_CONFLICT'
down2=deepcopy(down);down2['output'].update(rank_30d=.2,alert=False)
assert decide(up,regime,down2,anchor=a)['status']=='DOWNSIDE_REGIME_UNVALIDATED'
for change in (lambda x:x.update(reference_price=84600),
               lambda x:x['output'].update(alert=False),
               lambda x:x.update(due_utc='2026-10-03T14:00:00+00:00')):
    bad=deepcopy(down);change(bad)
    try:decide(up,regime,bad,anchor=a)
    except ValueError:pass
    else:raise AssertionError('invalid downside source accepted')
print('arbiter v4 selftest OK')
