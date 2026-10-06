"""Virtual-time stress tests for the vNext4R6 queued-successor design."""
from __future__ import annotations

import sys
import unittest
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from predictive_vnext4r6.scheduler import (
    START,
    ACTIVE_SESSION_RUNTIME,
    PRESTART_SESSION_RUNTIME,
    DEADLINE_SAFETY,
)
from predictive_vnext4r6.worker import CONFIG


def simulate(cadence, deadline, delays_minutes):
    issued = []
    missed = []
    cutoff = deadline - DEADLINE_SAFETY
    for i, delay in enumerate(delays_minutes):
        anchor = START + i * cadence
        arrival = anchor + timedelta(minutes=delay)
        if arrival < anchor + cutoff:
            issued.append(i)
        else:
            missed.append(i)
    return issued, missed


class StressTests(unittest.TestCase):
    def test_15m_heads_normal_restart_lag(self):
        delays = [0.8, 1.2, 2, 3, 5, 8, 10, 11] * 63
        delays = delays[:500]
        for head in ("1h", "4h"):
            issued, missed = simulate(
                CONFIG[head]["cadence"],
                CONFIG[head]["deadline"],
                delays,
            )
            self.assertEqual(len(issued), 500)
            self.assertEqual(missed, [])

    def test_15m_13m_delay_is_visible_miss(self):
        delays = [2] * 40
        delays[11] = 13
        issued, missed = simulate(
            CONFIG["1h"]["cadence"],
            CONFIG["1h"]["deadline"],
            delays,
        )
        self.assertEqual(missed, [11])
        self.assertNotIn(11, issued)

    def test_24h_head_42m_recovery_is_admissible(self):
        delays = [1, 5, 15, 25, 35, 42] * 50
        issued, missed = simulate(
            CONFIG["24h"]["cadence"],
            CONFIG["24h"]["deadline"],
            delays,
        )
        self.assertFalse(missed)
        self.assertEqual(len(issued), 300)

    def test_24h_head_44m_delay_is_visible_miss(self):
        delays = [2] * 40
        delays[11] = 44
        issued, missed = simulate(
            CONFIG["24h"]["cadence"],
            CONFIG["24h"]["deadline"],
            delays,
        )
        self.assertEqual(missed, [11])
        self.assertNotIn(11, issued)

    def test_session_length_below_hosted_limit(self):
        self.assertEqual(
            ACTIVE_SESSION_RUNTIME, timedelta(hours=4)
        )
        self.assertLess(
            PRESTART_SESSION_RUNTIME,
            timedelta(hours=5, minutes=30),
        )


if __name__ == "__main__":
    unittest.main()
