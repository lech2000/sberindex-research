import importlib.util,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.dont_write_bytecode=True
D=Path(__file__).resolve().parents[1];sys.path.insert(0,str(D/'economic-atlas/src'))
import atlas_m1_recovery_keys as r
P=D/'economic-atlas/protocols/M1_NUMERICAL_RECOVERY_V1.json'
class Recovery(unittest.TestCase):
 def test_full_exact334_and26_no_fit(self):
  p=r.read_protocol(P);f=json.loads(Path('/private/tmp/atlas-m1-frozen-execution-view-20261007/economic-atlas/protocols/M1_PROSPECTIVE_V1.json').read_text());out,keys=r.ancestral_records(p,f)
  self.assertEqual(sum(len(c['calibration'])+len(c['held']) for c in out.values()),334);self.assertEqual(len(keys),26);self.assertEqual(keys[0],['held',40,4,20261122]);self.assertTrue(all(c['fit']['sig_star'] is None for c in out.values()))
 def test_ancestral_hash_change_rejected_without_reads_or_science(self):
  p=r.read_protocol(P);p['ancestral_progress']['10']['SHA']='changed'
  with self.assertRaises(ValueError):r.ancestral_records(p,{})
 def test_journal_started_before_dispatch_response_after(self):
  with tempfile.TemporaryDirectory() as d:
   j=r.Journal(Path(d)/'fresh',{'fixture':True});key=['held',40,4,1];folder=j.out/r.token(key)
   def fun():self.assertTrue((folder/'STARTED.json').exists());self.assertFalse((folder/'RESPONSE.json').exists());return {'raw_gap':None}
   self.assertEqual(j.dispatch(key,fun,lambda:None),{'raw_gap':None});self.assertTrue((folder/'RESPONSE.json').exists())
 def test_UNKNOWN_error_never_autoretry(self):
  with tempfile.TemporaryDirectory() as d:
   j=r.Journal(Path(d)/'fresh',{});calls=[]
   def fail():calls.append(1);raise RuntimeError('mock failure')
   with self.assertRaises(RuntimeError):j.dispatch(['key'],fail,lambda:None)
   with self.assertRaises(FileExistsError):j.dispatch(['key'],fail,lambda:None)
   self.assertEqual(calls,[1]);self.assertTrue((j.out/r.token(['key'])/'ERROR.json').exists())
 def test_guard_failure_before_started_or_dispatch(self):
  with tempfile.TemporaryDirectory() as d:
   j=r.Journal(Path(d)/'fresh',{});calls=[]
   def stop():raise RuntimeError('STOP resource')
   with self.assertRaises(RuntimeError):j.dispatch(['key'],lambda:calls.append(1),stop)
   self.assertEqual(calls,[]);self.assertEqual(list(j.out.iterdir()),[])
 def test_no_alternate_namespace_resume(self):
  with tempfile.TemporaryDirectory() as d:
   j=r.Journal(Path(d)/'fresh',{})
   with self.assertRaises(FileExistsError):r.Journal(j.out,{})
 def test_EVD_full_dense_mock_no_real_eigen(self):
  import numpy as np
  import atlas_m1_evd_engine as e
  W=np.ones((3,3))-np.eye(3)
  with patch.object(e,'eigh',return_value=(np.array([-.5,-.5,1.]),np.eye(3))) as solve:
   stats,vals,vec=e.spectrum(W)
  self.assertEqual(solve.call_args.kwargs,{'check_finite':False,'driver':'evd'});self.assertEqual(solve.call_args.args[0].shape,(3,3));self.assertEqual(vec.shape,(3,3));self.assertEqual(stats['n'],3)
 def test_eigen_error_no_fallback(self):
  import numpy as np
  import atlas_m1_evd_engine as e
  with patch.object(e,'eigh',side_effect=RuntimeError('mock error')) as solve:
   with self.assertRaises(RuntimeError):e.spectrum(np.ones((3,3))-np.eye(3))
  self.assertEqual(solve.call_count,1)
 def test_engine_full_calibration_disabled(self):
  import atlas_m1_evd_engine as e
  with self.assertRaises(RuntimeError):e.calibrate()
if __name__=='__main__':unittest.main()
