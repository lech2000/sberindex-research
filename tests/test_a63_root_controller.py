import hashlib,importlib.util,io,json,os,pathlib,socket,tempfile,time,types,unittest
from unittest.mock import patch
ROOT=pathlib.Path(__file__).resolve().parents[1];src=ROOT/'economic-atlas/src/a63_root_controller.py';s=importlib.util.spec_from_file_location('a63_controller',src);c=importlib.util.module_from_spec(s);s.loader.exec_module(c)
class Controller(unittest.TestCase):
 def test_fixed_original_seed_inventory_only_no_generation(self):
  repo=pathlib.Path('/private/tmp/sberindex-official-laws-20261007');spec=json.loads(pathlib.Path('/private/tmp/atlas-a63-full-prospective-f7b-20261008/revision-oracle-metadata/candidate/economic-atlas/protocols/A63_NEW_PROSPECTIVE_SYNTHETIC_V1.json').read_text());i=c.seed_inventory(repo,spec);self.assertTrue(i['disjoint']);self.assertEqual(i['old_runs'],210);self.assertEqual(len(i['new_effective_rng_keys']),35)
  spec['seeds'][0]=20261003
  with self.assertRaises(ValueError):c.seed_inventory(repo,spec)
 def test_first_admission_failure_no_runtime_or_reservation(self):
  with tempfile.TemporaryDirectory() as d:
   p=pathlib.Path(d)
   with patch.object(c,'OUT',p/'out'),patch.object(c,'CONTROL',p/'control'),patch.object(c,'LEDGER',p/'ledger'),patch.object(c,'guard',side_effect=InterruptedError('disk')),patch.object(c,'validate',side_effect=AssertionError('must not readsource')),patch.object(c.signal,'setitimer'):
    r=c.execute(p,popen=lambda *a,**kw:self.fail('no process'))
   self.assertEqual(r['state'],'INCONCLUSIVE_CONTROLLER');self.assertFalse(list(p.iterdir()))
 def test_lowfree_elapsed_output_nan_false_guards(self):
  for defect in ['free','elapsed','output']:
   with patch.object(c,'output_size',return_value=c.MAXOUT if defect=='output' else 0),patch.object(c.shutil,'disk_usage',return_value=types.SimpleNamespace(free=0 if defect=='free' else 2**31)),self.assertRaises(InterruptedError):c.guard(time.monotonic()-1800 if defect=='elapsed' else time.monotonic())
  for anchor in [True,float('nan'),float('inf')]:
   with self.assertRaises(ValueError):c.guard(anchor)
 def test_preexisting_namespace_rejects_before_lease(self):
  with tempfile.TemporaryDirectory() as d:
   p=pathlib.Path(d);control=p/'control';control.mkdir();(control/'old-terminal').write_text('unchanged')
   with patch.object(c,'OUT',p/'out'),patch.object(c,'CONTROL',control),patch.object(c,'LEDGER',p/'ledger'),patch.object(c,'guard',return_value=1700),patch.object(c,'validate',return_value=({}, {}, {}, {})),patch.object(c.signal,'setitimer'):
    r=c.execute(p,popen=lambda *a,**kw:self.fail('no process'))
   self.assertIn('fresh fixed',r['error']);self.assertFalse((p/'ledger').exists());self.assertEqual((control/'old-terminal').read_text(),'unchanged')
 def test_log_drain_bounded_no_inherited_science_file_cap(self):
  fakepipe=types.SimpleNamespace(fileno=lambda:99);selector=types.SimpleNamespace(select=lambda timeout:[(types.SimpleNamespace(fileobj=fakepipe,data='stdout'),1)])
  target=io.BytesIO(b'x'*8000);target.seek(0,2)
  with patch.object(c.os,'read',return_value=b'a'*4096),self.assertRaises(InterruptedError):c.drain_logs(selector,{'stdout':target})
  self.assertEqual(len(target.getvalue()),8000)
  self.assertNotIn('preexec_fn',src.read_text());self.assertNotIn('capture_output',src.read_text().replace('# Bounded read and bounded on-disk logs, never communicate/capture_output.',''))
 def test_timeout_cleanup_only_mocked_owned_guardian(self):
  class Process:
   pid=999991;stdout=None;stderr=None
   def __init__(self):self.returncode=None;self.waitcalls=0
   def poll(self):return self.returncode
   def wait(self,timeout):self.waitcalls+=1;self.returncode=-15;return -15
  p=Process();native=types.SimpleNamespace(descendants=lambda root:[p.pid] if p.returncode is None else [])
  with patch.object(c.os,'killpg') as signals:r=c.cleanup(p,native)
  signals.assert_called_once_with(p.pid,c.signal.SIGTERM);self.assertTrue(r['immediate_reaped']);self.assertEqual(r['known_remaining'],[])
 def test_lease_permanent_and_directory_synced(self):
  with tempfile.TemporaryDirectory() as d:
   p=pathlib.Path(d)/'lease';original=c.os.fsync;calls=[]
   def fsync(fd):calls.append(fd);original(fd)
   with patch.object(c.os,'fsync',side_effect=fsync):c.once(p,{'state':'STARTED'})
   self.assertEqual(len(calls),2)
   with self.assertRaises(FileExistsError):c.once(p,{'state':'RETRY'})
 def test_unknown_fit_state_is_not_controller_scientificpass(self):
  # Kernel/native/Popen are all mocks; force failure AFTER durable controller
  # reservation, before any child. A second invocation must reject.
  with tempfile.TemporaryDirectory() as d:
   p=pathlib.Path(d);control=p/'control';ledger=p/'ledger';repo=p/'repo';repo.mkdir();approval=p/'reg';approval.write_text('rootapproval')
   a={'python_binary_SHA':'fake'};op={'pins':{}};inventory={}
   with patch.object(c,'OUT',p/'out'),patch.object(c,'CONTROL',control),patch.object(c,'LEDGER',ledger),patch.object(c,'guard',return_value=1700),patch.object(c,'validate',return_value=(a,op,inventory,{})),patch.object(c.importlib.util,'spec_from_file_location',side_effect=RuntimeError('mock future unknown guard')),patch.object(c.signal,'setitimer'):
    r=c.execute(repo,approval,popen=lambda *a,**kw:self.fail('noactualprocess'));self.assertFalse(r['scientific_pass']);self.assertTrue(c.lease('-controller').exists())
    before=c.lease('-controller').read_bytes();r2=c.execute(repo,approval,popen=lambda *a,**kw:self.fail('noretry'));self.assertEqual(c.lease('-controller').read_bytes(),before);self.assertIn('fresh fixed',r2['error'])
 def test_negative_root_registration_pin_or_versions_before_process(self):
  for defect in ['review','python','versions','seeds','ack']:
   with tempfile.TemporaryDirectory() as d:
    p=pathlib.Path(d);repo=p/'repo';(repo/'economic-atlas/protocols').mkdir(parents=True);(repo/c.OP).write_text(json.dumps({'pins':{}}));(repo/c.SPEC).write_text('{}');approval=p/'reg.json'
    inventory={'disjoint':True,'scope':'fake metadata fixture'};digest=hashlib.sha256(json.dumps(inventory,sort_keys=True,allow_nan=False).encode()).hexdigest()
    a={'root_reviewed':True,'one_use_key':c.KEY,'controller_SHA':'mock','operational_protocol_SHA':c.OP_SHA,'uid':os.getuid(),'host':socket.gethostname(),'pins':{},'python_binary_SHA':'mock','dependency_versions':dict.fromkeys(['numpy','pandas','scipy','scikit-learn'],'mockversion'),'seed_inventory_SHA':digest,'seed_prior_nonuse_root_attested':True,'independent_source_ACK_SHA':c.ACK_SHA}
    if defect=='review':a['root_reviewed']=False
    elif defect=='python':a['python_binary_SHA']='wrong'
    elif defect=='versions':a['dependency_versions']['numpy']='wrong'
    elif defect=='seeds':a['seed_prior_nonuse_root_attested']=False
    elif defect=='ack':a['independent_source_ACK_SHA']='wrong'
    approval.write_text(json.dumps(a))
    def sha(path):return c.OP_SHA if pathlib.Path(path)==repo/c.OP else 'mock'
    with patch.object(c,'APPROVAL',approval),patch.object(c,'sha',side_effect=sha),patch.object(c.importlib.metadata,'version',return_value='mockversion'),patch.object(c,'seed_inventory',return_value=inventory),self.assertRaises(ValueError):c.validate(repo,approval)

 def test_cleanup_refuses_foreground_group(self):
  process=types.SimpleNamespace(pid=99)
  with patch.object(c.os,'getpgrp',return_value=99),patch.object(c.os,'killpg') as signals,self.assertRaises(RuntimeError):c.cleanup(process,None)
  signals.assert_not_called()

 def test_early_watchdog_interrupts_validation_without_lease_and_restores(self):
  with tempfile.TemporaryDirectory() as d:
   p=pathlib.Path(d);handlers={};observed=[];count=[0]
   def register(sig,fn):handlers[sig]=fn
   def guard(*args,**kwargs):
    count[0]+=1
    if count[0]>1:raise InterruptedError('mock source validation timeout')
    return 1700
   def validate(*args):
    self.assertIn(c.signal.SIGALRM,handlers);self.assertIn((c.signal.ITIMER_REAL,.25,.25),observed);handlers[c.signal.SIGALRM](c.signal.SIGALRM,None)
   with patch.object(c,'OUT',p/'out'),patch.object(c,'CONTROL',p/'control'),patch.object(c,'LEDGER',p/'ledger'),patch.object(c,'guard',side_effect=guard),patch.object(c,'validate',side_effect=validate),patch.object(c.signal,'getsignal',return_value=c.signal.SIG_DFL),patch.object(c.signal,'signal',side_effect=register),patch.object(c.signal,'setitimer',side_effect=lambda *args:observed.append(args)):
    r=c.execute(p,popen=lambda *a,**kw:self.fail('no process'))
   self.assertIn('source validation timeout',r['error']);self.assertFalse(list(p.iterdir()));self.assertTrue(all(handlers[sig]==c.signal.SIG_DFL for sig in [c.signal.SIGALRM,c.signal.SIGTERM,c.signal.SIGINT]))

if __name__=='__main__':unittest.main()
