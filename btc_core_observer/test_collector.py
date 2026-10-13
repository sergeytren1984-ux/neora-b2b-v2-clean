import unittest,datetime as dt
from btc_core_observer.collector import registration,due_missing_or_current,START,END
from unittest.mock import patch

class CollectorTests(unittest.TestCase):
    def test_no_late_registration(self):
        with patch('btc_core_observer.collector.now',return_value=START):
            with self.assertRaises(RuntimeError):registration('a'*40)

    def test_registration_exact_grid_and_no_authority(self):
        with patch('btc_core_observer.collector.now',return_value=START-dt.timedelta(minutes=1)):
            r=registration('a'*40)
        self.assertEqual(r['due_slots'],96);self.assertFalse(r['historical_candidates_deployed']);self.assertFalse(r['trading_authority'])

    def test_outside_epoch_never_eligible(self):
        self.assertTrue(due_missing_or_current(START));self.assertFalse(due_missing_or_current(END));self.assertFalse(due_missing_or_current(START-dt.timedelta(minutes=15)))

if __name__=='__main__':unittest.main()
