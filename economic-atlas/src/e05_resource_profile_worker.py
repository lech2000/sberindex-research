"""Private one-use owned resource worker. No direct public profile authorization."""
import time
ENTRY=time.monotonic()
import hashlib,importlib.util,json,os,pathlib,sys
P=pathlib.Path
CONTROL=P('/private/tmp/e05-resource-profile-control-v1')
OUT=P('/private/tmp/e05-resource-preflight-fullshape-v1')
LEDGER=P('/private/tmp/e05-resource-preflight-fullshape-v1-ledger')

def load(path,name):
 sp=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(sp);sp.loader.exec_module(m);return m

def authenticate(token_path,api,ps):
 if P(token_path)!=CONTROL/'dispatch-token.json':raise PermissionError('fixed internal token only')
 token=api.read_private(token_path)
 if type(token.get('UID'))is not int or token['UID']!=os.getuid()or token['parentPID']!=os.getppid():raise PermissionError('parent/UID')
 parent=ps.Process(token['parentPID'])
 if parent.create_time()!=token['parent_create_time']or parent.uids().real!=os.getuid():raise PermissionError('parent identity')
 now=time.monotonic()
 if api.finite(token['created_monotonic'])>now or now>api.finite(token['valid_until_monotonic']):raise PermissionError('one-use dispatch lease')
 if not isinstance(token['nonce'],str)or len(token['nonce'])!=64:raise PermissionError('nonce')
 if api.sha(__file__)!=token['worker_SHA256']:raise PermissionError('worker source bytes')
 command=[sys.executable,*sys.argv]
 if hashlib.sha256(json.dumps(command).encode()).hexdigest()!=token['command_SHA256']:raise PermissionError('exact command')
 if api.sha(CONTROL/'runtime.json')!=token['runtime_SHA256']:raise PermissionError('runtime changed')
 runtime=api.read_private(CONTROL/'runtime.json')
 if P(sys.executable).resolve()!=P(runtime['python_path'])or api.sha(P(sys.executable).resolve())!=runtime['python_SHA256']:raise PermissionError('Python changed')
 for rel,h in runtime['source_pins'].items():
  if api.sha(P(token['repo'])/rel)!=h:raise PermissionError('runtime source binding')
 for rel,h in token['source_protocol']['source_pins'].items():
  if api.sha(P(token['repo'])/rel)!=h:raise PermissionError('profile source binding')
 while not (CONTROL/'worker-binding.json').is_file():
  if time.monotonic()>token['valid_until_monotonic']:raise PermissionError('binding timeout no dispatch')
  time.sleep(.01)
 binding=api.read_private(CONTROL/'worker-binding.json')
 if binding['PID']!=os.getpid()or binding['PGID']!=os.getpgrp()or binding['command_SHA256']!=token['command_SHA256']or binding['nonce_SHA256']!=hashlib.sha256(token['nonce'].encode()).hexdigest():raise PermissionError('own parent binding')
 api.once(CONTROL/'dispatch-consumed.json',{'state':'CONSUMED','nonce_SHA256':binding['nonce_SHA256'],'PID':os.getpid(),'parentPID':os.getppid(),'original_anchor':token['spec']['original_anchor']})
 return token

class CadencedGuard:
 """Every-call original time checks; real expensive sampling only frozen cadence.
 No cached sample is portrayed as current/continuous measurement.
 """
 def __init__(self,base):
  self.base=base;self.anchor=base.anchor;self.roots=base.roots;self.samples=base.samples
  self.last_scan=None;self.active=False
 def clock_check(self):
  elapsed=self.base.clock()-self.anchor
  if elapsed<0 or elapsed>=self.base.spec['whole_seconds']-self.base.spec['final_reserve_seconds']:raise InterruptedError('original clock/reserve')
  if self.base.utc()>=self.base.deadline:raise InterruptedError('absolute deadline')
 def __call__(self):
  if self.active:raise RuntimeError('nonreentrant cadenced guard')
  self.active=True
  try:
   self.clock_check();now=self.base.clock()
   if self.last_scan is None or now-self.last_scan>=self.base.spec['poll_seconds']:
    self.base();self.last_scan=self.base.clock()
   self.clock_check()
  finally:self.active=False

def main(token_path):
 # Caller source location is pinned by controller and private token; no numeric import.
 repo=P(__file__).resolve().parents[2]
 api=load(repo/'economic-atlas/src/e05_resource_profile_controller.py','profile_authority')
 import psutil
 token=authenticate(token_path,api,psutil);repo=P(token['repo']);tool=load(repo/'economic-atlas/src/e05_full_resource_preflight.py','profile_toolkit')
 own=psutil.Process(os.getpid());parent=psutil.Process(token['parentPID']);parent_created=parent.create_time();native=api.load_native(repo)
 def rss():
  if parent.create_time()!=parent_created:raise RuntimeError('parent identity lost')
  # Native libraries use threads; any worker-created process would need parent registry.
  children=native.descendants(os.getpid())
  sizes=[native.rss(pid)for pid in [parent.pid,own.pid]+children]
  if sizes[0]is None or sizes[1]is None:raise RuntimeError('known parent/worker RSS unavailable')
  return sum(v for v in sizes if v is not None)
 def free():
  s=os.statvfs(OUT.parent);return s.f_bavail*s.f_frsize
 spec=token['spec'];guard=CadencedGuard(tool.SampledGuard(spec,spec['original_anchor'],[OUT,LEDGER,CONTROL],rss,free))
 def worker_local_cleanup():
  # Do not reap/kill self or report parent OS-group cleanup PASS. Outer parent owns it.
  children=native.descendants(os.getpid())
  tool.once(CONTROL/'worker-local-cleanup.json',{'worker_local_child_processes_observed':len(children),'worker_self_reaped':False,'outer_parent_cleanup_required':True})
  if children:raise RuntimeError('unexpected local descendant; parent must cleanup')
 source=json.loads((repo/'economic-atlas/protocols/E05_FULL_RESOURCE_PREFLIGHT_V1.json').read_bytes())
 # This authorization follows consumed private parent token+source ACK byte proofs,
 # not the public CLI or a user-supplied boolean alone.
 source['execution_authorized']=True
 result=tool.qualified_worker(repo,OUT,LEDGER,spec,source,guard,worker_local_cleanup)
 return result

if __name__=='__main__':
 if len(sys.argv)!=3 or sys.argv[1]!='--token':raise SystemExit('PRIVATE_DISPATCH_ONLY; no actual public execution')
 result=main(sys.argv[2]);raise SystemExit(0 if result['state']=='RESOURCE_PROFILE_MEASURED_NOT_FULL_QUALIFICATION'else 1)
