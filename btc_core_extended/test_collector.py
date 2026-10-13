import datetime as dt,unittest
from btc_core_extended import collector as c
from btc_core_observer import collector as old

class ExtendedTests(unittest.TestCase):
    def test_new_epoch_starts_at_old_end_without_editing_old_epoch(self):
        self.assertEqual(c.START,old.END)
        self.assertEqual(old.END,dt.datetime(2026,10,14,11,0,tzinfo=dt.timezone.utc))
        self.assertNotEqual(c.SOURCE,old.SOURCE);self.assertNotEqual(c.LEDGER,old.LEDGER)

    def test_registration_grid_is_exact_and_not_old_96(self):
        slots=int((c.END-c.START)/c.CADENCE)
        self.assertEqual(slots,578)
        self.assertFalse(c.due_missing_or_current(c.START-c.CADENCE))
        self.assertTrue(c.due_missing_or_current(c.START))
        self.assertTrue(c.due_missing_or_current(c.END-c.CADENCE))
        self.assertFalse(c.due_missing_or_current(c.END))

if __name__=='__main__':unittest.main()
