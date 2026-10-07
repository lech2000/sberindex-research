from pathlib import Path
import importlib.util,json,os,sys,tempfile,time,unittest,subprocess,signal,select
S=Path(__file__).resolve().parents[1]/'src/atlas_m1_executor.py';spec=importlib.util.spec_from_file_location('guard',S);g=importlib.util.module_from_spec(spec);spec.loader.exec_module(g)
class GuardTests(unittest.TestCase):
 def test_native_child_grandchild_resource_preflight_and_cleanup(self):
  with tempfile.TemporaryDirectory() as t:
   r=g.resource_preflight(Path(t)/'probe')
   self.assertEqual(r['state'],'PASS');self.assertEqual(len(r['expected_child_grandchild']),2)
   self.assertTrue(r['immediate_child_reaped']);self.assertEqual(r['expected_descendants_remaining'],[])
   self.assertGreater(r['aggregate_RSS_bytes'],0)
   self.assertTrue(all(int(r['RSS_bytes_by_knownPID'][pid])>0 for pid in r['expected_child_grandchild']))
 def test_native_preflight_measurement_failure_stops_before_method_and_cleans(self):
  class Bad(g.NativeMac):
   def own_tree_rss(self):raise PermissionError('injected native RSS failure')
  with tempfile.TemporaryDirectory() as t:
   path=Path(t)/'probe'
   with self.assertRaises(RuntimeError):g.resource_preflight(path,Bad())
   r=json.loads((path/'resource-preflight.json').read_text())
   self.assertEqual(r['state'],'INCONCLUSIVE_RESOURCE_PREFLIGHT');self.assertEqual(r['method_calls'],0)
   self.assertTrue(r['immediate_child_reaped']);self.assertEqual(r['expected_descendants_remaining'],[])
 def test_foreground_phase_limits_only_own_processgroup(self):
  with tempfile.TemporaryDirectory() as t:
   limits=dict(g.LIMITS);limits.update(wall=.15,sample=.02,disk_sample=0,free=0)
   r=g.run_phase([sys.executable,'-c','import time;time.sleep(20)'],t,'fixture',time.monotonic(),limits)
   self.assertEqual(r['state'],'INCONCLUSIVE_WALL_LIMIT');self.assertIsNotNone(r['exit_code'])
   self.assertNotIn(r['pid'],g.NativeMac().descendants(os.getpid()))
   self.assertTrue((Path(t)/'fixture-terminal.json').exists())
 def test_aggregate_RSS_failure_stops(self):
  with tempfile.TemporaryDirectory() as t:
   limits=dict(g.LIMITS);limits.update(rss=1,sample=.02,disk_sample=0,free=0)
   r=g.run_phase([sys.executable,'-c','import time;memory=bytearray(100000);time.sleep(20)'],t,'rssfixture',time.monotonic(),limits)
   self.assertEqual(r['state'],'INCONCLUSIVE_AGGREGATE_RSS_LIMIT');self.assertGreater(r['peak_aggregate_RSS_bytes'],1)
 def test_phase_success_preserves_log_and_atomic_terminal(self):
  with tempfile.TemporaryDirectory() as t:
   limits=dict(g.LIMITS);limits.update(sample=.02,free=0)
   r=g.run_phase([sys.executable,'-c','print("fixture success")'],t,'success',time.monotonic(),limits)
   self.assertEqual(r['state'],'COMPLETE');self.assertEqual(r['exit_code'],0)
   self.assertIn('fixture success',(Path(t)/'success.log').read_text())
   self.assertEqual(json.loads((Path(t)/'success-terminal.json').read_text())['state'],'COMPLETE')
   self.assertFalse(list(Path(t).glob('*.tmp')))
 def test_input_mismatch_rejected_before_runroot_creation(self):
  with tempfile.TemporaryDirectory() as t:
   with self.assertRaises((ValueError,FileNotFoundError)):g.check_inputs(t)
   self.assertEqual(list(Path(t).iterdir()),[])
 def test_inconclusive_and_negative_files_in_manifest(self):
  with tempfile.TemporaryDirectory() as t:
   root=Path(t);(root/'abstention.json').write_text('{"state":"ABSTAIN_M1"}');(root/'failure.log').write_text('failure retained')
   hashes=g.manifest(root)
   self.assertEqual(set(hashes),{'abstention.json','failure.log'})
   self.assertEqual(hashes['failure.log'],g.sha(root/'failure.log'))
 def test_operational_limits_match_prospective_plan(self):
  p=json.loads((Path(__file__).resolve().parents[1]/'protocols/M1_OPERATIONAL_EXECUTION_V1.json').read_text())
  self.assertEqual(g.LIMITS['rss'],p['aggregate_own_tree_RSS_bytes']);self.assertEqual(g.LIMITS['wall'],77881)
  self.assertEqual(g.SOURCE_SHA,p['source_sha256']);self.assertEqual(g.PROTOCOL_SHA,p['scientific_protocol_sha256'])
 def test_monitor_exception_cleans_own_child_and_preserves_failure(self):
  class Bad(g.NativeMac):
   def own_tree_rss(self):raise PermissionError('injected monitor error')
  with tempfile.TemporaryDirectory() as t:
   r=g.run_phase([sys.executable,'-c','import time;time.sleep(20)'],t,'monitorfailure',time.monotonic(),native=Bad())
   self.assertEqual(r['state'],'INCONCLUSIVE_GUARD_EXCEPTION')
   self.assertNotIn(r['pid'],g.NativeMac().descendants(os.getpid()))
   self.assertIn('PermissionError',r['error'])
 def test_output_budget_stops_without_deleting_failure_files(self):
  with tempfile.TemporaryDirectory() as t:
   limits=dict(g.LIMITS);limits.update(output=1,disk_sample=0,free=0,sample=.02)
   (Path(t)/'retained.json').write_text('negative result preserved')
   r=g.run_phase([sys.executable,'-c','import time;time.sleep(20)'],t,'outputbudget',time.monotonic(),limits)
   self.assertEqual(r['state'],'INCONCLUSIVE_OUTPUT_LIMIT')
   self.assertEqual((Path(t)/'retained.json').read_text(),'negative result preserved')
 def test_SIGTERM_guard_cleanup_reaps_only_its_worker_group(self):
  with tempfile.TemporaryDirectory() as t:
   code="import importlib.util,signal,pathlib,sys,time,json; s=importlib.util.spec_from_file_location('g',sys.argv[1]);g=importlib.util.module_from_spec(s);s.loader.exec_module(g);signal.signal(signal.SIGTERM,g.stop_requested);r=g.run_phase([sys.executable,'-c','import time;time.sleep(20)'],sys.argv[2],'interrupt',time.monotonic());print(json.dumps(r),flush=True)"
   p=subprocess.Popen([sys.executable,'-c',code,str(S),t],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True)
   try:
    self.assertTrue(select.select([p.stdout],[],[],5)[0])
    first=json.loads(p.stdout.readline());worker=first['pid']
    p.send_signal(signal.SIGTERM);stdout,stderr=p.communicate(timeout=5)
    self.assertEqual(p.returncode,0);r=json.loads(stdout)
    self.assertEqual(r['state'],'INCONCLUSIVE_GUARD_EXCEPTION');self.assertIn('InterruptedError',r['error'])
    self.assertNotIn(worker,g.NativeMac().descendants(os.getpid()))
   finally:
    if p.poll() is None:g.cleanup_owned_group(p)
    p.stdout.close();p.stderr.close()
if __name__=='__main__':unittest.main()
