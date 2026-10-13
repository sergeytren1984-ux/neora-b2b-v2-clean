"""Joint path preservation, causality, and calibration isolation checks."""
import unittest
import numpy as np
import conditional_path as p

class ConditionalPathTests(unittest.TestCase):
    def trajectories(self):
        rng=np.random.default_rng(42)
        increments=rng.normal(0,.01,(250,72))
        c=np.cumsum(increments,axis=1)
        prev=np.column_stack([np.zeros(len(c)),c[:,:-1]])
        return c,np.maximum(c,prev)+.002,np.minimum(c,prev)-.002

    def test_identity_and_constant_scale(self):
        c,h,l=self.trajectories()
        for scale in (1.,3.):
            actual=p.transform(c,h,l,np.full_like(c,scale))
            for expected,obtained in zip((c,h,l),actual):
                np.testing.assert_allclose(obtained,expected*scale,atol=1e-12)

    def test_variable_scale_retains_hourly_extrema(self):
        c,h,l=self.trajectories()
        multipliers=p.interpolate(np.tile(np.log([.5,1.,2.,.8]),(len(c),1)))
        cc,hh,ll=p.transform(c,h,l,multipliers)
        prev=np.column_stack([np.zeros(len(c)),cc[:,:-1]])
        self.assertTrue(np.all(hh>=np.maximum(cc,prev)))
        self.assertTrue(np.all(ll<=np.minimum(cc,prev)))

    def test_targets_are_per_row_without_future_dataset_dependency(self):
        c,_,_=self.trajectories()
        first=p.volatility_targets(c)
        c[200:]*=100
        np.testing.assert_array_equal(first[:200],p.volatility_targets(c)[:200])

    def test_nonfinite_rejected(self):
        c,h,l=self.trajectories();c[0,3]=np.nan
        with self.assertRaises(ValueError):p.transform(c,h,l,np.ones_like(c))

if __name__=='__main__':unittest.main()
