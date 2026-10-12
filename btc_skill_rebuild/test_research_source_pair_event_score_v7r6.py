"""Adversarial own-slot, lead-time, overlapping event paired comparisons."""
from datetime import datetime,timedelta,timezone
import unittest
from btc_skill_rebuild.research_source_pair_event_score_v7r6 import paired_source_signal_score
UTC=timezone.utc
ZERO=datetime(2026,10,14,12,tzinfo=UTC)

def iso(minutes):return (ZERO+timedelta(minutes=minutes)).isoformat()

class PairwiseProspectiveMath(unittest.TestCase):
    def observations(self):
        return [
            {'slot_id':'s1','direction':'UP_FIRST','touch_open_utc':iso(130)},
            {'slot_id':'s2','direction':'UP_FIRST','touch_open_utc':iso(131)},
            {'slot_id':'s3','direction':'NEITHER','touch_open_utc':None},
            {'slot_id':'s4','direction':'DOWN_FIRST','touch_open_utc':iso(175)},
            {'slot_id':'s5','direction':'AMBIGUOUS_SAME_MINUTE','touch_open_utc':None},
        ]
    def a(self,slot,side,public):
        return {'slot_id':slot,'side':side,'eligible':True,'public_delivery_utc':iso(public)}

    def test_same_future_grids_no_cross_slot_credit(self):
        # Before true first touch s1, a false UP alert for s3 NEITHER
        # must not be credited merely due to nearby s1/s2 wins.
        old=[self.a('s3','UP_FIRST',80)]
        new=[self.a('s1','UP_FIRST',75)]
        out=paired_source_signal_score('4h',7,2,self.observations(),old,new)
        self.assertEqual(out['resolved_due'],5)
        self.assertEqual(out['missing_due'],2)
        self.assertEqual(out['unique_resolved_episodes'],2)
        self.assertEqual(out['lead_minutes']['30']['baseline_episodes_own_slot_correct'],0)
        self.assertEqual(out['lead_minutes']['30']['candidate_episodes_own_slot_correct'],1)
        self.assertEqual(out['lead_minutes']['60']['candidate_episodes_own_slot_correct'],0)
        self.assertFalse(out['signed_rekor_proofs_verified_by_this_math_module'])
        self.assertFalse(out['trading_authority'])

    def test_wrong_side_and_missing_are_never_papered_over(self):
        a=[self.a('s1','DOWN_FIRST',70)]
        out=paired_source_signal_score('4h',7,2,self.observations(),a,[])
        self.assertEqual(out['lead_minutes']['30']['baseline_correct_public_alerts'],0)
        self.assertEqual(out['lead_minutes']['30']['baseline_alerts_not_own_slot_correct'],1)
        self.assertIsNone(out['lead_minutes']['30']['candidate_alert_precision'])
        with self.assertRaises(ValueError):
            paired_source_signal_score('4h',6,2,self.observations(),a,[])
        with self.assertRaises(ValueError):
            paired_source_signal_score('4h',7,2,self.observations(),a+a,[])
        with self.assertRaises(ValueError):
            paired_source_signal_score('4h',7,2,self.observations(),a,
                [{'slot_id':'s2','side':'UP_FIRST','eligible':False,
                  'public_delivery_utc':iso(60)}])

    def test_one_hour_cannot_rebrand_short_notice_as_hour_early(self):
        obs=[{'slot_id':'h','direction':'UP_FIRST','touch_open_utc':iso(60)}]
        delivered=[self.a('h','UP_FIRST',1)]
        out=paired_source_signal_score('1h',1,0,obs,delivered,[])
        self.assertEqual(out['lead_minutes']['30']['baseline_correct_public_alerts'],1)
        self.assertEqual(out['lead_minutes']['60']['baseline_correct_public_alerts'],0)

if __name__=='__main__':unittest.main()
