"""As-of 08:00 UTC production snapshot pair, plus adversarial time cases.
This fixture is read from the independently signed btc-context branch during development.
The production worker independently verifies Cosign and Rekor for every snapshot.
"""
from datetime import datetime, timezone, timedelta
from pathlib import Path
import json
import sys
from unittest.mock import patch

from context_trust import context_pair, verify_signed_snapshot, factor_status
from worker import required_context_ok

ROOT=Path(__file__).resolve().parents[2]
anchor=datetime(2026,10,2,8,tzinfo=timezone.utc)
protocol=json.loads(Path(__file__).with_name('protocol.json').read_text())

# The filenames reflect actual production capture times; data are deliberately
# minimal to isolate comparison semantics and source age from the transport.
now=datetime(2026,10,2,7,43,2,tzinfo=timezone.utc)
prev=datetime(2026,10,2,7,0,38,tzinfo=timezone.utc)

def snapshot(t):
    return {'captured_at_utc':t.isoformat(), 'factors':{
        'open_interest':{'status':'VALID','freshness_status':'FRESH','value_btc':29000,
                         'source_timestamp_utc':(t+timedelta(seconds=1)).isoformat(), 'max_age_seconds':900},
        'funding':{'status':'VALID','freshness_status':'FRESH','value':0.0001,
                   'source_timestamp_utc':(t-timedelta(seconds=10)).isoformat(),'max_age_seconds':900}}}

data={
    '20261002T074302Z.json':json.dumps(snapshot(now)).encode(),
    '20261002T070038Z.json':json.dumps(snapshot(prev)).encode(),
}
for n,t in (('20261002T074302Z.json',now),('20261002T070038Z.json',prev)):
    data[n+'.sigstore.json']=json.dumps({'verificationMaterial':{'tlogEntries':[
        {'integratedTime':int((t+timedelta(seconds=30)).timestamp()),
         'inclusionProof':{'checkpoint':'verified','hashes':[]}}]}}).encode()

def get(url,token=None):
    if '/git/trees/' in url:
        return json.dumps({'truncated':False,'tree':[
            {'type':'blob','path':'context_live/'+name} for name in data if name.endswith('Z.json')]}).encode()
    return data[url.rsplit('/',1)[-1]]

with patch('context_trust._get',get), patch('context_trust._run',return_value=''):
    pair=context_pair('owner/repo',anchor,protocol)
assert pair['snapshot_names']==['20261002T074302Z.json','20261002T070038Z.json']
assert pair['elapsed_seconds']==2544
assert not required_context_ok(pair,protocol), required_context_ok(pair,protocol)
assert pair['previous_proof']['snapshot_age_seconds']>3500
assert pair['previous_proof']['target_offset_seconds']<0

with patch('context_trust._run',return_value=''):
    try:
        verify_signed_snapshot(data['20261002T070038Z.json'],data['20261002T070038Z.json.sigstore.json'],anchor,protocol)
    except ValueError:
        pass
    else:
        raise AssertionError('old v3 semantics should reject the prior snapshot')
    try:
        verify_signed_snapshot(data['20261002T070038Z.json'],data['20261002T070038Z.json.sigstore.json'],
                               anchor,protocol,anchor-timedelta(hours=2),900)
    except ValueError:
        pass
    else:
        raise AssertionError('wrong comparison target was accepted')

bad=snapshot(now)
bad['factors']['open_interest']['source_timestamp_utc']=(now+timedelta(seconds=5)).isoformat()
assert not factor_status(bad,'open_interest',now,protocol)['available']
bad=snapshot(now)
bad['factors']['open_interest']['source_timestamp_utc']=(now-timedelta(seconds=901)).isoformat()
assert not factor_status(bad,'open_interest',now,protocol)['available']
print('REGIME_V4_CONTEXT_TIME_E2E_OK')
