"""SOURCE stdlib mocks only: no Popen, signals, native APIs or science imports."""
import ast,datetime,importlib.util,json,os,pathlib,tempfile,unittest,sys
from types import SimpleNamespace
from unittest.mock import patch,Mock
R=pathlib.Path(__file__).resolve().parents[1]
def load(name):
 sp=importlib.util.spec_from_file_location(name,R/'src'/f'{name}.py');m=importlib.util.module_from_spec(sp);sp.loader.exec_module(m);return m
c=load('e05_resource_profile_controller');w=load('e05_resource_profile_worker')
class NoSuchProcess(Exception):pass
class FakeP:
 def __init__(self,pid,alive=True):self.pid=pid;self.alive=alive;self.terms=0;self.kills=0;self.kids=[]
 def uids(self):return Mock(real=os.getuid())
 def create_time(self):return self.pid*10.
 def is_running(self):return self.alive
 def status(self):return 'running'
 def children(self,recursive):return self.kids
 def terminate(self):self.terms+=1;self.alive=False
 def kill(self):self.kills+=1;self.alive=False
class Tests(unittest.TestCase):
 def test_earliest_entry(self):
  for name in ['e05_resource_profile_controller','e05_resource_profile_worker']:
   tree=ast.parse((R/'src'/f'{name}.py').read_text());self.assertEqual(tree.body[2].targets[0].id,'ENTRY')
 def test_no_top_scientific_imports(self):
  for name in ['e05_resource_profile_controller','e05_resource_profile_worker']:
   tree=ast.parse((R/'src'/f'{name}.py').read_text())
   for node in tree.body:
    if isinstance(node,ast.Import):self.assertFalse(any(a.name.split('.')[0]in ['numpy','scipy','sklearn','pandas','pyarrow']for a in node.names))
 def test_missing_admission_before_dispatch(self):
  with patch.object(c,'admit',side_effect=ValueError('no root proof')),patch.object(c.subprocess,'Popen')as pop:
   with self.assertRaises(ValueError):c.main('/owned-fixture')
   pop.assert_not_called()
 def test_direct_worker_without_token_refuses(self):
  with self.assertRaises(PermissionError):w.authenticate('/other/token',Mock(),Mock())
 def test_private_file_mode(self):
  with tempfile.TemporaryDirectory()as d:
   p=pathlib.Path(d)/'x';p.write_text('{}');p.chmod(0o644)
   with self.assertRaises(ValueError):c.read_private(p)
   p.chmod(0o600);self.assertEqual(c.read_private(p),{})
 def test_metadata_cap(self):
  with tempfile.TemporaryDirectory()as d:
   p=pathlib.Path(d)/'x';p.write_text(' '*262145);p.chmod(0o600)
   with self.assertRaises(ValueError):c.read_private(p)
 def test_private_symlink(self):
  with tempfile.TemporaryDirectory()as d:
   p=pathlib.Path(d);(p/'target').write_text('{}');(p/'target').chmod(0o600);(p/'alias').symlink_to(p/'target')
   with self.assertRaises(ValueError):c.read_private(p/'alias')
 def test_once_lease_replay(self):
  with tempfile.TemporaryDirectory()as d:
   p=pathlib.Path(d)/'lease';c.once(p,{'one':1})
   with self.assertRaises(FileExistsError):c.once(p,{'two':2})
   self.assertEqual(json.loads(p.read_text()),{'one':1})
 def test_once_file_then_parent_fsync(self):
  with tempfile.TemporaryDirectory()as d:
   calls=[]
   with patch.object(c.os,'fsync',side_effect=lambda fd:calls.append('file')),patch.object(c,'sync_dir',side_effect=lambda p:calls.append('dir')):c.once(pathlib.Path(d)/'lease',{'one':1})
   self.assertEqual(calls,['file','dir'])
 def test_finite_boolean_nonfinite(self):
  for x in [True,float('inf'),float('nan')]:
   with self.assertRaises(ValueError):c.finite(x)
 def test_output_counts_all_roots_dedup(self):
  with tempfile.TemporaryDirectory()as d:
   p=pathlib.Path(d);(p/'a').write_bytes(b'1234');os.link(p/'a',p/'b');self.assertEqual(c.owned_bytes([p,p]),4)
 def test_output_symlink_reject(self):
  with tempfile.TemporaryDirectory()as d:
   p=pathlib.Path(d);(p/'a').write_text('x');(p/'b').symlink_to(p/'a')
   with self.assertRaises(ValueError):c.owned_bytes([p])
 def cleanup_fixture(self,exitcode):
  root=FakeP(100001,False);child=FakeP(100002);foreign=FakeP(100003)
  ps=Mock();ps.NoSuchProcess=NoSuchProcess;ps.STATUS_ZOMBIE='zombie';ps.Process.side_effect=lambda pid:root if pid==root.pid else child
  native=Mock();native.descendants.return_value=[child.pid]
  worker=Mock(pid=root.pid);worker.poll.return_value=exitcode;worker.wait.return_value=exitcode
  def send(pg,sig):
   self.assertEqual(pg,100001)
   if sig==0:raise ProcessLookupError()
   child.alive=False
  with patch.object(c.os,'getpgid',return_value=100001),patch.object(c.os,'killpg',side_effect=send)as signals:
   tree=c.OwnedTree(ps,native,worker);receipt=tree.cleanup(c.time.monotonic()+1)
  self.assertEqual(foreign.terms,0);self.assertEqual(foreign.kills,0);worker.wait.assert_called();self.assertEqual(receipt['known_owned_survivors'],0);self.assertEqual({x.args[0]for x in signals.call_args_list},{100001})
 def test_cleanup_after_normal_leader_exit(self):self.cleanup_fixture(0)
 def test_cleanup_after_nonzero_leader_exit(self):self.cleanup_fixture(1)
 def test_pid_reuse_excluded(self):
  p=FakeP(100001);ps=Mock();ps.NoSuchProcess=NoSuchProcess;ps.STATUS_ZOMBIE='zombie';tree=c.OwnedTree.__new__(c.OwnedTree);tree.ps=ps;tree.records={(p.pid,999.):p};self.assertEqual(tree.live(),[])
 def test_model_bank_namespace_not_shared(self):self.assertNotEqual(c.KEY,'E05-full-event-repaired-225cells-v1');self.assertNotEqual(c.OUT,pathlib.Path('/private/tmp/e05-full-event-repaired-actual'))
 def test_no_resource_scan_signal_handler(self):
  t=ast.parse((R/'src/e05_resource_profile_controller.py').read_text());f=next(n for n in ast.walk(t)if isinstance(n,ast.FunctionDef)and n.name=='stopping');self.assertFalse(any(isinstance(n,ast.Call)and isinstance(n.func,ast.Name)and n.func.id in ['owned_bytes','guard','admit']for n in ast.walk(f)))
 def test_no_defaults_runtime_keys(self):
  text=(R/'src/e05_resource_profile_controller.py').read_text();self.assertFalse(any(isinstance(n,ast.Constant)and n.value==600 for n in ast.walk(ast.parse(text))));self.assertIn("r['whole_seconds']",text)
