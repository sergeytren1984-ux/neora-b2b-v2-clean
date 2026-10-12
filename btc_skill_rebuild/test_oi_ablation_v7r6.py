"""Independent causal sensitivity tests of historical OI mathematics.

These tests are not proof of vendor HTTP publication: lagging a historical
vendor timestamp does NOT replace contemporaneously archived receipts.
"""
from __future__ import annotations
import math,unittest
from btc_skill_rebuild.research_oi_ablation_v7r6 import extra_asof,FEATURES,STEP,LAG_MS

class OptionalFuturesAsOf(unittest.TestCase):
    def test_required_oi_requires_exact_lagged_closed_vendor_slot(self):
        t=15*STEP
        past=t-LAG_MS
        um={past:100.,past-3*STEP:98.,past-12*STEP:94.}
        cm={past:80.,past-3*STEP:79.}
        # funding's settlement timestamp is older than input boundary
        fs={past-STEP:.0001}
        rows=extra_asof(t,um,cm,fs,sorted(cm),sorted(fs))
        self.assertEqual(len(rows),len(FEATURES))
        self.assertAlmostEqual(rows[0],math.log(100/98))
        self.assertAlmostEqual(rows[1],math.log(100/94))
        self.assertEqual(rows[-2],0.)
        # A new OI observation at or after decision is NOT usable.
        um[t]=10000.;cm[t]=9999.;fs[t]=1.
        same=extra_asof(t,um,cm,fs,sorted(cm),sorted(fs))
        self.assertEqual(rows,same)
        del um[past]
        self.assertIsNone(extra_asof(t,um,cm,fs,sorted(cm),sorted(fs)))

    def test_coinm_optional_and_staleness_fails_closed(self):
        t=15*STEP;past=t-LAG_MS
        um={past:100.,past-3*STEP:98.,past-12*STEP:94.}
        cm={past-20*STEP:80.}
        fs={past-STEP:.0001}
        r=extra_asof(t,um,cm,fs,sorted(cm),sorted(fs))
        self.assertIsNotNone(r)
        self.assertEqual(r[-2],1.)
        self.assertEqual(r[-1],1.)
        self.assertEqual(r[2],0.)
        self.assertIsNone(extra_asof(t,um,cm,{},sorted(cm),[]))

if __name__=='__main__':unittest.main()
