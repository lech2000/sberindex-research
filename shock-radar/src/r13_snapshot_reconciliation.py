"""Explicit metadata reconciliation of one named crash orphan. No scientific imports."""
import time
ENTRY=time.monotonic()
import argparse, collections, hashlib, importlib.util, json, math, os, pathlib, resource, shutil, signal
P=pathlib.Path
OUT=P('/private/tmp/radar-r13-full-actual-20261008-v1')
REPO=P(__file__).resolve().parents[2]
ORIGINAL='9409ccf7e7ef608bb490eccd45aab22e1dc3dc731c883a2c38431084fbedea01'
OLD_SOURCE='527afff235922b59e7a64732f8b8807643c9215b5a4854267d9a870046aa8b46'
OLD_CUMULATIVE=3893.441428624006
FIRST_REPORT=41.714114749993314
DIAGNOSIS=12.459174667004845
BASE=3947.6147181660053
FAMILY_REMAINING=545.8267105830018
INDEPENDENT_RESERVE=120
LIMIT=425.8267105830018
ORPHAN='checkpoints/999ee42521cea71b26867fd99f199bd13aab3ec60b488b8ee3162e443e9d454b.json.tmp'
EMPTY='e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'
DIAG=P('/private/tmp/radar-r13-checkpoint-mismatch-audit-20261008')
DIAG_SHA={'AUDIT.json':'9ce9d12923b7b060debeacba6bf7faf578692e92e83319e71f9e9cb054b10fc3','ASSOCIATION.json':'51defcc9be3758aa7aeb46ea79189303fa82e99be9c579bd24c10b046a5f1021'}
OLD_CONTROL=P('/private/tmp/radar-r13-reportonly-root-control-20261008')
NEW_CONTROL=P('/private/tmp/radar-r13-snapshot-reconciliation-root-control-20261008')
INDEPENDENT=P('/private/tmp/radar-r13-snapshot-reconciliation-independent-audit-20261008')
PINS={'shock-radar/src/r13_zero_model_report.py':OLD_SOURCE,'shock-radar/protocol/r13_zero_model_report_recovery_20261008.json':'45cdbd8691f48848cb9387d2c41d2a5f2fc6ea9d9578108b83ca27146b60811c','shock-radar/protocol/r13_zero_model_report_recovery_20261008.md':'f1585c06a1eb33ed9b62c40dfc5d9eec07713e9653d7d10e3c823b6d63e34266','tests/test_r13_zero_model_report.py':'80711a951c1f89127b7877e7ed510c70d3a37db2243ef72b62dbbabe61605a27'}
def sha(p):return hashlib.sha256(P(p).read_bytes()).hexdigest()
def read(p):return json.loads(P(p).read_bytes())
def finite(v):
 if type(v) not in (int,float) or not math.isfinite(v):raise ValueError('finite nonbool')
 return v
def atomic(path,value):
 tmp=P(str(path)+'.tmp')
 with tmp.open('w') as f:json.dump(value,f,ensure_ascii=False,allow_nan=False);f.write('\n');f.flush();os.fsync(f.fileno())
 os.replace(tmp,path)
def load_helpers():
 for name,digest in PINS.items():
  if sha(REPO/name)!=digest:raise ValueError('pinned old helper/source authority mismatch')
 file=REPO/'shock-radar/src/r13_zero_model_report.py';spec=importlib.util.spec_from_file_location('pinned_status_only_helpers',file);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
def guard(out,started,family_bytes=0):
 if time.monotonic()-started>=LIMIT or time.time()>=1791536400:raise RuntimeError('inclusive reconciliation time/deadline cap')
 rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*(1 if os.uname().sysname=='Darwin' else 1024)
 if rss>2147483648 or shutil.disk_usage(out).free<1073741824 or family_bytes>134217728:raise RuntimeError('fixed RSS/free/family-output cap')
def check_history(t):
 if t.get('state')!='INCONCLUSIVE_REPORT_STOP_NO_RETRY' or t.get('error')!='ValueError: checkpoint snapshot mismatch' or t.get('original_cumulative_wall_s')!=OLD_CUMULATIVE or finite(t.get('report_elapsed_seconds'))!=FIRST_REPORT or finite(t.get('cumulative_wall_s'))!=3935.1555434990005 or t.get('models')!=0 or t.get('scientific_pass') is not False:raise ValueError('first consumed report history unchanged')
