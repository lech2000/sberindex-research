"""R13 prospective full-registry amendment. Default prepare has zero model calls."""
from pathlib import Path
import argparse,collections,copy,datetime,hashlib,importlib.util,json,math,os,secrets,signal,subprocess,sys,time,shutil
for k in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS']:os.environ[k]='1'
os.environ['HF_HUB_OFFLINE']='1';os.environ['TRANSFORMERS_OFFLINE']='1';sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parent));import r13_registry_core as core
PROTOCOL_SHA='9409ccf7e7ef608bb490eccd45aab22e1dc3dc731c883a2c38431084fbedea01'
ORIGINAL_SHA='9a14b867953ed6065396b5b6c8cd04238f2919838c07d1fd1ed958c9b082d0cb'
def load(path,name):
 s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

def deadline(p):return (datetime.datetime.fromisoformat(p['resource_plan']['absolute_deadline_UTC'].replace('Z','+00:00'))-datetime.datetime.now(datetime.timezone.utc)).total_seconds()
def parser():
 a=argparse.ArgumentParser()
 for n in ['protocol','view','raw','paired','weights-dir','out','prophet-python']:a.add_argument('--'+n,type=Path,required=True)
 a.add_argument('--mode',choices=['prepare','run','recover','report'],default='prepare');a.add_argument('--dispatch',type=Path,help=argparse.SUPPRESS);return a

def validate(args):
 if core.sha(args.protocol)!=PROTOCOL_SHA:raise ValueError('frozen R13 protocol changed')
 p=core.read(args.protocol);v=args.view.resolve();source=v/'shock-radar/src/r11_chronos2_full.py'
 if core.sha(source)!=ORIGINAL_SHA:raise ValueError('original numerical source changed')
 for name,expected in [('r10_chronos2_causal.py','22b1572067518fc654dcad1fb7affc63a2f6691b156dfb7ebeb9c1af5978bebe'),('r11_prophet_worker.py','7ca3c5df48dca2ee63aefb1ca07a8f43e3acb76c5d96e1babddd1c5f0520fea6')]:
  if core.sha(source.with_name(name))!=expected:raise ValueError('original causal/estimator wrapper source changed')
 for name,expected in [('chronos2_causal_r9mask_20261007.json','3130f59c03c94908c491fddba63b02bb59911135ce2bab07fef1963c04226893'),('chronos2_full_cluster_mo_20261007.json','beef21e636c46a0e6cafdec70d678134986f35308d8236b92b34d37a8f647d87')]:
  if core.sha(v/'shock-radar/protocol'/name)!=expected:raise ValueError('original causal/uncertainty protocol changed')
 sys.path.insert(0,str(source.parent));b=load(source,'pinned_r11')
 for relative,expected in p['ancestral_snapshot'].items():
  if core.sha(Path(p['ancestral_path'])/relative)!=expected:raise ValueError('ancestral artifact changed: '+relative)
 for file,expected in [('raw',p['input_sha256']['raw']),('paired',p['input_sha256']['paired'])]:
  if core.sha(getattr(args,file))!=expected:raise ValueError('input SHA')
 for name,expected in [('model.safetensors',p['model']['weight_sha256']),('config.json',p['model']['config_sha256'])]:
  if core.sha(args.weights_dir/name)!=expected:raise ValueError('pinned model bytes')
 full=core.read(v/'shock-radar/protocol/chronos2_full_fair_v3_20261007.json')
 if core.sha(v/'shock-radar/protocol/chronos2_full_fair_v3_20261007.json')!=p['original_full_protocol_SHA'] or full['model']!=p['model'] or full['primary_mask']!=p['frozen_primary_mask'] or full['controls']!=p['controls']:raise ValueError('original scientific method/mask/control unchanged')
 return p,b,full

def inputs(args,p,b):
 smoke=core.read(args.view/'shock-radar/protocol/chronos2_causal_r9mask_20261007.json');smoke['input_paths']={'raw':str(args.raw),'paired':str(args.paired)}
 obs,rows,contexts,_,_=b.base.load_inputs(smoke)
 cache=args.view/'shock-radar/runs/R8_prophet_full_20260927';source=args.view/'shock-radar/src/r8_prophet_batch.py'
 if core.sha(source)!=b.PROPHET_SOURCE_SHA or core.sha(cache/'predictions.parquet')!=b.CACHE_SHA or core.sha(cache/'manifest.json')!='5630c677fb893a25cfacca918cdca8d784f5533fec3e2c719e2987a9fdfe69cc' or core.sha(cache/'fingerprint.json')!='c2ac8d8248b6c0872a2aee8509755810419e39d7ecde0f688c8f282d7031f52b':raise ValueError('cache/source SHA')
 f=core.read(cache/'fingerprint.json');m=core.read(cache/'manifest.json')
 if (f['raw_sha256'],f['seed'],f['release_lag'],f['min_train_points'],f['code_sha256'])!=(p['input_sha256']['raw'],20260927,2,6,b.PROPHET_SOURCE_SHA):raise ValueError('strict cache matching')
 config={'growth':'linear','yearly_seasonality':False,'weekly_seasonality':False,'daily_seasonality':False,'n_changepoints':3,'uncertainty_samples':0}
 if any(m['model'].get(k)!=v for k,v in config.items()):raise ValueError('cacheconfig')
 import pandas as pd
 frame=pd.read_parquet(cache/'predictions.parquet');frame.territory_id=frame.territory_id.astype(str);cached={b.base.key(r):r for r in frame.to_dict('records')};del frame
 if len(cached)!=171150:raise ValueError('cache duplicate/count')
 groups,excluded,reused=b.build_groups(rows,contexts,cached);del cached,contexts
 if len(rows)!=294570 or len(groups)!=196566 or len(excluded)!=12450 or reused!=109938 or b.digest_keys([b.base.key(r) for i in groups.values() for r in i['rows']])!=p['frozen_primary_mask']['canonical_keys_sha256']:raise ValueError('full registered mask')
 return obs,rows,groups,excluded

