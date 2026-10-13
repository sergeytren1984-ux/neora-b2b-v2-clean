import unittest
import numpy as np
import joint_candidate as j
import forecast as f

class JointTests(unittest.TestCase):
    def test_weighted_crps_matches_uniform_crps(self):
        samples=np.array([80.,90.,100.,120.]);w=np.full(4,.25)
        self.assertAlmostEqual(j.weighted_crps(samples,w,97.),f.crps(samples,97.))

    def test_deterministic_price_distribution(self):
        self.assertEqual(j.weighted_crps(np.array([100.]),np.array([1.]),80.),20.)
        np.testing.assert_array_equal(j.weighted_quantile(np.array([100.]),np.array([1.]),[.1,.5,.9]),[100.,100.,100.])

    def test_execution_actions_have_distinct_times(self):
        close=np.zeros((2,72));close[:,0]=np.log(1.1);close[:,4]=np.log(.9)
        out=j.entry(close,np.array([.5,.5]),100.,4,budget=1000.,premium=3.)
        self.assertAlmostEqual(out['expected_extra_btc'],1000/93-1000/113)
        self.assertEqual(out['probability_extra_btc'],1.)
        self.assertFalse(out['trading_authority'])

    def test_negative_distribution_mass_is_rejected(self):
        with self.assertRaises(ValueError):j.weighted_crps(np.array([1.,2.]),np.array([-1.,2.]),1.)

if __name__=='__main__':unittest.main()