def family_roots(out,lease):
 uid=str(os.getuid());leases=lease.parent
 return [out/'zero-model-report-v1',out/'snapshot-reconciliation-v1',DIAG,OLD_CONTROL,NEW_CONTROL,INDEPENDENT,leases/(uid+'-R13-ZERO_MODEL_REPORT-'+ORIGINAL+'.json'),leases/(uid+'-R13-ZERO_MODEL_REPORT-'+ORIGINAL+'-terminal.json'),lease,lease.with_name(lease.stem+'-terminal.json')]
def family_size(roots):
 seen=set();total=0
 for root in roots:
  files=[root] if root.is_file() else root.rglob('*') if root.is_dir() else []
  for f in files:
   if f.is_symlink():raise ValueError('metadata family symlink refused')
   if f.is_file():
    canonical=f.resolve()
    if canonical not in seen:seen.add(canonical);total+=f.stat().st_size
 return total
def orphan_inventory(out,header):
 actual={str(f.relative_to(out)):f for f in (out/'checkpoints').iterdir()};published=set(header['checkpoint_sha256'])
 if set(actual)!=published|{ORPHAN}:raise ValueError('only exact published set plus one frozen orphan allowed')
 f=actual[ORPHAN]
 if f.is_symlink() or not f.is_file() or f.stat().st_size!=0 or sha(f)!=EMPTY:raise ValueError('orphan must remain original zero-byte SHA')
 return {'path':str(f),'relative_path':ORPHAN,'size':0,'SHA':EMPTY,'classification':'PRESERVED_UNPUBLISHED_EMPTY_CRASH_TEMP_NOT_RESPONSE','excluded_from_published_state_explicitly':True}
def evidence(out,b,old):
 if b['source_SHA']!=sha(__file__) or b['original_cumulative_seconds']!=OLD_CUMULATIVE or b['first_report_seconds']!=FIRST_REPORT or b['diagnosis_seconds']!=DIAGNOSIS or b['new_phase_base_seconds']!=BASE or b['remaining_family_seconds']!=FAMILY_REMAINING or b['reconciliation_seconds']!=LIMIT or b['independent_audit_reserve_seconds']!=INDEPENDENT_RESERVE or b.get('root_authoritative_original_tree_gone') is not True:raise ValueError('root exact source/history/quiescence')
 if set(b['closed_file_SHA'])!=old.REQUIRED_CLOSED_FILES|{'zero-model-report-v1/terminal.json'}:raise ValueError('full old closed-file binding required')
 if sha(OLD_CONTROL/'ROOT_BINDING.json')!='703991e7849b05eed1bd4b145ecab041587484095041ab9fabae00f3d7e32903' or b['old_root_binding_SHA']!='703991e7849b05eed1bd4b145ecab041587484095041ab9fabae00f3d7e32903':raise ValueError('consumed original report rootbinding preserved')
 for name,digest in b['closed_file_SHA'].items():
  path=P(name)
  if path.is_absolute() or '..' in path.parts or sha(out/path)!=digest:raise ValueError('old closed artifact changed')
 check_history(read(out/'zero-model-report-v1/terminal.json'))
 for name,digest in DIAG_SHA.items():
  if sha(DIAG/name)!=digest or b['diagnostic_SHA'].get(name)!=digest:raise ValueError('exact independent orphan diagnostic')
 audit=read(DIAG/'AUDIT.json');assoc=read(DIAG/'ASSOCIATION.json')
 if audit['elapsed_seconds']!=DIAGNOSIS or audit['published_SHA_mismatches'] or audit['missing_paths'] or audit['extra_paths']!=[ORPHAN] or audit['checked_published']!=44184 or audit['all_published_scan_completed'] is not True:raise ValueError('complete exact orphan evidence')
 leases=P('/private/tmp/sberindex-one-use-ledger');uid=str(os.getuid())
 old_terminal=uid+'-R13-ZERO_MODEL_REPORT-'+ORIGINAL+'-terminal.json'
 expected_leases=[(uid+'-R13-'+ORIGINAL+'.json','23b2f154606d5d7bb7f8bcc67a8446095e8200eaec90fc773e893394852a960f'),(uid+'-R13-ZERO_MODEL_REPORT-'+ORIGINAL+'.json','5f290c724ea85ac17fa14b70a50fb208fbdfaa09322a5451824ad7099e4bb35e'),(old_terminal,b['closed_file_SHA']['zero-model-report-v1/terminal.json'])]
 if set(b['old_lease_SHA'])!={name for name,_ in expected_leases}:raise ValueError('all original model/report lease and NO_RETRY terminal bindings')
 for name,digest in expected_leases:
  if sha(leases/name)!=digest or b['old_lease_SHA'].get(name)!=digest:raise ValueError('old model/report lease immutable')
 header=read(out/'supervision.json');old.conservation(header,read(out/'resource-ledger.json'),out)
 original_fp=read(out/'fingerprint.json');view=P('/private/tmp/radar-r13-oneuse-launch-plan-20261008/revision-thin-runtime/frozen-execution-view')
 for name,digest in original_fp['code_SHA'].items():
  if sha(view/'shock-radar/src'/name)!=digest:raise ValueError('original actual scientific source unchanged')
 if sha(view/'shock-radar/protocol/chronos2_full_failure_accounted_r13_20261008.json')!=ORIGINAL:raise ValueError('original scientific protocol unchanged')
 if sha(out/'supervision.json')!=audit['header_SHA']:raise ValueError('same closed checkpoint authority')
 journal=out/'attempts/1791419316162486000-prophet-primary'
 if sha(journal/'request.json')!=assoc['request_file_SHA'] or sha(journal/'response.json')!=assoc['response_file_SHA'] or sha(journal/'status.json')!=assoc['status_file_SHA']:raise ValueError('orphan association journal changed')
 if assoc['group_keys']!=[['1594','Общественное питание','2023-11']] or assoc['response_metadata']['ok'] is not False or assoc['response_metadata']['error']!='BrokenPipeError: [Errno 32] Broken pipe':raise ValueError('exact failed-stage association')
 published=out/ORPHAN.removesuffix('.tmp')
 if sha(published)!=assoc['published_checkpoint_SHA'] or read(published)['group_key']!=assoc['published_group_key'] or assoc['target_dates']!={'999ee42521cea71b26867fd99f199bd13aab3ec60b488b8ee3162e443e9d454b':['2024-11']}:raise ValueError('exact orphan/published-stage association')
 return header,orphan_inventory(out,header)
