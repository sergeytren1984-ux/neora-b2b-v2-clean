"""Negative tests for direction-agnostic global event counting."""
import unittest
from btc_skill_rebuild.research_direction_agnostic_event_clusters_v7r6 import side_agnostic_clusters

M=60000
class EpisodeMathTests(unittest.TestCase):
    def test_cross_side_and_duplicate(self):
        result=side_agnostic_clusters([(10*M,0),(10*M,0),(25*M,1),(40*M,0)],60*M)
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]["unique_touch_labels"],3)
        self.assertEqual(set(result[0]["sides"]),{0,1})

    def test_week_boundary(self):
        edge=7*24*60*M
        events=[(edge-5*M,0),(edge+5*M,1)]
        self.assertEqual(len(side_agnostic_clusters(events,60*M)),1)
        self.assertEqual(sum(len(side_agnostic_clusters([x],60*M)) for x in events),2)

    def test_original_horizon_not_tuned(self):
        events=[(100*M,0),(165*M,1)]
        self.assertEqual(len(side_agnostic_clusters(events,60*M)),2)
        self.assertEqual(len(side_agnostic_clusters(events,240*M)),1)

    def test_connected_chain(self):
        self.assertEqual(len(side_agnostic_clusters([(0,0),(45*M,1),(90*M,0),(135*M,1)],60*M)),1)

    def test_invalid_event(self):
        for events in [[(-1,0)],[(1,2)],[(1,True)],[(1.0,0)]]:
            with self.assertRaises(ValueError):side_agnostic_clusters(events,60*M)

    def test_invalid_span(self):
        for span in (0,-1,1.5):
            with self.assertRaises(ValueError):side_agnostic_clusters([(0,0)],span)

    def test_order_invariance(self):
        x=[(20*M,0),(5*M,1),(20*M,0),(70*M,1),(150*M,0)]
        self.assertEqual(side_agnostic_clusters(x,60*M),side_agnostic_clusters(x[::-1],60*M))
        self.assertEqual(len(side_agnostic_clusters(x,60*M)),2)

if __name__=="__main__":unittest.main()
