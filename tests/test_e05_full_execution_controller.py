"""Hermetic stdlib source/lifecycle fixtures. No probes/processes/science."""
import ast,copy,hashlib,json,os,pathlib,sys,tempfile,unittest
from unittest.mock import patch,Mock
sys.path.insert(0,str(pathlib.Path(__file__).parents[1]/'economic-atlas/src'))
import e05_full_execution_controller as c
import e05_full_execution_worker as worker
import e05_full_guardian_toolkit_v2 as toolkit
class Test(unittest.TestCase):
 def spec(self):return dict(whole_seconds=3600,finalization_reserve_seconds=600,audit_receipt_reserve_seconds=30,metadata_bytes_limit=1048576,RSS_bytes=1024**3,minimum_free_bytes=1024**3,output_bytes=128*1024**2,receipt_reserve_bytes=65536,poll_seconds=.25,cleanup_seconds=10,CPU_threads=1,absolute_deadline_UTC='2099-01-01T00:00:00+00:00')
 def test_durable_once_no_overwrite_unknown(self):
  with tempfile.TemporaryDirectory()as d:
   p=pathlib.Path(d)/'lease';c.once(p,{'STARTED':True});before=p.read_bytes()
   with self.assertRaises(FileExistsError):c.once(p,{'retry':True})
   self.assertEqual(before,p.read_bytes())
 def test_once_file_and_directory_fsync(self):
  with tempfile.TemporaryDirectory()as d,patch.object(c.os,'fsync')as fs:c.once(pathlib.Path(d)/'lease',{});self.assertEqual(fs.call_count,2)
 def test_fresh_private_dir_collision_symlink(self):
  with tempfile.TemporaryDirectory()as d:
   root=pathlib.Path(d);c.private_dir(root/'new');self.assertEqual((root/'new').stat().st_mode&0o777,0o700)
   for p in [root/'new',root/'link']:
    if p.name=='link':p.symlink_to(root/'new')
    with self.assertRaises(ValueError):c.private_dir(p)
 def test_guard_original_elapsed_and_final_reserve(self):
  g=c.Guard(self.spec(),100,[],Mock(),{'real_IO_resource_report_SHA':'a'*64})
  with patch.object(c.time,'monotonic',return_value=3100):
   with self.assertRaises(InterruptedError):g()
  g.phase='publication'
  with patch.object(c.time,'monotonic',return_value=3670):
   with self.assertRaises(InterruptedError):g()
 def test_guard_disk_before_native_and_output(self):
  g=c.Guard(self.spec(),100,[],Mock(),{'real_IO_resource_report_SHA':'a'*64})
  with patch.object(c.time,'monotonic',return_value=101),patch.object(c.shutil,'disk_usage',return_value=Mock(free=0)):
   with self.assertRaises(InterruptedError):g()
   g.native.own_tree_rss.assert_not_called()
 def test_guard_combined_roots_and_RSS(self):
  g=c.Guard(self.spec(),100,[],Mock(),{'real_IO_resource_report_SHA':'a'*64})
  with patch.object(c.time,'monotonic',return_value=101),patch.object(c.shutil,'disk_usage',return_value=Mock(free=2*1024**3)),patch.object(toolkit,'total_bytes',return_value=2*1024**3):
   with self.assertRaises(InterruptedError):g()
  with patch.object(c.time,'monotonic',return_value=101),patch.object(c.shutil,'disk_usage',return_value=Mock(free=2*1024**3)),patch.object(toolkit,'total_bytes',return_value=0):
   g.native.own_tree_rss.return_value=(2*1024**3,{})
   with self.assertRaises(InterruptedError):g()
 def test_worker_external_refuses_before_numerical(self):
  with patch.dict(os.environ,{},clear=True),patch.object(c,'load')as load:
   with self.assertRaises(RuntimeError):worker.main(['--repo','/tmp/x','--root-binding','/tmp/y'])
   load.assert_not_called()
 def test_source_engine_call_and_observe_exact(self):
  s=pathlib.Path(worker.__file__).read_text();self.assertIn('with adapter.observe(engine):result=engine.execute(',s);self.assertIn('adapter.cell_callback)',s)
  self.assertNotIn('fit_predict(',s);self.assertNotIn('source_only_mock=True',s)
 def test_universe_before_engine_call(self):
  s=pathlib.Path(worker.__file__).read_text();self.assertLess(s.index("c.once(c.CONTROL/'territory-universe.json'"),s.index('engine.execute('));self.assertIn('1896',s);self.assertIn('tids!=sorted(tids)',s)
 def test_stopped_owned_process_cleanup_even_after_exit(self):
  with tempfile.TemporaryDirectory()as d:
   root=pathlib.Path(d);g=Mock();g.spec=self.spec();g.whole_seconds=3600;g.anchor=c.time.monotonic();g.native.descendants.return_value=[]
   process=Mock(pid=9191);process.stdout=Mock();process.stderr=Mock();process.stdout.fileno.return_value=11;process.stderr.fileno.return_value=12;process.poll.return_value=0
   with patch.object(c,'CONTROL',root),patch.object(c.os,'set_blocking'),patch.object(c.select,'select',return_value=([],[],[])),patch.object(c.os,'read',return_value=b''),patch.object(toolkit,'cleanup_owned',return_value={'unknown':False})as clean:
    r=c.supervise(['not-run'],g,{},'s',factory=Mock(return_value=process));self.assertEqual(r['exitcode'],0);self.assertEqual(clean.call_args.args[1],{9191});process.wait.assert_called()
 def test_interrupt_cleanup_and_lease_retained(self):
  with tempfile.TemporaryDirectory()as d:
   root=pathlib.Path(d);g=Mock();g.spec=self.spec();g.whole_seconds=3600;g.anchor=c.time.monotonic();g.native.descendants.return_value=[]
   process=Mock(pid=9191);process.stdout.fileno.return_value=11;process.stderr.fileno.return_value=12;process.poll.return_value=None
   with patch.object(c,'CONTROL',root),patch.object(c.os,'set_blocking'),patch.object(c.select,'select',side_effect=InterruptedError('STOP')),patch.object(toolkit,'cleanup_owned',return_value={'unknown':False})as clean:
    r=c.supervise(['not-run'],g,{},'s',factory=Mock(return_value=process));self.assertIn('STOP',r['error']);clean.assert_called_once();self.assertTrue((root/'worker-authorization.json').exists())
 def test_no_foreign_group_cleanup(self):
  with tempfile.TemporaryDirectory()as d:
   root=pathlib.Path(d);g=Mock();g.spec=self.spec();g.whole_seconds=3600;g.anchor=c.time.monotonic();g.native.descendants.return_value=[9292];process=Mock(pid=9191);process.stdout.fileno.return_value=11;process.stderr.fileno.return_value=12
   with patch.object(c,'CONTROL',root),patch.object(c.os,'set_blocking'),patch.object(c.os,'getpgid',return_value=3333),patch.object(toolkit,'cleanup_owned',return_value={'unknown':False})as clean:
    r=c.supervise(['not-run'],g,{},'s',factory=Mock(return_value=process));self.assertIn('unowned group',r['error']);self.assertEqual(clean.call_args.args[1],{9191})
 def test_invalidbinding_no_namespace_or_dispatch(self):
  with tempfile.TemporaryDirectory()as d:
   p=pathlib.Path(d)/'binding';p.write_text(json.dumps({'spec':self.spec()}));p.chmod(0o600)
   with patch.object(c.signal,'setitimer'),patch.object(c.signal,'signal'),patch.object(c,'validate',side_effect=ValueError('invalid pins')),patch.object(c,'private_dir')as mkdir,patch.object(c,'supervise')as run:
    self.assertEqual(c.main(['--repo',d,'--root-binding',str(p)]),1);mkdir.assert_not_called();run.assert_not_called()
 def test_metadata_big_nonfinite_and_duplicate_refuse(self):
  with tempfile.TemporaryDirectory()as d:
   p=pathlib.Path(d)/'j'
   for raw in ['{"x":NaN}','{"x":1,"x":2}',' '*((2*1024**2)+1)]:
    p.write_text(raw)
    with self.assertRaises(ValueError):c.read(p)
 def test_nonfinite_bools(self):
  for x in (True,float('inf'),float('nan'),None):
   with self.assertRaises(ValueError):c.finite(x)
 def test_source_clock_before_import_and_no_mock_bypass(self):
  s=pathlib.Path(c.__file__).read_text();self.assertLess(s.index('ENTRY=time.monotonic()'),s.index('import argparse'));self.assertNotIn('source_only_mock=True',s);self.assertIn("signal.getitimer(signal.ITIMER_REAL)",s)
 def validation_fixture(self,root):
  # All files here are tiny metadata fixtures, never native/source execution.
  required=['e05_full_execution_controller.py','e05_full_execution_worker.py','e05_full_real_publication_bridge.py','atlas_e05_remaining_v2.py','e05_full_receipt_adapter_v5.py','e05_full_guardian_toolkit_v2.py','atlas_m1_executor.py','e05_full_publication_finalizer_v5.py','e05_full_publication_validator_v5.py','e05_full_numeric_adapter.py','e05_independent_numerical_audit.py','e05_numpy_quality_reference.py']
  pins={}
  for n in required:
   f=root/'economic-atlas/src'/n;f.parent.mkdir(parents=True,exist_ok=True);f.write_text('metadata');pins[str(f.relative_to(root))]=c.sha(f)
  pins['economic-atlas/src/atlas_e05_remaining_v2.py']=c.METHOD_SHA;pins[c.PROTOCOL]=c.PROTOCOL_SHA
  (root/c.PROTOCOL).parent.mkdir(parents=True);(root/c.PROTOCOL).write_text('{"source_pins":{},"data_pins":{}}')
  b=dict(operation=c.KEY,UID=os.getuid(),host=c.platform.node(),source_binding=c.SOURCE_BINDING,paths=dict(out=str(c.OUT),control=str(c.CONTROL),ledger=str(c.LEDGER)),spec=self.spec(),source_pins=pins,python_path=str(pathlib.Path(sys.executable).resolve()),python_SHA='a'*64,dependency_versions={x:'fixture'for x in ('numpy','pandas','scipy','scikit-learn','pyarrow')},independent_source_ACK_SHA='b'*64)
  proofs={}
  for kind in ('native_owned_tree_preflight','monthly1896_K5_native_pair','supra45504_K5_native_pair','full225_status_and8220_journal_IO','independent_review'):
   f=root/(kind+'.json');f.write_text(json.dumps(dict(actual=True,source_only_mock=False,state='PASS',source_pins=pins)));proofs[kind]=dict(path=str(f),SHA=c.sha(f))
  report=dict(state='INDEPENDENTLY_ACCEPTED_REAL_E05_IO_RESOURCE',scope=dict(n=1896,months=24,cells=225,status_rows=10238400),source_pins=pins,spec=b['spec'],proofs=proofs,monthly_native_shape=[1896,5],supra_native_shape=[45504,5],full_status_IO_rows=10238400,typed_journal_IO_entries=8220,remaining_quality_control_cost_state='INDEPENDENTLY_ADMITTED',measured_profile_wall_seconds=1.,measured_profile_peak_RSS_bytes=100.)
  f=root/'report.json';f.write_text(json.dumps(report));b.update(real_IO_resource_report_path=str(f),real_IO_resource_report_SHA=c.sha(f));return b,report
 def run_validation(self,b,root):
  original=c.sha
  def hash_fixture(p):
   if str(p)==b['python_path']:return 'a'*64
   if pathlib.Path(p)==root/c.PROTOCOL:return c.PROTOCOL_SHA
   if pathlib.Path(p)==root/'economic-atlas/src/atlas_e05_remaining_v2.py':return c.METHOD_SHA
   return original(p)
  with patch.object(c,'sha',side_effect=hash_fixture),patch('importlib.metadata.version',return_value='fixture'):return c.validate(b,root)
 def test_valid_metadata_fixture_is_not_runtime_authority(self):
  with tempfile.TemporaryDirectory()as d:
   r=pathlib.Path(d).resolve();b,_=self.validation_fixture(r);self.assertEqual(self.run_validation(b,r),self.spec())
 def test_report_unknown_mock_wrong_scope_or_measurement_refuses(self):
  for key,value in [('state','SOURCE_ONLY_ACK'),('scope',dict(n=5,months=24,cells=225,status_rows=10238400)),('monthly_native_shape',[5,5]),('measured_profile_wall_seconds',True),('measured_profile_peak_RSS_bytes',float('inf'))]:
   with tempfile.TemporaryDirectory()as d:
    r=pathlib.Path(d).resolve();b,report=self.validation_fixture(r);report[key]=value;p=pathlib.Path(b['real_IO_resource_report_path']);p.write_text(json.dumps(report));b['real_IO_resource_report_SHA']=c.sha(p)
    with self.assertRaises(ValueError):self.run_validation(b,r)
 def test_report_bool_only_without_substantive_proofs_refuses(self):
  with tempfile.TemporaryDirectory()as d:
   r=pathlib.Path(d).resolve();b,report=self.validation_fixture(r);report['proofs']={};p=pathlib.Path(b['real_IO_resource_report_path']);p.write_text(json.dumps(report));b['real_IO_resource_report_SHA']=c.sha(p)
   with self.assertRaises(KeyError):self.run_validation(b,r)
 def test_report_linked_proof_mock_or_changed_bytes_refuses(self):
  for mock in (True,False):
   with tempfile.TemporaryDirectory()as d:
    r=pathlib.Path(d).resolve();b,report=self.validation_fixture(r);proof=report['proofs']['monthly1896_K5_native_pair'];p=pathlib.Path(proof['path']);doc=c.read(p);doc['source_only_mock']=True;p.write_text(json.dumps(doc))
    if mock:
     proof['SHA']=c.sha(p);path=pathlib.Path(b['real_IO_resource_report_path']);path.write_text(json.dumps(report));b['real_IO_resource_report_SHA']=c.sha(path)
    with self.assertRaises(ValueError):self.run_validation(b,r)
 def test_source_changed_or_missing_inventory_refuses(self):
  for missing in (True,False):
   with tempfile.TemporaryDirectory()as d:
    r=pathlib.Path(d).resolve();b,_=self.validation_fixture(r);n='economic-atlas/src/e05_full_numeric_adapter.py'
    if missing:del b['source_pins'][n]
    else:(r/n).write_text('changed')
    with self.assertRaises(ValueError):self.run_validation(b,r)
 def test_null_nonfinite_budget_refuses_no_default(self):
  for value in (None,True,float('inf'),-1):
   with tempfile.TemporaryDirectory()as d:
    r=pathlib.Path(d).resolve();b,_=self.validation_fixture(r);b['spec']['whole_seconds']=value
    with self.assertRaises(ValueError):self.run_validation(b,r)
 def test_namespace_or_UID_mismatch_refuses(self):
  for field in ('paths','UID'):
   with tempfile.TemporaryDirectory()as d:
    r=pathlib.Path(d).resolve();b,_=self.validation_fixture(r)
    if field=='UID':b[field]=-1
    else:b[field]['out']='/tmp/alternate'
    with self.assertRaises(ValueError):self.run_validation(b,r)
 def test_remaining_quality_UNKNOWN_refuses(self):
  with tempfile.TemporaryDirectory()as d:
   r=pathlib.Path(d).resolve();b,report=self.validation_fixture(r);report['remaining_quality_control_cost_state']='UNKNOWN';p=pathlib.Path(b['real_IO_resource_report_path']);p.write_text(json.dumps(report));b['real_IO_resource_report_SHA']=c.sha(p)
   with self.assertRaises(ValueError):self.run_validation(b,r)
 def test_existing_foreign_timer_preserved_before_handlers(self):
  with patch.object(c.signal,'getitimer',return_value=(1.,0.)),patch.object(c.signal,'signal')as signal,patch.object(c.signal,'setitimer')as timer:
   self.assertEqual(c.main([]),1);signal.assert_not_called();timer.assert_not_called()
 def test_output_above_numeric128MiB_refuses_before_lease(self):
  with tempfile.TemporaryDirectory()as d:
   r=pathlib.Path(d).resolve();b,_=self.validation_fixture(r);b['spec']['output_bytes']=128*1024**2+1
   with self.assertRaises(ValueError):self.run_validation(b,r)
 def test_rootbinding_changedbytes_and_samebytes_replacement_refuse(self):
  for changed in (True,False):
   with tempfile.TemporaryDirectory()as d:
    p=pathlib.Path(d).resolve()/'binding';p.write_text('{}');bound=c.snapshot(p)
    if changed:p.write_text('{"new":1}')
    else:q=p.with_name('replacement');q.write_bytes(p.read_bytes());q.replace(p)
    with self.assertRaises(ValueError):c.check_snapshot(bound)
 def test_primary_cleanup_exception_fallback_wait_and_ownonly_signals(self):
  with tempfile.TemporaryDirectory()as d:
   root=pathlib.Path(d);g=Mock();g.spec=self.spec();g.whole_seconds=3600;g.anchor=c.time.monotonic();g.native.descendants.return_value=[];process=Mock(pid=9191);process.stdout.fileno.return_value=11;process.stderr.fileno.return_value=12;process.poll.return_value=0
   with patch.object(c,'CONTROL',root),patch.object(c.os,'set_blocking'),patch.object(c.select,'select',return_value=([],[],[])),patch.object(c.os,'read',return_value=b''),patch.object(toolkit,'cleanup_owned',side_effect=OSError('cleanup failure')),patch.object(c.os,'killpg',side_effect=ProcessLookupError)as signals:
    r=c.supervise(['not-run'],g,{},'secret',factory=Mock(return_value=process));self.assertFalse(r['cleanup']['unknown']);self.assertIn('cleanup failure',r['cleanup_original_error']);self.assertTrue(process.wait.called);self.assertEqual({x.args[0]for x in signals.call_args_list},{9191})
 def test_fallback_failed_reap_remains_unknown_no_full(self):
  g=Mock();g.spec=self.spec();g.whole_seconds=3600;g.anchor=c.time.monotonic();process=Mock(pid=9191);process.wait.side_effect=c.subprocess.TimeoutExpired('mock',1)
  with patch.object(c.os,'killpg',side_effect=ProcessLookupError):self.assertTrue(c.fallback_owned_cleanup(process,{9191},g)['unknown'])
 def main_binding(self,root):
  p=root/'binding';p.write_text(json.dumps(dict(spec=self.spec(),source_pins={},python_SHA='a'*64,real_IO_resource_report_SHA='b'*64)));p.chmod(0o600);return p
 def test_binding_modified_during_validation_blocks_namespace(self):
  with tempfile.TemporaryDirectory()as d:
   root=pathlib.Path(d).resolve();p=self.main_binding(root)
   def modify(*args):p.write_text('{"changed":true}');return self.spec()
   with patch.object(c.signal,'setitimer'),patch.object(c.signal,'signal'),patch.object(c,'validate',side_effect=modify),patch.object(c,'private_dir')as mkdir,patch.object(c,'supervise')as run:
    self.assertEqual(c.main(['--repo',d,'--root-binding',str(p)]),1);mkdir.assert_not_called();run.assert_not_called()
 def test_terminal_storage_failure_returns_nonzero_after_full_callback(self):
  from types import SimpleNamespace
  with tempfile.TemporaryDirectory()as d:
   root=pathlib.Path(d).resolve();p=self.main_binding(root);ctrl=root/'control';out=root/'out';ledger=root/'ledger';native=Mock();native.own_tree_rss.return_value=(1,{})
   original_once=c.once
   def write(path,value):
    if pathlib.Path(path)==ctrl/'terminal.json':raise OSError('terminal storage failed')
    return original_once(path,value)
   def worker_result(*args):
    ids=[1,2,3];original_once(ctrl/'territory-universe.json',ids);original_once(ctrl/'territory-binding.json',dict(panel_SHA=c.PANEL_SHA,original_anchor=c.ENTRY,territory_file_SHA=c.sha(ctrl/'territory-universe.json'),source_pins={},territory_ids_SHA=hashlib.sha256(json.dumps(ids,separators=(',',':')).encode()).hexdigest()));return {'cleanup':{'unknown':False}}
   bridge=SimpleNamespace(complete_and_audit=Mock(return_value={'source_fixture':True}))
   with patch.object(c.signal,'setitimer'),patch.object(c.signal,'signal'),patch.object(c,'OUT',out),patch.object(c,'CONTROL',ctrl),patch.object(c,'LEDGER',ledger),patch.object(c,'validate',return_value=self.spec()),patch.object(c,'once',side_effect=write),patch.object(c,'supervise',side_effect=worker_result),patch.object(c,'load',side_effect=lambda repo,name:SimpleNamespace(NativeMac=lambda:native)if name=='atlas_m1_executor.py'else bridge):
    self.assertEqual(c.main(['--repo',str(root),'--root-binding',str(p)]),1);bridge.complete_and_audit.assert_called_once();self.assertTrue((ledger/'operation.json').is_file());self.assertFalse((ctrl/'terminal.json').exists())
 def test_exact_whole_boundary_no_terminal_cannot_return_success(self):
  from types import SimpleNamespace
  with tempfile.TemporaryDirectory()as d:
   root=pathlib.Path(d).resolve();p=self.main_binding(root);ctrl=root/'control';out=root/'out';ledger=root/'ledger';native=Mock();native.own_tree_rss.return_value=(1,{});clock=[c.ENTRY+.1]
   def worker_result(*args):
    ids=[1,2,3];c.once(ctrl/'territory-universe.json',ids);c.once(ctrl/'territory-binding.json',dict(panel_SHA=c.PANEL_SHA,original_anchor=c.ENTRY,territory_file_SHA=c.sha(ctrl/'territory-universe.json'),source_pins={},territory_ids_SHA=hashlib.sha256(json.dumps(ids,separators=(',',':')).encode()).hexdigest()));return {'cleanup':{'unknown':False}}
   def boundary(**kwargs):clock[0]=c.ENTRY+self.spec()['whole_seconds'];return {'source_fixture':True}
   bridge=SimpleNamespace(complete_and_audit=Mock(side_effect=boundary))
   with patch.object(c.time,'monotonic',side_effect=lambda:clock[0]),patch.object(c.signal,'setitimer'),patch.object(c.signal,'signal'),patch.object(c,'OUT',out),patch.object(c,'CONTROL',ctrl),patch.object(c,'LEDGER',ledger),patch.object(c,'validate',return_value=self.spec()),patch.object(c,'supervise',side_effect=worker_result),patch.object(c,'load',side_effect=lambda repo,name:SimpleNamespace(NativeMac=lambda:native)if name=='atlas_m1_executor.py'else bridge):
    self.assertEqual(c.main(['--repo',str(root),'--root-binding',str(p)]),1);bridge.complete_and_audit.assert_called_once();self.assertFalse((ctrl/'terminal.json').exists());self.assertTrue((ledger/'operation.json').exists())