def code_id():return {p.name:core.sha(p) for p in [Path(__file__),Path(core.__file__),Path(__file__).with_name('r13_prophet_journal_worker.py')]}
def fingerprint(args):return hashlib.sha256(json.dumps({'protocol':core.sha(args.protocol),'code':code_id(),'view':str(args.view.resolve()),'raw':str(args.raw.resolve()),'paired':str(args.paired.resolve()),'weights':str(args.weights_dir.resolve()),'prophet_python':str(args.prophet_python)},sort_keys=True).encode()).hexdigest()
def check_namespace(args,fp):
 if core.read(args.out/'fingerprint.json')['fingerprint']!=fp:raise ValueError('namespace fingerprint mismatch')

def request_chronos(p,b,batch):return {'model':p['model'],'prediction_length':max(b.base.month(r['target'])-i['cutoff'] for i in batch for r in i['rows']),'cross_learning':False,'context_length':24,'batch_size':len(batch),'inputs':{b.group_id(i['key']):[x.hex() if math.isfinite(x) else None for x in map(float,i['context'])] for i in batch}}
def need(s,item,model):return any(str(r['target']) not in s[model] and str(r['target']) not in s['terminal'][model] for r in item['rows'])

def freeze_worker(out,args,p,fp):
 token=secrets.token_hex(32);path=out/('worker-authority-'+secrets.token_hex(12)+'.json')
 core.atomic(path,{'parent_pid':os.getpid(),'secret_SHA':hashlib.sha256(token.encode()).hexdigest(),'worker_SHA':core.sha(Path(__file__).with_name('r13_prophet_journal_worker.py')),'original_runner_SHA':ORIGINAL_SHA,'prophet_source_SHA':'b9e7e993cf90e2e290001c7067fda36ed9684a900dee0ffa9d656e424ef97bf1','view':str(args.view.resolve()),'out':str(out.resolve()),'fingerprint':fp})
 os.environ['R13_WORKER_SECRET']=token;return path

def model_load(args,b,out):
 import torch,importlib.metadata
 from chronos import Chronos2Pipeline
 versions={n:importlib.metadata.version(n) for n in ['chronos-forecasting','torch','transformers','pandas','numpy','psutil']}
 if any(versions[k]!=v for k,v in {'chronos-forecasting':'2.3.2','torch':'2.14.0','transformers':'5.17.0','pandas':'2.3.3','numpy':'2.5.3'}.items()):raise ValueError('original model dependencies')
 torch.set_num_threads(1);torch.set_num_interop_threads(1);torch.manual_seed(20261007)
 pipe=Chronos2Pipeline.from_pretrained(str(args.weights_dir),device_map='cpu',torch_dtype=torch.float32,local_files_only=True);pipe.model.eval()
 if pipe.model.__class__.__name__!='Chronos2Model' or pipe.model.device.type!='cpu' or next(pipe.model.parameters()).dtype!=torch.float32:raise ValueError('model CPUfloat32')
 core.atomic(out/'model-metadata.json',{'class':pipe.model.__class__.__name__,'device':str(pipe.model.device),'dtype':str(next(pipe.model.parameters()).dtype),'threads':torch.get_num_threads(),'versions':versions});return pipe

class PlannedYield(Exception):pass

def controls(args,p,b,out,groups,obs,fp,pipe,worker,started):
 for h in [1,3,6,12]:
  path=out/f'control-h{h}.json'
  if path.exists():continue
  k=p['controls']['frozen_four_examples'][str(h)]['key'];g=tuple(k[:3]);item=groups[g];s=core.state(out,p,b,item,fp);target=k[4]
  if target not in s['chronos'] or target not in s['prophet']:
   core.atomic(path,{'pass':False,'status':'CONTROL_UNAVAILABLE_PRIMARY_FAILURE'});continue
  batch=next(x for x in b.fixed_batches(groups) if any(i['key']==g for i in x));changed=[]
  for i in batch:
   ng=i['key'];mut={m:v if m<=i['cutoff'] else v+1e6 for m,v in obs[(ng[0],ng[1])].items()};cutoff,values=b.base.causal_context(mut,ng[2],2)
   if cutoff!=i['cutoff'] or b.base.context_digest(values)!=b.base.context_digest(i['context']):raise ValueError('future invariance calendar/context')
   changed.append({**i,'context':values})
  replies=[]
  for kind,data in [('repeat',batch),('future',changed)]:
   purpose=f'control{h}-{kind}-chronos';existing=next((x for x in (out/'attempts').glob('*') if core.read(x/'request.json')['purpose']==purpose),None)
   if existing:r=core.validated_response(existing,fp)[1]
   else:
    if time.monotonic()-started>=3000:raise PlannedYield()
    r=core.call(out,p,b,groups,fp,purpose,'chronos',data,request_chronos(p,b,data),lambda path,q:b.batch_predict(pipe,data))
   replies.append(r)
  req=b.cache_request({**item,'cached_prophet':{}},obs)
  other=dict(obs);other[(g[0],g[1])]={m:v if m<=item['cutoff'] else v+1e6 for m,v in obs[(g[0],g[1])].items()};future_req=b.cache_request({**item,'cached_prophet':{}},other)
  if future_req!=req:raise ValueError('Prophet future train invariance')
  for kind,request in [('repeat',req),('future',future_req)]:
   purpose=f'control{h}-{kind}-prophet';existing=next((x for x in (out/'attempts').glob('*') if core.read(x/'request.json')['purpose']==purpose),None)
   if existing:r=core.validated_response(existing,fp)[1]
   else:
    if time.monotonic()-started>=3000:raise PlannedYield()
    r=core.call(out,p,b,groups,fp,purpose,'prophet',[item],{'fit':request,'source_SHA':b.PROPHET_SOURCE_SHA},lambda path,q:worker.fit({'journal':str(path),'request':request}))
   replies.append(r)
  passed=all(r['ok'] for r in replies) and replies[0]['values'][b.group_id(g)][target]==replies[1]['values'][b.group_id(g)][target]==s['chronos'][target] and replies[2]['values'][b.group_id(g)][target]==replies[3]['values'][b.group_id(g)][target]==s['prophet'][target]
  core.atomic(path,{'pass':passed,'horizon':h,'key':k,'same_native_batch':len(batch),'future_context_SHA_unchanged':True,'status':'PASS' if passed else 'CONTROL_FAILED_OR_UNAVAILABLE_NO_RETRY'})
 core.atomic(out/'controls.json',{'pass':all(core.read(out/f'control-h{h}.json')['pass'] for h in [1,3,6,12]),'proofs':[core.read(out/f'control-h{h}.json') for h in [1,3,6,12]]})

