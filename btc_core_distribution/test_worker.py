import datetime as dt,unittest
from unittest.mock import patch
import numpy as np
from btc_core_distribution import worker as w

class WorkerTests(unittest.TestCase):
    def test_fixed_grid_and_outcome_tail(self):
        self.assertEqual((w.END-w.START).total_seconds()/3600,168)
        self.assertEqual((w.ASSESSMENT_END-w.END).total_seconds()/3600,72)
        self.assertLess(w.START,w.END)

    def test_future_outcome_not_requested(self):
        r={'anchor_utc':w.now().isoformat()}
        with patch.object(w,'fetch') as fetch:
            with self.assertRaises(ValueError):w.outcome(r,1)
            fetch.assert_not_called()

    def test_closed_outcome_and_matching_baselines(self):
        at=w.START;ts=int(at.timestamp()*1000);rows=[]
        for i in range(12):rows.append([ts+i*300000,'100','101','99','100','1',ts+(i+1)*300000-1,'100','1','0.5','50','0'])
        r={'anchor_utc':at.isoformat(),'reference_spot':100.,'samples_log_returns':{k:{'1':[0.,0.]} for k in ('candidate','vol24')}}
        with patch.object(w,'now',return_value=at+dt.timedelta(hours=2)),patch.object(w,'fetch',return_value=w.json.dumps(rows).encode()):
            out=w.outcome(r,1)
        self.assertEqual(out['scores']['candidate']['crps'],0.)
        self.assertEqual(out['scores']['candidate'],out['scores']['vol24'])
        self.assertFalse(out['full_system_ready'])
        self.assertFalse(out['trading_authority'])

    def test_corrupt_outcome_candle_rejected(self):
        ts=int(w.START.timestamp()*1000)
        rows=[[ts+i*300000,'100','98','99','100','1',ts+(i+1)*300000-1] for i in range(12)]
        with patch.object(w,'now',return_value=w.START+dt.timedelta(hours=2)),patch.object(w,'fetch',return_value=w.json.dumps(rows).encode()):
            with self.assertRaises(ValueError):w.outcome({'anchor_utc':w.START.isoformat(),'reference_spot':100.},1)

if __name__=='__main__':unittest.main()
