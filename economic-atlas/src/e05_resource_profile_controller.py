"""Owned E05 diagnostic controller; NO default runtime and no bank admission."""
import time
ENTRY=time.monotonic()
import datetime,hashlib,importlib.metadata,json,math,os,pathlib,secrets,selectors,signal,subprocess,sys
P=pathlib.Path
CONTROL=P('/private/tmp/e05-resource-profile-control-v1')
OUT=P('/private/tmp/e05-resource-preflight-fullshape-v1')
LEDGER=P('/private/tmp/e05-resource-preflight-fullshape-v1-ledger')
KEY='E05-resource-profile-controller-v1'
CPU_ENV=('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS')
MAX_LOG_BYTES=8192

def sha(path):
 h=hashlib.sha256()
 with P(path).open('rb')as f:
  for b in iter(lambda:f.read(65536),b''):h.update(b)
 return h.hexdigest()

def read_private(path):
 path=P(path);s=path.lstat()
 if path.is_symlink()or not path.is_file()or s.st_uid!=os.getuid()or s.st_mode&0o077:raise ValueError('private regular owner file')
 if s.st_size>262144:raise ValueError('bounded private metadata')
 return json.loads(path.read_bytes())

def sync_dir(path):
 fd=os.open(path,os.O_RDONLY)
 try:os.fsync(fd)
 finally:os.close(fd)

def once(path,obj):
 if P(path).is_symlink():raise ValueError('symlink')
 fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
 with os.fdopen(fd,'w')as f:json.dump(obj,f,allow_nan=False);f.write('\n');f.flush();os.fsync(f.fileno())
 sync_dir(P(path).parent)

def finite(x):
 if isinstance(x,bool)or not isinstance(x,(float,int))or not math.isfinite(x):raise ValueError('finite nonbool')
 return x

def owned_bytes(roots):
 size=0;seen=set()
 for root in roots:
  if root.is_symlink():raise ValueError('root symlink')
  for f in root.rglob('*')if root.is_dir()else []:
   if f.is_symlink():raise ValueError('output symlink')
   if f.is_file():
    s=f.stat();key=s.st_dev,s.st_ino
    if key not in seen:size+=s.st_size;seen.add(key)
 return size