def finalize(args,p,b,out,obs,rows,groups,excluded,fp):
 records,pending=core.outcome_registry(out,p,b,groups,rows,excluded,fp,obs,final=True)
 if pending:core.atomic(out/'completion.json',{'status':'INCONCLUSIVE_RESOURCE_NOT_ALL_REQUIRED_STAGES_ATTEMPTED','pending':pending,'scientific_pass':False});return
 import pandas as pd
 pairs=[r for r in records if r['paired_success']]
 pd.DataFrame(records).to_parquet(out/'all-eligible-model-outcomes.parquet',index=False)
 pd.DataFrame(pairs).to_parquet(out/'paired-success-predictions.parquet',index=False)
 pairkeys=[b.base.key(r) for r in pairs];pairedsha=b.digest_keys(pairkeys)
 core.atomic(out/'metrics.json',{'status':'EXECUTED_RETROSPECTIVE_FAILURE_ACCOUNTED_COMPLETE_CASE','paired_support_rows':len(pairs),'paired_support_SHA':pairedsha,'eligible_rows':282120,'all_registry_requested_rows':294570,'interpretation':'Conditional common-successful support only; not full eligible risk; no ranking across different supports','model_successful_support_MAE':{m:{'rows':sum(r[col] is not None for r in records),'MAE':sum(abs(r['actual']-r[col]) for r in records if r[col] is not None)/sum(r[col] is not None for r in records) if any(r[col] is not None for r in records) else None,'different_support_not_rankable':True} for m,col in [('chronos','pred_chronos2'),('prophet','pred_prophet_lag2')]},'by_horizon':b.metrics(pairs),'pooled_common_success_rowweighted':{'rows':len(pairs),'chronos2_MAE':sum(abs(x['actual']-x['pred_chronos2']) for x in pairs)/len(pairs) if pairs else None,'prophet_lag2_MAE':sum(abs(x['actual']-x['pred_prophet_lag2']) for x in pairs)/len(pairs) if pairs else None,'MO_cluster_CI':b.mo_interval(pairs,'pred_prophet_lag2') if pairs else None,'support_SHA':pairedsha,'conditional_complete_case_only':True},'min12_sensitivity':b.metrics([r for r in pairs if r['nonmissing_context_points']>=12]),'full_population_paired_risk':'UNAVAILABLE','strict_V3':'INCONCLUSIVE','scientific_pass':False,'independent_holdout':False,'historical_asof_verified':False})
 core.atomic(out/'completion.json',{'status':'FULL_REGISTERED_OUTCOMES_COMPLETE_WITH_UNRESOLVED_COMPARATOR_NEEDS_REVIEW','registry_rows':294570,'paired_rows':len(pairs),'strict_V3':'INCONCLUSIVE','controls_pass':core.read(out/'controls.json')['pass'],'scientific_pass':False})