class FinalGateTests(unittest.TestCase):
 def outcome(self):return {'state':'RESOURCE_PROFILE_CHILD_EXITED_NOT_FULL_QUALIFICATION','exit':0,'cleanup':{'worker_reaped':True,'known_owned_survivors':0,'registered_owned_PG_survivors':0},'terminal_written':True,'post_IO_gate':True}
 def test_prior_false_exit_states_reject(self):
  for state in ['INCONCLUSIVE_BINDING_CHANGED','INCONCLUSIVE_LOG_IO','INCONCLUSIVE_CLEANUP_UNKNOWN','INCONCLUSIVE_TERMINAL_DURABILITY']:
   r=self.outcome();r['state']=state;self.assertFalse(c.successful_exit(r))
 def test_terminal_required(self):
  r=self.outcome();r['terminal_written']=False;self.assertFalse(c.successful_exit(r))
 def test_postterminal_whole_exact_boundary(self):
  with patch.object(c.time,'monotonic',return_value=c.ENTRY+60):self.assertFalse(c.final_gate(self.outcome(),True,{'whole_seconds':60,'output_bytes':128*2**20},datetime.datetime(2099,1,1,tzinfo=datetime.timezone.utc),[]))
 def test_postterminal_absolute_deadline(self):
  with patch.object(c.time,'monotonic',return_value=c.ENTRY+.1):self.assertFalse(c.final_gate(self.outcome(),True,{'whole_seconds':60,'output_bytes':128*2**20},datetime.datetime(2000,1,1,tzinfo=datetime.timezone.utc),[]))
 def test_postterminal_output_overcap(self):
  with patch.object(c.time,'monotonic',return_value=c.ENTRY+.1),patch.object(c,'owned_bytes',return_value=128*2**20+1):self.assertFalse(c.final_gate(self.outcome(),True,{'whole_seconds':60,'output_bytes':128*2**20},datetime.datetime(2099,1,1,tzinfo=datetime.timezone.utc),[]))
 def test_slow_final_scan_exact_whole_rejects(self):
  clock=[c.ENTRY+1]
  def scan(roots):clock[0]=c.ENTRY+60;return 0
  with patch.object(c.time,'monotonic',side_effect=lambda:clock[0]),patch.object(c,'owned_bytes',side_effect=scan):self.assertFalse(c.final_gate(self.outcome(),True,{'whole_seconds':60,'output_bytes':128*2**20},datetime.datetime(2099,1,1,tzinfo=datetime.timezone.utc),[]))
 def test_slow_final_scan_exact_utc_rejects(self):
  real=datetime.datetime;expired=[False]
  class Clock(real):
   @classmethod
   def now(cls,tz=None):return real(2099,1,1,tzinfo=datetime.timezone.utc)if expired[0]else real(2026,10,8,tzinfo=datetime.timezone.utc)
  def scan(roots):expired[0]=True;return 0
  with patch.object(c.time,'monotonic',return_value=c.ENTRY+1),patch.object(c.datetime,'datetime',Clock),patch.object(c,'owned_bytes',side_effect=scan):self.assertFalse(c.final_gate(self.outcome(),True,{'whole_seconds':60,'output_bytes':128*2**20},real(2099,1,1,tzinfo=datetime.timezone.utc),[]))
 def test_no_allpid_enumeration(self):
  for name in ['e05_resource_profile_controller','e05_resource_profile_worker']:
   tree=ast.parse((R/'src'/f'{name}.py').read_text())
   self.assertFalse(any(isinstance(n,ast.Call)and isinstance(n.func,ast.Attribute)and n.func.attr in ['process_iter','children']for n in ast.walk(tree)))
 def test_known_fallback_failed_reap_unknown(self):
  worker=Mock(pid=100001);worker.wait.side_effect=c.subprocess.TimeoutExpired('mock',1)
  with patch.object(c.os,'killpg',side_effect=ProcessLookupError),patch.object(c.time,'monotonic',return_value=1):
   with self.assertRaises(RuntimeError):c.fallback_known_child(worker,{100001},10)
 def test_known_fallback_expired_no_added_wait(self):
  worker=Mock(pid=100001)
  with patch.object(c.os,'killpg',side_effect=ProcessLookupError),patch.object(c.time,'monotonic',return_value=10):c.fallback_known_child(worker,{100001},10)
  self.assertEqual({x.kwargs['timeout']for x in worker.wait.call_args_list},{0})
