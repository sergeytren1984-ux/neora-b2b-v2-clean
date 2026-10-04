"""Invariant tests for predictive vNext2 research."""
import unittest
import numpy as np

from core import (first_touch_variable, masks, build_hourly_features,
                  build_15m_features, adaptive_baselines)


class PredictiveVNext2Tests(unittest.TestCase):
    def test_same_bar_is_ambiguous_and_first_touch_is_sticky(self):
        c=np.full(20,100.0);hi=c.copy();lo=c.copy()
        hi[2]=102;lo[2]=98;lo[3]=90
        y,when=first_touch_variable(np.array([1]),hi,lo,c,np.array([99.]),np.array([101.]),4)
        self.assertEqual((int(y[0]),int(when[0])),(3,1))

    def test_lower_first_cannot_be_overwritten_by_later_upper(self):
        c=np.full(20,100.0);hi=c.copy();lo=c.copy()
        lo[2]=98;hi[3]=105
        y,when=first_touch_variable(np.array([1]),hi,lo,c,np.array([99.]),np.array([101.]),4)
        self.assertEqual((int(y[0]),int(when[0])),(0,1))

    def test_purge_excludes_label_crossing_train_boundary(self):
        dates=np.array(["2025-09-28T00","2025-09-30T00","2025-10-01T00",
                        "2025-12-30T00","2026-01-08T00"],dtype="datetime64[h]")
        tr,ca,te=masks(dates,np.timedelta64(72,"h"),"2025-10-01","2025-10-01",
                       "2026-01-01","2026-01-08","2026-07-01")
        self.assertFalse(tr[1])
        self.assertTrue(ca[2])
        self.assertTrue(te[4])

    def _hourly_source(self,n=500):
        t=np.arange(n,dtype=np.int64)*3600000
        c=100+np.arange(n)*.01
        hi=c+.05;lo=c-.05;v=np.full(n,10.);tr=np.full(n,100.);tk=np.full(n,5.)
        return t,hi,lo,c,v,tr,tk

    def test_hourly_features_do_not_see_future_candle(self):
        t,hi,lo,c,v,tr,tk=self._hourly_source()
        ix,d,X,names,r,vol,atr=build_hourly_features(t,hi,lo,c,v,tr,tk,168)
        row=np.flatnonzero(ix==169)[0]
        baseline=X[row].copy()
        c[170]=100000;hi[170]=120000;v[170]=999999;tr[170]=999999;tk[170]=999999
        _,_,X2,_,_,_,_=build_hourly_features(t,hi,lo,c,v,tr,tk,168)
        np.testing.assert_allclose(baseline,X2[row])

    def test_atr_is_not_affected_by_future(self):
        t,hi,lo,c,v,tr,tk=self._hourly_source()
        ix,_,_,_,_,_,atr=build_hourly_features(t,hi,lo,c,v,tr,tk,168)
        row=np.flatnonzero(ix==169)[0];a=float(atr[row])
        hi[170]=999999;lo[170]=1
        _,_,_,_,_,_,atr2=build_hourly_features(t,hi,lo,c,v,tr,tk,168)
        self.assertEqual(a,float(atr2[row]))

    def test_15m_features_do_not_see_future(self):
        n=900;t=np.arange(n,dtype=np.int64)*900000
        c=100+np.arange(n)*.001;hi=c+.02;lo=c-.02
        v=np.full(n,5.);tr=np.full(n,50.);tk=np.full(n,2.5)
        ix,d,X,names,r,vol=build_15m_features(t,hi,lo,c,v,tr,tk,16)
        row=np.flatnonzero(ix==384)[0];base=X[row].copy()
        c[385]=99999;hi[385]=120000;v[385]=999999
        _,_,X2,_,_,_=build_15m_features(t,hi,lo,c,v,tr,tk,16)
        np.testing.assert_allclose(base,X2[row])

    def test_adaptive_baseline_does_not_use_not_yet_due_outcome(self):
        dates=np.arange(np.datetime64("2025-01-01T00"),np.datetime64("2025-01-20T00"),
                        np.timedelta64(1,"h"))
        n=len(dates);y=np.zeros(n,dtype=np.int8);reg=np.zeros(n,dtype=np.int8)
        vol=np.ones(n)
        train=dates<np.datetime64("2025-01-10T00")
        test=(dates>=np.datetime64("2025-01-15T00"))&(dates<np.datetime64("2025-01-16T00"))
        a=adaptive_baselines(dates,y,reg,vol,train,test,np.timedelta64(72,"h"))
        # Change labels whose due time is after the first test anchor; first prediction must not change.
        y2=y.copy();late=(dates>=np.datetime64("2025-01-12T01"));y2[late]=1
        b=adaptive_baselines(dates,y2,reg,vol,train,test,np.timedelta64(72,"h"))
        for key in a:
            np.testing.assert_allclose(a[key][0],b[key][0])

    def test_adaptive_probabilities_sum_to_one(self):
        dates=np.arange(np.datetime64("2025-01-01T00"),np.datetime64("2025-03-01T00"),
                        np.timedelta64(1,"h"))
        n=len(dates);y=np.arange(n,dtype=np.int64)%4
        reg=np.arange(n,dtype=np.int64)%4;vol=np.linspace(.1,1,n)
        train=dates<np.datetime64("2025-02-01T00")
        test=dates>=np.datetime64("2025-02-20T00")
        p=adaptive_baselines(dates,y,reg,vol,train,test,np.timedelta64(24,"h"))
        for arr in p.values():
            np.testing.assert_allclose(arr.sum(axis=1),1.0)


if __name__=="__main__":
    unittest.main()
