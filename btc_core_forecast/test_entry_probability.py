import unittest
import numpy as np
import entry_probability as p

class EntryProbabilityTests(unittest.TestCase):
    def test_exact_delayed_execution(self):
        close=np.zeros((2,72));close[0,0]=np.log(1.10);close[0,4]=np.log(.90)
        gain=p.realized_gain(close,np.ones(2),np.full(2,100.),4,premium=3.,budget=1000.)
        self.assertAlmostEqual(gain[0],1000/93-1000/113)
        self.assertEqual(gain[1],0.)

    def test_unseen_labels_do_not_change_fit_or_calibration(self):
        rng=np.random.default_rng(20);x=rng.normal(size=(900,3));gain=rng.normal(size=900)
        tr=np.arange(500);ca=np.arange(500,750)
        first=p.fit(x,gain,tr,ca)
        changed=gain.copy();changed[750:]=1000
        second=p.fit(x,changed,tr,ca)
        for fit in (first,second):
            prediction=fit[1].predict(fit[0].predict_proba(x[750:])[:,1])
            if fit is first:baseline=prediction
            else:np.testing.assert_array_equal(prediction,baseline)
        self.assertEqual(first[2:],second[2:])

    def test_flat_execution_is_not_positive_class(self):
        gains=p.realized_gain(np.zeros((3,72)),np.ones(3),np.full(3,100.),24)
        self.assertFalse((gains>0).any())

if __name__=='__main__':unittest.main()