class MainRegressionTests(unittest.TestCase):
 def run_main(self,variant):
  with tempfile.TemporaryDirectory()as d:
   root=pathlib.Path(d);ctrl=root/'ctrl';ctrl.mkdir();out=root/'out';ledger=root/'ledger';worker_file=root/'economic-atlas/src/e05_resource_profile_worker.py';worker_file.parent.mkdir(parents=True);worker_file.write_text('INERT SOURCE FIXTURE')
   (ctrl/'runtime.json').write_text('{}');(ctrl/'source-ack.json').write_text('{}');runtime_hash=c.sha(ctrl/'runtime.json');clock=[c.ENTRY+.1]
   r={'whole_seconds':60,'final_reserve_seconds':30,'cleanup_seconds':10,'poll_seconds':.2,'CPU_threads':1,'RSS_bytes':2**30,'minimum_free_bytes':2**30,'output_bytes':128*2**20,'receipt_reserve_bytes':8192,'absolute_deadline_UTC':'2099-01-01T00:00:00Z','_bindings':{'runtime.json':runtime_hash}}
   process=Mock(pid=100001);process.stdout.fileno.return_value=11;process.stderr.fileno.return_value=12;process.returncode=0
   def poll():
    if variant=='binding_changed':(ctrl/'runtime.json').write_text('{"changed":1}')
    return 0
   process.poll.side_effect=poll
   ps=SimpleNamespace(Process=lambda pid:SimpleNamespace(create_time=lambda:1.,memory_info=lambda:SimpleNamespace(rss=1)))
   tree=Mock(groups={100001});tree.rss.return_value=1
   if variant=='cleanup_error':tree.cleanup.side_effect=OSError('primary failure')
   else:tree.cleanup.return_value={'worker_reaped':True,'known_owned_survivors':0,'registered_owned_PG_survivors':0}
   selector=Mock();selector.select.return_value=[];selector.get_map.return_value={}
   original_once=c.once
   def write(path,obj):
    if pathlib.Path(path)==ctrl/'controller-terminal.json':
     if variant=='terminal_failure':raise OSError('fsync fixturefailure')
     original_once(path,obj)
     if variant=='terminal_overrun':clock[0]=c.ENTRY+60
    else:original_once(path,obj)
   with patch.dict(sys.modules,{'psutil':ps}),patch.object(c,'CONTROL',ctrl),patch.object(c,'OUT',out),patch.object(c,'LEDGER',ledger),patch.object(c,'admit',return_value=(r,{'source_pins':{}})),patch.object(c,'load_native',return_value=Mock()),patch.object(c,'OwnedTree',return_value=tree),patch.object(c.subprocess,'Popen',return_value=process)as pop,patch.object(c.selectors,'DefaultSelector',return_value=selector),patch.object(c.signal,'signal'),patch.object(c.os,'set_blocking'),patch.object(c.os,'statvfs',return_value=SimpleNamespace(f_bavail=2**32,f_frsize=1)),patch.object(c.os,'killpg',side_effect=ProcessLookupError)as signals,patch.object(c.time,'monotonic',side_effect=lambda:clock[0]),patch.object(c,'once',side_effect=write):
    result=c.main(str(root));self.assertEqual(pop.call_count,1)
   return result,process.wait.call_count,{x.args[0]for x in signals.call_args_list}
 def test_real_main_terminal_io_overrun_blocks(self):self.assertFalse(c.successful_exit(self.run_main('terminal_overrun')[0]))
 def test_real_main_terminal_fsync_failure_blocks(self):
  result,_,_=self.run_main('terminal_failure');self.assertFalse(result['terminal_written']);self.assertFalse(c.successful_exit(result))
 def test_real_main_binding_changed_blocks(self):self.assertFalse(c.successful_exit(self.run_main('binding_changed')[0]))
 def test_real_main_cleanup_exception_has_own_fallback(self):
  result,waits,signals=self.run_main('cleanup_error');self.assertGreater(waits,0);self.assertEqual(signals,{100001});self.assertTrue(c.successful_exit(result));self.assertIn('cleanup_primary_error',result)
