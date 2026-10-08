from pathlib import Path
import sys,importlib.util,json,math,tempfile,unittest
HERE=Path(__file__).resolve().parent
SOURCE=HERE if (HERE/'r11_chronos2_full.py').exists() else HERE.parent/'shock-radar/src'
sys.path.insert(0,str(SOURCE));sys.path.insert(0,str(HERE.parent))
spec=importlib.util.spec_from_file_location('full',SOURCE/'r11_chronos2_full.py');r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)
spec=importlib.util.spec_from_file_location('worker',SOURCE/'r11_prophet_worker.py');w=importlib.util.module_from_spec(spec);spec.loader.exec_module(w)

def row(tid='x',origin='2024-06',h=1):
 return {'territory_id':tid,'category':'c','origin':origin,'horizon':h,'target':r.base.ym(r.base.month(origin)+h),'actual':10.,'pred_prophet':9.}

def item(tid='x',origin='2024-06',horizons=(1,6),n=17):
 rows=[row(tid,origin,h) for h in horizons];cutoff=r.base.month(origin)-2
 return {'key':(tid,'c',origin),'cutoff':cutoff,'context':[float(cutoff-n+1+i) for i in range(n)],'rows':rows,'cached_prophet':{}}

class FakeNative:
 def __init__(self):self.calls=0
 def predict_quantiles(self,inputs,prediction_length,**kwargs):
  import torch
  self.calls+=1;self.kwargs=kwargs
  medians=[torch.tensor([[float(values[-1])+i for i in range(1,prediction_length+1)]]) for values in inputs]
  return [m.unsqueeze(-1) for m in medians],medians

