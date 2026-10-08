"""Pure stdlib, small schema-only fixtures. Never imports numerical libraries."""
import os,sys,pathlib,json,tempfile,unittest,hashlib,time,datetime,types
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).parents[1]/'economic-atlas/src'))
import e05_full_guardian_toolkit_v2 as g
import e05_full_receipt_adapter_v2 as a
import e05_full_publication_validator_v2 as v
P=json.loads(pathlib.Path(os.environ.get('E05_REPAIRED_PROTOCOL', str(pathlib.Path(__file__).parents[1]/'economic-atlas/protocols/E05_FULL_REMAINING_V2.json'))).read_text())

def spec():
 # SYNTHETIC mock bounds, not E05 execution policy or qualified estimates.
 return dict(whole_seconds=120,final_receipt_reserve_seconds=10,RSS_bytes=10000,minimum_free_bytes=100,output_bytes=1000000,receipt_reserve_bytes=10000,poll_seconds=.01,cleanup_seconds=2,CPU_threads=1,absolute_deadline_UTC=(datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(hours=1)).isoformat(),actual_fullsize_preflight_accepted=True,resource_spec_independently_accepted=True)
def records():return [dict(key=i,cell=c,status='NOT_ATTEMPTED_RESOURCE_STOP',protocol_SHA=v.PROTOCOL_SHA,method_SHA=v.METHOD_SHA) for i,c in enumerate(v.planned(P))]
def rows(status='COMPUTED',label=0):return [dict(territory_id=t,month=m,label=label,status=status) for m in ('a','b') for t in (1,2)]
CELL={'kind':'control','K':2}
class Array:
 shape=(2,);dtype='int64'
 def tobytes(self,order='C'):return b'synthetic-tensor'
