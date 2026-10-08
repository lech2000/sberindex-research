"""Root-admitted ONE full E05 operation. No defaults, resume or implicit retry.
Trusted same-user root binding is review authority, not a hostile-user sandbox.
"""
import time
ENTRY=time.monotonic()
ENTRY_UTC_EPOCH=time.time()
import argparse,datetime,hashlib,importlib.util,json,math,os,pathlib,secrets,select,shutil,signal,subprocess,sys,platform
P=pathlib.Path
KEY='E05-full-event-repaired-225cells-v1'
OUT=P('/private/tmp/e05-full-event-repaired-actual')
CONTROL=P('/private/tmp/e05-full-event-repaired-control')
LEDGER=P('/private/tmp/e05-full-event-repaired-operation-ledger')
PROTOCOL='economic-atlas/protocols/E05_FULL_REMAINING_V2.json'
PROTOCOL_SHA='b1b15d99a8094690ba532d89846206ebbf60b653f7b7bb7873307f9a5cfa931a'
METHOD_SHA='e5db7ad379bf2c6bcb261d05563bdb88c433a4178baec48399e3e9e0ef2ea21b'
PANEL_SHA='8716a802fb6e25ef4103406cca927de80ce3693a7ff243411cda765b732bcd93'
ACK='9c418c1f37284cbd6250bca1335753591fc2d2e6151c0f2cfd24d98e740395ef'
SOURCE_BINDING=dict(protocol_SHA=PROTOCOL_SHA,method_SHA=METHOD_SHA,source_ACK_SHA=ACK)
THREADS=('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS','VECLIB_MAXIMUM_THREADS')
def finite(v):
 if type(v)not in (int,float)or not math.isfinite(v):raise ValueError('finite nonbool scalar')
 return v
def sha(p):
 h=hashlib.sha256()
 with P(p).open('rb')as f:
  for b in iter(lambda:f.read(65536),b''):h.update(b)
 return h.hexdigest()
def token(v):return type(v)is str and len(v)==64 and all(c in '0123456789abcdef'for c in v)
def read(p):
 def pairs(items):
  d={}
  for k,v in items:
   if k in d:raise ValueError('duplicate JSON key')
   d[k]=v
  return d
 p=regular(p)
 if p.stat().st_size>2*1024**2:raise ValueError('bounded metadata2MiB')
 return json.loads(p.read_bytes(),object_pairs_hook=pairs,parse_constant=lambda _:(_ for _ in()).throw(ValueError('nonfinite JSON')))
def regular(p):
 p=P(p)
 if not p.is_absolute()or p.resolve()!=p or any(q.is_symlink()for q in (p,*p.parents))or not p.is_file():raise ValueError('canonical regular source path')
 return p
def snapshot(path):
 path=regular(path);a=path.stat();pin=sha(path);b=path.stat()
 st=lambda x:(x.st_dev,x.st_ino,x.st_size,x.st_mtime_ns)
 if st(a)!=st(b):raise ValueError('binding changed during initial hash')
 return {'path':str(path),'SHA':pin,'stat':list(st(a))}
def check_snapshot(bound):
 path=regular(bound['path']);a=path.stat()
 if list((a.st_dev,a.st_ino,a.st_size,a.st_mtime_ns))!=bound['stat']or sha(path)!=bound['SHA']:raise ValueError('original binding bytes/stat changed; never rebind')
 b=path.stat()
 if (a.st_dev,a.st_ino,a.st_size,a.st_mtime_ns)!=(b.st_dev,b.st_ino,b.st_size,b.st_mtime_ns):raise ValueError('binding changed during recheck')
 return bound['SHA']
def once(p,v):
 p=P(p);fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
 with os.fdopen(fd,'w')as f:json.dump(v,f,allow_nan=False);f.write('\n');f.flush();os.fsync(f.fileno())
 fd=os.open(p.parent,os.O_RDONLY)
 try:os.fsync(fd)
 finally:os.close(fd)
def private_dir(p):
 p=P(p)
 if p.exists()or p.is_symlink():raise ValueError('fresh private namespace only')
 p.mkdir(mode=0o700)
 fd=os.open(p.parent,os.O_RDONLY)
 try:os.fsync(fd)
 finally:os.close(fd)
