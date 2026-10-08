import copy,importlib.util,itertools,json,pathlib,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
s=importlib.util.spec_from_file_location('acceptance',ROOT/'economic-atlas/src/a63_prospective_acceptance.py');a=importlib.util.module_from_spec(s);s.loader.exec_module(a)
SPEC=json.loads((ROOT/'economic-atlas/protocols/A63_NEW_PROSPECTIVE_SYNTHETIC_V1.json').read_text())
class Prospective(unittest.TestCase):
 def fixture(self):
  rows=[];months=[]
  for seed,world,mode,factor in itertools.product(SPEC['seeds'],SPEC['worlds'],SPEC['modes'],SPEC['margin_factors']):
   key=dict(seed=seed,world=world,mode=mode,margin_factor=factor)
   rows.append(dict(key,execution_status='COMPLETE',recognition=dict(tp=100,fp_known=0,fp_unknown=0,fn=0,tn=100,cluster_decisions=100,decided_clusters=100,abstentions=0),events=dict(tp=10,fp=0,fn=0),negative_M3_false_events=0))
   months.extend(dict(key,month_index=m) for m in range(1,24))
  return rows,months
 def test_full_fake_metadata_only_acceptance(self):
  r,m=self.fixture();v=a.acceptance(SPEC,r,m);self.assertEqual(v['status'],'PASS');self.assertFalse(v['scientific_pass']);self.assertFalse(v['historical_preregistration_repaired'])
 def test_missing_or_duplicate_config_rejected(self):
  for alter in ['missing','duplicate','oldseed']:
   r,m=self.fixture()
   if alter=='missing':r.pop()
   elif alter=='duplicate':r[-1]=r[0]
   else:r[0]['seed']=20261003
   with self.assertRaises(ValueError):a.acceptance(SPEC,r,m)
 def test_missing_month_rejected(self):
  r,m=self.fixture();m.pop()
  with self.assertRaises(ValueError):a.acceptance(SPEC,r,m)
 def test_bad_sensitivity_cannot_select_primary_pass(self):
  r,m=self.fixture()
  for x in r:
   if x['margin_factor']==1.25:x['events']['fp']=10
  self.assertEqual(a.acceptance(SPEC,r,m)['status'],'FAIL')
 def test_abstentions_are_misses_not_success(self):
  r,m=self.fixture()
  for x in r:x['recognition'].update(tp=0,fn=100,decided_clusters=0,abstentions=100)
  self.assertEqual(a.acceptance(SPEC,r,m)['status'],'INCONCLUSIVE')
 def test_zero_event_denominator_is_inconclusive(self):
  r,m=self.fixture()
  for x in r:x['events']=dict(tp=0,fp=0,fn=0)
  self.assertEqual(a.acceptance(SPEC,r,m)['status'],'INCONCLUSIVE')
 def test_boolean_nan_count_refused(self):
  for bad in [True,float('nan'),-1]:
   r,m=self.fixture();r[0]['recognition']['fp_unknown']=bad
   with self.assertRaises(ValueError):a.acceptance(SPEC,r,m)
 def test_missing_computation_never_pass(self):
  r,m=self.fixture();r[0]['execution_status']='INCONCLUSIVE'
  self.assertEqual(a.acceptance(SPEC,r,m)['status'],'INCONCLUSIVE')
 def test_frozen_original_thresholds_and_newseed_hash(self):
  import hashlib
  expected=[1000000000+int(hashlib.sha256(('A6.3/prospective/original-generator/v1/2026-10-08/seed/'+str(i)).encode()).hexdigest()[:8],16)%1000000000 for i in range(5)]
  self.assertEqual(SPEC['seeds'],expected);self.assertFalse(set(expected)&set(range(20261003,20261008)));self.assertEqual(SPEC['thresholds']['M'],.7187007760980421)
if __name__=='__main__':unittest.main()