def session(args,p,b,full,fp,started):
 out=args.out;disk_admission(out,p,'child-before-native');rss_admission(out,b,'child-before-native');obs,rows,groups,excluded=inputs(args,p,b);core.recover(out,p,b,groups,fp);core.counters(out,p,fp)
 b.resource_preflight(out/('resource-probe-'+str(time.time_ns())))
 if time.monotonic()-started>=p['resource_plan']['soft_no_new_attempt_after_session_seconds']:return
 worker_ref=[None];worker=None;pipe=None
 def stop_owned_worker(signum,frame):
  if worker_ref[0] is not None:worker_ref[0].close()
  raise KeyboardInterrupt('owned supervised session terminated')
 signal.signal(signal.SIGTERM,stop_owned_worker)
 try:
  disk_admission(out,p,'child-before-worker');rss_admission(out,b,'child-before-worker')
  authority=freeze_worker(out,args,p,fp);command=[str(args.prophet_python),str(Path(__file__).with_name('r13_prophet_journal_worker.py')),'--authority',str(authority)]
  worker=b.Worker(str(args.prophet_python),args.view/'shock-radar/src/r8_prophet_batch.py',out,worker_ref,_command=command);os.environ.pop('R13_WORKER_SECRET',None)
  disk_admission(out,p,'child-before-model-load');rss_admission(out,b,'child-before-model-load')
  pipe=model_load(args,b,out)
  for batch in b.fixed_batches(groups):
   if time.monotonic()-started>=p['resource_plan']['soft_no_new_attempt_after_session_seconds']:break
   states=[core.state(out,p,b,i,fp) for i in batch];needed=[need(s,i,'chronos') for s,i in zip(states,batch)]
   if any(needed):
    if not all(needed):raise ValueError('mixed resolved native batch must not replay successful forecasts')
    core.call(out,p,b,groups,fp,'primary','chronos',batch,request_chronos(p,b,batch),lambda path,q:b.batch_predict(pipe,batch))
   for item in batch:
    if time.monotonic()-started>=p['resource_plan']['soft_no_new_attempt_after_session_seconds']:break
    s=core.state(out,p,b,item,fp)
    if need(s,item,'prophet'):
     req=b.cache_request(item,obs)
     if any(t in s['prophet'] or t in s['terminal']['prophet'] for t in req['targets']):raise ValueError('successful/terminal primary fit must not repeat')
     core.call(out,p,b,groups,fp,'primary','prophet',[item],{'fit':req,'source_SHA':b.PROPHET_SOURCE_SHA},lambda path,q:worker.fit({'journal':str(path),'request':req}))
  all_terminal=all(core.terminal(core.state(out,p,b,i,fp),i) for i in groups.values())
  if all_terminal and time.monotonic()-started<p['resource_plan']['soft_no_new_attempt_after_session_seconds']:
   try:controls(args,p,b,out,groups,obs,fp,pipe,worker,started)
   except PlannedYield:pass
   worker.close();worker=None;del pipe;pipe=None
   if (out/'controls.json').exists():
    import gc;gc.collect();finalize(args,p,b,out,obs,rows,groups,excluded,fp)
  core.atomic(out/'session-result.json',{'status':'ALL_PRIMARY_TERMINAL' if all_terminal else 'PROSPECTIVE_PLANNED_YIELD_RESUMABLE_NO_UNKNOWN_CALL','counters':core.counters(out,p,fp),'scientific_pass':False})
 finally:
  if worker is not None:worker.close()
  os.environ.pop('R13_WORKER_SECRET',None)

# Parent ownership/supervision is below; child cannot enter session without one-use authorization.
def canonical(args):
 out=args.out.resolve();ancestor=Path(core.read(args.protocol)['ancestral_path']).resolve()
 if out==ancestor or ancestor in out.parents or out in ancestor.parents:raise ValueError('fresh namespace must not overlap ancestor')
 return out,out.parent/(out.name+'.r13-lock')

def dispatch(args,p,fp,lock):
 token=os.environ.pop('R13_SESSION_SECRET',None)
 if not token or not args.dispatch.is_file():raise ValueError('unauthorized session before numerical imports')
 a=core.read(args.dispatch);owner=core.read(lock)
 if a['mode']!=args.mode or os.getpgrp()!=os.getpid() or a['parent_pid']!=os.getppid() or owner['pid']!=os.getppid() or a['nonce']!=owner['nonce'] or a['secret_SHA']!=hashlib.sha256(token.encode()).hexdigest() or a['out']!=str(args.out.resolve()) or a['fingerprint']!=fp or a['source_SHA']!=core.sha(__file__) or time.monotonic()>a['expires_monotonic']:raise ValueError('session private parent/out/source/deadline scope')
 used=args.dispatch.with_suffix('.consumed');fd=os.open(used,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd);args.dispatch.unlink()


HISTORICAL_WALL=961.611384207994

def finite_wall(value,floor=HISTORICAL_WALL):
 if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<floor:raise ValueError('finite nonbool conserved historical wall required')
 return value

def counter_floor(c,floor):
 if any(type(v) is not int or v<floor.get(k,0) for k,v in c.items()) or any(c.get(k,-1)<v for k,v in floor.items()):raise ValueError('finite integer cumulative counters cannot reset')
 return c

def session_pins(out):return {str(x.relative_to(out)):core.sha(x) for x in sorted((out/'sessions').glob('session-*.json'))}

def disk_admission(out,p,phase):
 try:
  target=out if out.exists() else out.parent;free=shutil.disk_usage(target).free
  size=sum(x.stat().st_size for x in out.rglob('*') if x.is_file()) if out.exists() else 0
  if type(free) is not int or type(size) is not int or free<1073741824 or size>3221225472:raise ValueError('fixed disk/free admission limits failed')
  return {'phase':phase,'free_bytes':free,'output_bytes':size,'PASS':True}
 except Exception as exc:
  failure=out/'admission-failure.json' if out.exists() else out.parent/(out.name+'.admission-failure.json')
  core.atomic(failure,{'phase':phase,'status':'NO_MODEL_NATIVE_OR_CHILD_DISPATCH','reason':type(exc).__name__+': '+str(exc),'scientific_pass':False})
  raise ValueError('disk/output admission blocked before dispatch') from exc

def rss_admission(out,b,phase,reader=None):
 try:
  if reader is None:
   import psutil
   reader=lambda pid:psutil.Process(pid).memory_info().rss
  sizes=[reader(pid) for pid in [os.getpid()]+b.own_descendants(os.getpid())]
  if any(type(v) is not int or v<=0 for v in sizes) or sum(sizes)>2147483648:raise ValueError('aggregate known-owned RSS admission failed')
  return {'phase':phase,'RSS_bytes':sum(sizes),'PASS':True}
 except Exception as exc:
  core.atomic(out/'rss-admission-failure.json',{'phase':phase,'status':'NO_NEW_CHILD_OR_MODEL','reason':type(exc).__name__+': '+str(exc)});raise ValueError('RSS admission blocked before dispatch') from exc

