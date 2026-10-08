import ast,hashlib,importlib.util,json,os,pathlib,socket,tempfile,time,types,unittest
from unittest.mock import patch
ROOT=pathlib.Path(__file__).resolve().parents[1]
def load(name):
 s=importlib.util.spec_from_file_location(name,ROOT/'economic-atlas/src'/(name+'.py'));m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
g=load('a63_full_guardian');w=load('a63_full_worker')
class Operational(unittest.TestCase):
 def test_imports_stdlib_only(self):
  for name in ['a63_full_guardian','a63_full_worker']:
   tree=ast.parse((ROOT/'economic-atlas/src'/(name+'.py')).read_text())
   imported={x.name.split('.')[0] for n in tree.body if isinstance(n,ast.Import) for x in n.names}
   self.assertFalse(imported & {'numpy','pandas','sklearn','a6_identities','a6_frozen_controls'})
 def test_unknown_job_never_repeats(self):
  with tempfile.TemporaryDirectory() as d:
   out=pathlib.Path(d);(out/'journals').mkdir();calls=[]
   def fail():calls.append(1);raise ValueError('unknown fit')
   with self.assertRaises(ValueError):w.job(out,'fit/seed/world/1',{'fixed':1},fail)
   with self.assertRaises(FileExistsError):w.job(out,'fit/seed/world/1',{'fixed':1},fail)
   self.assertEqual(len(calls),1);self.assertEqual(len(list((out/'journals').glob('*.STARTED.json'))),1);self.assertFalse(list((out/'journals').glob('*.RESPONSE.json')))
 def test_successful_job_request_response_linked(self):
  with tempfile.TemporaryDirectory() as d:
   out=pathlib.Path(d);(out/'journals').mkdir();self.assertEqual(w.job(out,'test',{},lambda:7),7)
   response=json.loads(next((out/'journals').glob('*.RESPONSE.json')).read_text());self.assertEqual(response['request_SHA'],w.sha(next((out/'journals').glob('*.STARTED.json'))))
 def test_public_worker_authority_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   p=pathlib.Path(d);auth=p/'auth.json';auth.write_text(json.dumps({'secret_SHA':'wrong'}))
   with patch.dict(os.environ,{},clear=True),self.assertRaises(ValueError):w.consume(auth,p,p)
   self.assertFalse(auth.with_suffix('.consumed.json').exists())
 def test_worker_scope_or_source_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   p=pathlib.Path(d);auth=p/'auth.json';a={'secret_SHA':hashlib.sha256(b's').hexdigest(),'parent_pid':-1,'out':str(p),'repo':str(p),'worker_SHA':w.sha(w.__file__)};auth.write_text(json.dumps(a))
   with patch.dict(os.environ,{'A63_PRIVATE_AUTH':'s'}),self.assertRaises(ValueError):w.consume(auth,p,p)
 def test_lowdisk_output_elapsed_no_model(self):
  for defect in ['disk','output','elapsed']:
   with patch.object(g,'sizes',return_value=134217728 if defect=='output' else 0),patch.object(g.shutil,'disk_usage',return_value=types.SimpleNamespace(free=0 if defect=='disk' else 2**31)),self.assertRaises(InterruptedError):g.admission(time.monotonic()-1800 if defect=='elapsed' else time.monotonic())
 def test_nonfinite_or_reset_anchor(self):
  for value in [True,float('inf'),float('nan')]:
   with self.assertRaises(ValueError):g.admission(value)
  with self.assertRaises(InterruptedError):g.admission(time.monotonic()+1)
 def test_once_permanent_canonical(self):
  with tempfile.TemporaryDirectory() as d:
   p=pathlib.Path(d)/'lease';g.once(p,{'key':'x'})
   with self.assertRaises(FileExistsError):g.once(p,{'key':'changed'})
   self.assertEqual(json.loads(p.read_text())['key'],'x')
 def test_combined_output_counts_control_and_terminal_once(self):
  with tempfile.TemporaryDirectory() as d:
   p=pathlib.Path(d);out=p/'out';out.mkdir();control=p/'control';control.mkdir();ledger=p/'ledger';ledger.mkdir()
   (out/'x').write_bytes(b'123');(control/'binding').write_bytes(b'12')
   with patch.object(g,'OUT',out),patch.object(g,'CONTROL',control),patch.object(g,'LEDGER',ledger):
    g.lease_path().write_bytes(b'1');g.lease_path().with_suffix('.terminal.json').write_bytes(b'1234');self.assertEqual(g.sizes(),10)
    (out/'link').symlink_to(control/'binding')
    with self.assertRaises(ValueError):g.sizes()
 def test_worker_authority_consumed_before_import_and_fresh_job_allocation(self):
  src=(ROOT/'economic-atlas/src/a63_full_worker.py').read_text()
  self.assertLess(src.index('authority=consume('),src.index(' import numpy as np'))
  self.assertIn("job(out,f'select/",src);self.assertIn("job(out,f'fit/",src)
 def test_fullscope_not_348_fixed_events(self):
  spec=json.loads((ROOT/'economic-atlas/protocols/A63_NEW_PROSPECTIVE_SYNTHETIC_V1.json').read_text());self.assertEqual(len(spec['seeds'])*len(spec['worlds'])*len(spec['modes'])*len(spec['margin_factors']),210);self.assertEqual(210*23,4830);self.assertEqual(spec['truth_event_expectations_over210configs'],300)
 def test_mocked_guardian_negative_complete_or_preflight_failure(self):
  for preflight_failure in [False,True]:
   with tempfile.TemporaryDirectory() as d:
    root=pathlib.Path(d);out=root/'actual';control=root/'control';control.mkdir();ledger=root/'ledger';ledger.mkdir(mode=0o700);repo=root/'repo';src=repo/'economic-atlas/src';src.mkdir(parents=True);prot=repo/'economic-atlas/protocols';prot.mkdir();(prot/'A63_FULL_ONE_USE_OPERATIONAL_V1.json').write_text('{}');binding=control/'ROOT_BINDING.json';binding.write_text('{}')
    code="""import json
class NativeMac:
 def descendants(self,pid):return []
def resource_preflight(out,native):
 out.mkdir()
 if FAIL:raise RuntimeError('mock native unavailable')
def run_phase(command,out,phase,started,limits,native):
 for name,val in [('runs.json',[{}]*210),('months.json',[{}]*4830),('metrics.json',{'acceptance':'FAIL'}),('manifest.json',{}),('truth.json',[]),('events.json',[])]:
  (out/name).write_text(json.dumps(val))
 return {'state':'COMPLETE','mocked_no_process':True}
""".replace('if FAIL:',f'if {preflight_failure}:')
    (src/'atlas_m1_executor.py').write_text(code)
    with patch.object(g,'OUT',out),patch.object(g,'CONTROL',control),patch.object(g,'LEDGER',ledger),patch.object(g,'validate',return_value=(time.monotonic(),{'economic-atlas/src/a63_full_worker.py':'fake'})),patch.object(g,'admission',return_value=0),patch.object(g.sys,'argv',['guardian','--repo',str(repo),'--binding',str(binding)]):
     if preflight_failure:
      with self.assertRaises(SystemExit):g.main()
     else:g.main()
     terminal=json.loads((out/'guardian-terminal.json').read_text());self.assertFalse(terminal['scientific_pass']);self.assertTrue(g.lease_path().exists())
     self.assertEqual(terminal['state'],'INCONCLUSIVE' if preflight_failure else 'FULL_SUITE_ARTIFACTS_COMPLETE_INDEPENDENT_AUDIT_PENDING')
     with self.assertRaises(ValueError):g.main()

 def test_every_seven_native_fit_and_selected_fit_observed_unchanged(self):
  class Array:
   shape=(2,1);dtype='float64'
   def __init__(self,data):self.data=data
   def tobytes(self,order='C'):return self.data
  X=Array(b'input');calls=[]
  class Estimator:
   def __init__(self,k):self.k=k;self.cluster_centers_=Array(b'centers'+bytes([k]))
   def get_params(self,deep=False):return {'n_clusters':self.k,'n_init':10,'random_state':1632643743+self.k}
   def fit_predict(self,x,*args,**kwargs):calls.append((self.k,x,args,kwargs));return Array(b'labels'+bytes([self.k]))
  original=Estimator.fit_predict
  with tempfile.TemporaryDirectory() as d:
   out=pathlib.Path(d);(out/'journals').mkdir();context={}
   with w.observe_fits(out,context,Estimator):
    values=w.fit_stage(context,'select/seed/world/0',lambda:[Estimator(k).fit_predict(X) for k in range(2,9)],7)
    w.fit_stage(context,'selected/seed/world/0',lambda:Estimator(2).fit_predict(X,None,sample_weight=None),1)
   self.assertIs(Estimator.fit_predict,original);self.assertEqual(len(calls),8);self.assertTrue(all(x[1] is X for x in calls));self.assertEqual(calls[-1][2:],((None,),{'sample_weight':None}))
   starts=list((out/'journals').glob('*.STARTED.json'));responses=list((out/'journals').glob('*.RESPONSE.json'));self.assertEqual(len(starts),8);self.assertEqual(len(responses),8)
   requests=[json.loads(x.read_text())['request'] for x in starts];self.assertTrue(all(x['params']['n_init']==10 for x in requests));self.assertTrue(all(x['input']['tensor_SHA']==hashlib.sha256(b'input').hexdigest() for x in requests))
   self.assertTrue(all(len(json.loads(x.read_text())['result_structure'])==2 for x in responses))
 def test_unknown_native_fit_restores_original_no_response(self):
  class Estimator:
   def get_params(self,deep=False):return {'n_clusters':2,'n_init':10,'random_state':1632643745}
   def fit_predict(self,x):raise RuntimeError('unknown mock fit')
  original=Estimator.fit_predict
  with tempfile.TemporaryDirectory() as d:
   out=pathlib.Path(d);(out/'journals').mkdir();context={}
   with self.assertRaises(RuntimeError):
    with w.observe_fits(out,context,Estimator):w.fit_stage(context,'selected/seed/world/1',lambda:Estimator().fit_predict([1,2]),1)
   self.assertIs(Estimator.fit_predict,original);self.assertEqual(len(list((out/'journals').glob('*.STARTED.json'))),1);self.assertFalse(list((out/'journals').glob('*.RESPONSE.json')))
 def test_lease_journal_file_and_directory_fsync(self):
  for module in [g,w]:
   with tempfile.TemporaryDirectory() as d:
    target=pathlib.Path(d)/'receipt.json'
    original_fsync=os.fsync;calls=[]
    def observed(fd):calls.append(fd);return original_fsync(fd)
    with patch.object(module.os,'fsync',side_effect=observed):module.once(target,{'state':'STARTED'})
    self.assertEqual(len(calls),2)
 def test_sigterm_sigint_unwind_pinned_cleanup_without_real_signals(self):
  import sys
  src=pathlib.Path('/private/tmp/sberindex-official-laws-20261007/economic-atlas/src/atlas_m1_executor.py')
  spec=importlib.util.spec_from_file_location('pinned_mock_guard',src);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
  for signum in [g.signal.SIGTERM,g.signal.SIGINT]:
   handlers={};old={s:g.signal.getsignal(s) for s in [g.signal.SIGTERM,g.signal.SIGINT]}
   class Process:
    pid=987654;returncode=None
    def poll(self):handlers[signum](signum,None)
    def wait(self,timeout=None):self.returncode=-15;return -15
   process=Process();native=types.SimpleNamespace(own_tree_rss=lambda:(100,{process.pid:100}))
   with tempfile.TemporaryDirectory() as d,patch.object(g.signal,'signal',side_effect=lambda sig,handler:handlers.update({sig:handler})),patch.object(g.signal,'setitimer'),patch.object(m.subprocess,'Popen',return_value=process),patch.object(m.os,'killpg') as signals:
    previous=g.install_owned_interrupts();status=m.run_phase(['MOCK_ONLY'],pathlib.Path(d),'mock',time.monotonic(),native=native);g.restore_owned_interrupts(previous)
    self.assertEqual(status['state'],'INCONCLUSIVE_GUARD_EXCEPTION');self.assertEqual(process.returncode,-15);signals.assert_called_once_with(process.pid,g.signal.SIGTERM)
    self.assertEqual(handlers[g.signal.SIGTERM],old[g.signal.SIGTERM]);self.assertEqual(handlers[g.signal.SIGINT],old[g.signal.SIGINT])

 def test_object_tensor_semantic_hash_not_pointer_bytes(self):
  class ObjectArray:
   shape=(2,);dtype='object'
   def tobytes(self,order='C'):raise AssertionError('never hash pointer bytes')
   def tolist(self):return ['A1','A2']
  result=w.result_structure(ObjectArray());self.assertEqual(result['semantic_JSON_SHA'],hashlib.sha256(json.dumps(['A1','A2'],sort_keys=True,allow_nan=False).encode()).hexdigest())

 def test_history_truth_metadata_oracle_and_unsupervised(self):
  # Only evaluates the saved metadata expression from its AST, no science.
  source=(ROOT/'economic-atlas/src/a63_full_worker.py').read_text();tree=ast.parse(source)
  mappings=[n for n in ast.walk(tree) if isinstance(n,ast.Dict) and any(isinstance(k,ast.Constant) and k.value=='truth_consumed_by_fit' for k in n.keys)]
  self.assertEqual(len(mappings),1);node=mappings[0]
  expr=node.values[next(i for i,k in enumerate(node.keys) if isinstance(k,ast.Constant) and k.value=='truth_consumed_by_fit')]
  self.assertIsInstance(expr,ast.Compare);self.assertIsInstance(expr.left,ast.Name);self.assertEqual(expr.left.id,'mode');self.assertEqual(expr.comparators[0].value,'oracle')
  for mode,expected in [('oracle',True),('unsupervised',False)]:self.assertEqual(mode==expr.comparators[0].value,expected)

if __name__=='__main__':unittest.main()
