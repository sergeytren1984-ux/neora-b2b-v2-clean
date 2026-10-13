import unittest
import numpy as np
from supervised_direction import tilt

class SignPathTests(unittest.TestCase):
    def support(self):return np.repeat(np.array([-.01,-.001,.001,.01])[:,None],72,axis=1)
    def test_direction_changes_mass_preserving_paths(self):
        paths=self.support();copy=paths.copy();w,_=tilt(paths,[.8,.8,.8]);self.assertAlmostEqual(w[2:].sum(),.8);np.testing.assert_array_equal(paths,copy)
    def test_equal_direction_preserves_uniform_weights(self):
        w,_=tilt(self.support(),[.5,.5,.5]);np.testing.assert_allclose(w,[.25]*4)
    def test_absent_support_not_fabricated(self):
        w,missing=tilt(abs(self.support()),[.2,.2,.2]);self.assertEqual(missing,[1,4,24]);np.testing.assert_allclose(w,[.25]*4)
    def test_invalid_probability_rejected(self):
        with self.assertRaises(ValueError):tilt(self.support(),[1,.5,.5])

if __name__=='__main__':unittest.main()
