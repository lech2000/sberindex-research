import ast,datetime,hashlib,importlib.util,json,os,pathlib,socket,tempfile,time,types,unittest
from unittest.mock import patch
ROOT=pathlib.Path(__file__).resolve().parents[1]
def module(name):
 p=ROOT/'economic-atlas/src'/name;s=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
c=module('atlas_m4_recovery_controller_v2.py');m=module('atlas_m4_recovery_v2.py')
class Recovery(unittest.TestCase):
 def m1(self):return {'state':'AUTHORITATIVE_M1_OWNED_PARENTS_GONE','checked_at_UTC':datetime.datetime.now(datetime.timezone.utc).isoformat(),'signals':0,'known_pids':{str(p):{'ps_exit':1,'stdout':'','stderr':''} for p in [72250,72253]}}
 def old(self):return {'state':'AUTHORITATIVE_OLD_M4_JOB_GONE_NO_SCIENCE_STARTED','checked_at_UTC':datetime.datetime.now(datetime.timezone.utc).isoformat(),'signals':0,'label':m.OLD_LABEL,'processes':[],'launchctl_state':'not running','runs':1,'last_exit_code':1,'old_status_sha256':m.OLD_EVIDENCE[str(m.OLD_CONTROLLER.parent/'ROOT_FIRST_ACTUAL_STATUS.json')]}
 def test_exact_raw_pretty_copy_and_readback(self):
  with tempfile.TemporaryDirectory() as d:
   a=pathlib.Path(d)/'a';b=a.with_name('b');a.write_text(json.dumps(self.m1(),indent=2)+'\n');h=c.sha(a);c.copy_raw_once(a,b,h);self.assertEqual(a.read_bytes(),b.read_bytes());self.assertEqual(h,c.sha(b))
   with self.assertRaises(FileExistsError):c.copy_raw_once(a,b,h)
 def test_bad_rawsha_no_destination(self):
  with tempfile.TemporaryDirectory() as d:
   a=pathlib.Path(d)/'a';b=a.with_name('b');a.write_text('{}')
   with self.assertRaises(ValueError):c.copy_raw_once(a,b,'0'*64)
   self.assertFalse(b.exists())
 def authority_context(self,d):
  ledger=pathlib.Path(d)/'ledger';ledger.mkdir();old=pathlib.Path(d)/'old';old.mkdir();return ledger,old
 def test_oldmodel_consumed_or_oldscience_blocks(self):
  for kind in ('model','science','receipts'):
   with tempfile.TemporaryDirectory() as d:
    ledger,old=self.authority_context(d)
    if kind=='model':(ledger/(str(os.getuid())+'-M4-'+hashlib.sha256(m.KEY.encode()).hexdigest()+'.json')).write_text('STARTED')
    else:(old/kind).mkdir()
    with patch.object(m,'OLD_EVIDENCE',{}),patch.object(m,'LEDGER_ROOT',ledger),patch.object(m,'OLD_ACTUAL',old),self.assertRaises(ValueError):m.check_recovery_authority()
 def test_old_evidence_change_blocks(self):
  with tempfile.TemporaryDirectory() as d:
   f=pathlib.Path(d)/'evidence';f.write_text('changed')
   with patch.object(m,'OLD_EVIDENCE',{str(f):'0'*64}),self.assertRaises(ValueError):m.check_recovery_authority()
 def test_live_unknown_or_stale_oldjob_reject(self):
  for field,bad in [('processes',[{'pid':1}]),('runs',2),('last_exit_code',0),('launchctl_state','running'),('signals',1),('old_status_sha256','0'*64),('checked_at_UTC','2000-01-01T00:00:00+00:00')]:
   with self.subTest(field=field),tempfile.TemporaryDirectory() as d:
    ledger,old=self.authority_context(d);q=self.old();q[field]=bad
    with patch.object(m,'sha',side_effect=lambda p:m.OLD_EVIDENCE[str(p)]),patch.object(m,'LEDGER_ROOT',ledger),patch.object(m,'OLD_ACTUAL',old),self.assertRaises(ValueError):m.check_recovery_authority(q)
 def test_history_no_reset_and_full_budget(self):
  now=datetime.datetime(2026,10,8,3,tzinfo=datetime.timezone.utc)
  with self.assertRaises(ValueError):m.admission(now,historical=82.20326720799494)
  self.assertEqual(m.admission(now,startup=5),int(93600-m.HISTORICAL_SECONDS-5-30))
  with self.assertRaises(ValueError):m.admission(datetime.datetime(2026,10,9,8,tzinfo=datetime.timezone.utc))
 def test_modelkey_unchanged_distinct_bootstrap(self):
  self.assertEqual(c.KEY,m.KEY);self.assertEqual(m.KEY,'M4fullbank:6220a61fcaefe60ecc872f5c930023bb6453d0c60059c3f66721199882330969');self.assertIn('M4-bootstrap-recovery-v2-',pathlib.Path(m.__file__).read_text())
 def test_prepare_handoff_integration_mock_no_process(self):
  with tempfile.TemporaryDirectory() as d:
   p=pathlib.Path(d);runtime=p/'runtime';actual=p/'actual';ledger=p/'ledger';ledger.mkdir(mode=0o700);proof=p/'m1';op=p/'old';proof.write_text(json.dumps(self.m1(),indent=2)+'\n');op.write_text(json.dumps(self.old(),indent=2)+'\n');acc=p/'accept';acc.write_text('{}');source=p/'repo/economic-atlas/src';source.mkdir(parents=True);(source/'atlas_m4_recovery_v2.py').write_text('accepted fixture')
   dm=types.SimpleNamespace(LEDGER_ROOT=ledger,check_recovery_authority=lambda q:True,verify_dependency_files=lambda *a:True,admission=lambda *a,**k:93400,utcnow=lambda:datetime.datetime.now(datetime.timezone.utc),plist=lambda *a:b'mocked one-shot plist')
   desc={'result_sha256':'result','manifest_sha256':'manifest'};calls=[]
   def invoke(argv,**kw):calls.append(argv);return types.SimpleNamespace(returncode=0)
   with patch.object(c,'ROOT',runtime),patch.object(c,'ACTUAL',actual),patch.object(c,'REPO',p/'repo'),patch.object(c,'ACCEPT',acc),patch.object(c,'descriptor',return_value=desc),patch.object(c,'load_durable',return_value=dm),patch.object(c,'controller_guard',return_value=110):
    c.prepare(proof,c.sha(proof),op,c.sha(op));self.assertEqual(c.sha(proof),c.sha(runtime/'ROOT_M1_GONE.json'));self.assertEqual(c.bootstrap(invoke),0)
    with self.assertRaises(FileExistsError):c.bootstrap(invoke)
   self.assertEqual(len(calls),1);self.assertEqual(calls[0][:2],['/bin/launchctl','bootstrap']);self.assertFalse((ledger/(str(os.getuid())+'-M4-'+hashlib.sha256(c.KEY.encode()).hexdigest()+'.json')).exists())
 def test_timeout_retains_operational_lease_no_retry(self):
  # Same integration fixture exercises timeout through bootstrap actual control function.
  with tempfile.TemporaryDirectory() as d:
   p=pathlib.Path(d);rt=p/'rt';rt.mkdir();actual=p/'actual';actual.mkdir();ledger=p/'ledger';ledger.mkdir(mode=0o700)
   (rt/'ROOT_M1_GONE.json').write_text(json.dumps(self.m1()));(rt/'ROOT_OLD_M4_GONE.json').write_text(json.dumps(self.old()));(rt/'ONE_JOB.plist').write_text('mock')
   entry={'controller_source_sha256':c.sha(c.__file__),'uid':os.getuid(),'host':socket.gethostname(),'monotonic_entry':time.monotonic()};(rt/'entry.json').write_text(json.dumps(entry));lease=ledger/(str(os.getuid())+'-M4-bootstrap-recovery-v2-'+hashlib.sha256(c.KEY.encode()).hexdigest()+'.json');(rt/'ROOT_BINDING.json').write_text(json.dumps({'bootstrap_reservation':str(lease),'controller_entry_sha256':c.sha(rt/'entry.json')}));(rt/'PREPARATION.json').write_text(json.dumps({'binding_sha256':c.sha(rt/'ROOT_BINDING.json'),'plist_sha256':c.sha(rt/'ONE_JOB.plist')}));dm=types.SimpleNamespace(LEDGER_ROOT=ledger,check_recovery_authority=lambda q:True,admission=lambda *a,**k:1,utcnow=lambda:datetime.datetime.now(datetime.timezone.utc))
   with patch.object(c,'ROOT',rt),patch.object(c,'ACTUAL',actual),patch.object(c,'load_durable',return_value=dm),patch.object(c,'controller_guard',return_value=100):
    with self.assertRaises(RuntimeError):c.bootstrap(lambda *a,**k:(_ for _ in ()).throw(TimeoutError('mock')))
    self.assertTrue(lease.exists());self.assertIn('HANDOFF_UNKNOWN',json.loads(lease.with_name(lease.stem+'-terminal.json').read_text())['state'])
    with self.assertRaises(FileExistsError):c.bootstrap(lambda *a,**k:self.fail('retry'))
 def test_controller_time_space_guards(self):
  with patch.object(c.time,'monotonic',return_value=121),self.assertRaises(InterruptedError):c.controller_guard(0)
  with patch.object(c.time,'monotonic',return_value=1),patch.object(c,'output_sizes',return_value=(0,0)),patch.object(c.shutil,'disk_usage',return_value=types.SimpleNamespace(free=0)),self.assertRaises(InterruptedError):c.controller_guard(0)
 def test_rawproof_worker_binding_checked_before_imports(self):
  tree=ast.parse(pathlib.Path(m.__file__).read_text());main=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='main');code=ast.unparse(main);self.assertLess(code.index('controller_anchor(binding)'),code.index("'pinned_m4'"));self.assertLess(code.index('controller_anchor(binding)'),code.index('reserve(reservation, record)'))
 def test_all_original_sciencepins_preserved(self):
  old=pathlib.Path('/private/tmp/sberindex-official-laws-20261007/economic-atlas/src/atlas_m4_durable.py');tree=ast.parse(old.read_text());pin=next(n for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(x,ast.Name) and x.id=='PINS' for x in n.targets));original=ast.literal_eval(pin.value)
  for k,v in original.items():self.assertEqual(m.PINS[k],v)
