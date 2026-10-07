"""Known-PID lifecycle/control-flow tests; no real process signals or science runs."""
from pathlib import Path
import importlib.util,unittest,tempfile,types,json,hashlib,os,signal,time
P=Path(__file__).resolve().parents[1]/'src/atlas_m1_adopt_monitor.py';spec=importlib.util.spec_from_file_location('adopt',P);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class AdoptTests(unittest.TestCase):
 def p(self):return {'original_pid':53084,'original_pgid':53084,'expected_birth_utc_second':'2026-10-07T15:47:45+00:00','original_wall_start_utc':'2026-10-07T15:47:45.854058+00:00','limits':{'RSS_bytes':1073741824,'combined_output_bytes_max':268435456,'free_disk_bytes_min':1073741824,'wall_seconds_from_original_start':77881}}
 def info(self):return {'pid':53084,'ppid':1,'uid':os.getuid(),'pgid':53084,'birth_sec':int(m.datetime.datetime.fromisoformat(self.p()['expected_birth_utc_second']).timestamp()),'birth_usec':123456,'status':2}
 def native(self,info=None):return types.SimpleNamespace(info=lambda pid:self.info() if info is None else info,argv=lambda pid:['python','fixed-source','--phase','calibrate'])
 def test_sdk_bsd_layout_and_microsecond_identity(self):
  raw=bytearray(136)
  for off,val in ((4,2),(12,53084),(16,1),(20,501),(100,53084)):raw[off:off+4]=val.to_bytes(4,'little')
  raw[120:128]=(123456789).to_bytes(8,'little');raw[128:136]=(987654).to_bytes(8,'little');info=m.parse_bsd(bytes(raw));self.assertEqual((info['pid'],info['pgid'],info['birth_sec'],info['birth_usec']),(53084,53084,123456789,987654))
  with self.assertRaises(ValueError):m.parse_bsd(bytes(raw[:96]))
 def test_known_pid_argv_parse_excludes_environment(self):
  raw=(4).to_bytes(4,'little',signed=True)+b'/python\0\0python\0source.py\0--phase\0calibrate\0SECRET=not-output\0'
  self.assertEqual(m.parse_args(raw),['python','source.py','--phase','calibrate'])
 def test_uid_pgid_birth_ppid_and_exact_command_checked(self):
  cmd=['python','fixed-source','--phase','calibrate'];p=self.p();base=self.info()
  self.assertEqual(m.verify_live(self.native(),p,cmd),base)
  for key in ('uid','pgid','birth_sec','ppid'):
   altered={**base,key:base[key]+1}
   with self.assertRaises(ValueError):m.verify_live(self.native(altered),p,cmd)
  with self.assertRaises(ValueError):m.verify_live(self.native(),p,cmd+['--resume'])
 def test_microsecond_pidreuse_no_signal(self):
  base=self.info();new={**base,'birth_usec':base['birth_usec']+1};sent=[]
  with self.assertRaisesRegex(ValueError,'PIDreuse'):m.stop_verified_original(self.native(new),self.p(),['python','fixed-source','--phase','calibrate'],m.identity(base),kill=lambda *args:sent.append(args),sleep=lambda x:None)
  self.assertEqual(sent,[])
 def test_stop_targets_only_verified_original_pid(self):
  base=self.info();calls=[];state={'live':True}
  native=self.native();native.info=lambda pid:base if state['live'] else None
  def kill(pid,sig):calls.append((pid,sig));state['live']=False
  result=m.stop_verified_original(native,self.p(),['python','fixed-source','--phase','calibrate'],m.identity(base),kill=kill,sleep=lambda x:None)
  self.assertEqual(calls,[(53084,signal.SIGTERM)]);self.assertEqual(len(result),1)
 def test_instrumentation_failure_never_signals(self):
  native=self.native();native.info=lambda pid:(_ for _ in ()).throw(PermissionError('native denied'));sent=[]
  with self.assertRaises(PermissionError):m.stop_verified_original(native,self.p(),['python','fixed-source','--phase','calibrate'],m.identity(self.info()),kill=lambda *a:sent.append(a))
  self.assertEqual(sent,[])
 def test_wall_anchor_not_reset_at_adoption(self):
  p=self.p();origin=m.datetime.datetime.fromisoformat(p['original_wall_start_utc']).timestamp();self.assertEqual(m.elapsed(p,lambda:origin+77882),77882)
 def fixture(self,t):
  root=Path(t);view=root/'view';run=root/'run';out=root/'watch';(view/'economic-atlas/protocols').mkdir(parents=True);(run/'calibrate-v1').mkdir(parents=True);out.mkdir()
  frozen={'calibration_seeds':list(range(20261008,20261018)),'validation_seeds':list(range(20261108,20261128)),'shuffle_seed_base':20261208};(view/'economic-atlas/protocols/M1_PROSPECTIVE_V1.json').write_text(json.dumps(frozen))
  result={'n':1896,'d':5,'input_sha256':{'panel':'panelSHA','A5_mask':'maskSHA'},'settings_sha256':hashlib.sha256(json.dumps(frozen,sort_keys=True).encode()).hexdigest(),'results':{}}
  for k in (10,20,40):
   records=lambda seeds:[{'R':R,'seed':seed,'m':R,'sig':2.,'raw_gap':.3,'status':'COMPUTED'} for R in (1,3,4,5) for seed in seeds]
   held=records(frozen['validation_seeds'])
   for x in held:x.update(verdict='INCONCLUSIVE_CALIBRATION',shuffle_raw_gaps=[.1]*99,shuffle_invalid_seeds=[])
   result['results'][str(k)]={'n':1896,'d':5,'k':k,'fit':{'sig_star':None},'method_quality':'FAIL_OR_INCONCLUSIVE_FIXED_CONTROLS','calibration':records(frozen['calibration_seeds']),'held':held}
  p={**self.p(),'frozen_view':str(view),'source_sha256':'codeSHA','protocol_sha256':'protocolSHA'};inputs={'source':'codeSHA','protocol':'protocolSHA','panel':'panelSHA','A5_mask':'maskSHA'}
  self.save(run,p,result);return p,inputs,view,run,out,result
 def save(self,run,p,r):
  file=run/'calibrate-v1/result.json';file.write_text(json.dumps(r));(file.parent/'manifest.json').write_text(json.dumps({'code_sha256':p['source_sha256'],'protocol_sha256':p['protocol_sha256'],'files_sha256':{'result.json':m.sha(file)}}))
 def test_complete_actual_negative_artifact_not_scientific_pass(self):
  with tempfile.TemporaryDirectory() as t:
   p,inputs,view,run,out,r=self.fixture(t);proof=m.completion(run,p,inputs);self.assertFalse(proof['scientific_pass']);self.assertFalse(proof['continuous_old_guard_coverage']);self.assertIsNone(proof['actual_old_child_exit_code']);self.assertEqual(set(proof['quality_by_k'].values()),{'FAIL_OR_INCONCLUSIVE_FIXED_CONTROLS'})
 def test_partial_duplicates_and_nonfinite_nulls_block_replay(self):
  for mode in ('partial','duplicate','nullgap','fakedPASS'):
   with tempfile.TemporaryDirectory() as t:
    p,inputs,view,run,out,r=self.fixture(t);c=r['results']['10']
    if mode=='partial':c['held'].pop()
    elif mode=='duplicate':c['held'][1]=c['held'][0]
    elif mode=='nullgap':c['held'][0]['shuffle_raw_gaps']=[None]*99
    else:c['method_quality']='PASS_FIXED_CONTROLS'
    self.save(run,p,r)
    with self.assertRaises(ValueError):m.completion(run,p,inputs)
 def test_output_mutation_invalidates_manifest(self):
  with tempfile.TemporaryDirectory() as t:
   p,inputs,view,run,out,r=self.fixture(t);file=run/'calibrate-v1/result.json';file.write_text(file.read_text()+' ')
   with self.assertRaisesRegex(ValueError,'SHA'):m.completion(run,p,inputs)
 def test_monitor_source_has_no_science_spawn_or_replay_call(self):
  import ast
  tree=ast.parse(P.read_text());self.assertNotIn('replay_once',[x.name for x in tree.body if isinstance(x,ast.FunctionDef)])
  self.assertNotIn('run_phase',P.read_text());self.assertNotIn('subprocess',P.read_text());self.assertNotIn('allow_replay',P.read_text())
if __name__=='__main__':unittest.main()