def continuity(out,p,fp,allow_stop=False):
 header=core.read(out/'supervision.json')
 if header['status']!='CLOSED' and not (allow_stop and header['status']=='STOP_REQUIRES_ZERO_MODEL_RECOVERY_REVIEW' and header.get('owned_child_reaped_and_tree_empty')):raise ValueError('unclosed supervisor; root review required, no automatic forced restart')
 if header['fingerprint']!=fp:raise ValueError('supervision fingerprint')
 if p['historical_elapsed_seconds']!=HISTORICAL_WALL:raise ValueError('pinned original historical wall floor')
 wall=finite_wall(header['cumulative_wall_s']);ledger=core.read(out/'resource-ledger.json');finite_wall(ledger['cumulative_wall_s'])
 c=core.counters(out,p,fp,write=False);counter_floor(c,p['historical_counters'])
 if core.read(out/'counters.json')!=c:raise ValueError('persisted counters changed/rolledback')
 if c!=header['counters'] or ledger['cumulative_wall_s']!=wall or ledger['counters']!=c:raise ValueError('counter/time continuity changed')
 snapshots=header['checkpoint_sha256']
 if {str(x.relative_to(out)):core.sha(x) for x in (out/'checkpoints').glob('*.json')}!=snapshots:raise ValueError('latest new checkpoints changed/lost')
 count=header['session_count']
 if count and header.get('owned_child_reaped_and_tree_empty') is not True:raise ValueError('latest owned lifecycle unresolved')
 if type(count) is not int or not 0<=count<=p['resource_plan']['max_total_new_sessions']:raise ValueError('persisted session count invalid')
 pins=session_pins(out);expected={f'sessions/session-{i:03d}.json' for i in range(1,count+1)}
 if set(pins)!=expected or pins!=header['session_receipt_sha256']:raise ValueError('numbered session history changed/lost')
 previous=HISTORICAL_WALL;previous_c=dict(p['historical_counters']);session_ids=[];report_ids=[]
 for event in header['ledger_events']:
  kind=event['kind'];file=out/event['path']
  if kind not in ('session','metadata_report') or core.sha(file)!=event['SHA']:raise ValueError('pinned ledger event changed')
  q=core.read(file)
  if q['fingerprint']!=fp or finite_wall(q['previous_cumulative_wall_s'])!=previous or q['counters_before']!=previous_c:raise ValueError('event wall/counter chain broken')
  if kind=='session':
   i=len(session_ids)+1;session_ids.append(i)
   if event['path']!=f'sessions/session-{i:03d}.json' or type(q['session_count']) is not int or q['session_count']!=i or q['status'] not in ('CLOSED','STOP_REQUIRES_ZERO_MODEL_RECOVERY_REVIEW') or q['mode'] not in ('run','recover'):raise ValueError('invalid numbered session receipt')
   if q.get('owned_child_reaped_and_tree_empty') is not True:raise ValueError('numbered owned lifecycle unresolved')
   last_session=q
  else:
   i=len(report_ids)+1;report_ids.append(i)
   if event['path']!=f'metadata-reports/report-{i:03d}.json' or q['model_calls']!=0 or q['counters']!=previous_c:raise ValueError('invalid zero-model reporting event')
  previous=finite_wall(q['cumulative_wall_s'],previous);previous_c=counter_floor(q['counters'],previous_c)
 if len(session_ids)!=count or set((out/'metadata-reports').glob('report-*.json'))!={out/f'metadata-reports/report-{i:03d}.json' for i in report_ids}:raise ValueError('ledger history lost/duplicated')
 if previous!=wall or previous_c!=c:raise ValueError('latest ledger event must conserve exact latest wall/counters')
 if count and last_session['status']!=header['status']:raise ValueError('last experimental session status does not match closed header')
 if core.journal_digest(out)!=header['journal_digest']:raise ValueError('latest committed journals changed/lost')
 return header

def pending_journal_statuses(out,b,fp):
 result={}
 for path in (out/'attempts').glob('*'):
  q=core.read(path/'request.json')
  if q['fingerprint']!=fp:raise ValueError('foreign reporting journal')
  if q['purpose']!='primary' or core.read(path/'status.json')['status']=='COMMITTED':continue
  status='UNKNOWN_STOP_REQUIRES_REVIEWED_RECOVERY_NEVER_RETRY'
  if (path/'response.json').exists():
   reply=core.validated_response(path,fp)[1]
   status='DURABLE_RESPONSE_REQUIRES_REVIEWED_COMMIT' if reply['ok'] else 'FAILED_REPORTED_RESPONSE_REQUIRES_REVIEWED_COMMIT:'+str(reply['error'])
  for gid,dates in q['target_dates'].items():
   for date in dates:result[(gid,q['model'],date)]=status
 return result

def terminal_notice(out,p,reason):
 core.atomic(out/'completion.json',{'status':'INCONCLUSIVE_STOP_FULL_REGISTRY_ACCOUNTING_REQUIRED','reason':reason,'requested_rows':p['registered_requested_rows'],'eligible_rows':p['eligible_rows'],'registry_materialized':False,'strict_V3':'INCONCLUSIVE','MAE_computed':False,'scientific_pass':False})

