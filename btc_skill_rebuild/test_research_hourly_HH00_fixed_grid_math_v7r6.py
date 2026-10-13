"""Mathematical negative tests for precommitted HH:00 grid."""
import copy,datetime as dt
from btc_skill_rebuild.research_hourly_HH00_fixed_grid_math_v7r6 import START,PRIOR,CODE_SHA1,WEIGHTS_SHA256,audit

def fixture():
    slot=START+dt.timedelta(hours=5)
    key=slot.isoformat()
    f={"source_anchor_utc":key,"source_commit_utc":(slot+dt.timedelta(minutes=4)).isoformat(),
       "source_retrieved_utc":(slot+dt.timedelta(minutes=3)).isoformat(),
       "source_path":"btc_v7r3_evidence/slots/20261013T0500Z/snapshot.json",
       "source_blob_sha1":"a"*40,"forecast_commit_sha":"b"*40,
       "public_commit_utc":(slot+dt.timedelta(minutes=5)).isoformat(),
       "forecast_code_blob_sha1":CODE_SHA1,"weights_sha256":WEIGHTS_SHA256,
       "trading_authority":False,"heads":{}}
    for h,n,t in (("1h",1,.007),("4h",4,.012),("24h",24,.02)):
        f["heads"][h]={"target_utc":(slot+dt.timedelta(hours=n)).isoformat(),
                       "reference_price":83000.,"threshold":t,"p":list(PRIOR[h])}
    obs={}
    for h,n in (("1h",1),("4h",4)):
        target=slot+dt.timedelta(hours=n)
        obs[(key,h)]={"closed_bar_end_utc":target.isoformat(),
                      "outcome_snapshot_commit_utc":(target+dt.timedelta(minutes=5)).isoformat(),
                      "outcome_snapshot_retrieved_utc":(target+dt.timedelta(minutes=4)).isoformat(),
                      "outcome_snapshot_blob_sha1":"c"*40,"close":83200.}
    return key,f,obs

def rejected(fn):
    try:fn()
    except (ValueError,KeyError):return True
    return False

def test():
    key,f,obs=fixture()
    now=START+dt.timedelta(hours=19,minutes=32)
    a=audit(now,{key:f},obs)
    assert a["hourly_due"]==20 and a["missing_forecast"]==19
    assert a["horizons"]["1h"]["matured_HH00_due"]==19
    assert a["horizons"]["4h"]["matured_HH00_due"]==16
    assert a["horizons"]["24h"]["matured_HH00_due"]==0
    assert a["horizons"]["4h"]["nonoverlap_HH00_due"]==4
    assert a["horizons"]["4h"]["nonoverlap_scored"]==0
    assert a["horizons"]["1h"]["mean_Brier_gain_vs_pre_epoch_prior_overlapping"]==0
    off=(START+dt.timedelta(hours=4,minutes=45)).isoformat()
    assert audit(now,{key:f,off:f},obs)["off_grid_forecasts_excluded"]==1
    for field,value in (("public_commit_utc",(START+dt.timedelta(hours=5,minutes=14)).isoformat()),
                        ("source_commit_utc",(START+dt.timedelta(hours=5,minutes=6)).isoformat()),
                        ("weights_sha256","0"*64),("forecast_code_blob_sha1","0"*40)):
        bad=copy.deepcopy(f);bad[field]=value
        assert rejected(lambda:audit(now,{key:bad},obs)),field
    bad=copy.deepcopy(f)
    bad["heads"]["4h"]["target_utc"]=(START+dt.timedelta(hours=10)).isoformat()
    assert rejected(lambda:audit(now,{key:bad},obs))
    bad=copy.deepcopy(f);bad["heads"]["1h"]["p"]=[0,0,0]
    assert rejected(lambda:audit(now,{key:bad},obs))
    bad=copy.deepcopy(obs)
    bad[(key,"1h")]["closed_bar_end_utc"]=(START+dt.timedelta(hours=6,minutes=5)).isoformat()
    assert rejected(lambda:audit(now,{key:f},bad))
    bad=copy.deepcopy(obs)
    bad[(key,"1h")]["outcome_snapshot_commit_utc"]=(now+dt.timedelta(hours=1)).isoformat()
    assert rejected(lambda:audit(now,{key:f},bad))
    absent=audit(now,{key:f},{})
    assert absent["horizons"]["1h"]["matured_on_time_forecast_without_exact_outcome"]==1
    assert absent["horizons"]["1h"]["matured_scored"]==0
    print("BTC_V7R6_HH00_GRID_NEGATIVE_MATH_TESTS_PASS")

if __name__=="__main__":test()