class CadenceTests(unittest.TestCase):
 def base(self):
  class B:
   anchor=0;roots=[];samples={'count':0};now=0.;calls=0
   spec={'whole_seconds':600,'final_reserve_seconds':30,'poll_seconds':.2}
   deadline=datetime.datetime(2099,1,1,tzinfo=datetime.timezone.utc)
   def clock(self):return self.now
   def utc(self):return datetime.datetime(2026,1,1,tzinfo=datetime.timezone.utc)
   def __call__(self):self.calls+=1;self.samples['count']=self.calls
  return B()
 def test_expensive_scan_cadence_only(self):
  b=self.base();g=w.CadencedGuard(b)
  for i in range(100):g()
  self.assertEqual(b.calls,1);b.now=.21;g();self.assertEqual(b.calls,2)
 def test_clock_every_call_with_cached_resources(self):
  b=self.base();g=w.CadencedGuard(b);g();b.now=570
  with self.assertRaises(InterruptedError):g()
  self.assertEqual(b.calls,1);self.assertFalse(g.active)
 def test_slow_scan_postcheck_original_allowance(self):
  b=self.base();original=b.__class__.__call__
  def slow(self):original(self);self.now=571
  b.__class__.__call__=slow;g=w.CadencedGuard(b)
  with self.assertRaises(InterruptedError):g()
  self.assertFalse(g.active);self.assertEqual(g.anchor,0)
 def test_absolute_deadline_every_call(self):
  b=self.base();g=w.CadencedGuard(b);g();b.utc=lambda:b.deadline
  with self.assertRaises(InterruptedError):g()
  self.assertEqual(b.calls,1)
if __name__=='__main__':unittest.main()