def materialize(out,phase,b,old,header,quarantine,check,scope=(294570,282120,12450,44184,33319)):
 requested,eligible_count,excluded_count,cp_count,attempt_count=scope
 states={}
 for i,name in enumerate(sorted(header['checkpoint_sha256'])):
  file=out/name
  if sha(file)!=header['checkpoint_sha256'][name]:raise ValueError('published checkpoint SHA mismatch')
  s=read(file);key=tuple(s['group_key'])
  if s['fingerprint']!=old.FINGERPRINT or key in states:raise ValueError('published checkpoint identity')
  states[key]=s
  if i%1024==0:check()
 if len(states)!=cp_count:raise ValueError('published checkpoint full count')
 h=hashlib.sha256();unresolved={};counts=dict(chronos_calls=104,prophet_fits=1006,successful_native_calls=104,successful_Prophet_fits=1005);n=0
 for folder in sorted((out/'attempts').iterdir()):
  blobs={}
  for name in ['request.json','response.json','status.json','native-manifest.json']:
   f=folder/name
   if f.exists():raw=f.read_bytes();blobs[name]=raw;h.update((str(f.relative_to(out))+' '+hashlib.sha256(raw).hexdigest()+'\n').encode())
  q=json.loads(blobs['request.json']);s=json.loads(blobs['status.json']);r=json.loads(blobs['response.json']) if 'response.json' in blobs else None;rq=hashlib.sha256(blobs['request.json']).hexdigest()
  if q['fingerprint']!=old.FINGERPRINT or q['purpose']!='primary' or q['model'] not in ['chronos','prophet'] or s['request_SHA']!=rq or s['status'] not in ['STARTED','COMMITTED']:raise ValueError('attempt identity')
  if r is not None and (r['request_SHA']!=rq or r['fingerprint']!=old.FINGERPRINT or r['model']!=q['model']):raise ValueError('response identity')
  if s['status']=='COMMITTED' and (r is None or s['response_SHA']!=hashlib.sha256(blobs['response.json']).hexdigest()):raise ValueError('committed reply identity')
  if q['model']=='prophet' and list(old.UNKNOWN[:3]) in q['group_keys']:raise ValueError('ancestral unknown refitted')
  counts['chronos_calls' if q['model']=='chronos' else 'prophet_fits']+=1
  if r is not None and r.get('ok') is True:counts['successful_native_calls' if q['model']=='chronos' else 'successful_Prophet_fits']+=1
  if s['status']!='COMMITTED':
   status='UNKNOWN_STOP_REQUIRES_REVIEWED_RECOVERY_NEVER_RETRY'
   if r is not None:status='DURABLE_RESPONSE_REQUIRES_REVIEWED_COMMIT' if r['ok'] else 'FAILED_REPORTED_RESPONSE_REQUIRES_REVIEWED_COMMIT:'+str(r['error'])
   for key in q['group_keys']:
    for date in q['target_dates'][old.group_id(key)]:unresolved[(tuple(key),q['model'],date)]=status
  n+=1
  if n%1024==0:check()
 if n!=attempt_count or h.hexdigest()!=header['journal_digest'] or counts!=header['counters']:raise ValueError('full journal/counter conservation')
 keys=set();statuses=collections.Counter();excluded=0;eligible=0;written=0;prepared=hashlib.sha256();tmp=phase/'row-statuses.jsonl.tmp'
 with (out/'row-statuses.jsonl').open('rb') as original,tmp.open('wb') as target:
  for i,raw in enumerate(original):
   prepared.update(raw);row=json.loads(raw);key=tuple(row['key'])
   if len(key)!=5 or key in keys:raise ValueError('duplicate/malformed requested key')
   keys.add(key);excluded+=row.get('status')=='INSUFFICIENT_HISTORY';eligible+=row.get('status')!='INSUFFICIENT_HISTORY'
   result=old.select_status(row,states.get(key[:3]),unresolved)
   for model,status in result.get('model_status',{}).items():statuses[model+':'+status]+=1
   data=(json.dumps(result,ensure_ascii=False,separators=(',',':'),allow_nan=False)+'\n').encode();target.write(data);written+=len(data)
   if i%1024==0:check(written)
  target.flush();os.fsync(target.fileno())
 if prepared.hexdigest()!=old.PREPARED_SHA or len(keys)!=requested or eligible!=eligible_count or excluded!=excluded_count or old.UNKNOWN not in keys:raise ValueError('full requested key/preparedSHA contract')
 check(written);os.replace(tmp,phase/'row-statuses.jsonl');atomic(phase/'quarantine-inventory.json',quarantine)
 if orphan_inventory(out,header)!=quarantine:raise ValueError('orphan changed during reconciliation')
 for name,digest in b['closed_file_SHA'].items():
  if sha(out/name)!=digest:raise ValueError('old artifact changed during reconciliation')
 return {'state':'FULL_SNAPSHOT_EVIDENCE_RECONCILIATION_STATUS_ONLY','requested':len(keys),'eligible':eligible,'excluded':excluded,'registry_SHA':sha(phase/'row-statuses.jsonl'),'quarantine_inventory_SHA':sha(phase/'quarantine-inventory.json'),'quarantine':quarantine,'model_status_counts':dict(statuses),'counters':counts,'journal_SHA':h.hexdigest(),'original_prepared_SHA':prepared.hexdigest(),'MAE_computed':False,'scientific_pass':False,'original_V3':'INCONCLUSIVE','full_population_paired_risk':'UNAVAILABLE','model_calls':0,'old_files_modified':False}
