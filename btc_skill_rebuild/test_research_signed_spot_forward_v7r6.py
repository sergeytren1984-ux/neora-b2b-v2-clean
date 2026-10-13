"""Negative as-of mathematics invariants for 3-horizon BTC shadow."""
import gzip,json,unittest
from btc_skill_rebuild.research_signed_spot_forward_v7r6 import asof_last_feature
from btc_skill_rebuild.research_execution_drift_v7r6 import examples

ARCHIVE='/Users/sergey/btc-model-work-20261012/data/binance_closed5m_65d_20261011.json.gz'
class AsOfClosedOnly(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with gzip.open(ARCHIVE,'rt') as f:cls.all=json.load(f)
    def test_exact_frozen_equations_for_3_historical_asofs(self):
        for n in (12500,14500,17000):
            old=examples(self.all[:n+1])[-1]
            fresh=asof_last_feature(self.all[:n])
            self.assertEqual(old[1],fresh[0])
            self.assertEqual(old[3][old[0]],fresh[2])
            self.assertLess(max(abs(a-b) for a,b in zip(old[2],fresh[1])),1e-10)
    def test_one_future_5m_bar_cannot_modify_last_closed_feature(self):
        a=asof_last_feature(self.all[:15000])
        extended=self.all[:15000]+[self.all[15000].copy()]
        extended[-1][4]='90000.0'
        # We do not accidentally append or inspect this future row.
        b=asof_last_feature(extended[:-1])
        self.assertEqual(a,b)
    def test_gap_and_unclosed_source_rejected(self):
        rows=[z.copy() for z in self.all[13000:13400]]
        rows[10][0]=int(rows[10][0])+60000
        with self.assertRaises(ValueError):asof_last_feature(rows)
        rows=[z.copy() for z in self.all[13000:13400]]
        rows[-1][6]=int(rows[-1][6])-10
        with self.assertRaises(ValueError):asof_last_feature(rows)
if __name__=='__main__':unittest.main()
