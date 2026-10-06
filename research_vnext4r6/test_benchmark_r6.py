import unittest
import numpy as np
from research_vnext4r6.benchmark_r6 import SELECTORS

class R6StructuralContract(unittest.TestCase):
    def test_selector_set_is_predeclared(self):
        self.assertEqual(SELECTORS,("selector_regime","selector_regime_or_highvol"))

    def test_vol_scaled_distance_is_positive(self):
        ref=np.array([100.0,200.0])
        vol=np.array([0.01,0.02])
        for bars in (4,16,24):
            d=ref*vol*np.sqrt(float(bars))
            self.assertTrue(np.all(np.isfinite(d)))
            self.assertTrue(np.all(d>0))

if __name__=="__main__":
    unittest.main()
