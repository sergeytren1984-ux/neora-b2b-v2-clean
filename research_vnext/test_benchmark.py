"""Boundary and as-of invariants for the research benchmark."""
import unittest
import numpy as np

from benchmark import first_touch, masks, features


class BenchmarkInvariants(unittest.TestCase):
    def test_same_hour_is_ambiguous_and_later_touch_cannot_change_first(self):
        close=np.full(10,100.0); hi=close.copy(); lo=close.copy()
        hi[2]=102;lo[2]=98;lo[3]=95
        y,when=first_touch(np.array([1]),hi,lo,close,.01,4)
        self.assertEqual((int(y[0]),int(when[0])),(3,1))
        hi[2]=100;lo[2]=98;hi[3]=105
        y,when=first_touch(np.array([1]),hi,lo,close,.01,4)
        self.assertEqual((int(y[0]),int(when[0])),(0,1))

    def test_train_labels_and_calibration_labels_purged(self):
        dates=np.array(['2025-09-30T00:00','2025-10-01T00:00',
                        '2025-12-31T00:00','2026-01-08T00:00'],dtype='datetime64[m]')
        train,cal,test=masks(dates,24)
        self.assertEqual(train.tolist(),[False,False,False,False])
        self.assertEqual(cal.tolist(),[False,True,False,False])
        self.assertEqual(test.tolist(),[False,False,False,True])

    def test_future_candle_does_not_modify_anchor_features(self):
        n=400;t=np.arange(n,dtype=np.int64)*3600000
        c=100+np.arange(n)*.01;hi=c+.02;lo=c-.02
        v=np.full(n,2.);trades=np.full(n,100.);taker=np.full(n,1.)
        ix,_,base,micro,gate=features(t,hi,lo,c,v,trades,taker)
        j=np.flatnonzero(ix==169)[0]
        c[170]=100000;hi[170]=200000;v[170]=10000
        _,_,base2,micro2,gate2=features(t,hi,lo,c,v,trades,taker)
        np.testing.assert_array_equal(base[j],base2[j]);np.testing.assert_array_equal(micro[j],micro2[j])
        self.assertEqual(gate[j],gate2[j])


if __name__=='__main__':unittest.main()
