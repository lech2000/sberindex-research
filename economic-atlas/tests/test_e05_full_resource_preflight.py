"""Hermetic SOURCE checks only; never numerical imports, workers or native calls."""
import importlib.util,pathlib,tempfile,unittest,datetime,sys
from unittest.mock import patch
ROOT=pathlib.Path(__file__).resolve().parents[1]
sp=importlib.util.spec_from_file_location('preflight',ROOT/'src/e05_full_resource_preflight.py');m=importlib.util.module_from_spec(sp);sp.loader.exec_module(m)
def spec():return {'whole_seconds':600,'final_reserve_seconds':30,'cleanup_seconds':20,'poll_seconds':.2,'CPU_threads':1,'RSS_bytes':1073741824,'minimum_free_bytes':1073741824,'output_bytes':134217728,'receipt_reserve_bytes':8192,'absolute_deadline_UTC':'2099-01-01T00:00:00Z','external_whole_supervisor_source_accepted':True,'original_anchor':m.ENTRY}
class Checks(unittest.TestCase):
 def test_public_refusal(self):
  with self.assertRaises(PermissionError):m.execute(execution_authorized=True)
 def test_no_scientific_imports_at_load(self):
  import ast
  t=ast.parse((ROOT/'src/e05_full_resource_preflight.py').read_text())
  imports=[n for n in t.body if isinstance(n,(ast.Import,ast.ImportFrom))]
  self.assertFalse(any(x.name.split('.')[0]in ['numpy','scipy','sklearn','pandas','pyarrow']for n in imports for x in n.names))
 def test_runtime_budget_not_default(self):
  with self.assertRaises(KeyError):m.validate_spec({})
 def test_exact_resource_caps(self):
  for k in ['RSS_bytes','minimum_free_bytes','output_bytes']:
   s=spec();s[k]+=1
   with self.assertRaises(ValueError):m.validate_spec(s)
 def test_bool_nonfinite_limits(self):
  for v in [True,float('inf'),float('nan'),-1,0]:
   s=spec();s['whole_seconds']=v
   with self.assertRaises(ValueError):m.validate_spec(s)
 def test_reserve_no_extra_clock(self):
  s=spec();s['cleanup_seconds']=31
  with self.assertRaises(ValueError):m.validate_spec(s)
 def test_cpu_boolean_reject(self):
  s=spec();s['CPU_threads']=True
  with self.assertRaises(ValueError):m.validate_spec(s)
 def test_supervisor_required(self):
  s=spec();s['external_whole_supervisor_source_accepted']=False
  with self.assertRaises(ValueError):m.validate_spec(s)
 def test_deadline_requires_utc(self):
  s=spec();s['absolute_deadline_UTC']='2099-01-01T00:00:00+03:00'
  with self.assertRaises(ValueError):m.validate_spec(s)
 def test_full_45504_scope(self):self.assertEqual(m.verify_fixture_keys(m.fixture_keys()),45504);self.assertEqual(225*45504,10238400)
 def test_missing_fullsize_key(self):
  with self.assertRaises(ValueError):m.verify_fixture_keys(iter(list(m.fixture_keys())[:-1]))
 def test_duplicate_fullsize_key(self):
  rows=list(m.fixture_keys());rows[-1]=rows[-2]
  with self.assertRaises(ValueError):m.verify_fixture_keys(rows)
 def test_extra_fullsize_key(self):
  with self.assertRaises(ValueError):m.verify_fixture_keys(list(m.fixture_keys())+[(0,0)])
 def guard(self,clock=lambda:1,rss=lambda:1,free=lambda:2**31):return m.SampledGuard(spec(),0,[],rss,free,clock)
 def test_elapsed_boundary(self):
  with self.assertRaises(InterruptedError):self.guard(clock=lambda:570)()
 def test_anchor_future(self):
  with self.assertRaises(InterruptedError):self.guard(clock=lambda:-1)()
 def test_resource_boundaries(self):
  self.guard(rss=lambda:2**30,free=lambda:2**30)()
  for args in [dict(rss=lambda:2**30+1),dict(free=lambda:2**30-1)]:
   with self.assertRaises(InterruptedError):self.guard(**args)()
 def test_output_no_shrink(self):
  with patch.object(m,'bytes_owned',return_value=134217728):
   with self.assertRaises(InterruptedError):self.guard()()
 def test_slow_guard_clock_no_reset(self):
  it=iter([1,571]);g=self.guard(clock=lambda:next(it))
  with self.assertRaises(InterruptedError):g()
  self.assertFalse(g.active)
 def test_nonreentrant_observer(self):
  g=self.guard();g.rss=lambda:g()
  with self.assertRaises(RuntimeError):g()
  self.assertFalse(g.active)
 def test_durable_exclusive_replay(self):
  with tempfile.TemporaryDirectory()as d:
   p=pathlib.Path(d)/'lease.json';m.once(p,{'key':m.KEY})
   with self.assertRaises(FileExistsError):m.once(p,{'key':'retry'})
 def test_symlink_reject(self):
  with tempfile.TemporaryDirectory()as d:
   p=pathlib.Path(d);(p/'data').write_text('x');(p/'link').symlink_to(p/'data')
   with self.assertRaises(ValueError):m.bytes_owned([p])
 def test_exactly_two_pairs_static(self):
  text=(ROOT/'src/e05_full_resource_preflight.py').read_text();self.assertIn("('monthly1896_gamma0','supra45504_gamma2')",text);self.assertIn('method._partition(selected,5,seed',text);self.assertNotIn('method._partitions(',text)
if __name__=='__main__':unittest.main()