def validate(binding,repo,*,now=None):
 """Read-only BEFORE lease; actual report bytes+proofs, not True attributes."""
 now=time.monotonic()if now is None else finite(now);repo=P(repo)
 if repo.resolve()!=repo:raise ValueError('canonical repo')
 spec=binding['spec']
 for k in ('whole_seconds','finalization_reserve_seconds','audit_receipt_reserve_seconds','metadata_bytes_limit','RSS_bytes','minimum_free_bytes','output_bytes','receipt_reserve_bytes','poll_seconds','cleanup_seconds'):finite(spec[k])
 if any(spec[k]<=0 for k in spec if k in ('whole_seconds','finalization_reserve_seconds','audit_receipt_reserve_seconds','metadata_bytes_limit','RSS_bytes','minimum_free_bytes','output_bytes','receipt_reserve_bytes','poll_seconds','cleanup_seconds')):raise ValueError('explicit positive budgets')
 if type(spec['CPU_threads'])is not int or spec['CPU_threads']!=1:raise ValueError('CPU1')
 if not 0<spec['audit_receipt_reserve_seconds']<spec['finalization_reserve_seconds']<spec['whole_seconds']or spec['cleanup_seconds']>spec['audit_receipt_reserve_seconds']or not 65536<=spec['receipt_reserve_bytes']<spec['output_bytes']:raise ValueError('nested reserves from original whole budget')
 if not 0<spec['output_bytes']<=128*1024**2 or spec['RSS_bytes']>1024**3 or spec['minimum_free_bytes']<1024**3:raise ValueError('RSS1GiB/free1GiB')
 if any(type(spec[k])is not int for k in ('RSS_bytes','minimum_free_bytes','output_bytes','receipt_reserve_bytes','metadata_bytes_limit')):raise ValueError('integer bytecaps')
 deadline=datetime.datetime.fromisoformat(spec['absolute_deadline_UTC'])
 if deadline.tzinfo is None or deadline.utcoffset()!=datetime.timedelta(0)or datetime.datetime.now(datetime.timezone.utc)>=deadline:raise ValueError('explicit unexpired UTC deadline')
 if binding['operation']!=KEY or type(binding['UID'])is not int or binding['UID']!=os.getuid()or binding['host']!=platform.node()or binding['source_binding']!=SOURCE_BINDING:raise ValueError('exact root operation/UID/source')
 if binding['paths']!={'out':str(OUT),'control':str(CONTROL),'ledger':str(LEDGER)}:raise ValueError('no alternate namespace')
 if binding['python_path']!=str(P(sys.executable).resolve())or sha(regular(binding['python_path']))!=binding['python_SHA']:raise ValueError('pinned interpreter')
 required=['economic-atlas/src/e05_full_execution_controller.py','economic-atlas/src/e05_full_execution_worker.py','economic-atlas/src/e05_full_real_publication_bridge.py','economic-atlas/src/atlas_e05_remaining_v2.py',PROTOCOL,'economic-atlas/src/e05_full_receipt_adapter_v5.py','economic-atlas/src/e05_full_guardian_toolkit_v2.py','economic-atlas/src/atlas_m1_executor.py','economic-atlas/src/e05_full_publication_finalizer_v5.py','economic-atlas/src/e05_full_publication_validator_v5.py','economic-atlas/src/e05_full_numeric_adapter.py','economic-atlas/src/e05_independent_numerical_audit.py','economic-atlas/src/e05_numpy_quality_reference.py']
 if not set(required)<=set(binding['source_pins']):raise ValueError('full source inventory required')
 for name,pin in binding['source_pins'].items():
  if P(name).is_absolute()or '..'in P(name).parts:raise ValueError('source relative path')
  if not token(pin)or sha(regular(repo/name))!=pin:raise ValueError('source pin '+name)
 if binding['source_pins'][PROTOCOL]!=PROTOCOL_SHA or binding['source_pins']['economic-atlas/src/atlas_e05_remaining_v2.py']!=METHOD_SHA:raise ValueError('frozen scientific source')
 protocol=read(repo/PROTOCOL)
 for section in ('source_pins','data_pins'):
  for name,pin in protocol[section].items():
   if sha(regular(repo/name))!=pin:raise ValueError('original input pin '+name)
 import importlib.metadata
 for package,version in binding['dependency_versions'].items():
  if importlib.metadata.version(package)!=version:raise ValueError('dependency version binding')
 if set(binding['dependency_versions'])!={'numpy','pandas','scipy','scikit-learn','pyarrow'}:raise ValueError('full native dependency binding')
 validate_resource_report(binding)
 if not token(binding['independent_source_ACK_SHA']):raise ValueError('independent source review required')
 return spec
