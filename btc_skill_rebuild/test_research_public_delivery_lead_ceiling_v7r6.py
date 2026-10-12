"""Negative tests: no future candle can make a +3m published 1h signal
60min early; widening delivery delay cannot create earlier warning.
"""
from __future__ import annotations
import unittest
from btc_skill_rebuild.research_public_delivery_lead_ceiling_v7r6 import (
    clock_feasibility,MINIMUM_WARNING_LEAD_MIN)

class PhysicalLeadBounds(unittest.TestCase):
    def test_one_hour_after_publication_never_reaches_full_60m(self):
        base=1_000_000_000_000
        # For any 5m touch bar in the registered 60m horizon, even the
        # best-case touch at the END of the bar is <60m from public +3m.
        for m in range(0,60,5):
            for latency in (3,8,13):
                a=clock_feasibility(base,base+m*60_000,latency,60*60_000)
                self.assertFalse(a['possible_ge_60m_even_perfect_direction'])
                self.assertFalse(a['guaranteed_ge_60m_any_intrabar_touch'])

    def test_4h_early_possible_but_maturity_not_a_proof_of_skill(self):
        base=1_000_000_000_000
        soon=clock_feasibility(base,base+40*60_000,8,240*60_000)
        self.assertFalse(soon['possible_ge_60m_even_perfect_direction'])
        later=clock_feasibility(base,base+90*60_000,8,240*60_000)
        self.assertTrue(later['guaranteed_ge_60m_any_intrabar_touch'])
        self.assertEqual(later['best_possible_lead_minutes'],87.)
        for h in range(0,240,5):
            old=None
            for latency in (0,3,8,13):
                now=clock_feasibility(base,base+h*60_000,latency,240*60_000)
                if old is not None:
                    self.assertLessEqual(now['best_possible_lead_minutes'],old)
                old=now['best_possible_lead_minutes']

    def test_clock_cannot_accept_unregistered_touch(self):
        with self.assertRaises(ValueError):clock_feasibility(1000000,999999,3,3600000)
        with self.assertRaises(ValueError):clock_feasibility(1000000,4600000,3,3600000)
        with self.assertRaises(ValueError):clock_feasibility(1000000,1000000,-2,3600000)

if __name__=='__main__':unittest.main()