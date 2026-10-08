import copy, importlib.util, pathlib, unittest, json, tempfile, os
from unittest.mock import patch
P=pathlib.Path(__file__).parents[1]/'economic-atlas/src/atlas_m4_mixed_dependency.py'
s=importlib.util.spec_from_file_location('mixed_gate_test',P);g=importlib.util.module_from_spec(s);s.loader.exec_module(g)
class MixedGate(unittest.TestCase):
 def setUp(self):
  self.t={'state':'FULL_MIXED_RECOVERY_DESCRIPTIVE_VERIFIED_NEEDS_INDEPENDENT_AUDIT','authority':g.AUTHORITY,'owned_lifecycle_tree_empty':True,'scientific_pass':False,'economic_identity_pass':False,'source_actions_closed':0,'inclusive_elapsed_seconds':10000,'continuous_total_resource_pass':False,'original_exit_code':None}
  self.t['budget_record']={'out':'/private/tmp/exact-recovery-root'}
  self.b={'recovery_root':'/private/tmp/exact-recovery-root','authority':g.AUTHORITY,'bank_source_sha256':g.AUTHORITY['base_source'],'bank_numerical_driver':'evr','mixed_dependency_numerical_driver':'evd','root_independent_actual_M1_acceptance':True}
 def test_complete_negative_metadata_admissible(self):self.assertTrue(g.terminal_metadata(self.t,self.b))
 def test_partial_terminal_rejected(self):
  self.t['state']='INCONCLUSIVE_RECOVERY_STOP_NO_RETRY'
  with self.assertRaises(ValueError):g.terminal_metadata(self.t,self.b)
 def test_no_owned_cleanup_rejected(self):
  self.t['owned_lifecycle_tree_empty']=False
  with self.assertRaises(ValueError):g.terminal_metadata(self.t,self.b)
 def test_oldcode_masquerade_rejected(self):
  self.t['authority']={'engine':g.AUTHORITY['base_source']}
  with self.assertRaises(ValueError):g.terminal_metadata(self.t,self.b)
 def test_positive_flag_rejected(self):
  self.t['scientific_pass']=True
  with self.assertRaises(ValueError):g.terminal_metadata(self.t,self.b)
 def test_numeric_budget_invalid_rejected(self):
  for val in [True,None,float('nan'),float('inf'),-1,77881.01,'100']:
   with self.subTest(value=val):
    t=dict(self.t,inclusive_elapsed_seconds=val)
    with self.assertRaises(ValueError):g.terminal_metadata(t,self.b)
 def test_continuous_old_coverage_fabrication_rejected(self):
  self.t['continuous_total_resource_pass']=True
  with self.assertRaises(ValueError):g.terminal_metadata(self.t,self.b)
 def test_unknown_exit_must_remain_unknown(self):
  self.t['original_exit_code']=0
  with self.assertRaises(ValueError):g.terminal_metadata(self.t,self.b)
 def test_hidden_bank_evd_migration_rejected(self):
  self.b['bank_numerical_driver']='evd'
  with self.assertRaises(ValueError):g.terminal_metadata(self.t,self.b)
 def test_root_actual_acceptance_pending_rejected(self):
  self.b['root_independent_actual_M1_acceptance']=False
  with self.assertRaises(ValueError):g.terminal_metadata(self.t,self.b)
 def test_independent_full360_72_99_exact_artifacts(self):
  b=dict(result_sha256='c',replay_result_sha256='r',terminal_sha256='t',recovery_root='/private/tmp/exact-recovery-root',global_result_sha256='gr',global_manifest_sha256='gm',calibration_manifest_sha256='cm',replay_manifest_sha256='rm')
  r=dict(state='M1_FULL_RECOVERY_INDEPENDENTLY_VERIFIED',authority=g.AUTHORITY,scientific_pass=False,calibration_records=360,monthly_records=72,nulls_per_held_or_month=99,calibration_result_sha256='c',replay_result_sha256='r',terminal_sha256='t',recovery_root='/private/tmp/exact-recovery-root',global_result_sha256='gr',global_manifest_sha256='gm',calibration_manifest_sha256='cm',replay_manifest_sha256='rm')
  self.assertTrue(g.actual_acceptance(r,b))
  for field,value in [('calibration_records',334),('monthly_records',71),('nulls_per_held_or_month',98),('monthly_records',True),('calibration_result_sha256','changed'),('replay_result_sha256','changed'),('terminal_sha256','changed'),('scientific_pass',True),('recovery_root','/private/tmp/other-root'),('global_result_sha256','changed'),('global_manifest_sha256','changed'),('calibration_manifest_sha256','changed'),('replay_manifest_sha256','changed')]:
   bad=dict(r);bad[field]=value
   with self.assertRaises(ValueError):g.actual_acceptance(bad,b)
 def test_completed_other_terminal_namespace_rejected(self):
  self.t['budget_record']['out']='/private/tmp/other-complete-same-authority'
  with self.assertRaises(ValueError):g.terminal_metadata(self.t,self.b)
 def test_missing_terminal_out_rejected(self):
  self.t['budget_record']={}
  with self.assertRaises(ValueError):g.terminal_metadata(self.t,self.b)
 def test_replaced_valid_other_output_rejected(self):
  self.b['recovery_root']='/private/tmp/valid-other-output'
  with self.assertRaises(ValueError):g.terminal_metadata(self.t,self.b)
 def test_changed_descriptor_rejected_before_module_import(self):
  with tempfile.TemporaryDirectory() as d:
   p=pathlib.Path(d)/'descriptor.json';p.write_text('{}')
   with patch.dict(os.environ,{'M4_MIXED_DEPENDENCY_BINDING':str(p),'M4_MIXED_DEPENDENCY_BINDING_SHA':'0'*64}),patch.object(g,'load',side_effect=AssertionError('must not load')):
    with self.assertRaises(ValueError):g.check(pathlib.Path(d)/'result.json')
 def test_no_explicit_descriptor_rejected_before_numeric(self):
  with patch.dict(os.environ,{},clear=True),patch.object(g,'load',side_effect=AssertionError('must not load')):
   with self.assertRaises(KeyError):g.check('not-an-actual-calibration')
if __name__=='__main__':unittest.main()
