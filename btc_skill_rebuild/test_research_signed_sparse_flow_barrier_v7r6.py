import unittest,datetime as dt
from btc_skill_rebuild.research_signed_sparse_flow_barrier_v7r6 import outcome,heuristic,analyse
UTC=dt.timezone.utc
T=dt.datetime(2026,10,13,0,0,tzinfo=UTC)
def bar(k,hi=83000,lo=83000):
    t=T+dt.timedelta(minutes=k)
    start=int((t-dt.timedelta(minutes=5)).timestamp()*1000)
    return [start,'83000',str(hi),str(lo),'83000','1',start+299999]
class Guard(unittest.TestCase):
    def test_no_future_bar_is_not_neither(self):
        x={T+dt.timedelta(minutes=k):bar(k) for k in range(5,60,5)}
        self.assertFalse(outcome(x,T,83000,60,.007)['mature'])
        x[T+dt.timedelta(minutes=60)]=bar(60)
        self.assertEqual(outcome(x,T,83000,60,.007)['side'],'NEITHER')
    def test_first_touch_and_ambiguous_same_bar(self):
        x={T+dt.timedelta(minutes=k):bar(k) for k in range(5,65,5)}
        x[T+dt.timedelta(minutes=5)]=bar(5,hi=83700)
        self.assertEqual(outcome(x,T,83000,60,.007)['side'],'UP_FIRST')
        x[T+dt.timedelta(minutes=5)]=bar(5,hi=84000,lo=82000)
        self.assertEqual(outcome(x,T,83000,60,.007)['side'],'AMBIGUOUS_SAME_5M')
    def test_independent_book_rule_differs(self):
        x=heuristic({'flow15':.7,'flow3':.6,'book':-.8})
        self.assertEqual(x['two_binance_flows'],'UP_FIRST')
        self.assertIsNone(x['microflow_okx_book'])
    def test_denominator_and_duplicate_checks(self):
        due=[T.isoformat(),(T+dt.timedelta(minutes=15)).isoformat()]
        a={'slot':due[0],'flow15':.7,'flow3':.7,'book':.8,'price':83000,'blob':'a'*40}
        fut={'source_snapshot_git_blob_sha':'b'*40,'bars':[bar(k) for k in range(5,245,5)]}
        pre={'predeclared_due_anchors':due,'observed':[a]}
        result=analyse(pre,fut)
        self.assertEqual(result['horizons']['1h']['missing_R5_samples_full_due_denominator'],1)
        pre['observed'].append(a)
        with self.assertRaises(ValueError):analyse(pre,fut)
if __name__=='__main__':unittest.main()
