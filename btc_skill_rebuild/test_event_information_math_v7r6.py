"""Negative guards: effective event sample and no hindsight selection."""
from __future__ import annotations
import unittest
from btc_skill_rebuild.research_episode_effective_sample_v7r6 import grouped_episodes
from btc_skill_rebuild.research_signal_information_v7r6 import GROUPS,FEATURES,daily_gain

class PureMathCausality(unittest.TestCase):
    def test_group_by_exact_touch_and_conservative_consecutive_episodes(self):
        one_hour=3600000
        identical=[(0,0),(0,0),(0,0),(10*60000,0)]
        c=grouped_episodes(identical,one_hour)
        self.assertEqual(len(c),1)
        self.assertEqual(c[0]['distinct_touches'],2)
        # A same-side event at 70 minutes is still a continuation of the
        # latest member at +10m, not a fresh event anchored at 0m.
        c=grouped_episodes(identical+[(70*60000,0)],one_hour)
        self.assertEqual(len(c),1)
        self.assertEqual(c[0]['distinct_touches'],3)
        # Opposite side does not silently become proof of an UP episode.
        c=grouped_episodes(identical+[(11*60000,1)],one_hour)
        self.assertEqual(len(c),2)
        self.assertEqual({e['side'] for e in c},{0,1})
        c=grouped_episodes([(0,0),(70*60000,0)],one_hour)
        self.assertEqual(len(c),2)

    def test_predeclared_feature_ablation_no_lookahead(self):
        self.assertEqual(len(FEATURES),17)
        self.assertEqual(GROUPS['full_signed_flow_plus_volatility'],tuple(range(17)))
        self.assertTrue(all(0<=i<len(FEATURES) for group in GROUPS.values() for i in group))
        self.assertEqual(GROUPS['signed_flow_only'],(5,6,7,8))
        self.assertFalse(set(GROUPS['signed_flow_only']) & set(GROUPS['volatility_activity_only']))

    def test_day_not_15m_slots_is_effective_denominator(self):
        # 96 strongly overlapping slots of the same UTC day do NOT count
        # as 96 independent daily observations for uncertainty.
        one_utc_day=1700000000000
        points=[(one_utc_day+i*900000,0.0002) for i in range(96)]
        day=daily_gain(points)
        self.assertEqual(day['days'],2) # boundary crossing into next day
        self.assertEqual(day['positive_days'],2)
        self.assertIsNotNone(day['descriptive_L95'])

if __name__=='__main__':unittest.main()
