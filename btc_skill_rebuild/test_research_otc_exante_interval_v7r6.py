import unittest
from datetime import datetime,timedelta,timezone
from btc_skill_rebuild.research_otc_exante_interval_v7r6 import (
    PriceInterval,TimelyPair,otc_interval_decision)
UTC=timezone.utc
T=datetime(2026,11,5,15,0,tzinfo=UTC)
SHA='a'*64

def make(now,wait,days=24,public=8,authenticated=True):
    return TimelyPair(T,T+timedelta(minutes=public),PriceInterval(*now),
        PriceInterval(*wait),days,True,authenticated,SHA,
        T-timedelta(hours=20),.95,0)

class ExAnteEconomicInterval(unittest.TestCase):
    def test_points_and_uncertain_intervals_are_not_the_same(self):
        # Spot point difference 300 USDT appears to favor WAIT, but the
        # corresponding ±200 bands overlap once OTC markup varies.
        point=otc_interval_decision(make((83000,83000),(82700,82700)))
        self.assertEqual(point['mathematical_verdict'],'WAIT_RESEARCH_CANDIDATE')
        uncertain=otc_interval_decision(make((82800,83200),(82500,82900)))
        self.assertEqual(uncertain['mathematical_verdict'],'UNRESOLVED_NO_TRADE_SIGNAL')
        self.assertFalse(uncertain['trading_authority'])

    def test_losing_and_profitable_candidates_symmetric(self):
        self.assertEqual(otc_interval_decision(
            make((83000,83000),(83400,83400)))['mathematical_verdict'],
            'NOW_RESEARCH_CANDIDATE')
        self.assertEqual(otc_interval_decision(
            make((82700,83000),(82000,82200)))['mathematical_verdict'],
            'WAIT_RESEARCH_CANDIDATE')
        for a,b in [((0,83000),(82000,83000)),((83001,83000),(80000,82000))]:
            with self.assertRaises(ValueError):otc_interval_decision(make(a,b))

    def test_asof_sha_calibration_and_deadline_are_mandatory(self):
        self.assertEqual(otc_interval_decision(make((83000,83000),(82000,82000),days=19))['mathematical_verdict'],
            'INSUFFICIENT_CALIBRATION')
        self.assertEqual(otc_interval_decision(make((83000,83000),(82000,82000),authenticated=False))['mathematical_verdict'],
            'UNVERIFIED_MATH_INPUTS')
        self.assertEqual(otc_interval_decision(make((83000,83000),(82000,82000),public=14))['mathematical_verdict'],
            'NO_TIMELY_VALID_FORECAST')
        p=make((83000,83000),(82000,82000))
        object.__setattr__(p,'input_source_sha256','forged')
        self.assertEqual(otc_interval_decision(p)['mathematical_verdict'],'UNVERIFIED_MATH_INPUTS')

    def test_exante_intervals_require_joint_out_of_sample_coverage(self):
        a=make((83000,83000),(82000,82000))
        object.__setattr__(a,'retrospective_joint_interval_coverage',.85)
        self.assertEqual(otc_interval_decision(a)['mathematical_verdict'],
                         'UNCALIBRATED_PRICE_INTERVALS')
        object.__setattr__(a,'retrospective_joint_interval_coverage',.95)
        object.__setattr__(a,'last_completed_calibration_utc',T+timedelta(minutes=1))
        self.assertEqual(otc_interval_decision(a)['mathematical_verdict'],
                         'UNMATURED_CALIBRATION')
        object.__setattr__(a,'last_completed_calibration_utc',T-timedelta(hours=20))
        object.__setattr__(a,'missing_predeclared_calibration_days',1)
        self.assertEqual(otc_interval_decision(a)['mathematical_verdict'],
                         'INSUFFICIENT_CALIBRATION')

    def test_frozen_bands_boundary_no_false_strict_advantage(self):
        # Differential OTC markup can offset exactly 100 USDT price gain.
        p=otc_interval_decision(make((83000,83000),(82900,82900)))
        self.assertEqual(p['mathematical_verdict'],'UNRESOLVED_NO_TRADE_SIGNAL')
        self.assertAlmostEqual(p['wait_minus_now_BTC_lower'],0.)

if __name__=='__main__':unittest.main()