def validate_resource_report(binding):
 """Shared stdlib root-reviewed admission receipt validator; no cost run."""
 spec=binding['spec']
 report_path=regular(binding['real_IO_resource_report_path']);report_SHA=binding['real_IO_resource_report_SHA']
 if not token(report_SHA)or sha(report_path)!=report_SHA:raise ValueError('root-reviewed resource report SHA')
 report=read(report_path)
 if report['state']!='INDEPENDENTLY_ACCEPTED_REAL_E05_IO_RESOURCE' or report['scope']!={'n':1896,'months':24,'cells':225,'status_rows':10238400}or report['source_pins']!=binding['source_pins']or report['spec']!=spec:raise ValueError('real fullsize/source/resource admission identity')
 # Exact independently reviewed substantive receipts; tiny/source mocks cannot admit.
 for kind in ('native_owned_tree_preflight','monthly1896_K5_native_pair','supra45504_K5_native_pair','full225_status_and8220_journal_IO','independent_review'):
  proof=report['proofs'][kind];path=regular(proof['path'])
  if not token(proof['SHA'])or sha(path)!=proof['SHA']:raise ValueError('resource proof bytes '+kind)
  doc=read(path)
  if doc.get('actual')is not True or doc.get('source_only_mock')is not False or doc.get('state')not in ('PASS','ACCEPTED')or doc.get('source_pins')!=binding['source_pins']:raise ValueError('real substantive qualification '+kind)
 if report['monthly_native_shape']!=[1896,5] or report['supra_native_shape']!=[45504,5] or report['full_status_IO_rows']!=10238400 or report['typed_journal_IO_entries']!=8220 or finite(report['measured_profile_wall_seconds'])<=0 or finite(report['measured_profile_peak_RSS_bytes'])<=0:raise ValueError('fullsize measurement shape/time/RSS')
 if report.get('remaining_quality_control_cost_state')!='INDEPENDENTLY_ADMITTED':raise ValueError('remaining quality/control costs UNKNOWN; fullbank not admitted')
 return report
