"""Verify earliest barrier minute, not the post-event candle close."""
import unittest,datetime as dt
from btc_skill_rebuild.research_delayed_onset_v7r6 import delayed_label,STEP
class DelayedOnset(unittest.TestCase):
    def test_no_borrowed_time(self):
        issued=int(dt.datetime(2026,9,1,tzinfo=dt.timezone.utc).timestamp()*1000)
        self.assertEqual(delayed_label(0,issued+60*60000,issued),2)
        self.assertEqual(delayed_label(0,issued+65*60000,issued),0)
        self.assertEqual(delayed_label(1,issued+60*60000,issued),2)
        self.assertEqual(delayed_label(1,issued+65*60000,issued),1)
        self.assertEqual(delayed_label(2,None,issued),2)
        self.assertEqual(delayed_label(3,issued+60*60000,issued),3)
        with self.assertRaises(ValueError):delayed_label(0,None,issued)
if __name__=='__main__':unittest.main()
