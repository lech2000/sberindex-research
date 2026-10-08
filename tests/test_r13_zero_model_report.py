import importlib.util, pathlib, tempfile, unittest, json, math, ast
from unittest.mock import patch
from contextlib import ExitStack
PATH=pathlib.Path(__file__).parents[1]/'shock-radar/src/r13_zero_model_report.py'
s=importlib.util.spec_from_file_location('zero_report',PATH);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
class StatusOnly(unittest.TestCase):
 def main_fixture(self,out,ledger,guard=None,mkdir_race=False):
  out=out.resolve();ledger=ledger.resolve()
  original_path=pathlib.Path;binding=out.parent/'binding.json';binding.write_text('{}')
  b={'out':str(out),'original_protocol_SHA':m.ORIGINAL_PROTOCOL,'fingerprint':m.FINGERPRINT,'source_SHA':'a','historical_seconds':m.HISTORICAL,'root_authoritative_parent_and_owned_tree_gone':True,'closed_file_SHA':{n:'a' for n in m.REQUIRED_CLOSED_FILES}}
  def paths(value):return ledger if str(value)=='/private/tmp/sberindex-one-use-ledger' else original_path(value)
  def hashes(value):return m.ORIGINAL_LEASE_SHA if str(value).endswith('-R13-'+m.ORIGINAL_PROTOCOL+'.json') else 'a'
  def reads(value):return b if original_path(value)==binding else {'fingerprint':m.FINGERPRINT,'protocol_SHA':m.ORIGINAL_PROTOCOL}
  def mkdir(self,*args,**kwargs):
   if self==out/'zero-model-report-v1':
    original_mkdir(self,*args,**kwargs);(self/'terminal.json').write_text('FOREIGN_TERMINAL');raise FileExistsError('ownership race')
   return original_mkdir(self,*args,**kwargs)
  original_mkdir=original_path.mkdir
  with ExitStack() as stack:
   for target,name,value in [(m,'P',paths),(m,'ACTUAL_OUT',str(out)),(m,'sha',hashes),(m,'read',reads),(m,'ENTRY',0),(m.time,'monotonic',lambda:1),(m.time,'time',lambda:0),(m.signal,'signal',lambda *args:None),(m.signal,'setitimer',lambda *args:None)]:stack.enter_context(patch.object(target,name,value))
   stack.enter_context(patch.object(m,'guard',side_effect=guard));stack.enter_context(patch.object(m,'report',return_value={'state':'FULL_REQUESTED_STATUS_ONLY_REPORT','models':0,'scientific_pass':False}))
   stack.enter_context(patch('sys.argv',['report','--binding',str(binding),'--binding-sha','a']))
   if mkdir_race:stack.enter_context(patch.object(original_path,'mkdir',mkdir))
   return m.main()
 def test_main_existing_phase_terminal_retained_no_lease(self):
  with tempfile.TemporaryDirectory() as d:
   out=pathlib.Path(d)/'out';out.mkdir();phase=out/'zero-model-report-v1';phase.mkdir();terminal=phase/'terminal.json';terminal.write_bytes(b'PREEXISTING');ledger=pathlib.Path(d)/'ledger'
   with self.assertRaises(ValueError):self.main_fixture(out,ledger)
   self.assertEqual(terminal.read_bytes(),b'PREEXISTING');self.assertFalse(ledger.exists())
 def test_main_rejected_admission_no_lease_or_phase_terminal(self):
  with tempfile.TemporaryDirectory() as d:
   out=pathlib.Path(d)/'out';out.mkdir();ledger=pathlib.Path(d)/'ledger'
   with self.assertRaises(RuntimeError):self.main_fixture(out,ledger,guard=RuntimeError('low disk'))
   self.assertFalse(ledger.exists());self.assertFalse((out/'zero-model-report-v1').exists())
 def test_main_fresh_owned_phase_writes_own_terminal(self):
  with tempfile.TemporaryDirectory() as d:
   out=pathlib.Path(d)/'out';out.mkdir();ledger=pathlib.Path(d)/'ledger'
   self.assertEqual(self.main_fixture(out,ledger),0)
   terminal=json.loads((out/'zero-model-report-v1/terminal.json').read_text());self.assertEqual(terminal['state'],'FULL_REQUESTED_STATUS_ONLY_REPORT');self.assertEqual(terminal['models'],0)
   self.assertEqual(len(list(ledger.glob('*-terminal.json'))),1)
 def test_main_mkdir_race_cannot_overwrite_foreign_terminal(self):
  with tempfile.TemporaryDirectory() as d:
   out=pathlib.Path(d)/'out';out.mkdir();ledger=pathlib.Path(d)/'ledger'
   self.assertEqual(self.main_fixture(out,ledger,mkdir_race=True),1)
   self.assertEqual((out/'zero-model-report-v1/terminal.json').read_text(),'FOREIGN_TERMINAL')
 def test_one_use_lease_never_overwritten(self):
  with tempfile.TemporaryDirectory() as d:
   f=pathlib.Path(d)/'lease';m.reserve(f,{'models':0});before=f.read_bytes()
   with self.assertRaises(FileExistsError):m.reserve(f,{'models':0,'different_out':True})
   self.assertEqual(f.read_bytes(),before)
 def row(self,key=None):return {'key':list(key or ('1','cat','2024-01','1','2024-02')),'model_status':{'chronos':'PENDING','prophet':'PENDING'},'ancestry':None}
 def test_no_science_imports(self):
  imports={n.names[0].name for n in ast.walk(ast.parse(PATH.read_text())) if isinstance(n,ast.Import)}
  self.assertFalse(imports & {'torch','numpy','pandas','prophet','chronos','subprocess','ctypes'})
 def test_unknown_cannot_be_success(self):
  r=self.row(m.UNKNOWN);r['model_status']['prophet']='ANCESTRAL_UNKNOWN_RESOURCE_STOP_NEVER_REFIT'
  with self.assertRaises(ValueError):m.select_status(r,{'chronos':{},'prophet':{'2024-07':1},'terminal':{'chronos':{},'prophet':{}}},{})
 def test_missing_is_resource_na(self):self.assertEqual(m.select_status(self.row(),None,{})['model_status']['chronos'],'RESOURCE_NOT_ATTEMPTED:DISK_STOP')
 def test_cached_success_retained(self):
  r=self.row();r['model_status']['prophet']='SUCCESS';self.assertEqual(m.select_status(r,None,{})['model_status']['prophet'],'SUCCESS')
 def test_failed_terminal_retained(self):
  state={'chronos':{},'prophet':{},'terminal':{'chronos':{},'prophet':{'2024-02':'ERROR'}}}
  self.assertEqual(m.select_status(self.row(),state,{})['model_status']['prophet'],'ERROR')
 def test_uncommitted_failed_reply_is_not_retry_or_success(self):
  r=self.row();u={(tuple(r['key'][:3]),'prophet',r['key'][4]):'FAILED_REPORTED_RESPONSE_REQUIRES_REVIEWED_COMMIT:BrokenPipeError'}
  self.assertTrue(m.select_status(r,None,u)['model_status']['prophet'].startswith('FAILED_REPORTED'))
 def test_excluded_schema_unchanged(self):
  r={'key':['x']*5,'status':'INSUFFICIENT_HISTORY','chronos_status':'EXCLUDED','prophet_status':'EXCLUDED'};self.assertIs(m.select_status(r,None,{}),r)
 def test_no_prediction_values_emitted(self):
  state={'chronos':{'2024-02':900},'prophet':{},'terminal':{'chronos':{},'prophet':{}}}
  result=m.select_status(self.row(),state,{});self.assertNotIn('900',json.dumps(result));self.assertEqual(result['model_status']['chronos'],'SUCCESS')
 def test_finite_negative_chain_values(self):
  for v in [True,float('nan'),float('inf'),'3893',None]:
   with self.subTest(v=v),self.assertRaises(ValueError):m.finite(v)
 def test_budget_guard_before_writes(self):
  with patch.object(m.time,'monotonic',return_value=600),self.assertRaises(RuntimeError):m.guard(pathlib.Path('/private/tmp'),0,float('inf'))
 def test_low_disk(self):
  with patch.object(m.time,'monotonic',return_value=0),patch.object(m.shutil,'disk_usage',return_value=type('Disk',(),{'free':1})()),self.assertRaises(RuntimeError):m.guard(pathlib.Path('/private/tmp'),0,float('inf'))
 def test_ledger_reset_rejected(self):
  h={'status':'STOP_REQUIRES_ZERO_MODEL_RECOVERY_REVIEW','owned_child_reaped_and_tree_empty':True,'cumulative_wall_s':1,'counters':{}}
  with self.assertRaises(ValueError):m.conservation(h,{'cumulative_wall_s':1,'counters':{}},pathlib.Path('/private/tmp'))
 def test_unresolved_cleanup_rejected(self):
  h={'status':'STOP_REQUIRES_ZERO_MODEL_RECOVERY_REVIEW','owned_child_reaped_and_tree_empty':False}
  with self.assertRaises(ValueError):m.conservation(h,{},pathlib.Path('/private/tmp'))
 def test_small_full_pass_preserves_sources_and_failed_journal(self):
  with tempfile.TemporaryDirectory() as d:
   out=pathlib.Path(d);(out/'checkpoints').mkdir();(out/'attempts').mkdir();phase=out/'phase';phase.mkdir()
   r=self.row();unknown=self.row(m.UNKNOWN);unknown['model_status']={'chronos':'SUCCESS','prophet':'ANCESTRAL_UNKNOWN_RESOURCE_STOP_NEVER_REFIT'}
   excluded={'key':['x']*5,'status':'INSUFFICIENT_HISTORY','chronos_status':'EXCLUDED','prophet_status':'EXCLUDED'}
   (out/'row-statuses.jsonl').write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in [r,unknown,excluded]));prepared=m.sha(out/'row-statuses.jsonl')
   state={'fingerprint':m.FINGERPRINT,'group_key':r['key'][:3],'chronos':{'2024-02':100},'prophet':{},'terminal':{'chronos':{},'prophet':{}}};f=out/'checkpoints/a.json';f.write_text(json.dumps(state));cp={str(f.relative_to(out)):m.sha(f)}
   folder=out/'attempts/a';folder.mkdir();q={'fingerprint':m.FINGERPRINT,'purpose':'primary','model':'prophet','group_keys':[r['key'][:3]],'target_dates':{m.group_id(r['key'][:3]):['2024-02']}};(folder/'request.json').write_text(json.dumps(q));rqsha=m.sha(folder/'request.json')
   (folder/'status.json').write_text(json.dumps({'status':'STARTED','request_SHA':rqsha}));(folder/'response.json').write_text(json.dumps({'request_SHA':rqsha,'fingerprint':m.FINGERPRINT,'model':'prophet','ok':False,'error':'BrokenPipeError'}));j=__import__('hashlib').sha256()
   for name in ['request.json','response.json','status.json']:
    f=folder/name;j.update((str(f.relative_to(out))+' '+m.sha(f)+'\n').encode())
   c={'chronos_calls':104,'prophet_fits':1007,'successful_native_calls':104,'successful_Prophet_fits':1005}
   h={'fingerprint':m.FINGERPRINT,'checkpoint_sha256':cp,'journal_digest':j.hexdigest(),'counters':c};(out/'supervision.json').write_text(json.dumps(h));(out/'resource-ledger.json').write_text('{}')
   originals={str(x.relative_to(out)):m.sha(x) for x in out.rglob('*') if x.is_file()}
   with patch.object(m,'conservation'),patch.object(m,'guard'),patch.multiple(m,REQUESTED=3,ELIGIBLE=2,EXCLUDED=1,CHECKPOINTS=1,ATTEMPTS=1,PREPARED_SHA=prepared):
    result=m.report(out,{'closed_file_SHA':originals},0,float('inf'),phase)
   self.assertEqual(result['requested'],3);self.assertFalse(result['MAE_computed']);self.assertEqual(originals,{name:m.sha(out/name) for name in originals})
   rows=[json.loads(x) for x in (phase/'row-statuses.jsonl').read_text().splitlines()];self.assertTrue(rows[0]['model_status']['prophet'].startswith('FAILED_REPORTED_RESPONSE'));self.assertEqual(rows[1]['model_status']['prophet'],'ANCESTRAL_UNKNOWN_RESOURCE_STOP_NEVER_REFIT')
if __name__=='__main__':unittest.main()
