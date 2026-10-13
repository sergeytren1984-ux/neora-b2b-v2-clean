import hashlib,unittest
import calendar_ingest as c

class CalendarTests(unittest.TestCase):
    def event(self,stamp):
        return ('BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:x\nDTSTART;TZID=US-Eastern:'+stamp+'\nSUMMARY:CPI\nEND:VEVENT\nEND:VCALENDAR\n').encode()
    def receipt(self,raw,at='2026-10-13T11:00:00+00:00'):
        return {'sha256':hashlib.sha256(raw).hexdigest(),'received_at_utc':at,'source':'https://www.bls.gov/schedule/news_release/bls.ics'}
    def test_release_time_changes_with_US_DST(self):
        for date,utc,moscow in [('20261014T083000','12:30:00','15:30:00'),('20261110T083000','13:30:00','16:30:00')]:
            raw=self.event(date);e=c.parse(raw,self.receipt(raw))[0]
            self.assertIn(utc,e['release_utc']);self.assertIn(moscow,e['release_МСК'])
    def test_current_receipt_cannot_be_historical_pre_event_vintage(self):
        raw=self.event('20251014T083000');e=c.parse(raw,self.receipt(raw))[0]
        self.assertFalse(e['schedule_known_before_release']);self.assertIsNone(e['consensus_value'])
    def test_modified_calendar_rejected(self):
        raw=self.event('20261014T083000')
        with self.assertRaises(ValueError):c.parse(raw+b' ',self.receipt(raw))

if __name__=='__main__':unittest.main()