def admit(repo):
 """Private runtime/ACK are trusted root-owned instructions, not boolean capability.
 All exact byte bindings and complete budget validated before lease/Popen.
 """
 if CONTROL.is_symlink()or CONTROL.stat().st_uid!=os.getuid()or CONTROL.stat().st_mode&0o077:raise ValueError('private fixed control')
 required={'runtime.json','runtime-acceptance.json','source-ack.json'}
 if {p.name for p in CONTROL.iterdir()}!=required:raise FileExistsError('consumed/unknown control namespace')
 if OUT.exists()or LEDGER.exists()or OUT.is_symlink()or LEDGER.is_symlink():raise FileExistsError('profile consumed/collision')
 bindings={name:sha(CONTROL/name)for name in required}
 r=read_private(CONTROL/'runtime.json');approval=read_private(CONTROL/'runtime-acceptance.json');ack=read_private(CONTROL/'source-ack.json')
 if any(sha(CONTROL/name)!=h for name,h in bindings.items()):raise ValueError('input byte binding changed during admission')
 if approval.get('kind')!='ROOT_SOURCE_QUALIFIED_FROZEN_RUNTIME' or approval.get('runtime_SHA256')!=sha(CONTROL/'runtime.json') or approval.get('source_ACK_SHA256')!=sha(CONTROL/'source-ack.json'):raise ValueError('exact root runtime/source binding')
 if ack.get('verdict')!='SOURCE_ONLY_ACK' or ack.get('scientific_execution') is not False:raise ValueError('independent source ACK required')
 if r.get('key')!=KEY or r.get('repo')!=str(P(repo).resolve()):raise ValueError('fixed root/operation binding')
 if r.get('host')!=os.uname().nodename or type(r.get('UID'))is not int or r['UID']!=os.getuid():raise ValueError('samehost UID')
 executable=P(sys.executable).resolve()
 if r['python_path']!=str(executable)or r['python_SHA256']!=sha(executable):raise ValueError('Python bytes')
 for pkg,version in r['package_versions'].items():
  if importlib.metadata.version(pkg)!=version:raise ValueError('dependency '+pkg)
 if set(r['package_versions'])!={'numpy','pandas','scipy','scikit-learn','pyarrow','psutil'}:raise ValueError('complete dependency version pins')
 proto=P(repo)/'economic-atlas/protocols/E05_RESOURCE_PROFILE_CONTROLLER_V1.json'
 if r['protocol_SHA256']!=sha(proto)or ack['source_pins'].get('economic-atlas/protocols/E05_RESOURCE_PROFILE_CONTROLLER_V1.json')!=r['protocol_SHA256']:raise ValueError('controller protocol ACK pin')
 p=json.loads(proto.read_bytes())
 for rel,h in p['source_pins'].items():
  f=P(repo)/rel
  if f.is_symlink()or sha(f)!=h or ack['source_pins'].get(rel)!=h:raise ValueError('source/ACK pin '+rel)
 for rel in ['economic-atlas/src/e05_resource_profile_controller.py','economic-atlas/src/e05_resource_profile_worker.py']:
  if sha(P(repo)/rel)!=r['source_pins'].get(rel)or ack['source_pins'].get(rel)!=r['source_pins'][rel]:raise ValueError('controller/worker ACK')
 # Budget validation is stdlib only; no profile numerical imports.
 for k in ['whole_seconds','final_reserve_seconds','cleanup_seconds','poll_seconds']:
  if finite(r[k])<=0:raise ValueError(k)
 if r['poll_seconds']>1:raise ValueError('poll must be at most1s')
 if not 0<r['cleanup_seconds']<=r['final_reserve_seconds']<r['whole_seconds']:raise ValueError('one reserve/whole')
 for k,value in [('CPU_threads',1),('RSS_bytes',2**30),('minimum_free_bytes',2**30),('output_bytes',128*2**20)]:
  if type(r[k])is not int or r[k]!=value:raise ValueError('fixed '+k)
 if type(r['receipt_reserve_bytes'])is not int or not 0<r['receipt_reserve_bytes']<r['output_bytes']:raise ValueError('receipt reserve')
 deadline=datetime.datetime.fromisoformat(r['absolute_deadline_UTC'])
 if deadline.tzinfo is None or deadline.utcoffset()!=datetime.timedelta(0)or deadline<=datetime.datetime.now(datetime.timezone.utc):raise ValueError('UTC deadline')
 if time.monotonic()-ENTRY>=r['whole_seconds']-r['final_reserve_seconds']:raise InterruptedError('entry inclusive admission')
 r['_bindings']=bindings
 return r,p

def load_native(repo):
 import importlib.util
 path=P(repo)/'economic-atlas/src/atlas_m1_executor.py'
 sp=importlib.util.spec_from_file_location('profile_native_known_parent',path);module=importlib.util.module_from_spec(sp);sp.loader.exec_module(module)
 return module.NativeMac()

