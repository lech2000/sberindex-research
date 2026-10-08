import ast,hashlib,importlib.util,json,pathlib,tempfile,types,unittest,os
from unittest.mock import patch
P=pathlib.Path;ROOT=P(__file__).resolve().parents[1]
def load(name):
 s=importlib.util.spec_from_file_location(name,ROOT/'economic-atlas/src'/name);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
c=load('a63_root_controller_v2.py');g=load('a63_full_guardian_v2.py')
def handler(module,name,callback,signal):
 node=next(n for n in ast.walk(ast.parse(P(module.__file__).read_text())) if isinstance(n,ast.FunctionDef) and n.name==name)
 factory=ast.parse('def factory():\n checking=False\n return None').body[0];factory.body=[factory.body[0],node,ast.Return(ast.Name(id=name,ctx=ast.Load()))];tree=ast.fix_missing_locations(ast.Module(body=[factory],type_ignores=[]));ns={'signal':signal,'native':None,'anchor':300.,'guard':callback,'admission':callback};exec(compile(tree,'<actual_v2_handler_AST>','exec'),ns);return ns['factory']()
class Toolkit(unittest.TestCase):
 def pair(self,throw=False):
  for module,name,field in [(c,'watchdog','output_size'),(g,'alarm','sizes')]:
   state={'active':True,'calls':0,'scan':0};f=None;timer=[]
   def set_timer(*args):state['active']=bool(args[1]);timer.append(args)
   fake=types.SimpleNamespace(setitimer=set_timer,ITIMER_REAL=0)
   def scan():
    state['scan']+=1
    if state['active']:f()
    # Pending callback even after cancellation is rejected by busy flag.
    f()
    if throw:raise InterruptedError('unchanged resource STOP')
    return 0
   def guard(*args,**kwargs):
    state['calls']+=1
    if module is c:return c.guard(300.,native=None)
    return g.admission(300.)
   f=handler(module,name,guard,fake)
   with patch.object(module.time,'monotonic',return_value=2000.),patch.object(module,field,side_effect=scan),patch.object(module.shutil,'disk_usage',return_value=types.SimpleNamespace(free=2**31)),patch.object(module.resource,'getrusage',return_value=types.SimpleNamespace(ru_maxrss=1)):
    if throw:
     with self.assertRaises(InterruptedError):f()
    else:f()
   self.assertEqual(state['calls'],1);self.assertEqual(state['scan'],1);self.assertEqual(state['active'],not throw);self.assertEqual(timer[0],(0,0));self.assertNotIn('ENTRY',ast.unparse(next(n for n in ast.walk(ast.parse(P(module.__file__).read_text())) if isinstance(n,ast.FunctionDef) and n.name==name)))
 def test_pair_slow_guard_no_reentry_original_elapsed_preserved(self):self.pair()
 def test_pair_failure_keeps_timer_disabled_no_new_allowance(self):self.pair(throw=True)
 def test_old_consumed_namespaces_keys_refuse_before_validation_or_process(self):
  for kind in ['CONTROL','OUT','model','controller']:
   with tempfile.TemporaryDirectory() as d:
    p=P(d);control=p/'control';out=p/'out';ledger=p/'ledger';ledger.mkdir()
    with patch.object(c,'CONTROL',control),patch.object(c,'OUT',out),patch.object(c,'LEDGER',ledger),patch.object(c,'guard',return_value=1700),patch.object(c,'validate') as validate,patch.object(c.signal,'signal'),patch.object(c.signal,'setitimer'):
     target={'CONTROL':control,'OUT':out,'model':c.lease(''),'controller':c.lease('-controller')}[kind]
     if kind in ['CONTROL','OUT']:target.mkdir()
     else:target.write_text('immutable consumed operation')
     before=target.read_bytes() if target.is_file() else None;result=c.execute(p,popen=lambda *a,**k:self.fail('no process'));self.assertIn('existing consumed operation',result['error']);validate.assert_not_called()
     if before is not None:self.assertEqual(target.read_bytes(),before)
     self.assertFalse(result['scientific_pass'])
 def test_worker_numeric_bytes_and_pinchain_consistent_source_only(self):
  old=(P(os.environ.get('A63_REVIEW_BASE_REPO',str(ROOT)))/'economic-atlas/src/a63_full_worker.py').read_text();worker=(ROOT/'economic-atlas/src/a63_full_worker_v2.py').read_text();self.assertEqual(worker.replace('A63_WATCHDOG_SOURCE_FIX_V2.json','A63_FULL_ONE_USE_OPERATIONAL_V1.json'),old)
  opfile=ROOT/c.OP;op=json.loads(opfile.read_text());self.assertEqual(hashlib.sha256(opfile.read_bytes()).hexdigest(),c.OP_SHA);self.assertEqual(len(op['pins']),14);self.assertEqual(op['one_use_key'],c.KEY);self.assertEqual(c.KEY,g.KEY);self.assertEqual(c.OUT,g.OUT);self.assertEqual(c.CONTROL,g.CONTROL);self.assertEqual(g.OP,c.OP)
  for n in ['a63_full_worker_v2.py','a63_full_guardian_v2.py']:
   p=ROOT/'economic-atlas/src'/n;self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(),op['pins']['economic-atlas/src/'+n])
  self.assertEqual(op['execution_policy'],'EXPLICIT_NEW_PROSPECTIVE_SPEC_REQUIRED');self.assertFalse(op['science_resume_or_retry_authorized']);self.assertEqual(c.LIMIT,1800);self.assertEqual(c.WORK,1770);self.assertEqual(g.LIMITS['wall'],1770)
  self.assertIn('source-only watchdog toolkit cannot execute',P(c.__file__).read_text());self.assertIn('source-only watchdog toolkit cannot execute',P(g.__file__).read_text())
if __name__=='__main__':unittest.main()