if __name__=='__main__':unittest.main()
class FullHandoff(unittest.TestCase):
 m1=Recovery.m1
 old=Recovery.old
 def test_worker_handoff_exact_proof_bytes_and_history(self):
  with tempfile.TemporaryDirectory() as d:
   p=pathlib.Path(d).resolve();rt=p/'runtime';rt.mkdir(mode=0o700);ledger=p/'ledger';ledger.mkdir(mode=0o700)
   q=self.m1();(rt/'ROOT_M1_GONE.json').write_text(json.dumps(q,indent=2)+'\n');(rt/'ROOT_OLD_M4_GONE.json').write_text(json.dumps(self.old(),indent=2)+'\n')
   anchor=time.monotonic();stamp=datetime.datetime.now(datetime.timezone.utc).isoformat();entry={'origin':m.CONTROLLER_ORIGIN,'uid':os.getuid(),'host':socket.gethostname(),'monotonic_entry':anchor,'utc_entry':stamp,'controller_source_sha256':c.sha(c.__file__),'quiescence_sha256':c.sha(rt/'ROOT_M1_GONE.json')};(rt/'entry.json').write_text(json.dumps(entry))
   lease=ledger/(str(os.getuid())+'-M4-bootstrap-recovery-v2-'+hashlib.sha256(m.KEY.encode()).hexdigest()+'.json');b={'controller_monotonic_entry':anchor,'controller_entry_sha256':c.sha(rt/'entry.json'),'controller_source_sha256':c.sha(c.__file__),'controller_utc_entry':stamp,'quiescence_sha256':c.sha(rt/'ROOT_M1_GONE.json'),'oldjob_sha256':c.sha(rt/'ROOT_OLD_M4_GONE.json'),'bootstrap_reservation':str(lease)};(rt/'ROOT_BINDING.json').write_text(json.dumps(b));lease.write_text(json.dumps({'controller_entry_sha256':b['controller_entry_sha256'],'one_use_key':m.KEY,'binding_sha256':c.sha(rt/'ROOT_BINDING.json'),'outdir':str(m.ACTUAL_ROOT/'science'),'receipt_dir':str(m.ACTUAL_ROOT/'receipts')}))
   with patch.object(m,'CONTROLLER_ROOT',rt),patch.object(m,'LEDGER_ROOT',ledger),patch.object(m,'check_recovery_authority',return_value=True):
    self.assertEqual(m.controller_anchor(b),anchor)
    (rt/'ROOT_M1_GONE.json').write_text(json.dumps(q))
    with self.assertRaisesRegex(ValueError,'proof SHA'):m.controller_anchor(b)
 def test_wrong_oldjob_sha_rejected_before_authority(self):
  with tempfile.TemporaryDirectory() as d:
   rt=pathlib.Path(d);(rt/'ROOT_OLD_M4_GONE.json').write_text('{}')
   with patch.object(m,'CONTROLLER_ROOT',rt),patch.object(m,'check_recovery_authority') as call,self.assertRaises(ValueError):m.controller_anchor({'oldjob_sha256':'0'*64})
   call.assert_not_called()
 def test_no_scientific_ast_delta(self):
  old=ast.parse(pathlib.Path('/private/tmp/sberindex-official-laws-20261007/economic-atlas/src/atlas_m4_durable.py').read_text());new=ast.parse(pathlib.Path(m.__file__).read_text())
  names=['finite','admission','validate_scalars','verify_dependency_files','atomic','reserve','load','main']
  class StripDirectorySync(ast.NodeTransformer):
   def visit_Expr(self,node):
    if isinstance(node.value,ast.Call) and isinstance(node.value.func,ast.Name) and node.value.func.id=='sync_dir':return None
    return self.generic_visit(node)
  # Only explicit operational directory fsync calls are removed for comparison.
  new=StripDirectorySync().visit(new)
  a={n.name:ast.dump(n,include_attributes=False) for n in old.body if isinstance(n,ast.FunctionDef)};b={n.name:ast.dump(n,include_attributes=False) for n in new.body if isinstance(n,ast.FunctionDef)}
  for name in names:self.assertEqual(a[name],b[name],name)
