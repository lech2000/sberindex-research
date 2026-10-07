import unittest
import pandas as pd
from gm2_nationwide_audit import ledger
class SyntheticControls(unittest.TestCase):
 def sources(self):
  d=pd.DataFrame([{'territory_id':1,'oktmo':'37-604-000-000','year_from':2020,'year_to':2024},{'territory_id':2,'oktmo':'37-604-000-000','year_from':2024,'year_to':9999},{'territory_id':3,'oktmo':'37-609-000-000','year_from':2020,'year_to':9999}]);p=pd.DataFrame([{'territory_id':1,'date':'2024-02-01','value':None},{'territory_id':2,'date':'2024-02-01','value':0.},{'territory_id':999,'date':'2024-02-01','value':10.}]);o={2024:{'37604000000':{'native_introduction_date':'01.01.2014'}}};return d,p,o
 def test_endpoint_collision_and_missing_id_are_preserved(self):
  d,p,o=self.sources();r=ledger(d,p,o,{})
  half=[x for x in r['panel_id_year_policy_ledger'] if x['interval_policy']=='half_open'];inc=[x for x in r['panel_id_year_policy_ledger'] if x['interval_policy']=='inclusive_end'];self.assertEqual({x['territory_id'] for x in half},{1,2,999});self.assertEqual(sum(x['source_rows'] for x in half),3);self.assertEqual([x['binding_status'] for x in inc[:2]],['DICTIONARY_CODE_COLLISION']*2);self.assertEqual(half[0]['unmatched_reason'],'SOURCE_INTERVAL_ENDPOINT_UNKNOWN_SEMANTICS');self.assertEqual(half[2]['unmatched_reason'],'NO_NATIVE_DICTIONARY_ID')
 def test_same_code_contiguous_candidate_is_never_verified(self):
  d,p,o=self.sources();r=ledger(d,p,o,{})['finite_dictionary_ledger'][0];self.assertEqual(r['same_code_contiguous_candidates'][0]['native_candidate_tid'],2);self.assertEqual(r['successor_status'],'UNKNOWN_SUCCESSOR');self.assertIsNone(r['verified_successor_tid']);self.assertFalse(r['full_legal_statistical_binding_verified'])
 def test_future_official_component_cannot_create2024_binding(self):
  d,p,o=self.sources();r=ledger(d,p,o,{'37609000000':[{'successor_code11':'37509000000','native_valid_from':'2025-01-01','status':'CODE_COMPONENT_ONLY'}]})['all_dictionary_ledger'][2];self.assertEqual(r['year_to'],9999);self.assertEqual(r['successor_status'],'UNKNOWN_SUCCESSOR');self.assertFalse(r['full_legal_statistical_binding_verified']);self.assertIsNone(r['classifier_membership']['2024']);self.assertEqual(r['code_components'][0]['native_valid_from'],'2025-01-01')
 def test_dictionary_duplicate_native_id_fails(self):
  d,p,o=self.sources();d=pd.concat([d,d.iloc[[0]]]);self.assertRaises(ValueError,ledger,d,p,o,{})
 def test_no_names_required_and_input_frames_unchanged(self):
  d,p,o=self.sources();dd=d.copy(deep=True);pp=p.copy(deep=True);r=ledger(d,p,o,{});pd.testing.assert_frame_equal(d,dd);pd.testing.assert_frame_equal(p,pp);self.assertEqual(r['global_panel_ids_not_in_dictionary'],[999]);self.assertEqual(r['panel_rows'],3)
 def test_invalid_native_code_fails_instead_of_guess(self):
  d,p,o=self.sources();d.loc[0,'oktmo']='named-place';self.assertRaises(ValueError,ledger,d,p,o,{})
if __name__=='__main__':unittest.main()
