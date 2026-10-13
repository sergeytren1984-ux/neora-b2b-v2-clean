"""Extract frozen R6 inputs from exact signed contemporary records.

No synthetic historical book and no claim that an input vector is a forecast.
Old R5/R6 registered epochs and mathematical thresholds remain untouched.
"""
import hashlib,json,pathlib,inspect,datetime as dt
from btc_demand_v7.demand_change_v2 import feature,source_hash
from btc_demand_v7.source_integrity_v5 import rederive

SOURCE_SHA='b8d2d1be108f249427bd97d446a7fc261ba5b553'
IDENTITY='https://github.com/sergeytren1984-ux/neora-b2b-v2-clean/.github/workflows/btc-v7r3-signed-demand-shadow.yml@refs/heads/btc-core-forward-source-20261013'
ISSUER='https://token.actions.githubusercontent.com'
R6_FORMULA_BLOB='eb569c083b42936944da6abf638a0a876febd3f6'
NAMES=('signed_15m_taker','signed_3m_taker','book_imbalance','log_15m_volume_ratio','log_3m_volume_ratio','OI_change_15m_pct','spread_bps')
PROFILES={
    SOURCE_SHA:(IDENTITY,'2026-10-13T11:00:00+00:00','2026-10-14T11:00:00+00:00'),
    '6ad82b3afa3fce1eaff477a02ac26cb99ac878e5':(
        IDENTITY.replace('btc-core-forward-source-20261013','btc-core-forward-source2-20261014'),
        '2026-10-14T11:00:00+00:00','2026-10-20T11:30:00+00:00')}

def extract(path,verifier,source_sha=SOURCE_SHA):
    if source_sha not in PROFILES:raise ValueError('unregistered source epoch')
    identity,start,end=PROFILES[source_sha]
    code=pathlib.Path(inspect.getfile(feature)).read_bytes()
    if hashlib.sha1(b'blob '+str(len(code)).encode()+b'\0'+code).hexdigest()!=R6_FORMULA_BLOB:
        raise ValueError('frozen R6 formula changed')
    path=pathlib.Path(path)
    proof=verifier.verify(path,identity,ISSUER,source_sha)
    record=json.loads(path.read_bytes())
    if record.get('schema')!='btc-core-forward-slot-v1':raise ValueError('wrong slot schema')
    anchor=dt.datetime.fromisoformat(record['anchor_utc'])
    if anchor.tzinfo is None or not dt.datetime.fromisoformat(start)<=anchor<dt.datetime.fromisoformat(end):raise ValueError('anchor outside registered source epoch')
    if record.get('kind')!='RAW_CAPTURED':
        return {'available':False,'values':None,'status':record.get('kind'),'anchor_utc':record.get('anchor_utc'),
            'trading_authority':False,'prospective_skill_proven':False}
    bundle=json.loads(pathlib.Path(str(path)+'.sigstore.json').read_bytes())
    logged=max(int(t['integratedTime'])+1 for t in bundle['verificationMaterial']['tlogEntries'])
    signed_available=dt.datetime.fromtimestamp(logged,dt.timezone.utc).isoformat()
    snapshot=record['snapshot']
    canonical=(json.dumps(snapshot,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode()
    if hashlib.sha256(canonical).hexdigest()!=record['snapshot_sha256']:raise ValueError('wrapper snapshot digest mismatch')
    if snapshot['anchor_utc']!=record['anchor_utc']:raise ValueError('source anchor mismatch')
    rederive(snapshot)
    at,vector,status=feature(snapshot)
    return {'schema':'verified-frozen-r6-input-vector-v1','available':vector is not None,
        'anchor_utc':record['anchor_utc'],'input_received_at_utc':at.isoformat(),
        'values':None if vector is None else dict(zip(NAMES,vector)),
        'price_veto_status':status,'snapshot_math_digest':source_hash(snapshot),
        'signed_record_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
        'signed_record_available_not_before_utc':signed_available,
        'book_observed_at_utc':dt.datetime.fromtimestamp(int(snapshot['observation']['book']['vendor_timestamp_ms'])/1000,dt.timezone.utc).isoformat(),
        'microflow_closed_at_utc':dt.datetime.fromtimestamp(int(snapshot['observation']['microflow']['vendor_close_ms'])/1000,dt.timezone.utc).isoformat(),
        'source_sha':proof['source_sha'],'frozen_R6_formula_blob':R6_FORMULA_BLOB,
        'this_is_not_an_R6_alert_or_price_forecast':True,
        'trading_authority':False,'prospective_skill_proven':False,'calibrated_probability':False}
