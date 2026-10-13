"""Disallow premature, cross-slot and backdated BTC prospective scores."""
import datetime as dt,copy,unittest
from btc_skill_rebuild.research_score_public_shadow_v7r6 import resolved_endpoint
UTC=dt.timezone.utc
ANCHOR=dt.datetime(2026,10,13,4,45,tzinfo=UTC)
PUB=dt.datetime(2026,10,13,4,56,34,tzinfo=UTC)
PRICE=83000.

def sample():
    heads={};weights={}
    for name,mins,threshold in [('1h',60,.007),('4h',240,.012),('24h',1440,.02)]:
        heads[name]={'up':.1,'down':.1,'range':.8,
           'reference_spot_usdt':PRICE,'endpoint_threshold_fraction':threshold,
           'horizon_target_utc':(ANCHOR+dt.timedelta(minutes=mins)).isoformat(),
           'source_anchor_utc':ANCHOR.isoformat()}
        weights[name]={'duration_5m_steps':mins//5,'threshold':threshold,
                       'model_parameters':[[],[],[],[.15,.10,.75]],
                       'validation_selected_shrink':1.}
    pred={'clock_anchor_utc':ANCHOR.isoformat(),
          'evidence_signature_not_independently_verified':True,
          'input_R5_spot_source_path':'immutable/example',
          'input_R5_spot_source_blob_GitHub_sha1':'a'*40,
          'trading_authority':False,'three_way':heads}
    def bar(minute,price):
        end=ANCHOR+dt.timedelta(minutes=minute)
        start=int((end-dt.timedelta(minutes=5)).timestamp()*1000)
        return [start,'83000',str(max(83000,price)),str(min(83000,price)),str(price),'1',start+299999]
    t=ANCHOR+dt.timedelta(minutes=1445)
    outcome={'anchor_utc':t.isoformat(),'retrieved_at_utc':(t+dt.timedelta(minutes=2)).isoformat(),
          'no_backfill':True,'five_min_rows':[bar(60,83000),bar(240,85000),bar(1440,81000)]}
    return pred,{'heads':weights},outcome

class ProspectiveScoreSafety(unittest.TestCase):
    def test_correct_due_own_slot_3_heads(self):
        p,w,s=sample()
        result=resolved_endpoint(p,w,s,PUB.isoformat(),(ANCHOR+dt.timedelta(days=2)).isoformat())
        self.assertEqual(result['three_way_horizons']['1h']['actual_outcome'],'RANGE')
        self.assertEqual(result['three_way_horizons']['4h']['actual_outcome'],'UP')
        self.assertEqual(result['three_way_horizons']['24h']['actual_outcome'],'DOWN')
        self.assertFalse(result['prospective_market_skill_proven'])
        self.assertFalse(result['trading_authority'])

    def test_premature_target_not_resolved_or_backfilled(self):
        p,w,s=sample()
        s['anchor_utc']=(ANCHOR+dt.timedelta(minutes=65)).isoformat()
        s['retrieved_at_utc']=(ANCHOR+dt.timedelta(minutes=67)).isoformat()
        s['five_min_rows']=s['five_min_rows'][:1]
        r=resolved_endpoint(p,w,s,PUB.isoformat(),(ANCHOR+dt.timedelta(minutes=70)).isoformat())
        self.assertTrue(r['three_way_horizons']['1h']['resolved'])
        self.assertFalse(r['three_way_horizons']['4h']['due'])
        self.assertFalse(r['three_way_horizons']['24h']['due'])
        s['no_backfill']=False
        with self.assertRaises(ValueError):resolved_endpoint(p,w,s,PUB.isoformat(),(ANCHOR+dt.timedelta(minutes=70)).isoformat())

    def test_late_or_bogus_model_prior_rejected(self):
        p,w,s=sample()
        later=(ANCHOR+dt.timedelta(minutes=14)).isoformat()
        with self.assertRaises(ValueError):resolved_endpoint(p,w,s,later,(ANCHOR+dt.timedelta(days=2)).isoformat())
        p['three_way']['1h']['up']=.9
        with self.assertRaises(ValueError):resolved_endpoint(p,w,s,PUB.isoformat(),(ANCHOR+dt.timedelta(days=2)).isoformat())


    def test_immutable_horizon_targets_and_thresholds(self):
        for h in ('1h','4h','24h'):
            p,w,s=sample()
            p['three_way'][h]['horizon_target_utc']=(ANCHOR+dt.timedelta(minutes=5)).isoformat()
            with self.assertRaises(ValueError):resolved_endpoint(p,w,s,PUB.isoformat(),(ANCHOR+dt.timedelta(days=2)).isoformat())
            p,w,s=sample()
            p['three_way'][h]['endpoint_threshold_fraction']*=2
            with self.assertRaises(ValueError):resolved_endpoint(p,w,s,PUB.isoformat(),(ANCHOR+dt.timedelta(days=2)).isoformat())
            p,w,s=sample()
            p['three_way'][h]['source_anchor_utc']=(ANCHOR+dt.timedelta(minutes=5)).isoformat()
            with self.assertRaises(ValueError):resolved_endpoint(p,w,s,PUB.isoformat(),(ANCHOR+dt.timedelta(days=2)).isoformat())

    def test_missing_head_and_no_false_day_credit(self):
        p,w,s=sample()
        del p['three_way']['4h']
        with self.assertRaises(ValueError):resolved_endpoint(p,w,s,PUB.isoformat(),(ANCHOR+dt.timedelta(days=2)).isoformat())
        p,w,s=sample()
        s['anchor_utc']=(ANCHOR+dt.timedelta(minutes=5)).isoformat()
        s['retrieved_at_utc']=(ANCHOR+dt.timedelta(minutes=7)).isoformat()
        s['five_min_rows']=[]
        r=resolved_endpoint(p,w,s,PUB.isoformat(),(ANCHOR+dt.timedelta(minutes=8)).isoformat())
        self.assertEqual(r['independent_prospective_days_count'],0)
        self.assertEqual(r['fixed_horizon_due_count'],0)
        self.assertEqual(r['fixed_horizon_resolved_count'],0)
        self.assertEqual(r['calendar_days_with_any_resolved_endpoint'],0)

    def test_reject_impossible_snapshot_anchor(self):
        p,w,s=sample()
        s['anchor_utc']=(ANCHOR+dt.timedelta(hours=25)).isoformat()
        s['retrieved_at_utc']=(ANCHOR+dt.timedelta(minutes=1)).isoformat()
        with self.assertRaises(ValueError):resolved_endpoint(p,w,s,PUB.isoformat(),(ANCHOR+dt.timedelta(days=2)).isoformat())

    def test_cannot_resolve_cross_timestamps(self):
        p,w,s=sample()
        s['five_min_rows'][0][0]+=60000
        with self.assertRaises(ValueError):resolved_endpoint(p,w,s,PUB.isoformat(),(ANCHOR+dt.timedelta(days=2)).isoformat())
        s=sample()[2]
        s['five_min_rows']=s['five_min_rows'][1:]
        result=resolved_endpoint(p,w,s,PUB.isoformat(),(ANCHOR+dt.timedelta(days=2)).isoformat())
        self.assertFalse(result['three_way_horizons']['1h']['resolved'])

if __name__=='__main__':unittest.main()
