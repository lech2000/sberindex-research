"""Operational control-flow tests only; mocks never stand in for scientific evidence."""
from pathlib import Path
import importlib.util,json,tempfile,types,unittest,numpy as np,os,time
from unittest.mock import patch
P=Path(__file__).resolve().parents[1];spec=importlib.util.spec_from_file_location('pf',P/'src/atlas_m4_preflight.py');pf=importlib.util.module_from_spec(spec);spec.loader.exec_module(pf)
class PreflightTests(unittest.TestCase):
 def test_frozen_exact_size_disjoint_seed_no_budget_claim(self):
  p=json.loads((P/'protocols/M4_OPERATIONAL_PREFLIGHT_V1.json').read_text());self.assertEqual(pf.sha(P/'protocols/M4_OPERATIONAL_PREFLIGHT_V1.json'),pf.PREFLIGHT_SHA)
  self.assertEqual((p['n'],p['R'],p['channel'],p['k'],p['seed'],p['null_replicates']),(297,1,'B',40,999999,99))
  self.assertEqual(p['resource_limits']['wall_seconds'],600)
 def stubs(self,fail=False):
  calls=[];spectra=[]
  def atomic(p,r):Path(p).write_text(json.dumps(r))
  def world(*args):calls.append(('world',args));return None
  def graph(*args):return np.eye(3)
  def null(W,seed):
   calls.append(('null',seed))
   if fail and len(calls)==4:raise RuntimeError('injected null failure')
   return W,{'seed':seed,'complete':True,'successful_swaps':10,'attempts':15}
  def spectrum(W,tau):spectra.append(tau);return {'status':'COMPUTED','m':1,'raw_gap':.3},np.ones(3),np.eye(3)
  m=types.SimpleNamespace(world=world,graph=graph,degree_null=null,atomic=atomic)
  g=types.SimpleNamespace(NativeMac=lambda:types.SimpleNamespace(rss=lambda pid:12345))
  return m,g,types.SimpleNamespace(spectrum=spectrum),calls,spectra
 def test_all99_same_method_operations_preserved_no_qualification(self):
  with tempfile.TemporaryDirectory() as t:
   m,g,m1,calls,spectra=self.stubs();p=json.loads((P/'protocols/M4_OPERATIONAL_PREFLIGHT_V1.json').read_text());out=Path(t)/'fresh';pf.worker(m,g,p,m1,out)
   r=json.loads((out/'measurement.json').read_text());self.assertEqual(calls[0],('world',(297,1,'NONE',999999)));self.assertEqual([s for kind,s in calls if kind=='null'],list(range(99999900,99999999)))
   self.assertEqual(len(spectra),100);self.assertEqual(r['completed_nulls'],99);self.assertFalse(r['scientific_pass']);self.assertNotIn('sig_star',r)
 def test_exception_retains_exact_prefix_no_retry(self):
  with tempfile.TemporaryDirectory() as t:
   m,g,m1,calls,spectra=self.stubs(True);p=json.loads((P/'protocols/M4_OPERATIONAL_PREFLIGHT_V1.json').read_text());out=Path(t)/'fresh'
   with self.assertRaisesRegex(RuntimeError,'injected'):pf.worker(m,g,p,m1,out)
   r=json.loads((out/'measurement.json').read_text());self.assertEqual(r['state'],'INCONCLUSIVE_OPERATIONAL_EXCEPTION');self.assertEqual(r['completed_nulls'],2);self.assertEqual(len(spectra),3)
 def test_existing_output_rejected_before_computation(self):
  with tempfile.TemporaryDirectory() as t:
   m,g,m1,calls,spectra=self.stubs();p=json.loads((P/'protocols/M4_OPERATIONAL_PREFLIGHT_V1.json').read_text())
   with self.assertRaises(FileExistsError):pf.worker(m,g,p,m1,Path(t))
   self.assertEqual(calls,[])