class OwnedTree:
 """Known-parent NativeMac discovery; psutil only exact known PID identities.
 No process_iter/global process enumeration or psutil children walk.
 """
 def __init__(self,ps,native,worker):
  self.ps=ps;self.native=native;self.worker=worker;self.groups={worker.pid};self.records={};self.observe()
 def capture(self,pid):
  p=self.ps.Process(pid)
  if p.uids().real!=os.getuid():raise RuntimeError('unknown UID')
  identity=(p.pid,p.create_time());self.records[identity]=p
  pg=os.getpgid(pid)
  if pg==pid and pg!=os.getpgrp():self.groups.add(pg)
  elif pg not in self.groups:raise RuntimeError('known descendant joined foreign group')
 def observe(self):
  for pid in [self.worker.pid]+self.native.descendants(self.worker.pid):
   try:self.capture(pid)
   except self.ps.NoSuchProcess:pass
  return self.live()
 def matching(self):
  result=[]
  for (pid,created),p in self.records.items():
   try:
    if p.is_running()and p.create_time()==created:result.append(p)
   except self.ps.NoSuchProcess:pass
  return result
 def live(self):return [p for p in self.matching()if p.status()!=self.ps.STATUS_ZOMBIE]
 def rss(self):
  self.observe();sizes=[self.native.rss(os.getpid())]+[self.native.rss(p.pid)for p in self.matching()]
  if sizes[0]is None or sizes[0]<=0:raise RuntimeError('own parent RSS unavailable')
  return sum(x for x in sizes if x is not None)
 def cleanup(self,deadline):return fallback_known_child(self.worker,self.groups,deadline)

def fallback_known_child(worker,groups,deadline):
 """Fallback uses only the retained own Popen/session registry. Same original end.
 No extra wait allowance; ambiguous/gone proof fails closed.
 """
 if type(worker.pid)is not int or worker.pid not in groups or any(type(g)is not int or g<=0 or g==os.getpgrp()for g in groups):raise ValueError('registered own Popen groups only')
 errors=[];reaped=False
 for sig in (signal.SIGTERM,signal.SIGKILL):
  for pg in groups:
   try:os.killpg(pg,sig)
   except ProcessLookupError:pass
   except BaseException as e:errors.append(type(e).__name__)
  try:worker.wait(timeout=max(0,deadline-time.monotonic())/(2 if sig==signal.SIGTERM else 1));reaped=True
  except subprocess.TimeoutExpired:pass
  except BaseException as e:errors.append(type(e).__name__)
 gone=True
 for pg in groups:
  try:os.killpg(pg,0);gone=False
  except ProcessLookupError:pass
  except BaseException as e:errors.append(type(e).__name__);gone=False
 if not(reaped and gone and not errors):raise RuntimeError('OWN_CLEANUP_UNKNOWN; no extra allowance')
 return {'worker_reaped':True,'known_owned_survivors':0,'registered_owned_PG_survivors':0,'unknown_detached_process_absence_certified':False}

def final_gate(result,terminal_written,r,absolute,roots):
 """Called after terminal IO and again after post receipt IO; no clock reset."""
 if not terminal_written:return False
 if time.monotonic()-ENTRY>=r['whole_seconds']or datetime.datetime.now(datetime.timezone.utc)>=absolute:return False
 if owned_bytes(roots)>r['output_bytes']:return False
 # Last resource scan consumes the SAME original allowance; check after it too.
 if time.monotonic()-ENTRY>=r['whole_seconds']or datetime.datetime.now(datetime.timezone.utc)>=absolute:return False
 return successful_state(result)

def successful_state(result):
 clean=result.get('cleanup',{})
 return result.get('state')=='RESOURCE_PROFILE_CHILD_EXITED_NOT_FULL_QUALIFICATION'and result.get('exit')==0 and clean.get('worker_reaped')is True and clean.get('known_owned_survivors')==0 and clean.get('registered_owned_PG_survivors')==0

def successful_exit(result):
 return successful_state(result)and result.get('terminal_written')is True and result.get('post_IO_gate')is True

