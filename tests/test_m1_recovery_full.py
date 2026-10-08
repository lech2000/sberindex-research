"""No native/probe/solver/science/model calls: metadata and mocked dispatch only."""
import copy,datetime,hashlib,json,sys,tempfile,types,unittest
from pathlib import Path
from unittest.mock import patch,Mock
sys.dont_write_bytecode=True
D=Path(__file__).resolve().parents[1];sys.path.insert(0,str(D/'economic-atlas/src'))
import atlas_m1_recovery_guardian as g
import atlas_m1_recovery_keys as k
import atlas_m1_recovery_validate as v
P=D/'economic-atlas/protocols/M1_NUMERICAL_RECOVERY_V1.json'
class Publication(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
  self.auth={'engine':'engine','recovery':'recovery','guardian':'guard','validator':'validator','amendment':'amendment','base_source':'oldsource','base_protocol':'oldprotocol'}
  self.p=k.read_protocol(P);self.frozen=json.loads(Path('/private/tmp/atlas-m1-frozen-execution-view-20261007/economic-atlas/protocols/M1_PROSPECTIVE_V1.json').read_text());self.old,_=k.ancestral_records(self.p,self.frozen)
  self.input={'panel':'p','A5_mask':'m'}
 def write(self,path,value):path.write_text(json.dumps(value,allow_nan=True))
 def manifest(self,out):g.phase_manifest(out,self.auth)
 def replay(self):
  self.out=self.root/'replay';g.freeze(self.out,self.auth,'replay');self.rows=[]
  for t,month in enumerate([f'{y}-{m:02d}' for y in (2023,2024) for m in range(1,13)]):
   for knn in (10,20,40):
    self.rows.append({'month':month,'kNN':knn,'n':1896,'edges':1896*knn//2,'density':knn/1895,'isolates':1,'components':2,'m':None,'sig':None,'raw_gap':None,'status':'INCONCLUSIVE_GRAPH_ISOLATE','verdict':'INCONCLUSIVE_GRAPH_ISOLATE','spectrum_sha256':None,'shuffle_raw_gaps':[],'shuffle_invalid_seeds':list(range(self.frozen['shuffle_seed_base']+t*100,self.frozen['shuffle_seed_base']+t*100+99)),'method_quality':'FAIL_OR_INCONCLUSIVE_FIXED_CONTROLS','metrics':[{'K':K,'status':'NA_GRAPH_OR_K_DOMAIN','SW':None,'CH':None,'S_Dbw':None} for K in range(2,9)]})
  self.r={'state':'COMPUTED_DESCRIPTIVE','authority':self.auth,'numerical_driver':'evd','calibration_sha256':'cal','input_sha256':self.input,'economic_identity_pass':False,'independent_holdout':False,'causal_pass':False,'scientific_pass':False,'monthly':self.rows};self.write_replay()
 def write_replay(self):
  self.write(self.out/'result.json',self.r);self.write(self.out/'monthly-progress.json',self.rows);self.manifest(self.out)
 def verify_replay(self):return v.replay(self.out,self.auth,self.frozen,'cal',list(range(1896)),self.input,lambda:None)
 def test_valid_full72_negative(self):self.replay();self.assertEqual(len(self.verify_replay()['monthly']),72)
 def test_prior_blocker_missing_full_universe(self):
  self.replay();(self.out/'monthly-progress.json').unlink();self.manifest(self.out)
  with self.assertRaises((ValueError,FileNotFoundError)):self.verify_replay()
 def test_prior_blocker_unknown_verdict(self):
  self.replay();self.rows[0]['verdict']='INVENTED';self.write_replay()
  with self.assertRaises(ValueError):self.verify_replay()
 def test_prior_blocker_observed_nan(self):
  self.replay();self.rows[0]['raw_gap']=float('nan');self.write_replay()
  with self.assertRaises(ValueError):self.verify_replay()
 def test_prior_blocker_missing_metrics(self):
  self.replay();self.rows[0]['metrics'][0]={'K':2};self.write_replay()
  with self.assertRaises(ValueError):self.verify_replay()
 def test_prior_blocker_flags_true(self):
  self.replay();self.r['economic_identity_pass']=True;self.write_replay()
  with self.assertRaises(ValueError):self.verify_replay()
 def test_unknown_top_state(self):
  self.replay();self.r['state']='SCIENCE_PASS';self.write_replay()
  with self.assertRaises(ValueError):self.verify_replay()
 def test_duplicate_monthscope(self):
  self.replay();self.rows[-1]=copy.deepcopy(self.rows[0]);self.write_replay()
  with self.assertRaises(ValueError):self.verify_replay()
 def test_missing99null(self):
  self.replay();self.rows[0]['shuffle_invalid_seeds'].pop();self.write_replay()
  with self.assertRaises(ValueError):self.verify_replay()
 def test_oldsource_only_authority(self):
  self.replay();self.auth['engine']='oldsource';self.r['authority']['guardian']='invented';self.write_replay()
  expected=dict(self.auth);expected['guardian']='guard'
  with self.assertRaises(ValueError):v.replay(self.out,expected,self.frozen,'cal',list(range(1896)),self.input,lambda:None)
 def test_extra_file_not_authorized(self):
  self.replay();(self.out/'extra.json').write_text('{}');self.manifest(self.out)
  with self.assertRaises(ValueError):self.verify_replay()
 def test_missing_spectrum_not_suppressed(self):
  self.replay();self.rows[0].update(status='INCONCLUSIVE_NO_BULK',m=1896,spectrum_sha256='missing');self.rows[0]['metrics'].append({'K':1896,'status':'NA_GRAPH_OR_K_DOMAIN','SW':None,'CH':None,'S_Dbw':None});self.write_replay()
  with self.assertRaises((ValueError,FileNotFoundError)):self.verify_replay()
 def test_graph_density_contract(self):
  self.replay();self.rows[0]['density']=0.;self.write_replay()
  with self.assertRaises(ValueError):self.verify_replay()
 def cal(self):
  self.out=self.root/'cal';g.freeze(self.out,self.auth,'recovery_calibration');results=copy.deepcopy(self.old)
  for _,knn,R,seed in self.p['remaining_control_keys']:
   row=copy.deepcopy(results[str(knn)]['held'][-1]);row.update(R=R,seed=seed,shuffle_raw_gaps=[],shuffle_invalid_seeds=list(range(self.frozen['shuffle_seed_base']+seed*100,self.frozen['shuffle_seed_base']+seed*100+99)));results[str(knn)]['held'].append(row)
  self.r={'state':'COMPUTED_DESCRIPTIVE_MIXED_NUMERICAL_RECOVERY','input_sha256':{'panel':'8716a802fb6e25ef4103406cca927de80ce3693a7ff243411cda765b732bcd93','A5_mask':'12f40b15ee8f119cba7f386b5c9adf4babb5cff1bca2721dc04551d672f5e5d6'},'actual_recovery_source_SHA':self.auth['recovery'],'actual_evd_engine_SHA':self.auth['engine'],'amendment_protocol_SHA':self.auth['amendment'],'base_source_SHA':self.auth['base_source'],'authority':self.auth,'n':1896,'d':5,'results':results,'mixed_ancestral_numerics':True,'numerical_driver_new':'evd','economic_identity_pass':False,'scientific_pass':False,'settings_sha256':hashlib.sha256(json.dumps(self.frozen,sort_keys=True).encode()).hexdigest(),'record_origin':{'old334':self.p['ancestral_progress'],'new26':self.p['remaining_control_keys']}};self.write_cal()
 def write_cal(self):
  self.write(self.out/'result.json',self.r)
  for knn,c in self.r['results'].items():self.write(self.out/f'calibration-progress-k{knn}.json',{x:c[x] for x in ('calibration','fit','held')})
  self.manifest(self.out)
 def verify_cal(self):return v.calibration(self.out,self.auth,self.p,self.frozen,self.old,lambda:None)
 def test_full360_old334_exact_negative_valid(self):self.cal();self.assertEqual(sum(len(c['calibration'])+len(c['held']) for c in self.verify_cal()['results'].values()),360)
 def test_changed_old334_rejected(self):
  self.cal();self.r['results']['10']['held'][0]['seed']=123;self.write_cal()
  with self.assertRaises(ValueError):self.verify_cal()
 def test_missing_new26_rejected(self):
  self.cal();self.r['results']['40']['held'].pop();self.write_cal()
  with self.assertRaises(ValueError):self.verify_cal()
 def test_positive_quality_from_oldfit_rejected(self):
  self.cal();self.r['results']['40']['method_quality']='PASS_FIXED_CONTROLS';self.write_cal()
  with self.assertRaises(ValueError):self.verify_cal()
 def test_fit_retuning_rejected(self):
  self.cal();self.r['results']['40']['fit']['sig_star']=1.;self.write_cal()
  with self.assertRaises(ValueError):self.verify_cal()
 def test_mixed_origin_missing_rejected(self):
  self.cal();self.r['record_origin']['new26']=[];self.write_cal()
  with self.assertRaises(ValueError):self.verify_cal()
class SpectraLabels(unittest.TestCase):
 setUp=Publication.setUp
 write=Publication.write
 manifest=Publication.manifest
 replay=Publication.replay
 write_replay=Publication.write_replay
 verify_replay=Publication.verify_replay
 def add_spectrum_labels(self):
  import numpy as np
  self.replay();r=self.rows[0];r.update(m=1,status='DEGENERATE_BULK',sig=None,raw_gap=1.,bulk_spread=0.,lambda2_through_mplus2=[0.,0.],verdict='ABSTAIN_M1',isolates=0,components=1)
  name='spectrum-2023-01-knn10.npy';np.save(self.out/name,np.r_[1.,np.zeros(1895)]);r['spectrum_sha256']=v.sha(self.out/name)
  r['metrics']=[]
  for K in range(2,9):
   np.savez_compressed(self.out/f'labels-2023-01-knn10-K{K}.npz',territory_id=np.arange(1896),label=np.arange(1896)%K)
   r['metrics'].append({'K':K,'status':'COMPUTED','SW':.1,'CH':1.,'S_Dbw':.5,'S_Dbw_detail':{'status':'COMPUTED','S_Dbw':.5}})
  r['metrics'].insert(0,{'K':1,'status':'NA_GRAPH_OR_K_DOMAIN','SW':None,'CH':None,'S_Dbw':None});self.write_replay()
 def test_full_spectrum_and_originalK_labels_fixture(self):self.add_spectrum_labels();self.verify_replay()
 def test_missing_label_archive_rejected(self):
  self.add_spectrum_labels();(self.out/'labels-2023-01-knn10-K2.npz').unlink();self.manifest(self.out)
  with self.assertRaises((ValueError,FileNotFoundError)):self.verify_replay()
 def test_wrong_label_mask_rejected(self):
  import numpy as np
  self.add_spectrum_labels();np.savez_compressed(self.out/'labels-2023-01-knn10-K2.npz',territory_id=np.arange(1896)+1,label=np.arange(1896)%2);self.manifest(self.out)
  with self.assertRaises(ValueError):self.verify_replay()
 def test_full_spectrum_count_mismatch_rejected(self):
  self.add_spectrum_labels();self.rows[0]['m']=2;self.write_replay()
  with self.assertRaises(ValueError):self.verify_replay()
 def test_COMPUTED_SDbw_null_rejects(self):
  self.add_spectrum_labels();metric=self.rows[0]['metrics'][1];metric['S_Dbw']=None;metric['S_Dbw_detail']['S_Dbw']=None;self.write_replay()
  with self.assertRaises(ValueError):self.verify_replay()
 def test_NA_SDbw_finite_rejects(self):
  self.add_spectrum_labels();metric=self.rows[0]['metrics'][1];metric['status']='NA_ZERO_GLOBAL_VARIANCE';metric['S_Dbw_detail']['status']=metric['status'];self.write_replay()
  with self.assertRaises(ValueError):self.verify_replay()
 def test_lambda1_relative_tolerance_cannot_hide_violation(self):
  import numpy as np
  self.add_spectrum_labels();name='spectrum-2023-01-knn10.npy';np.save(self.out/name,np.r_[1.000001,np.zeros(1895)]);self.rows[0].update(raw_gap=1.000001,spectrum_sha256=v.sha(self.out/name));self.write_replay()
  with self.assertRaises(ValueError):self.verify_replay()
class Dispatch(unittest.TestCase):
 def test_no_worker_flag_authority_before_imports(self):
  with patch.object(g,'load') as loader:
   with self.assertRaises(ValueError):g.worker(types.SimpleNamespace(worker=None,dispatch_sha=None))
   loader.assert_not_called()
 def test_replay_all7200_calls_journalled_without_science(self):
  calls=[]
  class J:
   def dispatch(self,key,function,admission):calls.append(key);return function()
  engine=types.SimpleNamespace(spectrum=lambda *a:({'raw_gap':None},None,None),clean=lambda x:x)
  def replay(*a):
   for _ in range(7200):engine.spectrum(None,.95)
   return {'monthly':[{}]*72}
  engine.replay=replay
  original=engine.spectrum
  r=k.journalled_replay(engine,J(),None,{'shuffle_seed_base':20261208},{},None,lambda:None)
  self.assertIs(engine.spectrum,original);self.assertEqual(len(calls),7200);self.assertEqual(calls[0],['replay','2023-01',10,'observed']);self.assertEqual(calls[-1],['replay','2024-12',40,'null',20263606]);self.assertFalse(r['scientific_pass'])
 def test_replay_missing_call_no_completion(self):
  class J:
   def dispatch(self,key,function,admission):return function()
  engine=types.SimpleNamespace(spectrum=lambda *a:({},None,None),clean=lambda x:x,replay=lambda *a:{'monthly':[{}]*72})
  with self.assertRaises(ValueError):k.journalled_replay(engine,J(),None,{'shuffle_seed_base':1},{},None,lambda:None)
 def test_exact_deadline_and_reserve(self):
  for t in (g.START+datetime.timedelta(seconds=77881),g.START+datetime.timedelta(seconds=77881-30)):
   with self.assertRaises(ValueError):g.remaining(t)
  self.assertEqual(g.remaining(g.START),77851)
 def test_file_logs_lease_size_included(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'log';p.write_bytes(b'12345');self.assertEqual(g.files_size([p]),5)
 def test_irreversible_global_oneuse(self):
  with tempfile.TemporaryDirectory() as d,patch.object(g,'LEDGER',Path(d)/'ledger'):
   path=g.private_lease();g.once(path,{'state':'STARTED'})
   with self.assertRaises(FileExistsError):g.once(g.private_lease(),{'out':'alternate'})
 def test_same_size_preflight_literal_source_no_call(self):
  source=(D/'economic-atlas/src/atlas_m1_recovery_keys.py').read_text();self.assertIn('engine.world(1896,5,1,999999)',source);self.assertIn("for driver in ('evr','evd')",source);self.assertNotIn('eigvals_only=True',source)
class Lifecycle(unittest.TestCase):
 def test_public_worker_bad_parent_rejects_before_imports(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'dispatch.json';p.write_text(json.dumps({'parent_pid':-1,'uid':0,'native_preflight_pass':True}))
   with patch.object(g,'load') as load:
    with self.assertRaises(ValueError):g.worker(types.SimpleNamespace(worker=p,dispatch_sha=g.sha(p)))
    load.assert_not_called()
 def test_actual_remaining26_frozen_no_choice(self):
  p=k.read_protocol(P);self.assertEqual(len(p['remaining_control_keys']),26);self.assertEqual(p['remaining_control_keys'][-1],['held',40,5,20261127]);self.assertEqual(p['failed_block']['failed_null_seed'],'UNKNOWN_UNJOURNALLED_ANCESTRAL_EXCEPTION')
 def test_native_preflight_failure_no_worker_phase_and_terminal_retained(self):
  self.fake_main(preflight_error=True)
 def test_child_failure_no_completion_and_no_retry(self):
  self.fake_main(preflight_error=False)
 def fake_main(self,preflight_error):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);out=root/'out';receipt=root/'receipt';lease=root/'lease.json'
   native=types.SimpleNamespace(own_tree_rss=lambda:(1,{}),descendants=lambda pid:[])
   run=Mock(return_value={'state':'INCONCLUSIVE_PHASE_EXIT','exit_code':1})
   def preflight(path,n):
    if preflight_error:raise RuntimeError('mock native preflight STOP')
    path.mkdir();g.atomic(path/'resource-preflight.json',{'state':'PASS'});return {'state':'PASS'}
   guard=types.SimpleNamespace(NativeMac=lambda:native,resource_preflight=preflight,run_phase=run,stop_requested=lambda *a:None,LIMITS={'wall':77881,'output':268435456,'rss':1073741824,'free':1073741824,'sample':.25,'disk_sample':10})
   original=g.load
   def loader(path,name):return guard if name=='accepted_guard' else original(path,name)
   with patch.object(g,'load',side_effect=loader),patch.object(g,'private_lease',return_value=lease),patch.object(g,'destinations',return_value=(out,receipt)),patch.object(g,'binding',return_value={}),patch.object(g,'check_pins'),patch.object(g,'admit'),patch.object(g,'remaining',return_value=1000),patch.object(g,'elapsed',return_value=70000),patch.object(g.signal,'getsignal'),patch.object(g.signal,'signal'),patch.object(g.signal,'setitimer'):
    with self.assertRaises(SystemExit):g.main(['--protocol',str(P),'--binding',str(root/'binding'),'--binding-sha','fixture','--outdir',str(out),'--receipt-dir',str(receipt)])
   terminal=lease.with_name(lease.stem+'-terminal.json');r=json.loads(terminal.read_text());self.assertTrue(r['state'].startswith('INCONCLUSIVE'));self.assertFalse(r['scientific_pass']);self.assertEqual(r['source_actions_closed'],0)
   self.assertEqual(run.call_count,0 if preflight_error else 1)
   with self.assertRaises(FileExistsError):g.once(lease,{'state':'STARTED','out':'alternate'})
if __name__=='__main__':unittest.main()
