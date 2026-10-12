"""No possible research promotion based on future labels or unverified risk."""
from __future__ import annotations
import unittest,math,datetime as dt
from btc_skill_rebuild.research_regime_recency_v7r6 import weighted_fit,HALF_LIVES_DAYS
from btc_skill_rebuild.research_competing_barriers_v7r6 import prob
from btc_skill_rebuild.research_risk_direction_split_v7r6 import split_prob,masked_flow,SIGNAL_INDICES
from btc_skill_rebuild.research_conditional_direction_v7r6 import train_direction

class FixedMathContract(unittest.TestCase):
    def samples(self):
        t=int(dt.datetime(2026,9,1,tzinfo=dt.timezone.utc).timestamp()*1000)
        return [(t+15*60000*i,tuple(math.sin(i/(4+j)) for j in range(17)),i%4)
                for i in range(1660)]

    def test_recency_is_probabilistic_and_not_certain(self):
        a=self.samples()
        self.assertEqual(HALF_LIVES_DAYS,(None,7,14))
        model=weighted_fit(a,7)
        p=prob(model,a[-1][1],1.)
        self.assertEqual(len(p),4)
        self.assertAlmostEqual(sum(p),1.,places=10)
        self.assertTrue(all(0<p0<1 for p0 in p))
        with self.assertRaises(ValueError):weighted_fit(a,31)

    def test_risk_preserving_direction_split_does_not_invent_event_odds(self):
        a=self.samples()
        onlyflow=[(t,masked_flow(x),y) for t,x,y in a]
        m=train_direction(onlyflow)
        q=[0.17,0.10,0.70,0.03]
        for alpha in (0.,.25,.5,.75,1.):
            z=split_prob(q,m,a[-1][1],alpha)
            self.assertAlmostEqual(z[0]+z[1],q[0]+q[1],places=12)
            self.assertEqual(z[2:],q[2:])
            self.assertAlmostEqual(sum(z),1.,places=12)
        self.assertEqual(SIGNAL_INDICES,(5,6,7,8))
        with self.assertRaises(ValueError):split_prob([.5,.7,.02,.02],m,a[-1][1],.5)

if __name__=='__main__':unittest.main()