def main(repo):
 r,p=admit(repo);stop={'reason':None};old={}
 # Handler only marks stop. No recursive guard scan or clock reset.
 def stopping(sig,frame):stop['reason']='signal '+str(sig)
 for sig in (signal.SIGTERM,signal.SIGINT):old[sig]=signal.signal(sig,stopping)
 worker=None;tree=None;sel=None;logs={};terminal_written=False;result={'state':'INCONCLUSIVE_CONTROLLER','scientific_bank_started':False,'resource_PASS':False}
 deadline_mono=ENTRY+r['whole_seconds'];work_deadline=deadline_mono-r['final_reserve_seconds']
 absolute=datetime.datetime.fromisoformat(r['absolute_deadline_UTC'])
 try:
  once(CONTROL/'controller-operation.json',{'key':KEY,'state':'STARTED','ENTRY':ENTRY,'runtime_SHA256':sha(CONTROL/'runtime.json'),'source_ACK_SHA256':sha(CONTROL/'source-ack.json')})
  import psutil
  native=load_native(repo)
  spec=dict(r,original_anchor=ENTRY,external_whole_supervisor_source_accepted=True,execution_authorized=True)
  worker_path=P(repo)/'economic-atlas/src/e05_resource_profile_worker.py';nonce=secrets.token_hex(32)
  command=[sys.executable,str(worker_path),'--token',str(CONTROL/'dispatch-token.json')]
  token={'nonce':nonce,'parentPID':os.getpid(),'parent_create_time':psutil.Process(os.getpid()).create_time(),'UID':os.getuid(),'created_monotonic':time.monotonic(),'valid_until_monotonic':min(work_deadline,time.monotonic()+45),'repo':str(P(repo).resolve()),'worker_SHA256':sha(worker_path),'command_SHA256':hashlib.sha256(json.dumps(command).encode()).hexdigest(),'runtime_SHA256':r['_bindings']['runtime.json'],'spec':spec,'source_protocol':p}
  once(CONTROL/'dispatch-token.json',token)
  env=os.environ.copy();env.update({k:'1'for k in CPU_ENV});env['PYTHONDONTWRITEBYTECODE']='1'
  free=os.statvfs(OUT.parent);free=free.f_bavail*free.f_frsize
  if psutil.Process(os.getpid()).memory_info().rss>r['RSS_bytes']or free<r['minimum_free_bytes']or owned_bytes([OUT,LEDGER,CONTROL])>r['output_bytes']-r['receipt_reserve_bytes']:raise InterruptedError('resources before dispatch')
  if time.monotonic()>=work_deadline or datetime.datetime.now(datetime.timezone.utc)>=absolute or stop['reason']:raise InterruptedError('before dispatch')
  if any(sha(CONTROL/name)!=h for name,h in r['_bindings'].items()):raise ValueError('runtime/ACK changed before dispatch')
  worker=subprocess.Popen(command,env=env,start_new_session=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
  tree=OwnedTree(psutil,native,worker);once(CONTROL/'worker-binding.json',{'PID':worker.pid,'PGID':worker.pid,'command_SHA256':token['command_SHA256'],'nonce_SHA256':hashlib.sha256(nonce.encode()).hexdigest()})
  sel=selectors.DefaultSelector()
  for name,pipe in [('stdout',worker.stdout),('stderr',worker.stderr)]:
   os.set_blocking(pipe.fileno(),False);sel.register(pipe,selectors.EVENT_READ,name);fd=os.open(CONTROL/(name+'.log'),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);logs[name]=[fd,0]
  samples={'peak_aggregate_RSS':0,'min_free_bytes':None,'peak_combined_bytes':0,'count':0}
  while True:
   elapsed=time.monotonic()-ENTRY;rss=tree.rss();free=os.statvfs(OUT.parent);free=free.f_bavail*free.f_frsize;size=owned_bytes([OUT,LEDGER,CONTROL]);samples['count']+=1;samples['peak_aggregate_RSS']=max(samples['peak_aggregate_RSS'],rss);samples['min_free_bytes']=free if samples['min_free_bytes']is None else min(free,samples['min_free_bytes']);samples['peak_combined_bytes']=max(samples['peak_combined_bytes'],size)
   if stop['reason']or time.monotonic()>=work_deadline or datetime.datetime.now(datetime.timezone.utc)>=absolute or rss>r['RSS_bytes']or free<r['minimum_free_bytes']or size>r['output_bytes']-r['receipt_reserve_bytes']:raise InterruptedError('sampled whole/RSS/free/output/signal limit')
   for key,_ in sel.select(min(r['poll_seconds'],max(0,work_deadline-time.monotonic()))):
    data=os.read(key.fileobj.fileno(),4096)
    if not data:sel.unregister(key.fileobj);continue
    fd,n=logs[key.data]
    if n+len(data)>MAX_LOG_BYTES:raise InterruptedError('bounded log cap')
    os.write(fd,data);logs[key.data][1]+=len(data)
   if worker.poll()is not None and not sel.get_map():break
  result.update(state='RESOURCE_PROFILE_CHILD_EXITED_NOT_FULL_QUALIFICATION',exit=worker.returncode,samples=samples)
 except BaseException as e:result.update(error=type(e).__name__+': '+str(e))
 finally:
  # Signals ignored only during bounded own cleanup; totalclock unchanged.
  for sig in old:signal.signal(sig,signal.SIG_IGN)
  try:
   cleanup_deadline=min(deadline_mono,time.monotonic()+r['cleanup_seconds'],time.monotonic()+max(0,(absolute-datetime.datetime.now(datetime.timezone.utc)).total_seconds()))
   if worker is not None:
    groups=tree.groups if tree is not None else {worker.pid}
    try:
     if tree is None:raise RuntimeError('known tree binding failed')
     result['cleanup']=tree.cleanup(cleanup_deadline)
    except BaseException as primary:
     result['cleanup_primary_error']=type(primary).__name__
     result['cleanup']=fallback_known_child(worker,groups,cleanup_deadline)
     if tree is None:result['state']='INCONCLUSIVE_IDENTITY_BINDING'
  except BaseException as e:result.update(state='INCONCLUSIVE_CLEANUP_UNKNOWN',cleanup_error=type(e).__name__)
  if sel is not None:sel.close()
  for fd,n in logs.values():
   try:os.fsync(fd)
   except BaseException as e:result.update(state='INCONCLUSIVE_LOG_IO',log_IO_error=type(e).__name__)
   finally:os.close(fd)
  try:
   if any(sha(CONTROL/name)!=h for name,h in r['_bindings'].items()):result.update(state='INCONCLUSIVE_BINDING_CHANGED')
  except BaseException as e:result.update(state='INCONCLUSIVE_BINDING_UNKNOWN',binding_error=type(e).__name__)
  result.update(ENTRY=ENTRY,elapsed_before_terminal_fsync=time.monotonic()-ENTRY,final_controller_receipt_IO_independently_timed=False,monitor='sampled; blocking call bounded by outer process loop',whole_seconds=r['whole_seconds'],absolute_deadline_UTC=r['absolute_deadline_UTC'])
  try:
   once(CONTROL/'controller-terminal.json',result);terminal_written=True
  except BaseException as e:result.update(state='INCONCLUSIVE_TERMINAL_DURABILITY',terminal_error=type(e).__name__)
  result['terminal_written']=terminal_written
  try:
   result['post_IO_gate']=final_gate(result,terminal_written,r,absolute,[OUT,LEDGER,CONTROL])
   if not result['post_IO_gate']:result['state']='INCONCLUSIVE_FINAL_GATE'
   once(CONTROL/'controller-post-IO.json',{'state':result['state'],'terminal_written':terminal_written,'post_IO_gate':result['post_IO_gate'],'elapsed_through_terminal_fsync':time.monotonic()-ENTRY,'last_receipt_IO_independently_timed':False})
   result['post_IO_gate']=final_gate(result,terminal_written,r,absolute,[OUT,LEDGER,CONTROL])
   if not result['post_IO_gate']:result['state']='INCONCLUSIVE_FINAL_IO'
  except BaseException as e:result.update(state='INCONCLUSIVE_FINAL_IO',post_IO_gate=False,final_IO_error=type(e).__name__)
  finally:
   for sig,handler in old.items():signal.signal(sig,handler)

 return result

if __name__=='__main__':
 if len(sys.argv)!=2:raise SystemExit('explicit pinned repo argument required')
 outcome=main(sys.argv[1]);raise SystemExit(0 if successful_exit(outcome)else 1)
