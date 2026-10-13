import copy,json,pathlib,tempfile,unittest
from unittest.mock import patch
import r6_factor_adapter as a

class VerifierRejects:
    def verify(self,*args):raise ValueError('untrusted signature')

class VerifierTestDouble:
    def verify(self,*args):return {'source_sha':a.SOURCE_SHA}

class R6AdapterTests(unittest.TestCase):
    def test_unsigned_record_is_not_an_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=pathlib.Path(tmp)/'raw.json';p.write_text('{}')
            with self.assertRaises(ValueError):a.extract(p,VerifierRejects())

    def test_missing_slot_never_becomes_zero_numeric_factors(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=pathlib.Path(tmp)/'raw.json';p.write_text(json.dumps({'schema':'btc-core-forward-slot-v1','kind':'MISSING_NOT_BACKFILLED','anchor_utc':'2026-10-13T11:15:00+00:00'}))
            r=a.extract(p,VerifierTestDouble())
            self.assertFalse(r['available']);self.assertIsNone(r['values']);self.assertFalse(r['trading_authority'])

    def test_changed_math_cannot_claim_frozen_R6_blob(self):
        with patch.object(a.inspect,'getfile',return_value=__file__):
            with self.assertRaises(ValueError):a.extract('not_used',VerifierTestDouble())

if __name__=='__main__':unittest.main()
