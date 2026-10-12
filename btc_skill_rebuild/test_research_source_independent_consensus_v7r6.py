"""Synthetic reproducible counterexamples: 3m+15m are ONE source family."""
import unittest
from btc_demand_v7.test_demand_change_v2 import snap
from btc_demand_v7.demand_change_v2 import BASELINE_COUNT,replay
from btc_skill_rebuild.research_source_independent_consensus_v7r6 import (
    paired_mathematical_replay,source_family_consensus,binance_window_overlap_minutes)


def after_bearish_recovery(i):
    obs=snap(i,direction=-1)
    obs['observation']['15m_taker_buy_fraction']=.51
    obs['observation']['book']['top10_size_imbalance']=-.20
    obs['observation']['microflow']['recent3_taker_buy_fraction']=.51
    for row in obs['microflow_rows'][-3:]:
        v=float(row[5]);row[9]=str(.51*v);row[10]=str(83000*.51*v)
    return obs

class SourceCorrelationVeto(unittest.TestCase):
    def test_recent_microflow_is_not_a_subset_of_older_15m(self):
        from datetime import datetime,timezone,timedelta
        item=snap(BASELINE_COUNT,direction=1)
        # Snapshot was retrieved at anchor+3m; the most recent 3m bar
        # ranges [anchor-1m,anchor+2m] and overlaps ONLY 1m of the old 15m.
        self.assertEqual(binance_window_overlap_minutes(item),1)
        # A later anchored source retrieval can overlap zero minutes.
        from copy import deepcopy
        later=deepcopy(item)
        for row in later['microflow_rows']:
            row[0]+=4*60000;row[6]+=4*60000
        self.assertEqual(binance_window_overlap_minutes(later),0)

    def test_two_correlated_taker_votes_wrongly_confirm_up(self):
        base=[snap(i,direction=-1) for i in range(BASELINE_COUNT)]
        future=[after_bearish_recovery(BASELINE_COUNT+j) for j in range(8)]
        combined=base+future
        _,frozen=replay(combined,absolute_consensus_required=True)
        suspect=frozen[BASELINE_COUNT:]
        self.assertTrue(any(r['alert'] and r['warning_side']=='UP' and
            r['absolute_buy_votes']==2 and r['absolute_sell_votes']==1
            for r in suspect))
        self.assertFalse(source_family_consensus(future[1],'UP'))
        alternative=paired_mathematical_replay(combined)
        last=alternative['diagnostics'][BASELINE_COUNT:]
        self.assertTrue(any(r['old_unfiltered_alarm'] for r in last))
        self.assertFalse(any(r['alert'] for r in last))
        self.assertFalse(alternative['future_directional_skill_proven'])

    def test_rejected_warning_does_not_consume_future_true_up_budget(self):
        base=[snap(i,direction=-1) for i in range(BASELINE_COUNT)]
        weak=[after_bearish_recovery(BASELINE_COUNT+j) for j in range(5)]
        later=[snap(BASELINE_COUNT+5+j,direction=1) for j in range(8)]
        all_snapshots=base+weak+later
        _,frozen=replay(all_snapshots,absolute_consensus_required=True)
        frozen_weak=frozen[BASELINE_COUNT:BASELINE_COUNT+5]
        self.assertTrue(any(z['alert'] for z in frozen_weak))
        self.assertFalse(any(z['alert'] for z in frozen[BASELINE_COUNT+5:]))
        alternative=paired_mathematical_replay(all_snapshots)
        future=alternative['diagnostics'][BASELINE_COUNT+5:]
        self.assertFalse(any(z['alert'] for z in alternative['diagnostics'][BASELINE_COUNT:BASELINE_COUNT+5]))
        self.assertTrue(any(z['alert'] and z['warning_side']=='UP' for z in future))

    def test_symmetry_when_flow_and_book_agree(self):
        for sign in (-1,1):
            o=snap(BASELINE_COUNT,direction=sign)
            self.assertTrue(source_family_consensus(o,'UP' if sign>0 else 'DOWN'))
            self.assertFalse(source_family_consensus(o,'DOWN' if sign>0 else 'UP'))

if __name__=='__main__':unittest.main()