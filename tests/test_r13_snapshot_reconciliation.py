import importlib.util,pathlib,tempfile,json,hashlib,unittest,types
from unittest.mock import patch
FILE=pathlib.Path(__file__).parents[1]/'shock-radar/src/r13_snapshot_reconciliation.py'
s=importlib.util.spec_from_file_location('reconciliation_fixture',FILE);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
class Reconciliation(unittest.TestCase):
 def header(self,out):
  (out/'checkpoints').mkdir();f=out/'checkpoints/a.json';f.write_text('{}');orphan=out/m.ORPHAN;orphan.write_bytes(b'');return {'checkpoint_sha256':{'checkpoints/a.json':m.sha(f)}}
 def test_exact_known_orphan_preserved(self):
  with tempfile.TemporaryDirectory() as d:
   out=pathlib.Path(d);h=self.header(out);r=m.orphan_inventory(out,h);self.assertEqual(r['size'],0);self.assertTrue((out/m.ORPHAN).exists());self.assertEqual(r['SHA'],m.EMPTY)
 def test_unknown_extra_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   out=pathlib.Path(d);h=self.header(out);(out/'checkpoints/unknown.tmp').write_bytes(b'')
   with self.assertRaises(ValueError):m.orphan_inventory(out,h)
 def test_nonzero_orphan_rejected_retained(self):
  with tempfile.TemporaryDirectory() as d:
   out=pathlib.Path(d);h=self.header(out);(out/m.ORPHAN).write_bytes(b'partial')
   with self.assertRaises(ValueError):m.orphan_inventory(out,h)
   self.assertEqual((out/m.ORPHAN).read_bytes(),b'partial')
 def test_missing_published_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   out=pathlib.Path(d);h=self.header(out);(out/'checkpoints/a.json').unlink()
   with self.assertRaises(ValueError):m.orphan_inventory(out,h)
 def test_source_mismatch_before_import(self):
  with tempfile.TemporaryDirectory() as d,patch.object(m,'REPO',pathlib.Path(d)),patch.object(m,'sha',return_value='foreign'),patch.object(m.importlib.util,'spec_from_file_location',side_effect=AssertionError('must not import')):
   with self.assertRaises(ValueError):m.load_helpers()
 def history(self):return {'state':'INCONCLUSIVE_REPORT_STOP_NO_RETRY','error':'ValueError: checkpoint snapshot mismatch','original_cumulative_wall_s':m.OLD_CUMULATIVE,'report_elapsed_seconds':m.FIRST_REPORT,'cumulative_wall_s':3935.1555434990005,'models':0,'scientific_pass':False}
 def test_exact_consumed_history(self):m.check_history(self.history())
 def test_history_reset_and_false_success_rejected(self):
  for key,value in [('original_cumulative_wall_s',961.611),('report_elapsed_seconds',0),('cumulative_wall_s',3893),('state','FULL'),('models',1),('scientific_pass',True),('report_elapsed_seconds',True),('report_elapsed_seconds',float('nan'))]:
   with self.subTest(key=key),self.assertRaises(ValueError):m.check_history(dict(self.history(),**{key:value}))
 def test_remaining_family_guard(self):
  with patch.object(m.time,'monotonic',return_value=m.LIMIT),self.assertRaises(RuntimeError):m.guard(pathlib.Path('/private/tmp'),0)
 def test_low_free_guard(self):
  with patch.object(m.time,'monotonic',return_value=0),patch.object(m.time,'time',return_value=0),patch.object(m.shutil,'disk_usage',return_value=types.SimpleNamespace(free=1)),self.assertRaises(RuntimeError):m.guard(pathlib.Path('/private/tmp'),0)
 def test_preexisting_phase_main_rejects_before_lease(self):
  with tempfile.TemporaryDirectory() as d:
   out=pathlib.Path(d).resolve();phase=out/'snapshot-reconciliation-v1';phase.mkdir();f=phase/'terminal.json';f.write_bytes(b'OLD_TERMINAL');binding=out/'binding.json';binding.write_text('{}')
   with patch.object(m,'OUT',out),patch.object(m,'NEW_CONTROL',out),patch.object(m,'sha',return_value='a'),patch.object(m,'read',return_value={'out':str(out)}),patch('sys.argv',['reconcile','--binding',str(out/'ROOT_BINDING.json'),'--binding-sha','a']),patch.object(m.os,'open',side_effect=AssertionError('no lease')):
    with self.assertRaises(ValueError):m.main()
   self.assertEqual(f.read_bytes(),b'OLD_TERMINAL')
 def test_budget_family_reserves_independent120_no_reset(self):
  self.assertAlmostEqual(m.FIRST_REPORT+m.DIAGNOSIS+m.LIMIT+m.INDEPENDENT_RESERVE,600,places=10)
  self.assertAlmostEqual(m.LIMIT+m.INDEPENDENT_RESERVE,m.FAMILY_REMAINING,places=10)
  self.assertEqual(3935.1555434990005+m.DIAGNOSIS,m.BASE)
  self.assertGreaterEqual(m.BASE,m.OLD_CUMULATIVE+m.FIRST_REPORT+m.DIAGNOSIS)
 def test_family_size_no_nested_doublecount(self):
  with tempfile.TemporaryDirectory() as d:
   root=pathlib.Path(d);f=root/'receipt';f.write_bytes(b'123')
   self.assertEqual(m.family_size([root,f]),3)
 def fixture(self,out):
  with patch.object(m,'REPO',pathlib.Path('/private/tmp/sberindex-official-laws-20261007')):real=m.load_helpers()
  (out/'checkpoints').mkdir();(out/'attempts').mkdir();phase=out/'snapshot-reconciliation-v1';phase.mkdir();(out/m.ORPHAN).write_bytes(b'')
  normal={'key':['1594','cat','2023-11','12','2024-11'],'model_status':{'chronos':'PENDING','prophet':'PENDING'},'ancestry':None};unknown={'key':list(real.UNKNOWN),'model_status':{'chronos':'SUCCESS','prophet':'ANCESTRAL_UNKNOWN_RESOURCE_STOP_NEVER_REFIT'},'ancestry':{'old':True}};excluded={'key':['x']*5,'status':'INSUFFICIENT_HISTORY','chronos_status':'EXCLUDED','prophet_status':'EXCLUDED'}
  (out/'row-statuses.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in [normal,unknown,excluded]));old=types.SimpleNamespace(FINGERPRINT=real.FINGERPRINT,UNKNOWN=real.UNKNOWN,PREPARED_SHA=m.sha(out/'row-statuses.jsonl'),group_id=real.group_id,select_status=real.select_status)
  state={'fingerprint':old.FINGERPRINT,'group_key':normal['key'][:3],'chronos':{'2024-11':100},'prophet':{},'terminal':{'chronos':{},'prophet':{}}};f=out/'checkpoints/a.json';f.write_text(json.dumps(state));header={'checkpoint_sha256':{'checkpoints/a.json':m.sha(f)}}
  folder=out/'attempts/a';folder.mkdir();q={'fingerprint':old.FINGERPRINT,'purpose':'primary','model':'prophet','group_keys':[normal['key'][:3]],'target_dates':{old.group_id(normal['key'][:3]):['2024-11']}};(folder/'request.json').write_text(json.dumps(q));rq=m.sha(folder/'request.json');(folder/'status.json').write_text(json.dumps({'status':'STARTED','request_SHA':rq}));(folder/'response.json').write_text(json.dumps({'request_SHA':rq,'fingerprint':old.FINGERPRINT,'model':'prophet','ok':False,'error':'BrokenPipeError'}));digest=hashlib.sha256()
  for name in ['request.json','response.json','status.json']:digest.update((str((folder/name).relative_to(out))+' '+m.sha(folder/name)+'\n').encode())
  header.update(journal_digest=digest.hexdigest(),counters={'chronos_calls':104,'prophet_fits':1007,'successful_native_calls':104,'successful_Prophet_fits':1005});binding={'closed_file_SHA':{'row-statuses.jsonl':m.sha(out/'row-statuses.jsonl')}};return phase,old,header,binding
 def test_full_fixture_accounts_orphan_unknown_failed_without_mutation(self):
  with tempfile.TemporaryDirectory() as d:
   out=pathlib.Path(d);phase,old,h,b=self.fixture(out);before={str(f.relative_to(out)):m.sha(f) for f in out.rglob('*') if f.is_file()};q=m.orphan_inventory(out,h)
   r=m.materialize(out,phase,b,old,h,q,lambda *args:None,scope=(3,2,1,1,1));self.assertEqual(r['requested'],3);self.assertFalse(r['MAE_computed']);self.assertTrue((phase/'quarantine-inventory.json').exists())
   rows=[json.loads(x) for x in (phase/'row-statuses.jsonl').read_text().splitlines()];self.assertTrue(rows[0]['model_status']['prophet'].startswith('FAILED_REPORTED_RESPONSE'));self.assertEqual(rows[1]['model_status']['prophet'],'ANCESTRAL_UNKNOWN_RESOURCE_STOP_NEVER_REFIT');self.assertEqual(before,{name:m.sha(out/name) for name in before})
 def test_missing_rows_rejected_no_complete(self):
  with tempfile.TemporaryDirectory() as d:
   out=pathlib.Path(d);phase,old,h,b=self.fixture(out)
   with self.assertRaises(ValueError):m.materialize(out,phase,b,old,h,m.orphan_inventory(out,h),lambda *args:None,scope=(4,3,1,1,1))
   self.assertFalse((phase/'row-statuses.jsonl').exists())
 def test_changed_published_SHA_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   out=pathlib.Path(d);phase,old,h,b=self.fixture(out);(out/'checkpoints/a.json').write_text('{}')
   with self.assertRaises(ValueError):m.materialize(out,phase,b,old,h,m.orphan_inventory(out,h),lambda *args:None,scope=(3,2,1,1,1))
if __name__=='__main__':unittest.main()