class Durability(unittest.TestCase):
 def fixture(self,p):
  rt=p/'runtime';rt.mkdir(mode=0o700);actual=p/'actual';actual.mkdir(mode=0o700);ledger=p/'ledger';ledger.mkdir(mode=0o700)
  (rt/'ROOT_M1_GONE.json').write_text(json.dumps(Recovery().m1()));(rt/'ROOT_OLD_M4_GONE.json').write_text(json.dumps(Recovery().old()));(rt/'ONE_JOB.plist').write_text('mock')
  entry={'controller_source_sha256':c.sha(c.__file__),'uid':os.getuid(),'host':socket.gethostname(),'monotonic_entry':time.monotonic()};(rt/'entry.json').write_text(json.dumps(entry));lease=ledger/(str(os.getuid())+'-M4-bootstrap-recovery-v2-'+hashlib.sha256(c.KEY.encode()).hexdigest()+'.json');(rt/'ROOT_BINDING.json').write_text(json.dumps({'bootstrap_reservation':str(lease),'controller_entry_sha256':c.sha(rt/'entry.json')}));(rt/'PREPARATION.json').write_text(json.dumps({'binding_sha256':c.sha(rt/'ROOT_BINDING.json'),'plist_sha256':c.sha(rt/'ONE_JOB.plist')}));dm=types.SimpleNamespace(LEDGER_ROOT=ledger,check_recovery_authority=lambda q:True,admission=lambda *a,**k:1,utcnow=lambda:datetime.datetime.now(datetime.timezone.utc));return rt,actual,ledger,lease,dm
 def test_once_rawcopy_atomic_file_then_directory(self):
  import stat
  real=os.fsync;events=[]
  def spy(fd):events.append('directory' if stat.S_ISDIR(os.fstat(fd).st_mode) else 'file');return real(fd)
  with tempfile.TemporaryDirectory() as temp:
   p=pathlib.Path(temp);source=p/'source';source.write_text('{\n  "raw": true\n}\n')
   with patch.object(os,'fsync',side_effect=spy):
    c.once(p/'one',{'x':1});self.assertEqual(events,['file','directory']);events.clear()
    c.copy_raw_once(source,p/'copy',c.sha(source));self.assertEqual(events,['file','directory']);events.clear()
    m.atomic(p/'terminal',{'state':'STOP'});self.assertEqual(events,['file','directory'])
 def test_directory_sync_failure_prevents_handoff_preserves_unknown(self):
  with tempfile.TemporaryDirectory() as temp:
   p=pathlib.Path(temp).resolve();rt,actual,ledger,lease,dm=self.fixture(p);calls=[];original=c.sync_dir
   def fail_directory(path):
    if pathlib.Path(path)==ledger:raise OSError('mock directory fsync failed')
    return original(path)
   with patch.object(c,'ROOT',rt),patch.object(c,'ACTUAL',actual),patch.object(c,'load_durable',return_value=dm),patch.object(c,'controller_guard',return_value=100),patch.object(c,'sync_dir',side_effect=fail_directory):
    with self.assertRaises(OSError):c.bootstrap(lambda *a,**kw:calls.append(a))
    self.assertTrue(lease.exists());terminal=json.loads(lease.with_name(lease.stem+'-terminal.json').read_text());self.assertEqual(terminal['state'],'BOOTSTRAP_STOP_DURABILITY_UNPROVEN_NO_RETRY');self.assertFalse(terminal['handoff_invoked']);self.assertFalse(terminal['durable_publication_proven'])
    with self.assertRaises(FileExistsError):c.bootstrap(lambda *a,**kw:calls.append(a))
   self.assertEqual(calls,[])
 def test_lease_directory_synced_before_invoke(self):
  with tempfile.TemporaryDirectory() as temp:
   p=pathlib.Path(temp).resolve();rt,actual,ledger,lease,dm=self.fixture(p);events=[];original=c.sync_dir
   def spy(path):events.append(('dir',pathlib.Path(path)));return original(path)
   def invoke(*a,**kw):self.assertTrue(lease.exists());self.assertEqual(events[-1],('dir',ledger));events.append(('HANDOFF',None));return types.SimpleNamespace(returncode=0)
   with patch.object(c,'ROOT',rt),patch.object(c,'ACTUAL',actual),patch.object(c,'load_durable',return_value=dm),patch.object(c,'controller_guard',return_value=100),patch.object(c,'sync_dir',side_effect=spy):self.assertEqual(c.bootstrap(invoke),0)
   self.assertEqual(sum(e[0]=='HANDOFF' for e in events),1)
 def test_plist_directory_sync_and_mkdir_before_prepare_complete(self):
  import inspect
  text=inspect.getsource(c.prepare.__wrapped__)
  self.assertLess(text.index("sync_dir(ROOT)"),text.index("once(ROOT/'PREPARATION.json'"));self.assertIn('sync_dir(ROOT.parent.parent)',text);self.assertIn('ROOT.mkdir(mode=0o700,exist_ok=False);sync_dir(ROOT.parent)',text)
 def test_file_sync_failure_no_copy_or_once_publication_claim(self):
  with tempfile.TemporaryDirectory() as temp:
   p=pathlib.Path(temp);source=p/'source';source.write_text('{}')
   with patch.object(os,'fsync',side_effect=OSError('mock file sync')),self.assertRaises(OSError):c.copy_raw_once(source,p/'copy',c.sha(source))
   self.assertTrue((p/'copy').exists())
