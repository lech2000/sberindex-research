"""SOURCE ONLY E05 supervision primitives. Public execute ALWAYS refuses."""
import time
ENTRY=time.monotonic()
import datetime,hashlib,json,math,os,pathlib,resource,shutil,signal,subprocess,sys
P=pathlib.Path
KEY='E05-full-event-repaired-225cells-v1'  # Own namespace, never another study's key.
OUT=P('/private/tmp/e05-full-event-repaired-actual')
CONTROL=P('/private/tmp/e05-full-event-repaired-control')
LEDGER=P('/private/tmp/e05-full-event-repaired-operation-ledger')
LEASE=LEDGER/'operation.json'

def finite(v):
 if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v):raise ValueError('finite nonbool scalar')
 return v

def sha(p):
 h=hashlib.sha256()
 with P(p).open('rb') as f:
  for data in iter(lambda:f.read(65536),b''):h.update(data)
 return h.hexdigest()

def sync_parent(p):
 fd=os.open(P(p).parent,os.O_RDONLY)
 try:os.fsync(fd)
 finally:os.close(fd)

def once(p,v):
 fd=os.open(p,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
 with os.fdopen(fd,'w') as f:json.dump(v,f,allow_nan=False,ensure_ascii=False);f.write('\n');f.flush();os.fsync(f.fileno())
 sync_parent(p)

def operational_spec(spec):
 """No default runtime estimates: unknown values reject before mutation."""
 for name in ['whole_seconds','final_receipt_reserve_seconds','RSS_bytes','minimum_free_bytes','output_bytes','receipt_reserve_bytes','poll_seconds','cleanup_seconds']:
  if finite(spec[name])<=0:raise ValueError('positive explicit budget '+name)
 if spec['final_receipt_reserve_seconds']>=spec['whole_seconds'] or spec['receipt_reserve_bytes']>=spec['output_bytes']:raise ValueError('positive work budget after reserve')
 if spec['cleanup_seconds']>spec['final_receipt_reserve_seconds']:raise ValueError('cleanup shares final reserve')
 if type(spec['CPU_threads'])is not int or spec['CPU_threads']!=1:raise ValueError('inherited CPU1 only')
 deadline=datetime.datetime.fromisoformat(spec['absolute_deadline_UTC'])
 if deadline.tzinfo is None or deadline.utcoffset()!=datetime.timedelta(0):raise ValueError('explicit UTC deadline')
 if spec.get('actual_fullsize_preflight_accepted') is not True or spec.get('resource_spec_independently_accepted') is not True:raise ValueError('resource specification/preflight pending')
 return deadline

def total_bytes(roots):
 seen=set();total=0
 for root in map(P,roots):
  if root.is_symlink():raise ValueError('owned root symlink')
  paths=[root] if root.is_file() else root.rglob('*') if root.is_dir() else []
  for p in paths:
   if p.is_symlink():raise ValueError('owned output symlink')
   if p.is_file() and str(p.resolve()) not in seen:seen.add(str(p.resolve()));total+=p.stat().st_size
 return total

class Budget:
 """Polling, no SIGALRM: expensive directory scan cannot reenter itself."""
 def __init__(self,spec,anchor,roots,rss_observer,free_observer=None):
  self.spec=spec;self.deadline=operational_spec(spec);self.anchor=finite(anchor);self.roots=roots;self.rss=rss_observer;self.free=free_observer or (lambda:shutil.disk_usage(OUT.parent).free)
 def check(self):
  elapsed=time.monotonic()-self.anchor
  if elapsed<0 or elapsed>self.spec['whole_seconds']-self.spec['final_receipt_reserve_seconds']:raise InterruptedError('original whole anchor/reserve exhausted')
  if datetime.datetime.now(datetime.timezone.utc)>self.deadline:raise InterruptedError('whole absolute deadline')
  if total_bytes(self.roots)>self.spec['output_bytes']-self.spec['receipt_reserve_bytes']:raise InterruptedError('combined output reserve')
  if finite(self.free())<self.spec['minimum_free_bytes']:raise InterruptedError('minimum free disk')
  if finite(self.rss())>self.spec['RSS_bytes']:raise InterruptedError('known-own aggregate RSS')
  elapsed=time.monotonic()-self.anchor
  if elapsed<0 or elapsed>self.spec['whole_seconds']-self.spec['final_receipt_reserve_seconds'] or datetime.datetime.now(datetime.timezone.utc)>self.deadline:raise InterruptedError('guard IO consumed original allowance')
  return elapsed

class Journal:
 """One durable per-cell/per-native key; unknown and failed are never retried."""
 def __init__(self,root,guard):self.root=P(root);self.guard=guard
 def path(self,key,state):return self.root/(hashlib.sha256(key.encode()).hexdigest()+'.'+state+'.json')
 def start(self,key,request):
  self.guard()
  try:once(self.path(key,'STARTED'),{'key':key,'request':request,'monotonic':time.monotonic()})
  except FileExistsError:raise
  except BaseException as e:raise InterruptedError('durability UNKNOWN; no dispatch/retry') from e
 def response(self,key,result):
  self.guard();started=self.path(key,'STARTED')
  if not started.is_file():raise ValueError('response without durable start')
  try:once(self.path(key,'RESPONSE'),{'key':key,'started_SHA':sha(started),'result':result,'monotonic':time.monotonic()})
  except BaseException as e:raise InterruptedError('response durability UNKNOWN; no retry') from e
 def call(self,key,request,fn):
  self.start(key,request);value=fn();self.response(key,value);return value

def require_fresh():
 if any(p.exists() or p.is_symlink() for p in [OUT,CONTROL,LEASE]):raise ValueError('existing E05 operation/namespace cannot resume or alias')

def cleanup_owned(process,known_groups,remaining_seconds,*,clock=time.monotonic,sleep=time.sleep):
 """Known-own SESSION GROUPS only; leader exit never means subtree exit.
 The caller must establish these handles from its own child/tree observations.
 killpg(group,0) probes registered groups even after their leaders exit; no
 arbitrary PID walk/search. No real process invokes this source-only toolkit.
 """
 if process is None:return {'reaped':True,'owned_groups_gone':True,'unknown':False}
 foreground=os.getpgrp()
 if type(process.pid)is not int or process.pid not in known_groups:raise ValueError('refuse unregistered child')
 if not known_groups or any(type(pid)is not int or pid<=0 or pid==foreground for pid in known_groups):raise ValueError('refuse foreign/foreground group')
 finite(remaining_seconds)
 if remaining_seconds<0:raise ValueError('cleanup requires remaining original allowance')
 deadline=clock()+remaining_seconds;reaped=False;errors=[];killed=False
 def alive(pid):
  try:os.killpg(pid,0);return True
  except ProcessLookupError:return False
  except PermissionError:errors.append('unknown group permission');return True
 def send(pid,sig):
  try:os.killpg(pid,sig)
  except ProcessLookupError:pass
  except PermissionError:errors.append('unknown group permission')
 # Always inspect/terminate registered groups, even when poll()==0 or !=0.
 for pid in sorted(known_groups,reverse=True):
  if alive(pid):send(pid,signal.SIGTERM)
 try:process.wait(timeout=max(0,deadline-clock()));reaped=True
 except subprocess.TimeoutExpired:pass
 grace=clock()+max(0,deadline-clock())/2
 while clock()<grace and any(alive(pid) for pid in known_groups):sleep(min(.01,max(0,grace-clock())))
 for pid in sorted(known_groups,reverse=True):
  if alive(pid):send(pid,signal.SIGKILL);killed=True
 if not reaped:
  try:process.wait(timeout=max(0,deadline-clock()));reaped=True
  except subprocess.TimeoutExpired:errors.append('owned leader reap timeout')
 while clock()<deadline and any(alive(pid) for pid in known_groups):sleep(min(.01,max(0,deadline-clock())))
 gone=not any(alive(pid) for pid in known_groups)
 return {'reaped':reaped,'owned_groups_gone':gone,'unknown':not (reaped and gone and not errors),'errors':errors,'SIGKILL_used':killed,'continuous_resource_pass':False}

def supervise_mockable(command,budget,paths,*,factory,clock=time.monotonic,sleep=time.sleep,cleanup=cleanup_owned):
 """Mock-only contract exercise: factory MUST declare source_only_mock=True.
 Real dispatch is unavailable even with a numeric specification. Production
 source/Python/dependency/preflight authority and worker token wiring remain
 a new prospective F7b prerequisite, never inferred from passing these mocks.
 """
 if getattr(factory,'source_only_mock',False) is not True:raise RuntimeError('NOT_EXECUTABLE: real process factories refused')
 process=None;groups=set();record={'state':'INCONCLUSIVE','scientific_pass':False,'continuous_resource_pass':False,'automatic_retry':False,'sampled_monitor':True}
 lease,logs,terminal=map(P,paths);original=budget.anchor
 try:
  budget.check()
  if lease.exists() or logs.exists() or terminal.exists():raise ValueError('consumed operation or namespace STOP; no resume')
  # Existing parents only. Future accepted registration must create/fsync
  # directory names and bind canonical E05 source/interpreter/worker authority.
  once(lease,{'operation':KEY,'state':'STARTED','original_anchor':original,'command':command,'source_only_fixture':True})
  budget.check()
  env={k:'1' for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS','VECLIB_MAXIMUM_THREADS')}
  process=factory(command,env=env,start_new_session=True)
  if type(process.pid)is not int or process.pid<=0:raise ValueError('owned child handle')
  groups.add(process.pid)
  with logs.open('xb') as f:
   while True:
    budget.check()
    chunk=process.read_bounded(4096) # Contract: bounded, nonblocking mock IO.
    if len(chunk)>4096:raise ValueError('unbounded child log read')
    if chunk:f.write(chunk);f.flush()
    budget.check() # Account logs immediately; all roots share one budget.
    exitcode=process.poll()
    if exitcode is not None:
     process.wait(timeout=max(0,budget.spec['whole_seconds']-(clock()-original)))
     record['state']='CHILD_EXIT_OBSERVED';record['exitcode']=exitcode;break
    sleep(budget.spec['poll_seconds'])
   f.flush();os.fsync(f.fileno())
  sync_parent(logs)
 except BaseException as e:record['error']=type(e).__name__+': '+str(e)
 finally:
  remaining=max(0,budget.spec['whole_seconds']-(clock()-original))
  if process is not None:
   try:record['cleanup']=cleanup(process,groups,min(remaining,budget.spec['cleanup_seconds'])/2)
   except BaseException as e:record['cleanup_unknown']=type(e).__name__+': '+str(e)
  record['original_anchor']=original;record['elapsed_before_terminal']=clock()-original
  # Receipt IO is charged to the same anchor, never a new allowance.
  try:
   if remaining<=0:record['whole_budget_exhausted']=True
   once(terminal,record)
  except BaseException as e:record['terminal_durability_unknown']=type(e).__name__+': '+str(e)
  elapsed=clock()-original
  if elapsed>budget.spec['whole_seconds'] or total_bytes(budget.roots)>budget.spec['output_bytes']:record['final_IO_budget_violation']=True
 return record

def execute(*args,**kwargs):
 raise RuntimeError('NOT_EXECUTABLE: independent source + prospective operational/resource spec + fullsize preflight pending')
if __name__=='__main__':execute()