def main():
 started=ENTRY
 for key in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS']:os.environ[key]='1'
 ap=argparse.ArgumentParser();ap.add_argument('--binding',type=P,required=True);ap.add_argument('--binding-sha',required=True);args=ap.parse_args()
 if args.binding.resolve()!=(NEW_CONTROL/'ROOT_BINDING.json') or sha(args.binding)!=args.binding_sha:raise ValueError('fixed root binding path/SHA')
 b=read(args.binding);out=P(b['out']).resolve();phase=out/'snapshot-reconciliation-v1'
 if out!=OUT or phase.exists():raise ValueError('same namespace/fresh owned reconciliation sidecar before lease')
 if b['source_SHA']!=sha(__file__) or b['new_phase_base_seconds']!=BASE or b.get('root_authoritative_original_tree_gone') is not True:raise ValueError('root source/history/quiescence admission')
 if b['amendment_protocol_SHA']!=sha(REPO/'shock-radar/protocol/r13_snapshot_reconciliation_20261008.json'):raise ValueError('root frozen explicit amendment protocol')
 guard(out,started)
 leases=P('/private/tmp/sberindex-one-use-ledger');s=leases.lstat()
 if leases.is_symlink() or s.st_uid!=os.getuid() or s.st_mode&0o077:raise ValueError('private UID0700 canonical lease')
 lease=leases/(str(os.getuid())+'-R13-SNAPSHOT_RECONCILIATION_V1-'+ORIGINAL+'.json');fd=os.open(lease,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
 with os.fdopen(fd,'w') as f:json.dump({'state':'STARTED','out':str(out),'binding_SHA':args.binding_sha,'base_cumulative_seconds':BASE,'model_calls':0},f);f.flush();os.fsync(f.fileno())
 owned=False;result={'state':'INCONCLUSIVE_RECONCILIATION_STOP_NO_RETRY','model_calls':0,'scientific_pass':False}
 def alarm(*unused):raise RuntimeError('family bounded reconciliation cap with30s receipt reserve')
 previous=signal.signal(signal.SIGALRM,alarm);signal.setitimer(signal.ITIMER_REAL,max(.001,LIMIT-30-(time.monotonic()-started)))
 try:
  old=load_helpers();header,quarantine=evidence(out,b,old)
  baseline=0
  for i,f in enumerate(out.rglob('*')):
   if f.is_symlink():raise ValueError('snapshot symlink refused')
   if f.is_file():baseline+=f.stat().st_size
   if i%1024==0:guard(out,started)
  roots=family_roots(out,lease);family=family_size(roots)
  inside_family=family_size([out/'zero-model-report-v1',out/'snapshot-reconciliation-v1'])
  if baseline-inside_family+134217728>3221225472:raise ValueError('original3GiB cap with family128MiB reservation, no doublecount')
  phase.mkdir(mode=0o700,exist_ok=False);owned=True
  result=materialize(out,phase,b,old,header,quarantine,lambda written=0:guard(out,started,family_size(roots)+65536))
  evidence(out,b,old)
  guard(out,started,family_size(roots)+65536)
 except BaseException as exc:result.update(error=type(exc).__name__+': '+str(exc))
 finally:
  signal.setitimer(signal.ITIMER_REAL,0);signal.signal(signal.SIGALRM,previous);spent=time.monotonic()-started
  if spent>LIMIT or BASE+spent>108000 or time.time()>=1791536400:result['state']='INCONCLUSIVE_RECONCILIATION_FINALIZATION_BUDGET'
  result.update(original_cumulative_seconds=OLD_CUMULATIVE,first_report_seconds=FIRST_REPORT,diagnosis_seconds=DIAGNOSIS,new_phase_base_seconds=BASE,reconciliation_elapsed_seconds=spent,cumulative_wall_seconds=BASE+spent,family_elapsed_seconds=FIRST_REPORT+DIAGNOSIS+spent,continuous_resource_pass=False,last_receipt_fsync_independently_timed=False)
  result.update(independent_audit_status='INDEPENDENT_AUDIT_PENDING',independent_audit_reserve_seconds=INDEPENDENT_RESERVE)
  result['family_output_roots']=[str(x) for x in family_roots(out,lease)]
  try:result['family_output_bytes_before_final_receipts']=family_size(family_roots(out,lease))
  except BaseException as exc:result.update(state='INCONCLUSIVE_RECONCILIATION_FAMILY_ACCOUNTING',family_output_accounting_error=repr(exc))
  atomic(lease.with_name(lease.stem+'-terminal.json'),result)
  if owned:atomic(phase/'terminal.json',result)
 return 0 if result['state']=='FULL_SNAPSHOT_EVIDENCE_RECONCILIATION_STATUS_ONLY' else 1
if __name__=='__main__':raise SystemExit(main())