def load(repo,name):
 path=P(repo)/'economic-atlas/src'/name;s=importlib.util.spec_from_file_location(name[:-3],path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def remaining_original(spec,anchor):
 """One allowance: earliest original monotonic or absolute UTC deadline."""
 mono=finite(spec['whole_seconds'])-(time.monotonic()-anchor)
 utc=(datetime.datetime.fromisoformat(spec['absolute_deadline_UTC'])-datetime.datetime.now(datetime.timezone.utc)).total_seconds()
 if not math.isfinite(mono)or not math.isfinite(utc):raise ValueError('nonfinite original remaining allowance')
 return max(0,min(mono,utc))
class Guard:
 def __init__(self,spec,anchor,roots,native,admission):
  self.spec=spec;self.anchor=anchor;self.roots=roots;self.native=native;self.whole_seconds=spec['whole_seconds'];self.finalization_reserve_seconds=spec['finalization_reserve_seconds'];self.source_binding=SOURCE_BINDING;self.qualified_e05_audit_io=True;self.resource_admission_SHA=admission['real_IO_resource_report_SHA'];self.phase='science'
 def __call__(self):
  if hasattr(self,'binding_snapshot'):check_snapshot(self.binding_snapshot)
  from e05_full_guardian_toolkit_v2 import total_bytes
  elapsed=time.monotonic()-self.anchor;reserve=self.spec['finalization_reserve_seconds']if self.phase=='science'else self.spec['audit_receipt_reserve_seconds']
  if elapsed<0 or elapsed>=self.whole_seconds-reserve:raise InterruptedError('whole entry anchor/reserve exhausted')
  if datetime.datetime.now(datetime.timezone.utc)>=datetime.datetime.fromisoformat(self.spec['absolute_deadline_UTC']):raise InterruptedError('absolute deadline')
  if shutil.disk_usage(OUT.parent).free<self.spec['minimum_free_bytes']:raise InterruptedError('minimum free admission')
  if total_bytes(self.roots)>self.spec['output_bytes']-self.spec['receipt_reserve_bytes']:raise InterruptedError('whole output/control/lease roots')
  rss,_=self.native.own_tree_rss()
  if finite(rss)>self.spec['RSS_bytes']:raise InterruptedError('known own aggregate RSS')
  if remaining_original(self.spec,self.anchor)<=reserve:raise InterruptedError('resource scan consumed original allowance')
def stop(signum,frame):raise InterruptedError('owned operation interrupt '+str(signum))
def fallback_owned_cleanup(process,groups,guard):
 """Independent failclosed fallback; ONLY handles retained from own Popen/tree.
 Each wait/signal consumes remaining original allowance; no fresh budget.
 """
 if type(process.pid)is not int or process.pid not in groups or any(type(g)is not int or g<=0 or g==os.getpgrp()for g in groups):raise ValueError('never signal unowned group')
 end=min(guard.anchor+guard.whole_seconds,time.monotonic()+guard.spec['cleanup_seconds']);errors=[];reaped=False
 def remaining():return max(0,min(end-time.monotonic(),remaining_original(guard.spec,guard.anchor)))
 def send(sig):
  for group in groups:
   if remaining()<=0:errors.append('original cleanup allowance exhausted');return
   try:os.killpg(group,sig)
   except ProcessLookupError:pass
   except BaseException as e:errors.append(repr(e))
 send(signal.SIGTERM)
 try:process.wait(timeout=remaining()/3);reaped=True
 except subprocess.TimeoutExpired:pass
 except BaseException as e:errors.append(repr(e))
 send(signal.SIGKILL)
 if not reaped:
  try:process.wait(timeout=remaining()/2);reaped=True
  except BaseException as e:errors.append(repr(e))
 gone=True
 for group in groups:
  try:os.killpg(group,0);gone=False
  except ProcessLookupError:pass
  except BaseException as e:gone=False;errors.append(repr(e))
 return {'reaped':reaped,'owned_groups_gone':gone,'unknown':not(reaped and gone and not errors),'errors':errors,'fallback':True}
def supervise(command,guard,authorization,secret,*,factory=subprocess.Popen):
 """Bounded real foreground dispatch. Register own handle immediately."""
 from e05_full_guardian_toolkit_v2 import cleanup_owned
 process=None;groups=set();state={'state':'INCONCLUSIVE','automatic_retry':False,'continuous_resource_PASS':False};logs=[]
 try:
  guard();env=dict(os.environ);env.update({k:'1'for k in THREADS});env['E05_PRIVATE_TOKEN']=secret;env['PYTHONDONTWRITEBYTECODE']='1'
  process=factory(command,env=env,start_new_session=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE);groups.add(process.pid)
  once(CONTROL/'worker-authorization.json',dict(authorization,owned_PID=process.pid,secret_SHA=hashlib.sha256(secret.encode()).hexdigest()))
  for fd,name in ((process.stdout,'stdout.log'),(process.stderr,'stderr.log')):os.set_blocking(fd.fileno(),False);logs.append((fd,(CONTROL/name).open('xb')))
  while True:
   guard()
   # Native discovery traverses only this known spawned parent; never scans PIDs.
   for pid in guard.native.descendants(process.pid):
    try:pg=os.getpgid(pid)
    except ProcessLookupError:continue
    if pg==pid and pg!=os.getpgrp():groups.add(pg)
    elif pg not in groups:raise InterruptedError('known child joined unowned group; never signal foreign group')
   ready,_,_=select.select([fd for fd,_ in logs],[],[],guard.spec['poll_seconds'])
   for fd,out in logs:
    if fd in ready:
     data=os.read(fd.fileno(),4096)
     if data:out.write(data);out.flush();guard()
   code=process.poll()
   if code is not None:
    # Drain bounded pending pipe bytes; continue guard checks, no capture_output.
    for fd,out in logs:
     while True:
      try:data=os.read(fd.fileno(),4096)
      except BlockingIOError:break
      if not data:break
      out.write(data);out.flush();guard()
    process.wait(timeout=remaining_original(guard.spec,guard.anchor));state.update(state='WORKER_EXIT_OBSERVED',exitcode=code);break
 except BaseException as e:state['error']=type(e).__name__+': '+str(e)
 finally:
  for fd,out in logs:
   try:out.flush();os.fsync(out.fileno());out.close();fd.close()
   except Exception as e:state['log_close_error']=repr(e)
  if process is not None:
   try:state['cleanup']=cleanup_owned(process,groups,min(guard.spec['cleanup_seconds'],remaining_original(guard.spec,guard.anchor)))
   except BaseException as e:
    state['cleanup_original_error']=repr(e)
    try:state['cleanup']=fallback_owned_cleanup(process,groups,guard)
    except BaseException as secondary:state['cleanup_unknown']=repr(secondary)
 return state
def main(argv=None):
 # Module entry precedes imports; early handlers cover source/admission/setup.
 if signal.getitimer(signal.ITIMER_REAL)!=(0.0,0.0):return 1 # never alter a foreign existing timer
 old={s:signal.getsignal(s)for s in (signal.SIGTERM,signal.SIGINT)};owned=False;timer_owned=False;terminal_written=False;guard=None;state={'state':'INCONCLUSIVE','scientific_pass':False,'automatic_retry':False}
 for s in old:signal.signal(s,stop)
 previous_alarm=signal.getsignal(signal.SIGALRM);signal.signal(signal.SIGALRM,stop)
 try:
  ap=argparse.ArgumentParser();ap.add_argument('--repo',type=P,required=True);ap.add_argument('--root-binding',type=P,required=True);args=ap.parse_args(argv)
  binding_path=regular(args.root_binding)
  if binding_path.stat().st_uid!=os.getuid()or binding_path.stat().st_mode&0o077:raise ValueError('private UID root binding')
  binding_snapshot=snapshot(binding_path);binding=read(binding_path);check_snapshot(binding_snapshot);pre=remaining_original(binding['spec'],ENTRY)-finite(binding['spec']['audit_receipt_reserve_seconds'])
  if pre<=0:raise InterruptedError('startup whole budget exhausted')
  if signal.getitimer(signal.ITIMER_REAL)!=(0.0,0.0):raise RuntimeError('refuse reentrant existing timer')
  signal.setitimer(signal.ITIMER_REAL,pre);timer_owned=True;spec=validate(binding,args.repo)
  if time.monotonic()-ENTRY>=spec['whole_seconds']-spec['finalization_reserve_seconds']:raise InterruptedError('startup budget consumed')
  if shutil.disk_usage(OUT.parent).free<spec['minimum_free_bytes']:raise InterruptedError('disk before namespace/native admission')
  check_snapshot(binding_snapshot)
  if any(p.exists()or p.is_symlink()for p in (OUT,CONTROL,LEDGER)):raise ValueError('existing canonical operation; no resume/rekey')
  private_dir(CONTROL);owned=True;private_dir(LEDGER)
  sys.path.insert(0,str(args.repo/'economic-atlas/src'));native=load(args.repo,'atlas_m1_executor.py').NativeMac();guard=Guard(spec,ENTRY,[OUT,CONTROL,LEDGER],native,binding);guard.binding_snapshot=binding_snapshot;guard()
  original=dict(operation=KEY,state='STARTED',original_anchor=ENTRY,entry_UTC=datetime.datetime.fromtimestamp(ENTRY_UTC_EPOCH,datetime.timezone.utc).isoformat(),whole_seconds=spec['whole_seconds'],finalization_reserve_seconds=spec['finalization_reserve_seconds'],source_binding=SOURCE_BINDING,panel_SHA=PANEL_SHA,admissionreportSHA=binding['real_IO_resource_report_SHA'])
  check_snapshot(binding_snapshot);once(LEDGER/'operation.json',dict(original,root_binding_SHA=binding_snapshot['SHA'],root_binding_stat=binding_snapshot['stat']));once(CONTROL/'admission.json',binding)
  auth=dict(parent_PID=os.getpid(),UID=os.getuid(),repo=str(args.repo),root_binding_SHA=binding_snapshot['SHA'],root_binding_stat=binding_snapshot['stat'],source_pins=binding['source_pins'],python_SHA=binding['python_SHA'],anchor=ENTRY,whole_seconds=spec['whole_seconds'],out=str(OUT),control=str(CONTROL),ledger=str(LEDGER))
  command=[sys.executable,str(args.repo/'economic-atlas/src/e05_full_execution_worker.py'),'--repo',str(args.repo),'--root-binding',str(args.root_binding)]
  check_snapshot(binding_snapshot);worker=supervise(command,guard,auth,secrets.token_hex(32));once(CONTROL/'worker-terminal.json',worker)
  if worker.get('cleanup',{}).get('unknown',True):raise InterruptedError('owned lifecycle unresolved; publication blocked')
  guard.phase='publication';guard();territory=CONTROL/'territory-universe.json';universe=read(CONTROL/'territory-binding.json')
  if universe['panel_SHA']!=PANEL_SHA or universe['original_anchor']!=ENTRY or universe['territory_file_SHA']!=sha(territory)or universe['source_pins']!=binding['source_pins']:raise ValueError('durable original universe binding')
  original['territory_ids_SHA']=hashlib.sha256(json.dumps(read(territory),sort_keys=True,separators=(',',':')).encode()).hexdigest()
  if universe['territory_ids_SHA']!=original['territory_ids_SHA']:raise ValueError('exact tuple universe hash')
  once(CONTROL/'original-operation-universe-bound.json',dict(original,initial_operation_SHA=sha(LEDGER/'operation.json'),territory_binding_SHA=sha(CONTROL/'territory-binding.json')))
  check_snapshot(binding_snapshot);bridge=load(args.repo,'e05_full_real_publication_bridge.py')
  result=bridge.complete_and_audit(repo=args.repo,raw_root=OUT/'raw',publication_root=OUT/'publication',stage_root=OUT/'publication-stage',journal_root=OUT/'journals',territory_file=territory,guard=guard,original_operation=original,admission=binding,finalization_lease=LEDGER/'finalization.json')
  state.update(state='FULL_PUBLICATION_AND_AUDIT_RECEIPT',result=result)
 except BaseException as e:state['error']=type(e).__name__+': '+str(e)
 finally:
  if timer_owned:
   remaining=remaining_original(binding['spec'],ENTRY)
   signal.setitimer(signal.ITIMER_REAL,remaining if remaining>0 else 0)
  else:remaining=0
  state.update(original_anchor=ENTRY,elapsed_before_terminal=time.monotonic()-ENTRY,continuous_resource_PASS=False,solver_numerical_audit='UNKNOWN_FINGERPRINTS_ONLY_NOT_RESIDUALS')
  if owned and remaining>0:
   try:once(CONTROL/'terminal.json',state);terminal_written=True
   except BaseException as e:state['terminal_durability_unknown']=repr(e);state['state']='INCONCLUSIVE_TERMINAL_DURABILITY'
  if owned and not terminal_written:state['state']='INCONCLUSIVE_NO_DURABLE_TERMINAL'
  if guard is not None:
   from e05_full_guardian_toolkit_v2 import total_bytes
   if remaining_original(guard.spec,ENTRY)<=0 or total_bytes(guard.roots)>guard.spec['output_bytes']:state['final_IO_budget_violation']=True;state['state']='INCONCLUSIVE_FINAL_IO_LIMIT'
  if timer_owned:signal.setitimer(signal.ITIMER_REAL,0)
  signal.signal(signal.SIGALRM,previous_alarm)
  for s,h in old.items():signal.signal(s,h)
 return 0 if terminal_written and state['state']=='FULL_PUBLICATION_AND_AUDIT_RECEIPT'else 1
if __name__=='__main__':sys.exit(main())