class Tests(unittest.TestCase):
 def test_native_batch_calendar_matches_each_single_and_no_crosslearning(self):
  a=item();b=item('y','2024-05',(6,),n=15);pipe=FakeNative();batched=r.batch_predict(pipe,[a,b]);self.assertFalse(pipe.kwargs['cross_learning']);self.assertEqual(pipe.kwargs['batch_size'],2)
  self.assertEqual(batched,r.batch_predict(pipe,[a])|r.batch_predict(pipe,[b]))
  for i in [a,b]:
   for row in i['rows']:self.assertEqual(batched[r.group_id(i['key'])][row['target']],r.base.month(row['target']))
 def test_reject_mixed_step_bucket(self):
  with self.assertRaisesRegex(ValueError,'buckets'):r.batch_predict(FakeNative(),[item(horizons=(1,)),item('y',horizons=(6,))])
 def test_sparse_calendar_nan_preserved(self):
  obs={r.base.month('2023-01')+i:float(i) for i in range(7)};del obs[r.base.month('2023-03')]
  cutoff,v=r.base.causal_context(obs,'2023-09',2);self.assertEqual(len(v),7);self.assertTrue(math.isnan(v[2]));self.assertEqual(cutoff,r.base.month('2023-07'))
 def test_exact_cache_reuse_and_actual_guard(self):
  a=row();b=row(h=6);g=('x','c','2024-06');contexts={g:(r.base.month('2024-04'),list(range(16)))};cache={r.base.key(a):{**a,'pred_prophet':11.}}
  groups,excluded,reused=r.build_groups([a,b],contexts,cache);self.assertEqual(reused,1);self.assertEqual(groups[g]['cached_prophet'],{'2024-07':11.});self.assertFalse(excluded)
  cache[r.base.key(a)]['actual']=999
  with self.assertRaisesRegex(ValueError,'actual'):r.build_groups([a,b],contexts,cache)
 def test_history_exclusion_never_zero_filled(self):
  a=row();g=('x','c','2024-06');groups,excluded,reused=r.build_groups([a],{g:(r.base.month('2024-04'),[1,2,3,4,5,float('nan')])},{})
  self.assertFalse(groups);self.assertEqual(excluded,[r.base.key(a)])
 def test_worker_fitonce_real_dates_many_targets_and_future_guard(self):
  req={'cutoff':'2023-06','train':[[f'2023-{m:02d}',float(m)] for m in range(1,7)],'targets':['2023-09','2024-08'],'seed':20260927};seen=[]
  def spy(train,targets,seed):seen.append((train,targets,seed));return [float(r.base.month(str(t))) for t in targets]
  result=w.fit(req,spy);self.assertEqual(len(seen),1);self.assertEqual(result['2024-08'],r.base.month('2024-08'));self.assertEqual(str(seen[0][1][0])[:7],'2023-09')
  req['train'].append(['2023-07',7.])
  with self.assertRaisesRegex(ValueError,'future'):w.fit(req,spy)
 def test_cached_predictions_do_not_serialize_fitted_model(self):
  i=item();i['cached_prophet']={'2024-07':10.};obs={('x','c'):{r.base.month('2023-01')+m:float(m) for m in range(24)}};req=r.cache_request(i,obs)
  self.assertEqual(req['targets'],['2024-12']);self.assertTrue(all(d<='2024-04' for d,v in req['train']))
 def test_checkpoint_resume_skips_known_predictions_and_blocks_uncertain(self):
  i=item()
  with tempfile.TemporaryDirectory(dir=HERE) as tmp:
   out=Path(tmp);state=r.read_checkpoint(out,i,'f');state.update(status='complete',chronos={'2024-07':1.},prophet={'2024-07':2.});r.save_checkpoint(out,i,state);self.assertEqual(r.read_checkpoint(out,i,'f')['chronos'],state['chronos'])
   with self.assertRaisesRegex(ValueError,'mismatch'):r.read_checkpoint(out,i,'other')
   state['uncertain_inflight']='prophet';r.save_checkpoint(out,i,state)
   with self.assertRaisesRegex(ValueError,'review'):r.read_checkpoint(out,i,'f')
 def test_fixed_batch_membership_independent_of_resume_status(self):
  groups={}
  for n in range(1020):
   i=item(str(n),horizons=(1,));groups[i['key']]=i
  before=[[i['key'] for i in batch] for batch in r.fixed_batches(groups)]
  for i in groups.values():i['cached_prophet']={r['target']:0. for r in i['rows']}
  after=[[i['key'] for i in batch] for batch in r.fixed_batches(groups)]
  self.assertEqual(before,after);self.assertTrue(all(len(b)<=16 for b in before));self.assertEqual(sum(map(len,before)),1020)
 def test_every_requested_key_accounted_and_no_partial_metric(self):
  i=item(horizons=(1,));excluded=tuple(r.base.key(row('bad')));rows=i['rows']+[row('bad')];groups={i['key']:i};obs={('x','c'):{}}
  with tempfile.TemporaryDirectory(dir=HERE) as tmp:
   out=Path(tmp);records,complete=r.emit_statuses(out,rows,groups,[excluded],'f',obs);self.assertFalse(complete);self.assertEqual(records,[]);coverage=json.loads((out/'coverage.json').read_text());self.assertEqual(sum(coverage['counts'].values()),2)
   with self.assertRaisesRegex(ValueError,'coverage'):r.emit_statuses(out,rows,groups,[excluded],'f',obs,require_complete=True)
 def test_exact_monthbootstrap_not_rowbootstrap(self):
  data=[{'target':'2024-07','difference':-2.},{'target':'2024-08','difference':2.}];ci=r.month_interval(data);self.assertEqual(ci['resamples'],4);self.assertAlmostEqual(ci['low'],-1.85);self.assertAlmostEqual(ci['high'],1.85);self.assertEqual(ci['unit'],'targetmonth')
 def test_cluster_MO_uncertainty_keeps_rows_together_constant_oracle(self):
  data=[{'territory_id':tid,'actual':0.,'pred_chronos2':3.,'pred_prophet_lag2':2.} for tid in ['x','x','y']]
  ci=r.mo_interval(data,'pred_prophet_lag2');self.assertEqual(ci['units'],2);self.assertEqual(ci['resamples'],1000);self.assertEqual(ci['low'],1.);self.assertEqual(ci['high'],1.);self.assertFalse(ci['independence_claimed'])
 def test_failed_resource_probe_preserves_receipt_and_own_cleanup_before_models(self):
  with tempfile.TemporaryDirectory(dir=HERE) as tmp:
   def denied(pid):raise PermissionError('simulatedRSS denial')
   with self.assertRaisesRegex(RuntimeError,'preflight'):r.resource_preflight(Path(tmp),reader=denied)
   receipt=json.loads((Path(tmp)/'resource-preflight.json').read_text());self.assertEqual(receipt['status'],'INCONCLUSIVE_BEFORE_MODEL_CALLS');self.assertTrue(receipt['owned_group_removed']);self.assertEqual(receipt['new_model_calls'],0)
 def test_failed_worker_readiness_reaps_owned_child_and_clears_handle(self):
  with tempfile.TemporaryDirectory(dir=HERE) as tmp:
   out=Path(tmp);ref=[None];seen=[]
   # Capture child handle for independent wait/poll proof; no Prophet/model import.
   original=r.subprocess.Popen
   def capture(*args,**kwargs):
    p=original(*args,**kwargs);seen.append(p);return p
   r.subprocess.Popen=capture
   try:
    with self.assertRaisesRegex(RuntimeError,'timeout'):r.Worker(sys.executable,Path('unused'),out,ref,_timeout=.05,_command=[sys.executable,'-c','import time;time.sleep(10)'])
   finally:r.subprocess.Popen=original
   self.assertIsNone(ref[0]);self.assertIsNotNone(seen[0].poll());self.assertTrue(seen[0].stdout.closed)
 def test_invalid_ready_worker_ignoring_TERM_is_KILLed_only_own_group(self):
  with tempfile.TemporaryDirectory(dir=HERE) as tmp:
   out=Path(tmp);ref=[None];seen=[];original=r.subprocess.Popen
   def capture(*args,**kwargs):
    p=original(*args,**kwargs);seen.append(p);return p
   r.subprocess.Popen=capture
   try:
    command=[sys.executable,'-c',"import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);print('not-json',flush=True);time.sleep(10)"]
    with self.assertRaises(json.JSONDecodeError):r.Worker(sys.executable,Path('unused'),out,ref,_timeout=2,_command=command)
   finally:r.subprocess.Popen=original
   self.assertIsNone(ref[0]);self.assertIsNotNone(seen[0].poll());self.assertEqual(seen[0].returncode,-9)
 def test_partial_ready_line_does_not_bypass_readiness_timeout(self):
  with tempfile.TemporaryDirectory(dir=HERE) as tmp:
   ref=[None];seen=[];original=r.subprocess.Popen
   def capture(*args,**kwargs):
    p=original(*args,**kwargs);seen.append(p);return p
   r.subprocess.Popen=capture
   try:
    command=[sys.executable,'-c',"import sys,time;sys.stdout.write('partial');sys.stdout.flush();time.sleep(10)"]
    with self.assertRaisesRegex(RuntimeError,'timeout'):r.Worker(sys.executable,Path('unused'),Path(tmp),ref,_timeout=.1,_command=command)
   finally:r.subprocess.Popen=original
   self.assertIsNone(ref[0]);self.assertIsNotNone(seen[0].poll())
 def test_frozen_full_v3_and_smoke_hashes(self):
  protocol=HERE.parent/'FULL_EVAL_PROTOCOL_V3.json' if (HERE.parent/'FULL_EVAL_PROTOCOL_V3.json').exists() else SOURCE.parent/'protocol/chronos2_full_fair_v3_20261007.json'
  smoke=HERE.parent/'PROTOCOL.json' if (HERE.parent/'PROTOCOL.json').exists() else SOURCE.parent/'protocol/chronos2_causal_r9mask_20261007.json'
  self.assertEqual(r.base.sha(protocol),r.FULL_PROTOCOL_SHA);self.assertEqual(r.base.sha(smoke),r.SMOKE_PROTOCOL_SHA);self.assertEqual(r.base.sha(Path(r.base.__file__)),r.BASE_RUNNER_SHA)
if __name__=='__main__':unittest.main()
