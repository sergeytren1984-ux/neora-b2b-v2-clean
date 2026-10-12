"""Reject matching a candidate to a different price/time/slot or future data."""
import copy,unittest
from datetime import timedelta
from btc_demand_v7.v7r6_paired_forward_audit import one_pair,fixed_grid_score,PINNED_RUNNER_SHA
from btc_demand_v7.v7r6_live_pair_worker import START,R6_SHA,sha
from btc_demand_v7.shadow_contract_v3 import future_anchor

class PairedAudit(unittest.TestCase):
    def fixture(self,horizon='4h',direction='UP_FIRST',touch_at=100):
        anchor=START+timedelta(minutes=480)
        pub=anchor+timedelta(minutes=9,seconds=30)
        d={'current_snapshot_sha256':'snapshot-hash','alert':True,'warning_side':'UP'}
        c={'current_snapshot_sha256':'snapshot-hash','alert':False,'warning_side':None}
        shadow={'schema':'btc-v7r6-paired-future-public-shadow-v1','kind':'R6_SIGNED_SHADOW',
            'slot_id':anchor.strftime('%Y%m%dT%H%MZ'),'anchor_utc':anchor.isoformat(),
            'decision_computed_utc':(anchor+timedelta(minutes=8)).isoformat(),
            'research_model_sha':R6_SHA,'runner_sha':PINNED_RUNNER_SHA,
            'source_r5_snapshot_sha256':'snapshot-hash',
            'baseline_r5_diagnostic':d,'challenger_diagnostic':c,
            'trading_authority':False}
        proof={'status':'VERIFIED_GITHUB_COMPLETED_JOB_AND_SIGNED_COMMIT',
               'conclusion':'success','run_id':1234,'job_source_sha':PINNED_RUNNER_SHA,
               'job_completed_utc':pub.isoformat(),
               'signed_shadow_sha256':sha(shadow)}
        end=pub.replace(second=0,microsecond=0)
        open_time=end-timedelta(minutes=1)
        ms=lambda ts:int(ts.timestamp()*1000)
        reference=[ms(open_time),'83000','83000','83000','83000','1',ms(end)-1]
        n={'1h':60,'4h':240}[horizon]
        start=future_anchor(pub)
        rows=[]
        for i in range(n):
            o=start+timedelta(minutes=i)
            high='84100' if i==touch_at and direction=='UP_FIRST' else '83000'
            low='81900' if i==touch_at and direction=='DOWN_FIRST' else '83000'
            rows.append([ms(o),'83000',high,low,'83000','1',ms(o+timedelta(minutes=1))-1])
        due=start+timedelta(minutes=n)
        return shadow,proof,reference,rows,(due+timedelta(minutes=1)).isoformat()

    def test_shared_true_future_and_no_claim_of_OTC_fills(self):
        s,p,ref,rows,t=self.fixture()
        v=one_pair(s,p,ref,rows,'4h',observed_utc=t,as_of_utc=t)
        self.assertEqual(v['event_result'],'UP_FIRST')
        self.assertTrue(v['candidate_stats']['frozen_v7r5']['correct_with_60m_lead'])
        self.assertFalse(v['candidate_stats']['consensus_v7r6']['issued'])
        self.assertTrue(v['same_forward_reference_for_both_models'])
        self.assertFalse(v['actual_OTC_fill_observed'])
        score_time=(__import__('datetime').datetime.fromisoformat(t)+timedelta(minutes=40)).isoformat()
        score=fixed_grid_score([v],horizon='4h',as_of_utc=score_time)
        self.assertEqual(score['matured_registered_due'],1)
        self.assertEqual(score['missing_due_including_missing_signals'],0)
        self.assertEqual(score['comparison']['frozen_v7r5']['correct_with_60m_lead'],1)
        self.assertFalse(score['trade_skill_proven'])
        missing=fixed_grid_score([],horizon='4h',as_of_utc=score_time)
        self.assertEqual(missing['missing_due_including_missing_signals'],1)
        self.assertTrue(missing['missing_blocks_trading'])

    def test_one_hour_cannot_claim_sixty_minute_warning(self):
        s,p,ref,rows,t=self.fixture('1h',touch_at=40)
        v=one_pair(s,p,ref,rows,'1h',observed_utc=t,as_of_utc=t)
        self.assertTrue(v['candidate_stats']['frozen_v7r5']['correct_with_30m_lead'])
        self.assertFalse(v['candidate_stats']['frozen_v7r5']['correct_with_60m_lead'])
        self.assertTrue(v['candidate_stats']['frozen_v7r5']['false_or_insufficient_60m'])

    def test_no_cross_window_or_time_cheat(self):
        s,p,ref,rows,t=self.fixture()
        cases=[]
        bad=copy.deepcopy(s);bad['slot_id']='WRONG';cases.append((bad,p,ref,rows,t))
        bad=copy.deepcopy(s);bad['challenger_diagnostic']['current_snapshot_sha256']='FUTURE';cases.append((bad,p,ref,rows,t))
        bad=copy.deepcopy(p);bad['signed_shadow_sha256']='FAKE';cases.append((s,bad,ref,rows,t))
        bad=copy.deepcopy(p);bad['status']='SELF_ASSERTED';cases.append((s,bad,ref,rows,t))
        bad=copy.deepcopy(p);bad['job_source_sha']='MAIN_NOT_PINNED';cases.append((s,bad,ref,rows,t))
        bad=copy.deepcopy(s);bad['runner_sha']='NOT_THE_PREREGISTERED_RUNNER';cases.append((bad,p,ref,rows,t))
        bad=copy.deepcopy(p);bad['job_completed_utc']=(START+timedelta(hours=8,minutes=14)).isoformat();cases.append((s,bad,ref,rows,t))
        bad=copy.deepcopy(ref);bad[0]-=60000;bad[6]-=60000;cases.append((s,p,bad,rows,t))
        bad=copy.deepcopy(rows);bad[0][6]+=60000;cases.append((s,p,ref,bad,t))
        late=(START+timedelta(hours=8,minutes=10)).isoformat()
        cases.append((s,p,ref,rows,late))
        for a,b,c,d,e in cases:
            with self.subTest(case=len(cases)):
                with self.assertRaises(ValueError):one_pair(a,b,c,d,'4h',observed_utc=e,as_of_utc=t)

    def test_grid_rejects_duplicate_and_nonregistered_outcomes(self):
        s,p,ref,rows,t=self.fixture()
        good=one_pair(s,p,ref,rows,'4h',observed_utc=t,as_of_utc=t)
        with self.assertRaises(ValueError):fixed_grid_score([good,good],horizon='4h',as_of_utc=t)
        old=copy.deepcopy(good);old['slot_id']='20260101T0000Z'
        with self.assertRaises(ValueError):fixed_grid_score([old],horizon='4h',as_of_utc=t)
        with self.assertRaises(ValueError):fixed_grid_score([good],horizon='1h',as_of_utc=t)

if __name__=='__main__':unittest.main()
