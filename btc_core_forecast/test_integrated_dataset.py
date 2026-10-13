import unittest
import copy,datetime as dt
import numpy as np
from integrated_dataset import targets,training_readiness,trajectory_matrix
from factor_integration import FEATURE_NAMES

class TargetTests(unittest.TestCase):
    def rows(self):
        start=1791889200000
        return [[start+i*300000,'100','103','99','102','1',start+(i+1)*300000-1] for i in range(12)]
    def sample(self):return {'anchor_utc':'2026-10-13T11:00:00+00:00','reference_spot':100,'eligible_for_research_matrix':True,'macro_quotes':{'immutable_collector_source_proven':True}}
    def test_closed_hour_label_not_extended_to_four_or_24_hours(self):
        r=targets([self.sample()],self.rows(),'2026-10-13T12:00:00+00:00')[0]
        self.assertIsNotNone(r['direction_targets']['1']);self.assertIsNone(r['direction_targets']['4']);self.assertIsNone(r['direction_targets']['24']);self.assertIsNone(r['delayed_entry_spot_proxy_targets']['1'])
    def test_future_candle_is_rejected_not_truncated_into_label(self):
        with self.assertRaisesRegex(ValueError,'unclosed'):targets([self.sample()],self.rows(),'2026-10-13T11:55:00+00:00')
    def test_training_blocks_with_missing_horizon_and_one_class(self):
        r=targets([self.sample()],self.rows(),'2026-10-13T12:00:00+00:00')
        check=training_readiness(r);self.assertFalse(check['can_begin_full_candidate_training']);self.assertIn('NO_CLOSED_DIRECTION_TARGETS:24h',check['reasons'])

class TrajectoryTests(unittest.TestCase):
    def data(self):
        start=1790640000000
        bars=[[start+i*300000,100,103,99,102,1,start+(i+1)*300000-1] for i in range(72*12)]
        row={'anchor_utc':'2026-09-29T00:00:00+00:00','reference_spot':100,'past_sigma':.01,
            'features':[1.]*len(FEATURE_NAMES),'feature_names':FEATURE_NAMES,'eligible_for_research_matrix':True}
        return row,bars
    def test_observed_extrema_and_close_use_same_reference_and_scale(self):
        row,bars=self.data();a,selected,report=trajectory_matrix([row],bars,'2026-10-02T00:00:00+00:00')
        self.assertEqual(report['accepted_rows'],1);self.assertEqual(a['close'].shape,(1,72))
        np.testing.assert_allclose(a['close'],np.log(1.02)/.01)
        np.testing.assert_allclose(a['high'],np.log(1.03)/.01)
        np.testing.assert_allclose(a['low'],np.log(.99)/.01)
    def test_one_missing_bar_rejects_path_without_interpolation(self):
        row,bars=self.data();del bars[19]
        a,selected,r=trajectory_matrix([row],bars,'2026-10-02T00:00:00+00:00')
        self.assertEqual(len(selected),0);self.assertEqual(a['x'].shape,(0,len(FEATURE_NAMES)))
        self.assertEqual(r['rejected_rows'][0]['reason'],'ACTUAL_TRAJECTORY_GAP')
    def test_unfinished_72h_path_cannot_be_fitted_as_observed(self):
        row,bars=self.data();a,selected,r=trajectory_matrix([row],bars[:-1],'2026-10-01T23:55:00+00:00')
        self.assertEqual(len(selected),0);self.assertEqual(r['rejected_rows'][0]['reason'],'72H_TARGET_NOT_CLOSED')

if __name__=='__main__':unittest.main()
