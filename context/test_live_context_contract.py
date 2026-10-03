"""Guard the OI unit contract consumed by the frozen regime context validator."""
import json
import unittest
from unittest.mock import patch
from context import live_context_collector as collector


class OpenInterestContract(unittest.TestCase):
    def test_canonical_oi_does_not_switch_exchanges(self):
        okx = {"value_btc": 28450.0, "source_timestamp_utc": "2026-10-03T18:30:00+00:00"}
        with patch.object(collector, "okx_oi", return_value=okx), \
             patch.object(collector, "binance_oi", side_effect=AssertionError("cross-exchange OI")):
            result = collector.canonical_oi()
        self.assertEqual(result["source"], "OKX_SWAP")
        self.assertEqual(result["value_btc"], 28450.0)

    def test_binance_btc_units_are_named_for_regime(self):
        data = {"openInterest": "12345.50", "time": 1791043200000}
        response = {"raw": json.dumps(data), "requested_url": "https://fapi.binance.com/fapi/v1/openInterest",
                    "final_url": "https://fapi.binance.com/fapi/v1/openInterest",
                    "http_status": 200, "retrieved_at_utc": "2026-10-03T16:00:00+00:00",
                    "sha256": "test", "raw_response_b64": "test"}
        with patch.object(collector, "fetch", return_value=response):
            result = collector.binance_oi()
        self.assertEqual(result["value_btc"], 12345.5)
        self.assertEqual(result["value"], result["value_btc"])
        self.assertEqual(result["unit"], "BTC_contract_units")
        self.assertIn("source_timestamp_utc", result)
        self.assertIn("receipt", result)


if __name__ == "__main__":
    unittest.main()
