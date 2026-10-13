import unittest
from integrated_dataset import targets,training_readiness

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

if __name__=='__main__':unittest.main()
