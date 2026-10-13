import base64,copy,datetime as dt,hashlib,json,unittest
from macro_quote_adapter import replay,asof

class QuoteTests(unittest.TestCase):
    def factor(self):
        at=int(dt.datetime(2026,10,13,11,tzinfo=dt.timezone.utc).timestamp())
        obj={'chart':{'error':None,'result':[{'meta':{'symbol':'NQ=F'},'timestamp':[at], 'indicators':{'quote':[{'close':[30000.]}]}}]}}
        raw=json.dumps(obj).encode();url='https://query1.finance.yahoo.com/v8/finance/chart/NQ%3DF?interval=5m'
        return {'status':'VALID','value':30000.,'source_timestamp_utc':'2026-10-13T11:00:00+00:00',
            'receipt':{'requested_url':url,'final_url':url,'http_status':200,'retrieved_at_utc':'2026-10-13T11:10:00+00:00',
            'sha256':hashlib.sha256(raw).hexdigest(),'raw_response_b64':base64.b64encode(raw).decode()}}
    def test_quote_recomputed_from_embedded_publisher_bytes(self):self.assertEqual(replay(self.factor(),'NQ=F')['value'],30000.)
    def test_cash_index_cannot_replace_futures(self):
        f=self.factor();f['receipt']['requested_url']=f['receipt']['requested_url'].replace('NQ%3DF','%5ENDX')
        with self.assertRaisesRegex(ValueError,'symbol substitution'):replay(f,'NQ=F')
    def test_tampered_number_rejected(self):
        f=self.factor();f['value']=29000
        with self.assertRaisesRegex(ValueError,'not reproduced'):replay(f,'NQ=F')
    def test_changed_receipt_bytes_rejected(self):
        f=self.factor();f['receipt']['raw_response_b64']=base64.b64encode(b'{}').decode()
        with self.assertRaisesRegex(ValueError,'digest'):replay(f,'NQ=F')
    def test_asof_uses_response_and_signing_time_not_capture_start(self):
        q=replay(self.factor(),'NQ=F');record={'quotes':{k:q for k in ('dxy','nasdaq_futures','us10y')},'available_at':dt.datetime(2026,10,13,11,10,5,tzinfo=dt.timezone.utc),'record_sha256':'test','source_sha':'test'}
        out=asof(record,'2026-10-13T11:10:00+00:00');self.assertFalse(out['available']);self.assertIsNone(out['features'])
    def test_stale_macro_not_filled_with_zero(self):
        q=replay(self.factor(),'NQ=F');record={'quotes':{k:q for k in ('dxy','nasdaq_futures','us10y')},'available_at':q['received'],'record_sha256':'test','source_sha':'test'}
        out=asof(record,'2026-10-13T12:00:00+00:00');self.assertFalse(out['available']);self.assertIsNone(out['features'])

if __name__=='__main__':unittest.main()
