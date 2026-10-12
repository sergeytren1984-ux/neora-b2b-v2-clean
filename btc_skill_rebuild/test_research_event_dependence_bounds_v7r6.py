"""Adversarial pure mathematical v7R6 event-dependence tests."""
import unittest
from btc_skill_rebuild.research_event_dependence_bounds_v7r6 import anchored,summarize,checked_events

H=60*60*1000

class TestEventDependence(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(summarize([],H)["both_sides_first_touch_anchored_nonoverlapping_windows"],0)

    def test_identical_repeated_forecast_outcomes_are_one_touch(self):
        events=[(0,0)]*24+[(5*60*1000,0)]*40
        self.assertEqual(summarize(events,H)["global_unique_first_touch_time_direction_pairs"],2)
        self.assertEqual(len(anchored(events,H,split_sides=False)),1)

    def test_no_transitive_chaining_beyond_horizon(self):
        events=[(0,0),(50*60*1000,0),(100*60*1000,0)]
        result=summarize(events,H)
        self.assertEqual(result["original_same_side_single_link_chained_episodes"],1)
        self.assertEqual(result["original_chains_spanning_more_than_one_horizon"],1)
        self.assertEqual(result["same_side_first_touch_anchored_episodes"],2)
        self.assertEqual(result["both_sides_first_touch_anchored_nonoverlapping_windows"],2)

    def test_reversals_inside_one_window_not_independent(self):
        events=[(0,0),(5*60*1000,1),(10*60*1000,0)]
        result=summarize(events,H)
        self.assertEqual(result["same_side_first_touch_anchored_episodes"],2)
        self.assertEqual(result["both_sides_first_touch_anchored_nonoverlapping_windows"],1)
        self.assertEqual(result["both_sides_anchored_windows_containing_UP_and_DOWN"],1)

    def test_horizon_inclusive_at_end(self):
        self.assertEqual(len(anchored([(0,0),(H,0)],H,split_sides=False)),1)
        self.assertEqual(len(anchored([(0,0),(H+1,0)],H,split_sides=False)),2)

    def test_input_order_invariant(self):
        a=[(0,1),(5,0),(10,1),(H+100,0),(H+101,1)]
        self.assertEqual(summarize(a,H),summarize(list(reversed(a)),H))

    def test_same_timestamp_opposite_side_is_ambiguous_episode(self):
        result=summarize([(0,0),(0,1)],H)
        self.assertEqual(result["global_unique_first_touch_time_direction_pairs"],2)
        self.assertEqual(result["both_sides_first_touch_anchored_nonoverlapping_windows"],1)
        self.assertEqual(result["both_sides_anchored_windows_containing_UP_and_DOWN"],1)

    def test_far_apart_events_separate(self):
        result=summarize([(0,0),(H+1,1),(2*H+2,0)],H)
        self.assertEqual(result["both_sides_first_touch_anchored_nonoverlapping_windows"],3)

    def test_reject_negative_timestamp(self):
        with self.assertRaises(ValueError):checked_events([(-1,0)])

    def test_reject_non_binary_direction(self):
        with self.assertRaises(ValueError):checked_events([(0,2)])

    def test_reject_boolean_as_direction(self):
        with self.assertRaises(ValueError):checked_events([(0,True)])

    def test_reject_invalid_horizon(self):
        with self.assertRaises(ValueError):anchored([(0,0)],0,split_sides=False)

    def test_every_event_assigned_once(self):
        events=[(k*10*60*1000,k%2) for k in range(36)]
        for split in (False,True):
            groups=anchored(events,H,split_sides=split)
            self.assertEqual(sum(x["distinct_first_touch_pairs"] for x in groups),len(events))
            self.assertTrue(all(x["last_touch_ms"]-x["first_touch_ms"]<=H for x in groups))

if __name__=="__main__":unittest.main()