class DispatchTests(unittest.TestCase):
 def test_public_worker_rejected_before_numerical_setup(self):
  with patch.dict(os.environ,{},clear=True),patch.object(pf.sys,'argv',['probe','--worker','--repo','/nonexistent','--outdir','/nonexistent/measurement-v1']),patch.object(pf,'setup') as setup:
   with self.assertRaisesRegex(ValueError,'unauthorized'):pf.main()
   setup.assert_not_called()
 def fixture(self,t):
  root=Path(t);repo=root/'repo';out=root/'out';out.mkdir();(repo/'economic-atlas/src').mkdir(parents=True)
  guard=repo/'economic-atlas/src/atlas_m1_executor.py';guard.write_text('fake stdlib guard')
  proof=out/'native-preflight';proof.mkdir();(proof/'resource-preflight.json').write_text(json.dumps({'state':'PASS'}))
  authority=pf.create_authority(out,repo,time.monotonic(),{'state':'PASS'});args=types.SimpleNamespace(repo=repo,outdir=out/'measurement-v1',dispatch_authority=authority)
  fake=types.SimpleNamespace(NativeMac=lambda:types.SimpleNamespace(children=lambda pid:[os.getpid()]))
  return args,guard,fake
 def test_bound_authority_consumed_once_and_worker_pid_recorded(self):
  with tempfile.TemporaryDirectory() as t,patch.dict(os.environ,{},clear=True):
   args,guard,fake=self.fixture(t);token=os.environ[pf.DISPATCH_ENV]
   with patch.object(pf,'GUARD_SHA',pf.sha(guard)),patch.object(pf,'load',return_value=fake),patch.object(pf.os,'getppid',return_value=os.getpid()),patch.object(pf.os,'getpgrp',return_value=os.getpid()):
    pf.consume_authority(args)
    self.assertFalse(args.dispatch_authority.exists());r=json.loads(args.dispatch_authority.with_name('dispatch-consumed.json').read_text());self.assertEqual(r['owned_worker_pid'],os.getpid())
    os.environ[pf.DISPATCH_ENV]=token
    with self.assertRaises(FileNotFoundError):pf.consume_authority(args)
 def test_wrong_parent_output_source_expiry_or_token_rejected(self):
  for mode in ('parent','output','source','expiry','token','nativeproof'):
   with tempfile.TemporaryDirectory() as t,patch.dict(os.environ,{},clear=True):
    args,guard,fake=self.fixture(t);data=json.loads(args.dispatch_authority.read_text())
    if mode=='parent':data['parent_pid']=-1
    if mode=='source':data['executor_sha256']='wrong'
    if mode=='expiry':data['deadline_monotonic']=0
    if mode=='token':os.environ[pf.DISPATCH_ENV]='wrong'
    if mode=='output':args.outdir=args.outdir.with_name('other')
    if mode=='nativeproof':(args.dispatch_authority.parent/'native-preflight/resource-preflight.json').write_text('{}')
    args.dispatch_authority.write_text(json.dumps(data))
    with patch.object(pf.os,'getppid',return_value=os.getpid()):
     with self.assertRaises(ValueError):pf.consume_authority(args)
    self.assertFalse(args.dispatch_authority.with_name('dispatch-consumed.json').exists())
 def test_authority_requires_native_PASS_and_fresh_one_time_creation(self):
  with tempfile.TemporaryDirectory() as t,patch.dict(os.environ,{},clear=True):
   out=Path(t)
   with self.assertRaisesRegex(ValueError,'native'):pf.create_authority(out,out,time.monotonic(),{'state':'FAIL'})
   args,guard,fake=self.fixture(t)
   with self.assertRaises(FileExistsError):pf.create_authority(args.outdir.parent,args.repo,time.monotonic(),{'state':'PASS'})
 def test_owned_session_and_known_child_required_before_imports(self):
  with tempfile.TemporaryDirectory() as t,patch.dict(os.environ,{},clear=True):
   args,guard,fake=self.fixture(t)
   with patch.object(pf,'GUARD_SHA',pf.sha(guard)),patch.object(pf,'load',return_value=fake),patch.object(pf.os,'getppid',return_value=os.getpid()),patch.object(pf.os,'getpgrp',return_value=-1):
    with self.assertRaisesRegex(ValueError,'isolated native-known'):pf.consume_authority(args)
if __name__=='__main__':unittest.main()