class E05(unittest.TestCase):
 def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.root=pathlib.Path(self.tmp.name)
 def tearDown(self):self.tmp.cleanup()
 def budget(self,s=None,rss=0,free=10000):return g.Budget(s or spec(),time.monotonic(),[self.root],lambda:rss,lambda:free)
 def test_public_all_execute_unconditional_refusal(self):
  for module in (g,a,v):
   with self.assertRaisesRegex(RuntimeError,'NOT_EXECUTABLE'):module.execute()
 def test_scope225_rows_10238400(self):self.assertEqual(len(v.planned(P))*1896*24,10238400)
 def test_nominal4110_not_runtime(self):self.assertEqual(v.nominal_calls(P),4110)
 def test_native8220_not_internal_init_count(self):self.assertEqual(len(a.nominal_registry(P)[1]),8220)
 def test_registry_missing(self):
  with self.assertRaises(ValueError):v.registry(P,records()[:-1])
 def test_registry_seed_change(self):
  r=records();r[0]['cell']=dict(r[0]['cell'],seed=0)
  with self.assertRaises(ValueError):v.registry(P,r)
 def test_registry_protocol_change(self):
  r=records();r[0]['protocol_SHA']='0'*64
  with self.assertRaises(ValueError):v.registry(P,r)
 def test_full_status_small_universe(self):self.assertEqual(v.row_universe(rows(),[1,2],['a','b'],2,CELL,'COMPUTED')['rows'],4)
 def test_duplicate_rows(self):
  with self.assertRaises(ValueError):v.row_universe(rows()+rows()[:1],[1,2],['a','b'],2,CELL,'COMPUTED')
 def test_missing_rows(self):
  with self.assertRaises(ValueError):v.row_universe(rows()[:-1],[1,2],['a','b'],2,CELL,'COMPUTED')
 def test_unknown_not_zero(self):
  with self.assertRaises(ValueError):v.row_universe(rows('UNKNOWN_NATIVE_RESPONSE',0),[1,2],['a','b'],2,CELL,'UNKNOWN_NATIVE_RESPONSE')
 def test_failure_full_null_rows(self):self.assertEqual(v.row_universe(rows('INCONCLUSIVE_METHOD_FAILURE',None),[1,2],['a','b'],2,CELL,'INCONCLUSIVE')['rows'],4)
 def test_computed_missing_month_rejected(self):
  with self.assertRaises(ValueError):v.row_universe(rows(),[1,2],['a','b'],2,{'kind':'real','arm':{'feature':'growth_mom'}},'COMPUTED')
 def test_expected_math_na_preserved(self):
  r=rows();r[0].update(status='INPUT_UNAVAILABLE',label=None);r[1].update(status='INPUT_UNAVAILABLE',label=None)
  self.assertEqual(v.row_universe(r,[1,2],['a','b'],2,{'kind':'real','arm':{'feature':'growth_mom'}},'COMPUTED')['status_counts']['INPUT_UNAVAILABLE'],2)
 def test_bool_label_rejected(self):
  with self.assertRaises(ValueError):v.row_universe(rows(label=True),[1,2],['a','b'],2,CELL,'COMPUTED')
 def test_status_unknown_rejected(self):
  with self.assertRaises(ValueError):v.row_universe(rows('MISSING',None),[1,2],['a','b'],2,CELL,'INCONCLUSIVE')
 def test_controls_zero_undefined_not_pass(self):self.assertEqual(v.control_budget({'miss_fraction':None,'median_delay':None},'abrupt_shift',P),'INCONCLUSIVE_UNDEFINED')
 def test_controls_failed_not_pass(self):self.assertEqual(v.control_budget({'miss_fraction':1,'median_delay':3},'abrupt_shift',P),'CONTROL_BUDGET_FAIL')
 def test_unknown_resource_spec_refuses(self):
  s=spec();s['whole_seconds']=None
  with self.assertRaises(ValueError):g.operational_spec(s)
 def test_boolean_resource_refuses(self):
  s=spec();s['RSS_bytes']=True
  with self.assertRaises(ValueError):g.operational_spec(s)
 def test_preflight_pending_refuses(self):
  s=spec();s['actual_fullsize_preflight_accepted']=False
  with self.assertRaises(ValueError):g.operational_spec(s)
 def test_earliest_anchor_no_reset(self):
  b=self.budget();b.anchor=time.monotonic()-111
  with self.assertRaises(InterruptedError):b.check()
 def test_disk_guard(self):
  with self.assertRaises(InterruptedError):self.budget(free=0).check()
 def test_own_rss_guard(self):
  with self.assertRaises(InterruptedError):self.budget(rss=10001).check()
 def test_output_logs_control_same_roots(self):
  (self.root/'log').write_bytes(b'x'*101);s=spec();s.update(output_bytes=110,receipt_reserve_bytes=10)
  with self.assertRaises(InterruptedError):self.budget(s).check()
 def test_dedup_nested_roots(self):
  (self.root/'x').write_bytes(b'abc');self.assertEqual(g.total_bytes([self.root,self.root/'x']),3)
 def test_symlink_refusal(self):
  (self.root/'link').symlink_to('/tmp')
  with self.assertRaises(ValueError):g.total_bytes([self.root])
 def test_journal_start_before_call_response(self):
  j=g.Journal(self.root,lambda:None)
  def fn():self.assertTrue(j.path('x','STARTED').exists());return {'result':1}
  j.call('x',{'inputSHA':'1'*64},fn);r=json.loads(j.path('x','RESPONSE').read_text());self.assertEqual(r['started_SHA'],g.sha(j.path('x','STARTED')))
 def test_unknown_call_no_retry(self):
  j=g.Journal(self.root,lambda:None)
  with self.assertRaises(RuntimeError):j.call('x',{},lambda:(_ for _ in ()).throw(RuntimeError('fake native failure')))
  self.assertFalse(j.path('x','RESPONSE').exists())
  with self.assertRaises(FileExistsError):j.call('x',{},lambda:1)
 def test_file_then_directory_fsync(self):
  events=[]
  with patch.object(g.os,'fsync',side_effect=lambda fd:events.append(fd)):g.once(self.root/'x',{})
  self.assertEqual(len(events),2)
 def test_fsync_failure_no_dispatch(self):
  j=g.Journal(self.root,lambda:None);called=[]
  with patch.object(g,'sync_parent',side_effect=OSError('mock directory durability failed')):
   with self.assertRaises(InterruptedError):j.call('x',{},lambda:called.append(True))
  self.assertEqual(called,[]);self.assertTrue(j.path('x','STARTED').exists())
 def test_native_forward_same_objects_restore(self):
  calls=[];array=Array()
  class KM:
   def __init__(self):self.cluster_centers_=array
   def get_params(self,deep=False):return dict(n_clusters=2,n_init=20,random_state=20261008)
   def fit_predict(self,X,*args,**kw):calls.append(('fit',X));return array
  oldfit=KM.fit_predict
  def eigen(X,*args,**kw):calls.append(('eigen',X,kw));return (array,array)
  lib=types.SimpleNamespace(_deps=lambda:(None,None,None,eigen,KM));olddeps=lib._deps
  adapter=a.Adapter(P,g.Journal(self.root,lambda:None),lambda:None,self.root);adapter.cell_callback(dict(key=0,state='STARTED',cell=adapter.cells[0]))
  with adapter.observe(lib):
   deps=lib._deps();self.assertIs(deps[3](array,k=2,which='SA',tol=1e-8,maxiter=5000,v0=array)[0],array);self.assertIs(KM().fit_predict(array),array)
  self.assertIs(lib._deps,olddeps);self.assertIs(KM.fit_predict,oldfit);self.assertEqual(len(calls),2);self.assertEqual(adapter.native['native/0/0/KMeans.fit_predict']['status'],'RESPONSE')
 def test_native_failure_unknown_no_repeat(self):
  adapter=a.Adapter(P,g.Journal(self.root,lambda:None),lambda:None,self.root);adapter.cell_callback(dict(key=0,state='STARTED',cell=adapter.cells[0]))
  with self.assertRaises(RuntimeError):adapter.native_call('eigsh',{},lambda:(_ for _ in ()).throw(RuntimeError('unknown')),lambda x:x)
  with self.assertRaises(ValueError):adapter.native_call('eigsh',{},lambda:1,lambda x:x)
 def test_cell_no_overlap_retry(self):
  adapter=a.Adapter(P,g.Journal(self.root,lambda:None),lambda:None,self.root);adapter.cell_callback(dict(key=0,state='STARTED',cell=adapter.cells[0]))
  with self.assertRaises(ValueError):adapter.cell_callback(dict(key=1,state='STARTED',cell=adapter.cells[1]))
 def test_missing_published_bytes_no_cell_commit(self):
  adapter=a.Adapter(P,g.Journal(self.root,lambda:None),lambda:None,self.root);adapter.cell_callback(dict(key=0,state='STARTED',cell=adapter.cells[0]))
  with self.assertRaises(InterruptedError):adapter.cell_callback(dict(key=0,state='INCONCLUSIVE',rowsSHA='0'*64,failureSHA='0'*64))
 def test_all_native_unattempted_inventory_retained(self):
  _,native=a.nominal_registry(P);self.assertEqual(v.validate_journals(P,records(),native,{},self.root,{})['nominal'],8220)
 def test_native_inventory_no_shrink(self):
  _,native=a.nominal_registry(P)
  with self.assertRaises(ValueError):v.validate_journals(P,records(),native[:-1],{},self.root,{})
 def test_unknown_journal_missing_refuses(self):
  _,native=a.nominal_registry(P);native[0]['status']='UNKNOWN_NATIVE_RESPONSE'
  with self.assertRaises(ValueError):v.validate_journals(P,records(),native,{},self.root,{})
 def test_real_factory_refused_before_mutation(self):
  with self.assertRaises(RuntimeError):g.supervise_mockable([],self.budget(),[self.root/'lease',self.root/'log',self.root/'terminal'],factory=lambda:None)
  self.assertEqual(list(self.root.iterdir()),[])
 def test_mock_dispatch_cpu1_lease_before_spawn(self):
  class Child:
   pid=100001
   def read_bounded(self,n):return b''
   def poll(self):return 0
   def wait(self,timeout):return 0
  def factory(command,**kw):
   self.assertTrue((self.root/'lease').exists());self.assertEqual(set(kw['env'].values()),{'1'});self.assertTrue(kw['start_new_session']);return Child()
  factory.source_only_mock=True
  r=g.supervise_mockable(['synthetic'],self.budget(),[self.root/'lease',self.root/'log',self.root/'terminal'],factory=factory,cleanup=lambda *args:{'reaped':True})
  self.assertEqual(r['state'],'CHILD_EXIT_OBSERVED');self.assertFalse(r['continuous_resource_pass'])
 def test_consumed_mock_lease_no_dispatch(self):
  (self.root/'lease').write_text('{}');called=[]
  def factory(*args,**kw):called.append(True)
  factory.source_only_mock=True
  r=g.supervise_mockable([],self.budget(),[self.root/'lease',self.root/'log',self.root/'terminal'],factory=factory)
  self.assertEqual(called,[]);self.assertIn('consumed',r['error'])
 def test_foreign_group_cleanup_refuses_without_signal(self):
  child=types.SimpleNamespace(pid=100001)
  with patch.object(g.os,'killpg') as kill:
   with self.assertRaises(ValueError):g.cleanup_owned(child,set(),.1)
   kill.assert_not_called()
 def test_no_signal_alarm_polling(self):
  self.assertNotIn('setitimer',pathlib.Path(g.__file__).read_text())
 def test_missing_pairings_no_success(self):
  r=records();r[0]['status']='COMPUTED'
  with self.assertRaises(ValueError):v.validate_pairing(P,r,[])
 def test_finite_tensor_reject_object_pointer(self):
  x=Array();x.dtype='object'
  with self.assertRaises(ValueError):a.fingerprint(x)
 def test_guard_io_charged_before_dispatch(self):
  b=self.budget();b.anchor=100
  with patch.object(g.time,'monotonic',side_effect=[101,211]):
   with self.assertRaisesRegex(InterruptedError,'guard IO'):b.check()
 def test_cpu_bool_no_loophole(self):
  s=spec();s['CPU_threads']=True
  with self.assertRaises(ValueError):g.operational_spec(s)
 def test_cached_deps_does_not_doublewrap(self):
  class KM:
   def fit_predict(self,*args):return []
  original=KM.fit_predict;lib=types.SimpleNamespace(_deps=lambda:(None,None,None,lambda *args:[],KM))
  adapter=a.Adapter(P,g.Journal(self.root,lambda:None),lambda:None,self.root)
  with adapter.observe(lib):self.assertIs(lib._deps(),lib._deps())
  self.assertIs(KM.fit_predict,original)
 def test_actual_adapter_journal_binding_validated(self):
  journal=g.Journal(self.root,lambda:None);adapter=a.Adapter(P,journal,lambda:None,self.root)
  adapter.cell_callback(dict(key=0,state='STARTED',cell=adapter.cells[0]))
  fp=a.fingerprint(Array())
  adapter.native_call('eigsh',{'matrix':fp,'args':[],'kwargs':dict(k=2,which='SA',tol=1e-8,maxiter=5000,v0=fp)},lambda:[fp,fp],lambda x:x)
  adapter.native_call('KMeans.fit_predict',{'params':dict(n_clusters=2,n_init=20,random_state=20261008),'X':fp,'args':[],'kwargs':{}},lambda:{'labels':fp,'centers':fp},lambda x:x)
  r=records();r[0]['status']='UNKNOWN_NATIVE_RESPONSE';inv={};files={}
  for key in ('cell/0','native/0/0/eigsh','native/0/0/KMeans.fit_predict'):
   inv[key]={}
   for state in ('STARTED','RESPONSE'):
    f=journal.path(key,state)
    if f.exists():inv[key][state]=f.name;files[f.name]=g.sha(f)
  result=v.validate_journals(P,r,adapter.registry,inv,self.root,files)
  self.assertEqual(result['responses'],2);self.assertEqual(result['unknown'],1)
  response=journal.path('native/0/0/eigsh','RESPONSE');bad=json.loads(response.read_text());bad['started_SHA']='0'*64;response.write_text(json.dumps(bad))
  with self.assertRaisesRegex(ValueError,'SHA binding'):v.validate_journals(P,r,adapter.registry,inv,self.root,files)
 def pair_fixture(self,baseline='COMPUTED',arm='COMPUTED'):
  rec=records();rec[0]['status']=baseline;rec[10]['status']=arm;cell=rec[10]['cell']
  pair={'cell':cell,'denominators':{'universe':45504,'paired_available':45504,'unpaired':0},'agreement':[{'month':m,'n':1896,'status':'COMPUTED','ARI_vs_sameKseed_shares':0.,'NMI_vs_sameKseed_shares':0.} for m in P['months']]}
  return rec,pair
 def test_independent_B1_failed_baseline_pairing_rejected(self):
  rec,pair=self.pair_fixture('INCONCLUSIVE')
  with self.assertRaisesRegex(ValueError,'successful exact'):v.validate_pairing(P,rec,[pair])
 def test_pairing_unknown_baseline_rejected(self):
  rec,pair=self.pair_fixture('UNKNOWN_NATIVE_RESPONSE')
  with self.assertRaises(ValueError):v.validate_pairing(P,rec,[pair])
 def test_pairing_notattempted_baseline_rejected(self):
  rec,pair=self.pair_fixture('NOT_ATTEMPTED_RESOURCE_STOP')
  with self.assertRaises(ValueError):v.validate_pairing(P,rec,[pair])
 def test_pairing_unsuccessful_arm_rejected(self):
  rec,pair=self.pair_fixture('COMPUTED','INCONCLUSIVE')
  with self.assertRaises(ValueError):v.validate_pairing(P,rec,[pair])
 def test_pairing_success_exact_baseline_and_arm(self):
  rec,pair=self.pair_fixture();base={'cell':rec[0]['cell'],'denominators':{'universe':45504,'paired_available':45504,'unpaired':0},'agreement':[]}
  self.assertEqual(v.validate_pairing(P,rec,[base,pair]),2)
 def test_independent_B2_unattempted_cannot_be_unknown(self):
  with self.assertRaisesRegex(ValueError,'conserve exact'):v.row_universe(rows('UNKNOWN_NATIVE_RESPONSE',None),[1,2],['a','b'],2,CELL,'NOT_ATTEMPTED_RESOURCE_STOP')
 def test_notattempted_exact_full_status(self):
  self.assertEqual(v.row_universe(rows('NOT_ATTEMPTED_RESOURCE_STOP',None),[1,2],['a','b'],2,CELL,'NOT_ATTEMPTED_RESOURCE_STOP')['status_counts']['NOT_ATTEMPTED_RESOURCE_STOP'],4)
 def test_failed_cannot_hide_unattempted(self):
  with self.assertRaises(ValueError):v.row_universe(rows('NOT_ATTEMPTED_RESOURCE_STOP',None),[1,2],['a','b'],2,CELL,'INCONCLUSIVE')
 def test_unknown_cannot_hide_method_failure(self):
  with self.assertRaises(ValueError):v.row_universe(rows('INCONCLUSIVE_METHOD_FAILURE',None),[1,2],['a','b'],2,CELL,'UNKNOWN_NATIVE_RESPONSE')
 def cleanup_fixture(self,exitcode):
  alive={100001,100002};events=[];waits=[]
  def kill(pid,sig):
   self.assertIn(pid,{100001,100002});events.append((pid,sig))
   if pid not in alive:raise ProcessLookupError()
   if sig==g.signal.SIGTERM:alive.remove(pid)
  child=types.SimpleNamespace(pid=100001,poll=lambda:exitcode,wait=lambda **kw:waits.append(kw) or exitcode)
  with patch.object(g.os,'getpgrp',return_value=99999),patch.object(g.os,'killpg',side_effect=kill):r=g.cleanup_owned(child,{100001,100002},1.)
  self.assertTrue(r['reaped']);self.assertTrue(r['owned_groups_gone']);self.assertFalse(r['unknown']);self.assertEqual(len(waits),1)
  self.assertEqual({pid for pid,sig in events if sig==g.signal.SIGTERM},{100001,100002})
 def test_independent_B3_normal_leader_exit_still_cleans(self):self.cleanup_fixture(0)
 def test_nonzero_leader_exit_still_cleans(self):self.cleanup_fixture(7)
 def test_live_leader_also_cleans_and_reaps(self):self.cleanup_fixture(None)
 def test_dead_group_leader_but_alive_descendant_group(self):
  # killpg(group,0) observes the group without requiring its leader PID alive.
  self.cleanup_fixture(0)
 def test_foreground_in_known_set_refused_before_any_signal(self):
  child=types.SimpleNamespace(pid=100001)
  with patch.object(g.os,'getpgrp',return_value=99999),patch.object(g.os,'killpg') as kill:
   with self.assertRaises(ValueError):g.cleanup_owned(child,{100001,99999},1.)
   kill.assert_not_called()
 def test_remaining_owned_group_cannot_report_gone(self):
  child=types.SimpleNamespace(pid=100001,poll=lambda:0,wait=lambda **kw:0)
  with patch.object(g.os,'getpgrp',return_value=99999),patch.object(g.os,'killpg') as kill:r=g.cleanup_owned(child,{100001},0.)
  self.assertFalse(r['owned_groups_gone']);self.assertTrue(r['unknown']);self.assertTrue(r['reaped']);self.assertTrue(r['SIGKILL_used'])
 def wrapper_cleanup_fixture(self,exitcode):
  alive={100001};events=[];waits=[]
  class Child:
   pid=100001
   def read_bounded(self,n):return b''
   def poll(self):return exitcode
   def wait(self,timeout):waits.append(timeout);return exitcode
  def factory(*args,**kwargs):return Child()
  factory.source_only_mock=True
  def kill(pid,sig):
   events.append((pid,sig));self.assertEqual(pid,100001)
   if pid not in alive:raise ProcessLookupError()
   if sig==g.signal.SIGTERM:alive.remove(pid)
  budget=self.budget();anchor=budget.anchor
  with patch.object(g.os,'getpgrp',return_value=99999),patch.object(g.os,'killpg',side_effect=kill):
   r=g.supervise_mockable(['schema-only'],budget,[self.root/'lease',self.root/'log',self.root/'terminal'],factory=factory)
  self.assertEqual(r['exitcode'],exitcode);self.assertEqual(r['original_anchor'],anchor);self.assertTrue(r['cleanup']['reaped']);self.assertTrue(r['cleanup']['owned_groups_gone']);self.assertGreaterEqual(len(waits),2);self.assertIn((100001,g.signal.SIGTERM),events)
  self.assertLessEqual(r['elapsed_before_terminal'],budget.spec['whole_seconds']);self.assertFalse(r['continuous_resource_pass'])
 def test_wrapper_normal_exit_cleanup_same_anchor(self):self.wrapper_cleanup_fixture(0)
 def test_wrapper_nonzero_exit_cleanup_same_anchor(self):self.wrapper_cleanup_fixture(7)
 def test_no_scientific_modules_imported(self):
  self.assertFalse(set(('numpy','scipy','sklearn','pandas','pyarrow'))&set(sys.modules))
if __name__=='__main__':unittest.main()
