"""Foreground operational guard; immutable baseline M1 science, never resume."""
from pathlib import Path
import argparse,ctypes,datetime,errno,hashlib,json,os,platform,select,shutil,signal,subprocess,sys,time
SOURCE_SHA='5ad14f6e2df75ac89d2285e3a09c304e7894ce6c42a363334a1d568115c1758b'
PROTOCOL_SHA='fd3133bbda35fb7183908e4c3bd4697f5651962adaf8c0cccf74eb4b15c0dc30'
PANEL_SHA='8716a802fb6e25ef4103406cca927de80ce3693a7ff243411cda765b732bcd93'
MASK_SHA='12f40b15ee8f119cba7f386b5c9adf4babb5cff1bca2721dc04551d672f5e5d6'
LIMITS={'rss':1073741824,'wall':77881,'free':1073741824,'output':268435456,'sample':.25,'disk_sample':10}
THREAD_KEYS=('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS')

def stop_requested(signum,frame):raise InterruptedError('foreground guard stop signal '+str(signum))

def now():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def sha(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as f:
  for block in iter(lambda:f.read(1<<20),b''):h.update(block)
 return h.hexdigest()
def atomic(path,data):
 path=Path(path);temporary=path.with_name(path.name+'.tmp')
 with temporary.open('w') as f:json.dump(data,f,ensure_ascii=False,allow_nan=False,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
 os.replace(temporary,path)

class NativeMac:
 def __init__(self):
  if platform.system()!='Darwin':raise RuntimeError('validated native Mac instrumentation required')
  self.lib=ctypes.CDLL('/usr/lib/libproc.dylib',use_errno=True)
  self.lib.proc_listchildpids.argtypes=[ctypes.c_int,ctypes.c_void_p,ctypes.c_int];self.lib.proc_listchildpids.restype=ctypes.c_int
  self.lib.proc_pidinfo.argtypes=[ctypes.c_int,ctypes.c_int,ctypes.c_uint64,ctypes.c_void_p,ctypes.c_int];self.lib.proc_pidinfo.restype=ctypes.c_int
 def children(self,pid):
  buffer=(ctypes.c_int*256)();ctypes.set_errno(0)
  count=self.lib.proc_listchildpids(pid,buffer,ctypes.sizeof(buffer));error=ctypes.get_errno()
  if error==errno.ESRCH:return []
  if count<0 or error or count>=256:raise OSError(error,'knownparent native childlisting failed/truncated')
  return [int(buffer[i]) for i in range(count) if buffer[i]>0]
 def descendants(self,root):
  seen=set();todo=[root]
  while todo:
   for pid in self.children(todo.pop()):
    if pid not in seen:seen.add(pid);todo.append(pid)
  return sorted(seen)
 def rss(self,pid):
  buffer=ctypes.create_string_buffer(96);ctypes.set_errno(0)
  size=self.lib.proc_pidinfo(pid,4,0,buffer,96);error=ctypes.get_errno()
  if size!=96:
   if error==errno.ESRCH:return None
   raise OSError(error,'knownPID native RSS unavailable')
  return int.from_bytes(buffer.raw[8:16],'little')
 def own_tree_rss(self):
  root=os.getpid();pids=[root]+self.descendants(root)
  sizes={pid:self.rss(pid) for pid in pids};sizes={pid:r for pid,r in sizes.items() if r is not None}
  if root not in sizes or sizes[root]<=0:raise RuntimeError('self RSS unavailable')
  return sum(sizes.values()),sizes

def cleanup_owned_group(process):
 """Only the new session this guard spawned; always reap own immediate child."""
 if process.pid==os.getpgrp():raise RuntimeError('refuse cleanup of guard/user processgroup')
 try:os.killpg(process.pid,signal.SIGTERM)
 except ProcessLookupError:pass
 try:process.wait(timeout=5)
 except subprocess.TimeoutExpired:
  try:os.killpg(process.pid,signal.SIGKILL)
  except ProcessLookupError:pass
  process.wait(timeout=5)
 return process.returncode

PROBE_CODE="""import subprocess,sys,json,time,os,signal
c=subprocess.Popen([sys.executable,'-c','import time; memory=bytearray(16*1024*1024);time.sleep(10)'])
memory=bytearray(8*1024*1024)
def stop(signum,frame):
 try:c.wait(timeout=4)
 except subprocess.TimeoutExpired:c.kill();c.wait()
 sys.exit(0)
signal.signal(signal.SIGTERM,stop)
print(json.dumps({'child':os.getpid(),'grandchild':c.pid}),flush=True)
time.sleep(10)
c.wait()
"""
def resource_preflight(out,native=None):
 out=Path(out);out.mkdir(exist_ok=False);native=native or NativeMac();expected=set();process=None
 receipt={'started_at':now(),'state':'STARTED','method_calls':0,'discovery':'proc_listchildpids knownparents only; RSS proc_pidinfo knownPIDs only'}
 try:
  process=subprocess.Popen([sys.executable,'-c',PROBE_CODE],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True)
  receipt['owned_pgid']=process.pid
  if not select.select([process.stdout],[],[],5)[0]:raise RuntimeError('child/grandchild readiness timeout')
  ids=json.loads(process.stdout.readline());expected={ids['child'],ids['grandchild']}
  if ids['child']!=process.pid or len(expected)!=2:raise RuntimeError('probe PID mismatch')
  # Wait for grandchild allocation; not a scientific calculation.
  time.sleep(.2)
  descendants=set(native.descendants(os.getpid()))
  if not expected<=descendants:raise RuntimeError('own child/grandchild omitted')
  total,sizes=native.own_tree_rss()
  if not expected<=set(sizes) or any(sizes[pid]<=0 for pid in expected):raise RuntimeError('child/grandchild RSS invalid')
  if total>LIMITS['rss']:raise RuntimeError('preflight aggregate RSS exceeds1GiB')
  receipt.update(state='PASS',expected_child_grandchild=sorted(expected),RSS_bytes_by_knownPID=sizes,aggregate_RSS_bytes=total)
 except BaseException as exc:receipt.update(state='INCONCLUSIVE_RESOURCE_PREFLIGHT',error=type(exc).__name__+': '+str(exc))
 finally:
  if process is not None:
   try:receipt['child_exit_code']=cleanup_owned_group(process);receipt['immediate_child_reaped']=True
   except Exception as exc:receipt['cleanup_error']=repr(exc);receipt['state']='INCONCLUSIVE_RESOURCE_PREFLIGHT'
   if process.stdout:process.stdout.close()
   if process.stderr:process.stderr.close()
  try:
   receipt['expected_descendants_remaining']=sorted(expected&set(native.descendants(os.getpid())))
   if receipt['expected_descendants_remaining']:receipt['state']='INCONCLUSIVE_RESOURCE_PREFLIGHT'
  except Exception as exc:receipt['cleanup_discovery_error']=repr(exc);receipt['state']='INCONCLUSIVE_RESOURCE_PREFLIGHT'
  receipt['finished_at']=now();atomic(out/'resource-preflight.json',receipt)
 if receipt['state']!='PASS':raise RuntimeError('mandatory resource preflight failed; no calibration started')
 return receipt

def output_bytes(root):return sum(p.stat().st_size for p in Path(root).rglob('*') if p.is_file())

def run_phase(command,out,phase,started,limits=LIMITS,native=None):
 native=native or NativeMac();out=Path(out);process=None;peak=0;reason=None;returncode=None;last_disk=0.;last_json=0.
 status={'phase':phase,'started_at':now(),'command':list(command),'state':'STARTED','no_restart':True}
 log=out/(phase+'.log')
 try:
  env=dict(os.environ);env.update({name:'1' for name in THREAD_KEYS});env['PYTHONDONTWRITEBYTECODE']='1'
  with log.open('x') as stream:
   process=subprocess.Popen(command,stdout=stream,stderr=subprocess.STDOUT,env=env,start_new_session=True)
   status.update(pid=process.pid,owned_pgid=process.pid);atomic(out/'progress.json',status)
   print(json.dumps({'phase':phase,'pid':process.pid,'log':str(log)}),flush=True)
   while process.poll() is None:
    elapsed=time.monotonic()-started;total,sizes=native.own_tree_rss();peak=max(peak,total)
    if elapsed>limits['wall']:reason='INCONCLUSIVE_WALL_LIMIT'
    if total>limits['rss']:reason='INCONCLUSIVE_AGGREGATE_RSS_LIMIT'
    if elapsed-last_disk>=limits['disk_sample']:
     last_disk=elapsed;size=output_bytes(out);free=shutil.disk_usage(out).free
     if size>limits['output']:reason='INCONCLUSIVE_OUTPUT_LIMIT'
     if free<limits['free']:reason='INCONCLUSIVE_FREE_DISK_LIMIT'
     status.update(output_bytes=size,free_disk_bytes=free)
    status.update(elapsed_wall_seconds=elapsed,peak_aggregate_RSS_bytes=peak,known_tree_RSS_bytes=sizes)
    if elapsed-last_json>=1:atomic(out/'progress.json',status);last_json=elapsed
    if reason:break
    time.sleep(limits['sample'])
   returncode=process.poll()
 except BaseException as exc:reason='INCONCLUSIVE_GUARD_EXCEPTION';status['error']=type(exc).__name__+': '+str(exc)
 finally:
  if process is not None:
   try:cleanup_owned_group(process)
   except Exception as exc:reason='INCONCLUSIVE_OWN_GROUP_CLEANUP';status['cleanup_error']=repr(exc)
   returncode=process.returncode
  status.update(finished_at=now(),state=reason or ('COMPLETE' if returncode==0 else 'INCONCLUSIVE_PHASE_EXIT'),exit_code=returncode,peak_aggregate_RSS_bytes=peak,elapsed_wall_seconds=time.monotonic()-started)
  atomic(out/(phase+'-terminal.json'),status);atomic(out/'progress.json',status)
 return status

def check_inputs(repo):
 repo=Path(repo);paths={'source':repo/'economic-atlas/src/atlas_m1_spectral.py','protocol':repo/'economic-atlas/protocols/M1_PROSPECTIVE_V1.json','panel':repo/'economic-atlas/data/panel_v1.parquet','A5_mask':repo/'economic-atlas/runs/A5/features.parquet'}
 expected={'source':SOURCE_SHA,'protocol':PROTOCOL_SHA,'panel':PANEL_SHA,'A5_mask':MASK_SHA}
 actual={key:sha(path) for key,path in paths.items()}
 if actual!=expected:raise ValueError('immutable baseline/science/input SHA mismatch')
 return paths,actual

def manifest(out):
 return {str(p.relative_to(out)):sha(p) for p in Path(out).rglob('*') if p.is_file() and p.name not in {'terminal.json','progress.json'} and not p.name.endswith('.tmp')}

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--repo',type=Path,required=True);ap.add_argument('--outdir',type=Path,required=True);args=ap.parse_args()
 # No operational budget overrides or resume switch exposed.
 paths,hashes=check_inputs(args.repo)
 if shutil.disk_usage(args.outdir.parent).free<LIMITS['free']:raise RuntimeError('requires1GiB free before launch')
 args.outdir.mkdir(exist_ok=False);signal.signal(signal.SIGTERM,stop_requested);started=time.monotonic();terminal={'started_at':now(),'state':'STARTED','input_sha256':hashes,'executor_sha256':sha(__file__),'limits':LIMITS,'scientific_pass':False,'source_actions_closed':0,'automatic_resume':False};atomic(args.outdir/'progress.json',terminal)
 try:
  native=NativeMac();terminal['preflight']=resource_preflight(args.outdir/'native-preflight',native)
  if sha(paths['source'])!=SOURCE_SHA or sha(paths['protocol'])!=PROTOCOL_SHA:raise RuntimeError('accepted source changed before calibration')
  commands=[('calibrate',[sys.executable,str(paths['source']),'--phase','calibrate','--repo',str(args.repo),'--protocol',str(paths['protocol']),'--outdir',str(args.outdir/'calibrate-v1')]),('replay',[sys.executable,str(paths['source']),'--phase','replay','--repo',str(args.repo),'--protocol',str(paths['protocol']),'--calibration',str(args.outdir/'calibrate-v1/result.json'),'--outdir',str(args.outdir/'replay-v1')])]
  terminal['phases']=[]
  for phase,command in commands:
   # Inputs/source checked per phase; no optimization or historical mutation.
   check_inputs(args.repo)
   status=run_phase(command,args.outdir,phase,started,native=native);terminal['phases'].append(status)
   if status['state']!='COMPLETE':raise RuntimeError('foreground phase did not complete; preserve partial outputs')
  terminal['state']='COMPUTED_BASELINE_DESCRIPTIVE_NEEDS_INDEPENDENT_AUDIT'
 except BaseException as exc:terminal.update(state='INCONCLUSIVE_STOPPED',error=type(exc).__name__+': '+str(exc))
 finally:
  terminal.update(finished_at=now(),elapsed_wall_seconds=time.monotonic()-started)
  try:terminal['all_files_sha256_including_negative_and_abstention']=manifest(args.outdir)
  except Exception as exc:terminal['manifest_error']=repr(exc);terminal['state']='INCONCLUSIVE_STOPPED'
  atomic(args.outdir/'terminal.json',terminal);atomic(args.outdir/'progress.json',terminal)
 print(json.dumps({'state':terminal['state'],'receipt':str(args.outdir/'terminal.json'),'scientific_pass':False}),flush=True)
 if terminal['state']!='COMPUTED_BASELINE_DESCRIPTIVE_NEEDS_INDEPENDENT_AUDIT':raise SystemExit(1)
if __name__=='__main__':main()
