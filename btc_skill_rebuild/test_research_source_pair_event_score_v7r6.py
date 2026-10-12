"""Adversarial own-slot, lead-time, overlapping event paired comparisons."""
from datetime import datetime,timedelta,timezone
import unittest
from btc_skill_rebuild.research_source_pair_event_score_v7r6 import paired_source_signal_score
UTC=timezone.utc
ZERO=datetime(2026,10,14,12,tzinfo=UTC)

def iso(minutes):return (ZERO+timedelta(minutes=minutes)).isoformat()
def sid(minutes):return (ZERO+timedelta(minutes=minutes)).strftime('%Y%m%dT%H%MZ')

class PairwiseProspectiveMath(unittest.TestCase):
    def registry(self,start=75,n=7):
        return [{'slot_id':sid(start+15*i),
                 'slot_utc':iso(start+15*i),
                 'forecast_deadline_utc':iso(start+15*i+10)}
                for i in range(n)]

    def observations(self):
        return [
            {'slot_id':sid(75),'direction':'UP_FIRST','touch_open_utc':iso(130)},
            {'slot_id':sid(90),'direction':'UP_FIRST','touch_open_utc':iso(131)},
            {'slot_id':sid(105),'direction':'NEITHER','touch_open_utc':None},
            {'slot_id':sid(120),'direction':'DOWN_FIRST','touch_open_utc':iso(175)},
            {'slot_id':sid(135),'direction':'AMBIGUOUS_SAME_MINUTE','touch_open_utc':None},
        ]
    def a(self,slot,side,public):
        return {'slot_id':slot,'side':side,'eligible':True,'public_delivery_utc':iso(public)}

    def test_same_future_grids_no_cross_slot_credit(self):
        # Before true first touch s1, a false UP alert for s3 NEITHER
        # must not be credited merely due to nearby s1/s2 wins.
        old=[self.a(sid(105),'UP_FIRST',110)]
        new=[self.a(sid(75),'UP_FIRST',80)]
        out=paired_source_signal_score('4h',7,2,self.observations(),old,new,registered_due_slots=self.registry())
        self.assertEqual(out['resolved_due'],5)
        self.assertEqual(out['missing_due'],2)
        self.assertEqual(out['unique_resolved_episodes'],2)
        self.assertEqual(out['lead_minutes']['30']['baseline_episodes_own_slot_correct'],0)
        self.assertEqual(out['lead_minutes']['30']['candidate_episodes_own_slot_correct'],1)
        self.assertEqual(out['lead_minutes']['60']['candidate_episodes_own_slot_correct'],0)
        self.assertFalse(out['signed_rekor_proofs_verified_by_this_math_module'])
        self.assertFalse(out['trading_authority'])

    def test_wrong_side_and_missing_are_never_papered_over(self):
        a=[self.a(sid(75),'DOWN_FIRST',80)]
        out=paired_source_signal_score('4h',7,2,self.observations(),a,[],registered_due_slots=self.registry())
        self.assertEqual(out['lead_minutes']['30']['baseline_correct_public_alerts'],0)
        self.assertEqual(out['lead_minutes']['30']['baseline_alerts_not_own_slot_correct'],1)
        self.assertIsNone(out['lead_minutes']['30']['candidate_alert_precision'])
        with self.assertRaises(ValueError):
            paired_source_signal_score('4h',6,2,self.observations(),a,[],registered_due_slots=self.registry())
        with self.assertRaises(ValueError):
            paired_source_signal_score('4h',7,2,self.observations(),a+a,[],registered_due_slots=self.registry())
        with self.assertRaises(ValueError):
            paired_source_signal_score('4h',7,2,self.observations(),a,
                [{'slot_id':sid(90),'side':'UP_FIRST','eligible':False,
                  'public_delivery_utc':iso(95)}],registered_due_slots=self.registry())

    def test_pre_anchor_fake_publication_and_late_publication_rejected(self):
        obs=self.observations()
        for public in (74,89):
            with self.assertRaises(ValueError):
                paired_source_signal_score(
                    '4h',7,2,obs,[self.a(sid(75),'UP_FIRST',public)],[],
                    registered_due_slots=self.registry())
        with self.assertRaises(ValueError):
            paired_source_signal_score(
                '4h',7,2,obs,[self.a('unregistered','UP_FIRST',80)],[],
                registered_due_slots=self.registry())
        with self.assertRaises(ValueError):
            paired_source_signal_score(
                '4h',7,2,obs,[],[],registered_due_slots=self.registry(90,7))

    def test_outcome_touch_before_own_anchor_or_after_horizon_rejected(self):
        for touch in (74,75+240):
            edited=self.observations()
            edited[0]={**edited[0],'touch_open_utc':iso(touch)}
            with self.assertRaises(ValueError):
                paired_source_signal_score(
                    '4h',7,2,edited,[],[],
                    registered_due_slots=self.registry())

    def test_one_hour_cannot_rebrand_short_notice_as_hour_early(self):
        obs=[{'slot_id':sid(0),'direction':'UP_FIRST','touch_open_utc':iso(55)}]
        delivered=[self.a(sid(0),'UP_FIRST',1)]
        out=paired_source_signal_score('1h',1,0,obs,delivered,[],registered_due_slots=self.registry(0,1))
        self.assertEqual(out['lead_minutes']['30']['baseline_correct_public_alerts'],1)
        self.assertEqual(out['lead_minutes']['60']['baseline_correct_public_alerts'],0)

if __name__=='__main__':unittest.main()