def terminal_registry(args,p,b,fp,reason,charge_started=None):
 # Reporting is parent-owned metadata/IO only. No recovery, model imports, fits or accuracy.
 out=args.out;report_started=time.monotonic();charge_started=report_started if charge_started is None else charge_started;terminal_notice(out,p,reason)
 try:
  header=core.read(out/'supervision.json')
  if header['status'] not in ('CLOSED','STOP_REQUIRES_ZERO_MODEL_RECOVERY_REVIEW') or ((header['status']!='CLOSED' or header.get('session_count',0)>0) and header.get('owned_child_reaped_and_tree_empty') is not True):raise ValueError('unresolved owned lifecycle blocks full reporting/restart')
  disk_admission(out,p,'zero-model-terminal-registry')
  if reason=='RESOURCE_ADMISSION_FAILED' and (out/'rss-admission-failure.json').exists():raise ValueError('full registry deferred until reviewed safe RSS admission')
  def reporting_guard():
   if time.monotonic()>report_started+600:raise ValueError('bounded600s zero-model reporting limit')
   disk_admission(out,p,'periodic-zero-model-report');rss_admission(out,b,'periodic-zero-model-report')
  reporting_guard()
  obs,rows,groups,excluded=inputs(args,p,b)
  reporting_guard()
  unresolved=pending_journal_statuses(out,b,fp)
  records,pending=core.outcome_registry(out,p,b,groups,rows,excluded,fp,obs,final=True,unresolved=unresolved,stop_reason=reason,report_deadline=report_started+600,report_guard=reporting_guard)
  support=[b.base.key(r) for r in records if r['paired_success']]
  proof={'status':'INCONCLUSIVE_STOP_FULL_REQUESTED_REGISTRY_MATERIALIZED','reason':reason,'requested_rows':len(rows),'requested_keys_SHA':b.digest_keys([b.base.key(r) for r in rows]),'eligible_rows':p['eligible_rows'],'eligible_keys_SHA':p['frozen_primary_mask']['canonical_keys_sha256'],'registry_file_SHA':core.sha(out/'row-statuses.jsonl'),'paired_success_rows':len(support),'paired_support_SHA':b.digest_keys(support),'unattempted_rows':pending,'recovery_required_entries':len(unresolved),'registry_materialized':True,'strict_V3':'INCONCLUSIVE','full_population_paired_risk':'UNAVAILABLE','MAE_computed':False,'scientific_pass':False}
  reporting_guard()
  core.atomic(out/'terminal-accounting.json',proof);core.atomic(out/'completion.json',proof)
 except Exception as exc:
  core.atomic(out/'terminal-accounting-deferred.json',{'reason':reason,'report_error':type(exc).__name__+': '+str(exc),'all_requested_rows_retained':p['registered_requested_rows'],'MAE_computed':False,'scientific_pass':False,'next_step':'Restore safe reporting resources/validate inputs; explicit zero-model report after root review. No model retry.'})

  # Post-STOP metadata IO is accounted explicitly, never converted into new model allowance.
 finally:
  if (out/'supervision.json').exists():
   h=core.read(out/'supervision.json')
   if h['status'] in ('CLOSED','STOP_REQUIRES_ZERO_MODEL_RECOVERY_REVIEW'):
    elapsed=time.monotonic()-charge_started;previous=finite_wall(h['cumulative_wall_s']);wall=previous+elapsed
    reports=out/'metadata-reports';reports.mkdir(exist_ok=True);index=sum(e['kind']=='metadata_report' for e in h['ledger_events'])+1
    file=reports/f'report-{index:03d}.json';event={'fingerprint':fp,'previous_cumulative_wall_s':previous,'cumulative_wall_s':wall,'counters_before':h['counters'],'counters':h['counters'],'reason':reason,'model_calls':0,'elapsed_seconds':elapsed,'budget_exceeded_during_reporting':wall>108000,'deadline_expired':deadline(p)<=0}
    core.atomic(file,event);h['ledger_events'].append({'kind':'metadata_report','path':str(file.relative_to(out)),'SHA':core.sha(file)});h['cumulative_wall_s']=wall
    ledger=core.read(out/'resource-ledger.json');ledger['cumulative_wall_s']=wall;core.atomic(out/'resource-ledger.json',ledger);core.atomic(out/'supervision.json',h)


def terminate_child(child,b):
 try:owned=b.own_descendants(os.getpid())
 except Exception:
  # Always reap the directly owned isolated session even if instrumentation fails.
  b.stop_owned_group(child);raise
 for sig in [signal.SIGTERM,signal.SIGKILL]:
  current=set(b.own_descendants(os.getpid()))
  for pid in reversed(owned):
   if pid not in current:continue
   try:os.kill(pid,sig)
   except ProcessLookupError:pass
  if sig==signal.SIGTERM:
   try:child.wait(timeout=.5)
   except subprocess.TimeoutExpired:pass
 child.wait(timeout=2)

