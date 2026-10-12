"""The live comparator cannot cheat on expiry, time, state or source."""
from datetime import datetime,timedelta,timezone
import unittest,os
from unittest.mock import patch
from btc_demand_v7 import v7r6_live_pair_worker as worker
from btc_demand_v7.demand_change_v2 import advance,state_zero,BASELINE_COUNT
from btc_demand_v7.test_demand_change_v2 import snap

class Spec(unittest.TestCase):
    def test_precommitted_grid_and_no_trade(self):
        with patch.dict(os.environ,{'GITHUB_SHA':'b'*40}):
            reg=worker.registration('a'*40)
        self.assertEqual(reg['eligible_slot_count'],640)
        self.assertEqual(reg['max_commit_deadline_after_anchor_minutes'],13)
        self.assertFalse(reg['trading_authority'])
        self.assertEqual(reg['observer_workflow_sha'],'b'*40)

    def test_prospective_signed_source_absence_not_usable(self):
        rows=[snap(i,direction=-1) for i in range(BASELINE_COUNT)]
        with self.assertRaises(ValueError):worker.decision(None,rows,None,rows[-1]['retrieved_at_utc'])
        with self.assertRaises(ValueError):worker.decision(snap(32,direction=1),rows[:-1],None,rows[-1]['retrieved_at_utc'])

    def test_same_verified_snapshots_and_clock(self):
        rows=[snap(i,direction=-1) for i in range(BASELINE_COUNT+1)]
        t=rows[-1]['retrieved_at_utc']
        a,b=worker.decision(rows[-1],rows[:-1],None,t)
        x,y=advance(state_zero(),rows[:-1],rows[-1],issued_utc=t,absolute_consensus_required=True)
        self.assertEqual(a,x);self.assertEqual(b,y)
        self.assertFalse(b['calibrated_probability'])
        self.assertFalse(a['trading_authority'])
        issued=datetime.fromisoformat(t)+timedelta(minutes=11)
        with self.assertRaises(ValueError):worker.decision(rows[-1],rows[:-1],None,issued.isoformat())

    def test_missing_state_cannot_accidentally_be_accepted(self):
        with patch.object(worker,'now',return_value=worker.START+timedelta(minutes=32*15+14)):
            with patch.object(worker,'verify_runner',return_value='f'*40):
                with self.assertRaises(RuntimeError):worker.run_slot()

if __name__=='__main__':
    unittest.main()
