"""Negative/boundary math tests: direction does not imply independent episode."""
import unittest
from btc_skill_rebuild.research_cross_side_market_episodes_v7r6 import (
    market_episodes,compare_episode_independence)

M=60000
H=4*60*M
B=7*24*60*M

class CrossSideIndependence(unittest.TestCase):
    def test_same_minute_opposite_sign_one_market_episode(self):
        e=market_episodes([(B,0),(B,1)],H)
        self.assertEqual(len(e),1)
        self.assertEqual(e[0]['directions'],[0,1])
        self.assertTrue(e[0]['mixed_up_down'])
        self.assertEqual(e[0]['distinct_touch_timestamp_directions'],2)

    def test_alternating_signs_one_dependent_episode(self):
        self.assertEqual(len(market_episodes([
            (B-20*M,0),(B-5*M,1),(B+10*M,0),(B+15*M,1)],H)),1)

    def test_week_boundary_does_not_reset(self):
        self.assertEqual(len(market_episodes([(B-M,0),(B+M,1)],H)),1)

    def test_larger_than_horizon_separates(self):
        self.assertEqual(len(market_episodes([(0,0),(H+1,1)],H)),2)

    def test_exactly_horizon_is_dependent(self):
        self.assertEqual(len(market_episodes([(0,0),(H,1)],H)),1)

    def test_duplicate_and_order_invariant(self):
        a=market_episodes([(B,1),(B,0),(B,0),(B+M,1)],H)
        b=market_episodes([(B+M,1),(B,0),(B,1)],H)
        self.assertEqual(a,b)
        self.assertEqual(a[0]['distinct_touch_timestamp_directions'],3)

    def test_transitive_chain_is_conservative(self):
        chain=[(k*(H-1),k%2) for k in range(8)]
        e=market_episodes(chain,H)
        self.assertEqual(len(e),1)
        self.assertGreater(e[0]['span_ms'],H)

    def test_unconnected_opposite_directions_independent(self):
        self.assertEqual(len(market_episodes([(0,0),(10*H,1)],H)),2)

    def test_empty(self):
        self.assertEqual(market_episodes([],H),[])

    def test_reject_bad_input(self):
        for h in (0,-1,1.2,True):
            with self.subTest(h=h),self.assertRaises(ValueError):
                market_episodes([],h)
        for e in ([(0,2)],[(0,-1)],[(0,True)],[(True,0)],
                  [(-1,0)],[(1.2,0)],[(0,)],['garbage']):
            with self.subTest(e=e),self.assertRaises(ValueError):
                market_episodes(e,H)

    def test_side_specific_overcount_against_existing_math(self):
        r=compare_episode_independence([[(B-M,0)],[(B+M,1)]],H)
        self.assertEqual(r['existing_side_specific_directional_episode_count'],2)
        self.assertEqual(r['conservative_cross_side_market_episode_count'],1)
        self.assertEqual(r['directional_episode_count_overstatement'],1)
        self.assertEqual(r['cross_side_mixed_episodes'],1)
        self.assertFalse(r['trading_authority'])
        self.assertFalse(r['raw_5m_archive_recomputed'])

if __name__=='__main__':unittest.main()