def supervise(args,p,b,fp,lock,startup_charge=0):
 started=time.monotonic()-startup_charge
 out=args.out;previous=continuity(out,p,fp,allow_stop=args.mode=='recover');count=previous['session_count'];remaining=p['resource_plan']['cumulative_execution_seconds_including_history']-previous['cumulative_wall_s']
 if deadline(p)<=0 or remaining<=600:
  terminal_registry(args,p,b,fp,'DEADLINE_OR_CUMULATIVE_BUDGET_EXHAUSTED',charge_started=started);return 'TERMINAL_RESOURCE_STOP'
 if count>=p['resource_plan']['max_total_new_sessions']:
  terminal_registry(args,p,b,fp,'MAXIMUM_PERSISTED_SESSIONS_EXHAUSTED',charge_started=started);return 'TERMINAL_RESOURCE_STOP'
 try:
  disk_admission(out,p,'parent-before-native');rss_admission(out,b,'parent-before-native')
 except ValueError:
  terminal_registry(args,p,b,fp,'RESOURCE_ADMISSION_FAILED',charge_started=started);return 'TERMINAL_RESOURCE_STOP'
 # Parent instrumentation must pass before the authorized model child exists.
 count+=1;record=out/'sessions'/f'session-{count:03d}.json';core.atomic(record,{'status':'STARTED','session_count':count,'fingerprint':fp,'previous_cumulative_wall_s':previous['cumulative_wall_s'],'counters_before':previous['counters']});core.atomic(out/'supervision.json',{**previous,'status':'STARTED','session_count':count})
 token=secrets.token_hex(32);owner=core.read(lock);authority=out/('session-authority-'+secrets.token_hex(12)+'.json')
 core.atomic(authority,{'mode':args.mode,'parent_pid':os.getpid(),'nonce':owner['nonce'],'secret_SHA':hashlib.sha256(token.encode()).hexdigest(),'out':str(out.resolve()),'fingerprint':fp,'source_SHA':core.sha(__file__),'expires_monotonic':time.monotonic()+45});env=dict(os.environ);env['R13_SESSION_SECRET']=token
 command=[sys.executable,str(Path(__file__).resolve()),*sys.argv[1:],'--dispatch',str(authority)];reason=None;peak=0;child=None;last_disk=0
 def interrupted(signum,frame):raise KeyboardInterrupt('supervisor interrupted')
 signal.signal(signal.SIGTERM,interrupted)
 try:
  if args.mode!='recover':b.resource_preflight(out/('parent-resource-probe-'+str(time.time_ns())))
  disk_admission(out,p,'parent-before-child-spawn');rss_admission(out,b,'parent-before-child-spawn')
  with (out/f'session-{count:03d}.log').open('x') as log:child=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,env=env,start_new_session=True)
  import psutil
  while child.poll() is None:
   elapsed=time.monotonic()-started;total=psutil.Process(os.getpid()).memory_info().rss
   for pid in b.own_descendants(os.getpid()):
    try:total+=psutil.Process(pid).memory_info().rss
    except psutil.NoSuchProcess:pass
   peak=max(peak,total);active=core.read(out/'active-attempt.json') if (out/'active-attempt.json').exists() else {}
   if args.mode!='recover' and active.get('status')=='STARTED' and time.monotonic()-active['started_monotonic']>600:reason='PER_ATTEMPT_TIME_LIMIT_UNRESOLVED'
   if elapsed>(600 if args.mode=='recover' else 3600):reason='SESSION_TIME_LIMIT_UNRESOLVED'
   if previous['cumulative_wall_s']+elapsed>=108000-(0 if args.mode=='recover' else 600) or deadline(p)<=600:reason='GLOBAL_BUDGET_OR_DEADLINE_REPORTING_RESERVE_STOP'
   if total>2147483648:reason='AGGREGATE_RSS_STOP'
   if elapsed-last_disk>=60:
    import shutil
    last_disk=elapsed
    if sum(x.stat().st_size for x in out.rglob('*') if x.is_file())>3221225472 or shutil.disk_usage(out).free<1073741824:reason='DISK_STOP'
   core.atomic(out/'resource-live.json',{'session':count,'elapsed':elapsed,'cumulative_wall_s':previous['cumulative_wall_s']+elapsed,'peak_tree_RSS_bytes':peak,'active_attempt':active})
   if reason:terminate_child(child,b);break
   time.sleep(.25)
  exitcode=child.wait();elapsed=time.monotonic()-started
  # A bounded response/unknown commit recovery is a ZERO-MODEL subprocess, outside original scientific source.
  # Parent records STOP honestly; only future explicitly reviewed/declared recovery may close STARTED.
  owned_cleanup=child.poll() is not None and not b.own_descendants(os.getpid())
  status='CLOSED' if exitcode==0 and not reason and owned_cleanup else 'STOP_REQUIRES_ZERO_MODEL_RECOVERY_REVIEW'
  if not owned_cleanup:reason='OWNED_LIFECYCLE_UNRESOLVED_NO_RESTART'
  c=core.counters(out,p,fp)
  checkpoint_sha={str(x.relative_to(out)):core.sha(x) for x in (out/'checkpoints').glob('*.json')};journal_sha=core.journal_digest(out)
  elapsed=time.monotonic()-started;wall=previous['cumulative_wall_s']+elapsed
  core.atomic(record,{'status':status,'session_count':count,'fingerprint':fp,'previous_cumulative_wall_s':previous['cumulative_wall_s'],'counters_before':previous['counters'],'reason':reason,'exit':exitcode,'counters':c,'cumulative_wall_s':wall,'peak_tree_RSS_bytes':peak,'mode':args.mode,'owned_child_reaped_and_tree_empty':owned_cleanup})
  core.atomic(out/'resource-ledger.json',{'cumulative_wall_s':wall,'peak_tree_RSS_bytes':max(peak,core.read(out/'resource-ledger.json').get('peak_tree_RSS_bytes',0)),'counters':c})
  core.atomic(out/'supervision.json',{'status':status,'owned_child_reaped_and_tree_empty':owned_cleanup,'fingerprint':fp,'session_count':count,'counters':c,'cumulative_wall_s':wall,'checkpoint_sha256':checkpoint_sha,'journal_digest':journal_sha,'session_receipt_sha256':session_pins(out),'ledger_events':previous['ledger_events']+[{'kind':'session','path':str(record.relative_to(out)),'SHA':core.sha(record)}]})
  if status!='CLOSED':terminal_registry(args,p,b,fp,reason or 'MODEL_CHILD_EXIT_FAILED')
  elif args.mode=='recover':terminal_registry(args,p,b,fp,'EXPLICIT_ZERO_MODEL_RECOVERY_COMPLETED_NO_SCIENTIFIC_RESTART')
  return status
 except BaseException as exc:
  if child is not None and child.poll() is None:terminate_child(child,b)
  try:
   reaped=child is None or child.poll() is not None;empty=not b.own_descendants(os.getpid())
   c=core.counters(out,p,fp);wall=previous['cumulative_wall_s']+time.monotonic()-started;status='STOP_REQUIRES_ZERO_MODEL_RECOVERY_REVIEW'
   core.atomic(record,{'status':status,'session_count':count,'fingerprint':fp,'previous_cumulative_wall_s':previous['cumulative_wall_s'],'counters_before':previous['counters'],'reason':'SUPERVISOR_EXCEPTION:'+type(exc).__name__,'error':str(exc),'exit':child.returncode if child else None,'counters':c,'cumulative_wall_s':wall,'peak_tree_RSS_bytes':peak,'mode':args.mode,'owned_child_reaped_and_tree_empty':reaped and empty})
   core.atomic(out/'resource-ledger.json',{'cumulative_wall_s':wall,'peak_tree_RSS_bytes':peak,'counters':c})
   core.atomic(out/'supervision.json',{'status':status,'owned_child_reaped_and_tree_empty':reaped and empty,'fingerprint':fp,'session_count':count,'counters':c,'cumulative_wall_s':wall,'checkpoint_sha256':{str(x.relative_to(out)):core.sha(x) for x in (out/'checkpoints').glob('*.json')},'journal_digest':core.journal_digest(out),'session_receipt_sha256':session_pins(out),'ledger_events':previous['ledger_events']+[{'kind':'session','path':str(record.relative_to(out)),'SHA':core.sha(record)}]})
   if reaped and empty:terminal_registry(args,p,b,fp,'SUPERVISOR_EXCEPTION_SAFE_OWNED_CLEANUP')
   else:terminal_notice(out,p,'SUPERVISOR_EXCEPTION_OWNERSHIP_UNRESOLVED_NO_REPORT_OR_RESTART')
  except BaseException:terminal_notice(out,p,'SUPERVISOR_EXCEPTION_UNCLOSED_STARTED_REQUIRES_OWNER_REVIEW')
  raise

