import unittest
from impulse_check import inspect

class ImpulseTests(unittest.TestCase):
    def rows(self):
        return [[i*60000,10000.,10000.,10000.,10000.,1.,(i+1)*60000-1,10000.,1,.5,5000.,0] for i in range(16)]
    def set_last(self,r,price):r[-1][1:5]=[price]*4

    def test_500_move_in_six_minutes_is_not_called_quiet(self):
        r=self.rows();self.set_last(r,10500.)
        out=inspect(r,960000,960010)
        self.assertTrue(out['rapid_move_observed']);self.assertIn('РОСТ',out['state_рус'])
        self.assertTrue(out['observed_detection_not_a_prediction']);self.assertFalse(out['full_system_ready'])

    def test_1000_move_in_fifteen_minutes_is_detected(self):
        r=self.rows()
        for i in range(1,16):r[i][1:5]=[10000.+i*1000/15]*4
        out=inspect(r,960000,960010)
        self.assertTrue(out['rapid_move_observed']);self.assertAlmostEqual(out['delta_15m_usdt'],1000.)

    def test_fast_drop_is_explicit(self):
        r=self.rows();self.set_last(r,9500.)
        self.assertIn('СНИЖЕНИЕ',inspect(r,960000,960010)['state_рус'])

    def test_fast_intraminute_round_trip_is_not_hidden_by_unchanged_close(self):
        r=self.rows();r[-1][2]=10600.
        out=inspect(r,960000,960010)
        self.assertTrue(out['rapid_move_observed']);self.assertIn('КОЛЕБАНИЯ',out['state_рус'])

    def test_stale_source_never_returns_quiet(self):
        with self.assertRaises(ValueError):inspect(self.rows(),960000,1080001)

    def test_future_source_never_returns_current(self):
        with self.assertRaises(ValueError):inspect(self.rows(),960000,959999)

if __name__=='__main__':unittest.main()