class AbsoluteDeadlineTests(unittest.TestCase):
 def test_exact_absolute_deadline_after_bridge_returns_nonzero_retains_lease(self):
  from types import SimpleNamespace
  import datetime
  with tempfile.TemporaryDirectory()as d:
   root=pathlib.Path(d).resolve();p=Test().main_binding(root);ctrl=root/'control';out=root/'out';ledger=root/'ledger';native=Mock();native.own_tree_rss.return_value=(1,{});post=[False];real=datetime.datetime
   class Clock(real):
    @classmethod
    def now(cls,tz=None):return real(2099,1,1,tzinfo=datetime.timezone.utc)if post[0]else real(2026,10,8,tzinfo=datetime.timezone.utc)
   def worker(*args):
    ids=[1,2,3];c.once(ctrl/'territory-universe.json',ids);c.once(ctrl/'territory-binding.json',dict(panel_SHA=c.PANEL_SHA,original_anchor=c.ENTRY,territory_file_SHA=c.sha(ctrl/'territory-universe.json'),source_pins={},territory_ids_SHA=hashlib.sha256(json.dumps(ids,separators=(',',':')).encode()).hexdigest()));return {'cleanup':{'unknown':False}}
   def callback(**kwargs):post[0]=True;return {'fixture':True}
   bridge=SimpleNamespace(complete_and_audit=Mock(side_effect=callback))
   with patch.object(c.datetime,'datetime',Clock),patch.object(c.time,'monotonic',return_value=c.ENTRY+.1),patch.object(c.signal,'setitimer'),patch.object(c.signal,'signal'),patch.object(c,'OUT',out),patch.object(c,'CONTROL',ctrl),patch.object(c,'LEDGER',ledger),patch.object(c,'validate',return_value=Test().spec()),patch.object(c,'supervise',side_effect=worker),patch.object(c,'load',side_effect=lambda repo,name:SimpleNamespace(NativeMac=lambda:native)if name=='atlas_m1_executor.py'else bridge):
    self.assertEqual(c.main(['--repo',str(root),'--root-binding',str(p)]),1)
   self.assertTrue((ledger/'operation.json').exists());self.assertFalse((ctrl/'terminal.json').exists())
 def test_cleanup_uses_earlier_utc_allowance_not_new_wait(self):
  import datetime
  from types import SimpleNamespace
  real=datetime.datetime
  class Clock(real):
   @classmethod
   def now(cls,tz=None):return real(2098,12,31,23,59,58,tzinfo=datetime.timezone.utc)
  spec=Test().spec();g=SimpleNamespace(anchor=0,whole_seconds=3600,spec=spec);process=Mock(pid=9191)
  with patch.object(c.datetime,'datetime',Clock),patch.object(c.time,'monotonic',return_value=1),patch.object(c.os,'getpgrp',return_value=1234),patch.object(c.os,'killpg',side_effect=ProcessLookupError):
   self.assertEqual(c.remaining_original(spec,0),2);c.fallback_owned_cleanup(process,{9191},g)
   self.assertLessEqual(process.wait.call_args.kwargs['timeout'],2/3)
 def test_expired_absolute_allowance_is_zero(self):
  spec=Test().spec();spec['absolute_deadline_UTC']='2000-01-01T00:00:00+00:00'
  with patch.object(c.time,'monotonic',return_value=1):self.assertEqual(c.remaining_original(spec,0),0)
if __name__=='__main__':unittest.main()