def main():
 started=time.monotonic();args=parser().parse_args();out,lock=canonical(args);args.out=out;fp=fingerprint(args)
 # Private dispatch check is before validate/load original scientific helpers or tensor/model imports.
 if args.dispatch:
  dispatch(args,core.read(args.protocol),fp,lock);p,b,full=validate(args);check_namespace(args,fp)
  if args.mode=='report':raise ValueError('reporting is parent-only zero-model metadata')
  if args.mode=='recover':
   obs,rows,groups,excluded=inputs(args,p,b);core.recover(out,p,b,groups,fp);core.counters(out,p,fp);core.atomic(out/'recovery.json',{'status':'ZERO_MODEL_RESPONSE_COMMIT_OR_TERMINAL_UNKNOWN','models':0});return
  session(args,p,b,full,fp,started);return
 p,b,full=validate(args)
 # Public recovery is zero-model and must pass the persisted STOP/cleanup/continuity gate below.
 if lock.exists():raise ValueError('actual new output namespace locked')
 if args.mode=='prepare':
  disk_admission(out,p,'before-prepare-registry-writes')
  out.mkdir(exist_ok=False);(out/'checkpoints').mkdir();(out/'sessions').mkdir();(out/'attempts').mkdir();core.atomic(out/'fingerprint.json',{'fingerprint':fp,'protocol_SHA':PROTOCOL_SHA,'code_SHA':code_id(),'ancestral_fingerprint':p['ancestral_fingerprint'],'protocol_deviations':p['deviations']})
  obs,rows,groups,excluded=inputs(args,p,b)
  for batch in b.fixed_batches(groups):
   s=[core.state(out,p,b,i,fp) for i in batch];has=[bool(x['chronos']) for x in s]
   if any(has) and not all(has):raise ValueError('ancestral partial nativebatch would replay successful call; blocked')
  core.outcome_registry(out,p,b,groups,rows,excluded,fp,obs);c=core.counters(out,p,fp);wall=p['historical_elapsed_seconds'];core.atomic(out/'resource-ledger.json',{'cumulative_wall_s':wall,'peak_tree_RSS_bytes':0,'counters':c});core.atomic(out/'supervision.json',{'status':'CLOSED','fingerprint':fp,'session_count':0,'counters':c,'cumulative_wall_s':wall,'checkpoint_sha256':{},'journal_digest':core.journal_digest(out),'session_receipt_sha256':{},'ledger_events':[]});core.atomic(out/'preparation.json',{'status':'PREPARED_FULL_SCOPE_ZERO_MODEL_CALLS','requested':len(rows),'eligible':282120,'groups':len(groups),'unknown_ancestral':p['unknown_ancestral_group']['group_key'],'primary_native_batches_keep_original_membership':True,'no_original_file_mutations':True});print('PREPARED_FULL_SCOPE_ZERO_MODEL_CALLS');return
 check_namespace(args,fp);nonce=secrets.token_hex(32);fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.write(fd,json.dumps({'pid':os.getpid(),'nonce':nonce,'out':str(out)}).encode());os.fsync(fd);os.close(fd)
 try:
  if args.mode=='report':
   continuity(out,p,fp,allow_stop=True);terminal_registry(args,p,b,fp,'EXPLICIT_ZERO_MODEL_TERMINAL_REPORT',charge_started=started);return
  if args.mode=='recover':
   header=core.read(out/'supervision.json')
   if header['status']!='STOP_REQUIRES_ZERO_MODEL_RECOVERY_REVIEW':raise ValueError('explicit recovery requires stopped receipt; no STARTED or clean namespace bypass')
   supervise(args,p,b,fp,lock,time.monotonic()-started);return
  startup_charge=time.monotonic()-started
  while not ((out/'completion.json').exists() and core.read(out/'completion.json')['status']=='FULL_REGISTERED_OUTCOMES_COMPLETE_WITH_UNRESOLVED_COMPARATOR_NEEDS_REVIEW'):
   status=supervise(args,p,b,fp,lock,startup_charge);startup_charge=0
   if status!='CLOSED':break
 finally:lock.unlink(missing_ok=True)
if __name__=='__main__':main()
