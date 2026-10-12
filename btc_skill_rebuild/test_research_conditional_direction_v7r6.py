"""A directional improvement may not counterfeit movement probability."""
import datetime as dt,math,unittest
from btc_skill_rebuild.research_conditional_direction_v7r6 import (
    train_direction,adjusted,score,direction_up,DIRECTION_INPUT_INDICES)
from btc_skill_rebuild.research_competing_barriers_v7r6 import fit,prob

class DirectionalCausality(unittest.TestCase):
    def test_preserves_identical_event_risk_and_early_trained_inputs(self):
        base=int(dt.datetime(2026,8,12,tzinfo=dt.timezone.utc).timestamp()*1000)
        tr=[]
        for i in range(1700):
            x=[math.sin(i/(7+j)) for j in range(17)]
            y=(0 if i%4==0 else 1 if i%5==0 else 2)
            tr.append((base+i*900000,x,y))
        original=fit([(t,x,y,None) for t,x,y in tr])
        dir_model=train_direction(tr)
        self.assertEqual(len(DIRECTION_INPUT_INDICES),8)
        for z in (0.,.25,.5,1.):
            a,b=adjusted(original,dir_model,tr[-1][1],1.,z)
            self.assertAlmostEqual(sum(a),1.,places=10)
            self.assertAlmostEqual(sum(b),1.,places=10)
            self.assertAlmostEqual(a[0]+a[1],b[0]+b[1],places=12)
            self.assertEqual(a[2:],b[2:])
            self.assertTrue(all(math.isfinite(v) and 0<=v<=1 for v in b))
        self.assertAlmostEqual(direction_up(dir_model,tr[-1][1],0.),dir_model['prior_UP_conditional'],places=12)
        diag=score(tr[-180:],original,dir_model,1.,.5)
        self.assertTrue(diag['matched_any_event_risk'])
        self.assertEqual(diag['n_rows'],180)
        self.assertGreater(diag['n_actual_first_touch_updown'],0)

if __name__=='__main__':unittest.main()
