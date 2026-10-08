"""Zero-model fixtures: journal conservation, terminal accounting and private gates."""
import unittest,tempfile,types,hashlib,json,sys,math,os
from pathlib import Path
from unittest.mock import patch
source_root=Path(__file__).resolve().parents[1]/'shock-radar/src'
sys.path.insert(0,str(source_root if source_root.exists() else Path(__file__).parent));import r13_registry_core as c;import r13_full_registry as r
class Fixtures(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.out=self.root/'new';self.old=self.root/'old'
  for x in [self.out/'attempts',self.out/'checkpoints',self.out/'sessions',self.old/'checkpoints']:x.mkdir(parents=True)
  digest=lambda v:hashlib.sha256(json.dumps(v).encode()).hexdigest()
  self.base=types.SimpleNamespace(context_digest=digest,key=lambda x:(x['territory_id'],x['category'],x['origin'],str(x['horizon']),x['target']),month=lambda x:int(x[:4])*12+int(x[5:])-1,ym=lambda x:f'{x//12:04}-{x%12+1:02}')
  self.b=types.SimpleNamespace(__file__=c.__file__,group_id=digest,base=self.base)
  self.i={'key':('1018','Здоровье','2024-01'),'cutoff':24286,'context':[1.,2.], 'cached_prophet':{},'rows':[{'territory_id':'1018','category':'Здоровье','origin':'2024-01','horizon':6,'target':'2024-07','actual':9.}]}
  self.groups={self.i['key']:self.i};self.fp='newfp';self.p={'ancestral_path':str(self.old),'ancestral_fingerprint':'oldfp','ancestral_checkpoint_snapshot':{},'historical_elapsed_seconds':961.611384207994,'resource_plan':{'max_total_new_sessions':40,'cumulative_execution_seconds_including_history':108000,'absolute_deadline_UTC':'2026-10-09T09:00:00Z'},'registered_requested_rows':1,'frozen_primary_mask':{'canonical_keys_sha256':'fixture'},'historical_counters':{'chronos_calls':104,'prophet_fits':1006,'successful_native_calls':104,'successful_Prophet_fits':1005},'eligible_rows':1,'unknown_ancestral_group':{'group_key':list(self.i['key'])}}
  c.atomic(self.out/'counters.json',self.p['historical_counters'])
 def tearDown(self):self.tmp.cleanup()
 def begin(self,model='prophet',purpose='primary'):
  req={'fit':{'targets':['2024-07'],'train':[['2023-11',1.]],'seed':20260927}}
  return c.begin(self.out,purpose,model,[self.i],req,self.b,self.fp)
 def good(self,path,q,value=3.):return c.response(path,q,{self.b.group_id(self.i['key']):{'2024-07':value}})
 def oldstate(self,unknown=True):
  x={'fingerprint':'oldfp','group_key':list(self.i['key']),'context_sha256':self.base.context_digest(self.i['context']),'chronos':{'2024-07':2.},'prophet':{},'status':'pending','uncertain_inflight':'prophet' if unknown else None}
  file=self.old/'checkpoints'/(self.b.group_id(self.i['key'])+'.json');c.atomic(file,x);self.p['ancestral_checkpoint_snapshot'][str(file.relative_to(self.old))]=c.sha(file);return file
 def test_journal_before_callback(self):
  def f(path,q):
   self.assertEqual(c.read(path/'status.json')['status'],'STARTED');self.assertEqual(c.read(self.out/'counters.json')['prophet_fits'],1007);return {self.b.group_id(self.i['key']):{'2024-07':3.}}
  result=c.call(self.out,self.p,self.b,self.groups,self.fp,'primary','prophet',[self.i],{'fit':{'targets':['2024-07']}},f);self.assertTrue(result['ok'])
 def test_success_counts_exact(self):
  path,q=self.begin();self.good(path,q);c.commit(path,self.out,self.p,self.b,self.groups,self.fp);x=c.counters(self.out,self.p,self.fp);self.assertEqual((x['prophet_fits'],x['successful_Prophet_fits']),(1007,1006))
 def test_unreturned_unknown_never_callback(self):
  path,q=self.begin();c.recover(self.out,self.p,self.b,self.groups,self.fp);s=c.state(self.out,self.p,self.b,self.i,self.fp);self.assertIn('NEVER_RETRY',s['terminal']['prophet']['2024-07']);self.assertFalse(r.need(s,self.i,'prophet'))
 def test_response_replay_commit_only(self):
  path,q=self.begin();self.good(path,q);c.recover(self.out,self.p,self.b,self.groups,self.fp);self.assertEqual(c.state(self.out,self.p,self.b,self.i,self.fp)['prophet']['2024-07'],3.)
 def test_recovery_idempotent(self):
  path,q=self.begin();self.good(path,q);c.recover(self.out,self.p,self.b,self.groups,self.fp);before=c.sha(c.state_path(self.out,self.b,self.i));c.recover(self.out,self.p,self.b,self.groups,self.fp);self.assertEqual(before,c.sha(c.state_path(self.out,self.b,self.i)))
 def test_reported_failure_terminal(self):
  path,q=self.begin();c.response(path,q,error='MODEL_ERROR');c.commit(path,self.out,self.p,self.b,self.groups,self.fp);self.assertFalse(r.need(c.state(self.out,self.p,self.b,self.i,self.fp),self.i,'prophet'))
 def test_success_overwrite_prohibited(self):
  path,q=self.begin();self.good(path,q);c.commit(path,self.out,self.p,self.b,self.groups,self.fp);path,q=self.begin();self.good(path,q,4.)
  with self.assertRaises(ValueError):c.commit(path,self.out,self.p,self.b,self.groups,self.fp)
 def test_terminal_overwrite_prohibited(self):
  path,q=self.begin();c.response(path,q,error='UNKNOWN');c.commit(path,self.out,self.p,self.b,self.groups,self.fp);path,q=self.begin();self.good(path,q)
  with self.assertRaises(ValueError):c.commit(path,self.out,self.p,self.b,self.groups,self.fp)
 def test_target_mismatch(self):
  path,q=self.begin();c.response(path,q,{self.b.group_id(self.i['key']):{'2024-08':3.}})
  with self.assertRaises(ValueError):c.validated_response(path,self.fp)
 def test_request_mutation(self):
  path,q=self.begin();self.good(path,q);q['request']['fit']['seed']=1;c.atomic(path/'request.json',q)
  with self.assertRaises(ValueError):c.validated_response(path,self.fp)
 def test_foreign_fingerprint(self):
  path,q=self.begin();self.good(path,q)
  with self.assertRaises(ValueError):c.validated_response(path,'wrong')
 def test_bool_forecast(self):
  path,q=self.begin();self.good(path,q,True)
  with self.assertRaises(ValueError):c.validated_response(path,self.fp)
 def test_nonfinite_guard(self):
  path,q=self.begin()
  with self.assertRaises(ValueError):self.good(path,q,float('nan'))
 def test_old_unknown_retains_chronos(self):
  old=self.oldstate();before=c.sha(old);s=c.state(self.out,self.p,self.b,self.i,self.fp);self.assertEqual(s['chronos'],{'2024-07':2.});self.assertFalse(r.need(s,self.i,'prophet'));self.assertTrue(c.terminal(s,self.i));self.assertEqual(c.sha(old),before)
 def test_old_unknown_exact_sha(self):
  old=self.oldstate();old.write_text(old.read_text()+' ')
  with self.assertRaises(ValueError):c.state(self.out,self.p,self.b,self.i,self.fp)
 def test_old_pending_chronos_reusable(self):
  self.oldstate(False);s=c.state(self.out,self.p,self.b,self.i,self.fp);self.assertFalse(r.need(s,self.i,'chronos'));self.assertTrue(r.need(s,self.i,'prophet'))
 def test_full_registry_retains_terminal_unknown(self):
  self.oldstate();records,pending=c.outcome_registry(self.out,self.p,self.b,self.groups,self.i['rows'],[],self.fp,{('1018','Здоровье'):{24286:1.}},True);self.assertEqual(len(records),1);self.assertFalse(records[0]['paired_success']);self.assertIsNone(records[0]['pred_prophet_lag2']);self.assertEqual(pending,0)
 def test_attempt_cap_before_callback(self):
  c.atomic(self.out/'counters.json',{'prophet_fits':135396});called=[]
  with self.assertRaises(ValueError):c.call(self.out,self.p,self.b,self.groups,self.fp,'primary','prophet',[self.i],{},lambda *a:called.append(True))
  self.assertEqual(called,[]);self.assertEqual(list((self.out/'attempts').glob('*')),[])
 def test_control_cap(self):
  c.atomic(self.out/'counters.json',{'control_Chronos_calls':8})
  with self.assertRaises(ValueError):c.reserve_guard(self.out,'control1-repeat-chronos','chronos')
 def header(self):
  counters=c.counters(self.out,self.p,self.fp);c.atomic(self.out/'resource-ledger.json',{'cumulative_wall_s':self.p['historical_elapsed_seconds'],'counters':counters});h={'status':'CLOSED','fingerprint':self.fp,'counters':counters,'cumulative_wall_s':self.p['historical_elapsed_seconds'],'session_receipt_sha256':{},'ledger_events':[],'checkpoint_sha256':{},'journal_digest':c.journal_digest(self.out),'session_count':0};c.atomic(self.out/'supervision.json',h);return h
 def test_clean_continuity(self):self.header();self.assertEqual(r.continuity(self.out,self.p,self.fp)['status'],'CLOSED')
 def test_counter_rollback(self):
  self.header();c.atomic(self.out/'counters.json',{})
  with self.assertRaises(ValueError):r.continuity(self.out,self.p,self.fp)
 def test_started_blocks_even_recovery(self):
  h=self.header();h['status']='STARTED';c.atomic(self.out/'supervision.json',h)
  with self.assertRaises(ValueError):r.continuity(self.out,self.p,self.fp,True)
 def test_journal_mutation_blocks(self):
  path,q=self.begin();self.good(path,q);c.commit(path,self.out,self.p,self.b,self.groups,self.fp);self.header();c.atomic(path/'native-manifest.json',{'changed':True})
  with self.assertRaises(ValueError):r.continuity(self.out,self.p,self.fp)
 def test_checkpoint_addition_blocks(self):
  self.header();c.atomic(self.out/'checkpoints'/'rogue.json',{})
  with self.assertRaises(ValueError):r.continuity(self.out,self.p,self.fp)
 def test_unauthorized_dispatch_before_import(self):
  args=types.SimpleNamespace(dispatch=self.root/'absent',out=self.out)
  with patch.dict(os.environ,{},clear=True),self.assertRaises(ValueError):r.dispatch(args,{},self.fp,self.root/'no-lock')
 def test_stop_recovery_requires_cleanup(self):
  h=self.header();h['status']='STOP_REQUIRES_ZERO_MODEL_RECOVERY_REVIEW';h['owned_child_reaped_and_tree_empty']=False;c.atomic(self.out/'supervision.json',h)
  with self.assertRaises(ValueError):r.continuity(self.out,self.p,self.fp,True)
  h['owned_child_reaped_and_tree_empty']=True;c.atomic(self.out/'supervision.json',h);self.assertEqual(r.continuity(self.out,self.p,self.fp,True)['status'],h['status'])
 def test_normal_run_cannot_bypass_stopped(self):
  h=self.header();h['status']='STOP_REQUIRES_ZERO_MODEL_RECOVERY_REVIEW';h['owned_child_reaped_and_tree_empty']=True;c.atomic(self.out/'supervision.json',h)
  with self.assertRaises(ValueError):r.continuity(self.out,self.p,self.fp)
 def test_resolved_stage_blocks_before_callback(self):
  path,q=self.begin();self.good(path,q);c.commit(path,self.out,self.p,self.b,self.groups,self.fp);c.counters(self.out,self.p,self.fp);called=[]
  with self.assertRaises(ValueError):c.call(self.out,self.p,self.b,self.groups,self.fp,'primary','prophet',[self.i],{'fit':{'targets':['2024-07']}},lambda *a:called.append(True))
  self.assertEqual(called,[])
 def test_recovery_clears_stale_active_only_after_validation(self):
  path,q=self.begin();self.good(path,q);c.commit(path,self.out,self.p,self.b,self.groups,self.fp);c.atomic(self.out/'active-attempt.json',{'status':'STARTED','started_monotonic':0});c.recover(self.out,self.p,self.b,self.groups,self.fp);self.assertEqual(c.read(self.out/'active-attempt.json')['status'],'IDLE')
 def test_cleanup_instrumentation_failure_reaps_direct_owned(self):
  calls=[];child=object();b=types.SimpleNamespace(own_descendants=lambda pid:(_ for _ in ()).throw(PermissionError()),stop_owned_group=lambda handle:calls.append(handle))
  with self.assertRaises(PermissionError):r.terminate_child(child,b)
  self.assertEqual(calls,[child])
 def test_namespace_overlap(self):
  protocol=self.root/'p.json';c.atomic(protocol,{'ancestral_path':str(self.old)})
  with self.assertRaises(ValueError):r.canonical(types.SimpleNamespace(protocol=protocol,out=self.old/'evil'))
class OperationalGuards(unittest.TestCase):
 setUp=Fixtures.setUp
 tearDown=Fixtures.tearDown
 header=Fixtures.header
 oldstate=Fixtures.oldstate
 begin=Fixtures.begin
 good=Fixtures.good
 def make_chain(self,n=2,last_wall=None,status='CLOSED'):
  h=self.header();events=[];previous=self.p['historical_elapsed_seconds'];before=dict(self.p['historical_counters']);after=c.counters(self.out,self.p,self.fp)
  for i in range(1,n+1):
   wall=(last_wall if i==n and last_wall is not None else previous+1)
   q={'fingerprint':self.fp,'session_count':i,'status':status if i==n else 'CLOSED','mode':'run','previous_cumulative_wall_s':previous,'cumulative_wall_s':wall,'counters_before':before,'counters':after,'owned_child_reaped_and_tree_empty':True}
   file=self.out/'sessions'/f'session-{i:03d}.json';c.atomic(file,q);events.append({'kind':'session','path':str(file.relative_to(self.out)),'SHA':c.sha(file)});previous=wall;before=after
  h.update(session_count=n,cumulative_wall_s=previous,counters=after,session_receipt_sha256=r.session_pins(self.out),ledger_events=events,status=status,owned_child_reaped_and_tree_empty=True);c.atomic(self.out/'supervision.json',h);c.atomic(self.out/'resource-ledger.json',{'cumulative_wall_s':previous,'counters':after});return h
 def reporting_b(self):
  self.b.own_descendants=lambda pid:[]
  mock=patch.object(r,'rss_admission',return_value={});mock.start();self.addCleanup(mock.stop)
  self.b.digest_keys=lambda keys:hashlib.sha256(json.dumps(sorted(keys)).encode()).hexdigest();return self.b
 def fake_inputs(self):return {('1018','Здоровье'):{24286:1.}},self.i['rows'],self.groups,[]
 def test_B2_reporting_startup_charge_conserved(self):
  self.header();self.reporting_b()
  with patch.object(r,'inputs',return_value=self.fake_inputs()),patch.object(r,'rss_admission',return_value={}),patch.object(r,'disk_admission',return_value={}),patch.object(r.time,'monotonic',return_value=100):r.terminal_registry(self.args(),self.p,self.b,self.fp,'FIXTURE',charge_started=0)
  self.assertEqual(r.continuity(self.out,self.p,self.fp)['cumulative_wall_s'],self.p['historical_elapsed_seconds']+100)
 def test_B2_early_stop_charges_supervisor_startup(self):
  self.header();self.make_chain(n=1,last_wall=107999);self.reporting_b()
  with patch.object(r,'inputs',return_value=self.fake_inputs()),patch.object(r,'disk_admission',return_value={}),patch.object(r.time,'monotonic',return_value=100),patch.object(r,'deadline',return_value=1000000):r.supervise(self.args(),self.p,self.b,self.fp,self.root/'unused',startup_charge=100)
  self.assertEqual(r.continuity(self.out,self.p,self.fp)['cumulative_wall_s'],108099)
 def test_B2_public_report_failed_RSS_still_charges_validation(self):
  self.header();clock=[0];args=types.SimpleNamespace(out=self.out,mode='report',dispatch=None)
  def validation(args):clock[0]=50;return self.p,self.b,{}
  with patch.object(r,'parser',return_value=types.SimpleNamespace(parse_args=lambda:args)),patch.object(r,'canonical',return_value=(self.out,self.root/'lock')),patch.object(r,'fingerprint',return_value=self.fp),patch.object(r,'validate',side_effect=validation),patch.object(r,'check_namespace'),patch.object(r,'rss_admission',side_effect=ValueError('unsafe fixtureRSS')),patch.object(r,'disk_admission',return_value={}),patch.object(r.time,'monotonic',side_effect=lambda:clock[0]):r.main()
  self.assertEqual(r.continuity(self.out,self.p,self.fp)['cumulative_wall_s'],self.p['historical_elapsed_seconds']+50);self.assertTrue((self.out/'terminal-accounting-deferred.json').exists())
 def test_B3_unresolved_owned_lifecycle_defers_without_full_inputs(self):
  self.header();h=self.make_chain(n=1,status='STOP_REQUIRES_ZERO_MODEL_RECOVERY_REVIEW');h['owned_child_reaped_and_tree_empty']=False;c.atomic(self.out/'supervision.json',h)
  with patch.object(r,'inputs',side_effect=AssertionError('nofullreport')),patch.object(r,'rss_admission',side_effect=AssertionError('noguardprocessqueries')):r.terminal_registry(self.args(),self.p,self.b,self.fp,'STOP_OWNERSHIP_UNRESOLVED')
  self.assertFalse(c.read(self.out/'completion.json')['registry_materialized']);self.assertIn('unresolved owned lifecycle',c.read(self.out/'terminal-accounting-deferred.json')['report_error']);self.assertFalse(c.read(self.out/'supervision.json')['owned_child_reaped_and_tree_empty'])
 def test_B2_CLOSED_header_with_unresolved_owned_tree_rejects(self):
  self.header();h=self.make_chain(n=1);h['owned_child_reaped_and_tree_empty']=False;c.atomic(self.out/'supervision.json',h)
  with self.assertRaises(ValueError):r.continuity(self.out,self.p,self.fp)
 def test_B3_CLOSED_noninitial_unresolved_tree_cannot_fullreport(self):
  self.header();h=self.make_chain(n=1);h['owned_child_reaped_and_tree_empty']=False;c.atomic(self.out/'supervision.json',h)
  with patch.object(r,'inputs',side_effect=AssertionError('nofullreport')):r.terminal_registry(self.args(),self.p,self.b,self.fp,'BAD_CLOSED_TREE')
  self.assertFalse(c.read(self.out/'completion.json')['registry_materialized'])
 def args(self):return types.SimpleNamespace(out=self.out,mode='run')
 def test_B1_free_before_probe_spawn(self):
  self.header();probe=[];spawn=[];self.b.resource_preflight=lambda *a:probe.append(1)
  with patch.object(r.shutil,'disk_usage',return_value=types.SimpleNamespace(free=0)),patch.object(r.subprocess,'Popen',side_effect=lambda *a,**k:spawn.append(1)),patch.object(r,'deadline',return_value=1000000):
   result=r.supervise(self.args(),self.p,self.b,self.fp,self.root/'unused-lock')
  self.assertEqual(result,'TERMINAL_RESOURCE_STOP');self.assertEqual((probe,spawn),([],[]));self.assertTrue((self.out/'admission-failure.json').exists());self.assertTrue((self.out/'completion.json').exists())
 def test_B1_output_cap_before_probe_spawn(self):
  self.header();probe=[];spawn=[];self.b.resource_preflight=lambda *a:probe.append(1)
  with patch.object(r,'disk_admission',side_effect=ValueError('overcap')),patch.object(r.subprocess,'Popen',side_effect=lambda *a,**k:spawn.append(1)),patch.object(r,'deadline',return_value=1000000):r.supervise(self.args(),self.p,self.b,self.fp,self.root/'unused')
  self.assertEqual((probe,spawn),([],[]))
 def test_B1_measurement_error_failclosed(self):
  self.header()
  with patch.object(r.shutil,'disk_usage',side_effect=PermissionError()),self.assertRaises(ValueError):r.disk_admission(self.out,self.p,'fixture')
  self.assertTrue((self.out/'admission-failure.json').exists())
 def test_B1_exact_output_measurement_overcap(self):
  fake=types.SimpleNamespace(is_file=lambda:True,stat=lambda:types.SimpleNamespace(st_size=3221225473))
  with patch.object(r.shutil,'disk_usage',return_value=types.SimpleNamespace(free=2147483648)),patch.object(Path,'rglob',return_value=[fake]),self.assertRaises(ValueError):r.disk_admission(self.out,self.p,'overcap')
 def test_B1_prepare_gate_before_large_writes(self):
  fresh=self.root/'fresh';args=types.SimpleNamespace(out=fresh,mode='prepare',dispatch=None)
  with patch.object(r,'parser',return_value=types.SimpleNamespace(parse_args=lambda:args)),patch.object(r,'canonical',return_value=(fresh,self.root/'nolock')),patch.object(r,'fingerprint',return_value=self.fp),patch.object(r,'validate',return_value=(self.p,self.b,{})),patch.object(r.shutil,'disk_usage',return_value=types.SimpleNamespace(free=0)),self.assertRaises(ValueError):r.main()
  self.assertFalse(fresh.exists())
 def test_B1_RSS_guard_is_known_owned_and_failclosed(self):
  self.b.own_descendants=lambda pid:[7];calls=[]
  reader=lambda pid:(calls.append(pid) or 1073741825)
  with self.assertRaises(ValueError):r.rss_admission(self.out,self.b,'fixture',reader)
  self.assertEqual(calls,[os.getpid(),7]);self.assertTrue((self.out/'rss-admission-failure.json').exists())
 def test_B1_RSS_measurement_failure_no_native_probe(self):
  self.header();probe=[];spawn=[];self.b.resource_preflight=lambda *a:probe.append(1)
  with patch.object(r,'disk_admission',return_value={'PASS':True}),patch.object(r,'rss_admission',side_effect=ValueError('measurement')),patch.object(r.subprocess,'Popen',side_effect=lambda *a,**k:spawn.append(1)),patch.object(r,'inputs',side_effect=RuntimeError('report deferred')),patch.object(r,'deadline',return_value=1000000):r.supervise(self.args(),self.p,self.b,self.fp,self.root/'unused')
  self.assertEqual((probe,spawn),([],[]))
 def test_B1_second_gate_blocks_child_after_clean_probe(self):
  self.header();self.reporting_b();self.b.own_descendants=lambda pid:[];probe=[];spawn=[];self.b.resource_preflight=lambda *a:probe.append(1);lock=self.root/'lock';c.atomic(lock,{'nonce':'owner'})
  def gate(out,p,phase):
   if phase=='parent-before-child-spawn':raise ValueError('resourcechanged afterprobe')
   return {'PASS':True}
  with patch.object(r,'disk_admission',side_effect=gate),patch.object(r,'rss_admission',return_value={'PASS':True}),patch.object(r.subprocess,'Popen',side_effect=lambda *a,**k:spawn.append(1)),patch.object(r,'inputs',return_value=self.fake_inputs()),patch.object(r,'deadline',return_value=1000000),self.assertRaises(ValueError):r.supervise(self.args(),self.p,self.b,self.fp,lock)
  self.assertEqual(probe,[1]);self.assertEqual(spawn,[]);self.assertEqual(r.continuity(self.out,self.p,self.fp,True)['session_count'],1)
 def test_B2_finite_numerical_floor(self):
  for bad in (-100000,10,float('inf'),float('nan'),True,'961'):
   h=self.header();h['cumulative_wall_s']=bad;(self.out/'supervision.json').write_text(json.dumps(h));(self.out/'resource-ledger.json').write_text(json.dumps({'cumulative_wall_s':bad,'counters':h['counters']}))
   with self.assertRaises(ValueError):r.continuity(self.out,self.p,self.fp)
 def test_B2_valid_numbered_chain(self):self.make_chain();self.assertEqual(r.continuity(self.out,self.p,self.fp)['session_count'],2)
 def test_B2_latest_receipt_changed(self):
  self.make_chain();file=self.out/'sessions/session-002.json';file.write_text(file.read_text()+' ')
  with self.assertRaises(ValueError):r.continuity(self.out,self.p,self.fp)
 def test_B2_latest_receipt_missing(self):
  self.make_chain();(self.out/'sessions/session-002.json').unlink()
  with self.assertRaises(ValueError):r.continuity(self.out,self.p,self.fp)
 def test_B2_count_rollback(self):
  h=self.make_chain();h['session_count']=1;c.atomic(self.out/'supervision.json',h)
  with self.assertRaises(ValueError):r.continuity(self.out,self.p,self.fp)
 def test_B2_matching_wall_files_not_matching_last_session(self):
  h=self.make_chain();h['cumulative_wall_s']+=10;c.atomic(self.out/'supervision.json',h);c.atomic(self.out/'resource-ledger.json',{'cumulative_wall_s':h['cumulative_wall_s'],'counters':h['counters']})
  with self.assertRaises(ValueError):r.continuity(self.out,self.p,self.fp)
 def test_B2_decreasing_chain_even_updated_hashes(self):
  h=self.make_chain();file=self.out/'sessions/session-002.json';q=c.read(file);q['cumulative_wall_s']=q['previous_cumulative_wall_s']-.1;c.atomic(file,q);h['session_receipt_sha256']=r.session_pins(self.out);h['ledger_events'][-1]['SHA']=c.sha(file);h['cumulative_wall_s']=q['cumulative_wall_s'];c.atomic(self.out/'supervision.json',h);c.atomic(self.out/'resource-ledger.json',{'cumulative_wall_s':q['cumulative_wall_s'],'counters':h['counters']})
  with self.assertRaises(ValueError):r.continuity(self.out,self.p,self.fp)
 def test_B3_budget_stop_emits_full_registry_without_MAE_or_spawn(self):
  self.oldstate();self.make_chain(n=1,last_wall=107999);probe=[];spawn=[];self.b.resource_preflight=lambda *a:probe.append(1);self.reporting_b()
  with patch.object(r,'inputs',return_value=self.fake_inputs()),patch.object(r.shutil,'disk_usage',return_value=types.SimpleNamespace(free=2147483648)),patch.object(r,'finalize',side_effect=AssertionError('MAE forbidden')),patch.object(r.subprocess,'Popen',side_effect=lambda *a,**k:spawn.append(1)),patch.object(r,'deadline',return_value=1000000):result=r.supervise(self.args(),self.p,self.b,self.fp,self.root/'unused')
  proof=c.read(self.out/'terminal-accounting.json');self.assertTrue(proof['registry_materialized']);self.assertEqual(proof['requested_rows'],1);self.assertEqual(proof['paired_success_rows'],0);self.assertFalse(proof['MAE_computed']);self.assertEqual((probe,spawn),([],[]));self.assertEqual(result,'TERMINAL_RESOURCE_STOP');r.continuity(self.out,self.p,self.fp)
 def test_B3_UNKNOWN_unreturned_not_pending_or_retry(self):
  path,q=self.begin();c.counters(self.out,self.p,self.fp);self.make_chain(n=1,status='STOP_REQUIRES_ZERO_MODEL_RECOVERY_REVIEW');self.reporting_b()
  with patch.object(r,'inputs',return_value=self.fake_inputs()),patch.object(r.shutil,'disk_usage',return_value=types.SimpleNamespace(free=2147483648)),patch.object(r,'finalize',side_effect=AssertionError('MAE forbidden')):r.terminal_registry(self.args(),self.p,self.b,self.fp,'FIXTURE_STOP')
  text=(self.out/'row-statuses.jsonl').read_text();self.assertIn('UNKNOWN_STOP',text);self.assertIn('RESOURCE_NOT_ATTEMPTED:FIXTURE_STOP',text);self.assertNotIn('PENDING',text);self.assertFalse((path/'response.json').exists());r.continuity(self.out,self.p,self.fp,True)
 def test_B3_durable_response_no_commit_without_review(self):
  path,q=self.begin();self.good(path,q);c.counters(self.out,self.p,self.fp);self.make_chain(n=1,status='STOP_REQUIRES_ZERO_MODEL_RECOVERY_REVIEW');self.reporting_b()
  with patch.object(r,'inputs',return_value=self.fake_inputs()),patch.object(r.shutil,'disk_usage',return_value=types.SimpleNamespace(free=2147483648)):r.terminal_registry(self.args(),self.p,self.b,self.fp,'FIXTURE_STOP')
  self.assertIn('DURABLE_RESPONSE_REQUIRES_REVIEWED_COMMIT',(self.out/'row-statuses.jsonl').read_text());self.assertEqual(c.read(path/'status.json')['status'],'STARTED')
 def test_B3_lowdisk_deferred_receipt_is_honest(self):
  self.header()
  with patch.object(r.shutil,'disk_usage',return_value=types.SimpleNamespace(free=0)):r.terminal_registry(self.args(),self.p,self.b,self.fp,'DISK_STOP')
  self.assertFalse(c.read(self.out/'completion.json')['registry_materialized']);self.assertTrue((self.out/'terminal-accounting-deferred.json').exists());self.assertFalse((self.out/'row-statuses.jsonl').exists());r.continuity(self.out,self.p,self.fp)

if __name__=='__main__':unittest.main()
