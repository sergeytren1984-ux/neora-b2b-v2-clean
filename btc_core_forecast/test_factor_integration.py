import datetime as dt,hashlib,unittest
from unittest.mock import Mock,patch
import factor_integration as a
import candidate_contract as c

class FactorTests(unittest.TestCase):
    def calendar(self):
        raw=b'BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:test\nSUMMARY:Consumer Price Index\nDTSTART:20261014T123000Z\nEND:VEVENT\nEND:VCALENDAR\n'
        receipt={'source':a.BLS_SOURCE,'received_at_utc':'2026-10-13T11:28:36+00:00','sha256':hashlib.sha256(raw).hexdigest()}
        return raw,receipt
    def test_later_calendar_never_backfills_earlier_row(self):
        raw,r=self.calendar();out=a.calendar_features(raw,r,'2026-10-13T11:15:20+00:00');self.assertFalse(out['available']);self.assertIsNone(out['values'])
    def test_received_future_schedule_is_numeric_but_not_surprise(self):
        raw,r=self.calendar();out=a.calendar_features(raw,r,'2026-10-13T12:30:20+00:00')
        self.assertEqual(list(out['values'].values()),[0,0,1]);self.assertFalse(out['numeric_macro_surprise_available']);self.assertFalse(out['covers_all_required_macro_events'])
    def test_empty_calendar_count_is_not_missing_imputation(self):
        raw,r=self.calendar();out=a.calendar_features(raw,r,'2026-10-13T11:30:20+00:00');self.assertTrue(out['available']);self.assertEqual(list(out['values'].values()),[0,0,0])
    def test_plain_spot_model_cannot_use_R6_as_decorative_context(self):
        raw,r=self.calendar();inp={'eligible_for_research_matrix':True,'macro':a.calendar_features(raw,r,'2026-10-13T11:30:20+00:00')}
        gate=a.calculation_gate({'volatility':{}},inp)
        self.assertFalse(gate['direction']['allowed']);self.assertIn('MODEL_NOT_FITTED_WITH_R6_AND_CALENDAR_SCHEMA',gate['direction']['reasons'])
    def test_missing_dependency_prevents_predict_call(self):
        predict=Mock(side_effect=AssertionError('must not calculate'))
        out=a.guarded_calculate({}, {'eligible_for_research_matrix':False},predict)
        predict.assert_not_called();self.assertIsNone(out['forecast']);self.assertIsNone(out['entry'])
    def test_actual_candidate_entrypoint_blocks_before_paths(self):
        with patch.object(c.joint,'paths',side_effect=AssertionError('must not calculate')) as paths:
            out=c.summarize({},None,None,None,'2026-10-13T11:30:00+00:00',147600,350)
            paths.assert_not_called();self.assertEqual(out['status'],'BLOCKED_BEFORE_CALCULATION')
    def test_quote_blocks_entry_separately_from_direction(self):
        model={'integrated_feature_names':a.FEATURE_NAMES,'paired_causal_factor_training_verified':True}
        now=dt.datetime.now(dt.timezone.utc).isoformat()
        inp={'eligible_for_research_matrix':True,'macro':{'covers_all_required_macro_events':True},'macro_quotes':{'immutable_collector_source_proven':True},
            'features_available_at_utc':now,'R6':{'book_observed_at_utc':now,'microflow_closed_at_utc':now}}
        gate=a.calculation_gate(model,inp);self.assertTrue(gate['direction']['allowed']);self.assertFalse(gate['buy_or_wait']['allowed'])
    def test_old_verified_row_cannot_be_called_current(self):
        model={'integrated_feature_names':a.FEATURE_NAMES,'paired_causal_factor_training_verified':True}
        old='2026-10-13T11:30:00+00:00';inp={'eligible_for_research_matrix':True,'features_available_at_utc':old,'macro':{'covers_all_required_macro_events':True},
            'macro_quotes':{'immutable_collector_source_proven':True},'R6':{'book_observed_at_utc':old,'microflow_closed_at_utc':old}}
        gate=a.calculation_gate(model,inp,evaluated_at='2026-10-13T11:36:00+00:00')
        self.assertFalse(gate['direction']['allowed']);self.assertTrue(any('STALE_OR_FUTURE' in r for r in gate['direction']['reasons']))

if __name__=='__main__':unittest.main()
