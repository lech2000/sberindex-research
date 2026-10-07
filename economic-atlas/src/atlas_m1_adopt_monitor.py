"""Prospective durable supervision of one already-live original M1 process.

No calibration restart. Historical coverage gap and unknown exit code are retained.
All process discovery is targeted to known PID/known-parent descendants.
"""
from pathlib import Path
import argparse,ctypes,datetime,errno,hashlib,importlib.util,json,math,os,platform,signal,sys,time
sys.dont_write_bytecode=True
PROSPECTIVE_SHA='5299f8353f655a5864ec067fb7056924768301789ebbc9270d9c6c81d1eda054'

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def now():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def atomic(p,data):
 p=Path(p);temp=p.with_name(p.name+'.tmp')
 with temp.open('w') as f:json.dump(data,f,indent=2,allow_nan=False);f.write('\n');f.flush();os.fsync(f.fileno())
 os.replace(temp,p)
def load_guard(path,expected):
 if sha(path)!=expected:raise ValueError('accepted native guard SHA mismatch')
 spec=importlib.util.spec_from_file_location('accepted_m1_guard',path);g=importlib.util.module_from_spec(spec);spec.loader.exec_module(g);return g

def parse_bsd(raw):
 if len(raw)!=136:raise ValueError('native BSD record must be136bytes')
 u32=lambda off:int.from_bytes(raw[off:off+4],'little')
 return {'status':u32(4),'pid':u32(12),'ppid':u32(16),'uid':u32(20),'pgid':u32(100),'birth_sec':int.from_bytes(raw[120:128],'little'),'birth_usec':int.from_bytes(raw[128:136],'little')}
def parse_args(raw):
 if len(raw)<5:raise ValueError('native argument buffer missing')
 argc=int.from_bytes(raw[:4],'little',signed=True)
 if not 1<=argc<1000:raise ValueError('native argc invalid')
 pos=raw.find(b'\0',4)+1
 if pos<=4:raise ValueError('native executable terminator absent')
 while pos<len(raw) and raw[pos]==0:pos+=1
 args=raw[pos:].split(b'\0')[:argc]
 if len(args)!=argc:raise ValueError('native argv incomplete')
 return [x.decode('utf-8',errors='strict') for x in args]
class Native:
 def __init__(self,g):
  if platform.system()!='Darwin':raise RuntimeError('nativeMac required')
  self.guard=g.NativeMac();self.lib=self.guard.lib;self.lib.proc_pidpath.argtypes=[ctypes.c_int,ctypes.c_void_p,ctypes.c_uint32];self.lib.proc_pidpath.restype=ctypes.c_int;self.libc=ctypes.CDLL('/usr/lib/libSystem.B.dylib',use_errno=True)
  self.libc.sysctl.argtypes=[ctypes.POINTER(ctypes.c_int),ctypes.c_uint,ctypes.c_void_p,ctypes.POINTER(ctypes.c_size_t),ctypes.c_void_p,ctypes.c_size_t];self.libc.sysctl.restype=ctypes.c_int
 def info(self,pid):
  b=ctypes.create_string_buffer(136);ctypes.set_errno(0);size=self.lib.proc_pidinfo(pid,3,0,b,136);err=ctypes.get_errno()
  if size!=136:
   if err==errno.ESRCH:return None
   raise OSError(err,'knownPID native BSD identity unavailable')
  return parse_bsd(b.raw)
 def executable(self,pid):
  b=ctypes.create_string_buffer(4096);ctypes.set_errno(0);size=self.lib.proc_pidpath(pid,b,len(b));err=ctypes.get_errno()
  if not 0<size<len(b):raise OSError(err,'knownPID native executable path unavailable')
  return b.value.decode('utf-8',errors='strict')
 def argv(self,pid):
  # KERN_PROCARGS2 is targeted to this knownPID, never KERN_PROC/allPID enumeration.
  mib=(ctypes.c_int*3)(1,49,pid);size=ctypes.c_size_t(0);ctypes.set_errno(0)
  if self.libc.sysctl(mib,3,None,ctypes.byref(size),None,0)!=0:raise OSError(ctypes.get_errno(),'knownPID argv unavailable; identity cannot be skipped')
  if not 0<size.value<=1048576:raise ValueError('knownPID argv size invalid')
  b=ctypes.create_string_buffer(size.value)
  if self.libc.sysctl(mib,3,b,ctypes.byref(size),None,0)!=0:raise OSError(ctypes.get_errno(),'knownPID argv unavailable')
  return parse_args(b.raw[:size.value])
 def rss(self,pid):return self.guard.rss(pid)
 def descendants(self,pid):return self.guard.descendants(pid)

def identity(info):return {k:info[k] for k in ('pid','uid','pgid','birth_sec','birth_usec')}
def match_identity(info,pinned):return info is not None and identity(info)==pinned

def config(path):
 if sha(path)!=PROSPECTIVE_SHA:raise ValueError('prospective adopt protocol modified')
 p=json.loads(Path(path).read_text());view=Path(p['frozen_view']);run=Path(p['original_run'])
 guardsrc=view/'economic-atlas/src/atlas_m1_executor.py';g=load_guard(guardsrc,p['guard_sha256'])
 _,inputs=g.check_inputs(view)
 if inputs['source']!=p['source_sha256'] or inputs['protocol']!=p['protocol_sha256']:raise ValueError('original frozen source/protocol mismatch')
 cmd=json.loads((run/'progress.json').read_text())['command']
 expected=[cmd[0],str(view/'economic-atlas/src/atlas_m1_spectral.py'),'--phase','calibrate','--repo',str(view),'--protocol',str(view/'economic-atlas/protocols/M1_PROSPECTIVE_V1.json'),'--outdir',str(run/'calibrate-v1')]
 if cmd!=expected:raise ValueError('original command scope mismatch')
 if cmd[0]!=p['original_launcher'] or os.path.realpath(cmd[0])!=p['original_launcher_realpath'] or sha(cmd[0])!=p['original_launcher_sha256']:raise ValueError('original launcher provenance changed')
 if os.path.realpath(p['reviewed_native_executable'])!=p['reviewed_native_executable'] or sha(p['reviewed_native_executable'])!=p['reviewed_native_executable_sha256']:raise ValueError('reviewed native executable changed')
 return p,g,view,run,cmd,inputs

def verify_live(native,p,expected_argv,pinned=None):
 info=native.info(p['original_pid'])
 if info is None:return None
 if info['pid']!=p['original_pid'] or info['pgid']!=p['original_pgid'] or info['uid']!=p['expected_uid'] or info['uid']!=os.getuid():raise ValueError('originalPID UID/PGID mismatch')
 sec=int(datetime.datetime.fromisoformat(p['expected_birth_utc_second']).timestamp())
 if info['birth_sec']!=sec or info['birth_usec']!=p['expected_birth_usec'] or pinned is not None and not match_identity(info,pinned):raise ValueError('PIDreuse/original birth mismatch; no signal/restart')
 if pinned is None and info['ppid']!=1:raise ValueError('original orphan PPID1 required before adoption')
 if info['status']==5:return {**info,'terminal_zombie':True}
 args=native.argv(info['pid'])
 if len(args)!=len(expected_argv) or args[0]!=p['reviewed_native_argv0'] or args[1:]!=expected_argv[1:]:raise ValueError('exact live original command mismatch')
 executable=native.executable(info['pid'])
 if executable!=p['reviewed_native_executable'] or sha(executable)!=p['reviewed_native_executable_sha256']:raise ValueError('exact native executable/hash mismatch')
 if expected_argv[0]!=p['original_launcher'] or os.path.realpath(expected_argv[0])!=p['original_launcher_realpath'] or sha(expected_argv[0])!=p['original_launcher_sha256']:raise ValueError('original launcher provenance changed')
 after=native.info(info['pid'])
 if after is None:return None
 if identity(after)!=identity(info):raise ValueError('PIDreuse during native argv/executable validation; no signal')
 return {**after,'terminal_zombie':True} if after['status']==5 else after

def elapsed(p,clock=time.time):return clock()-datetime.datetime.fromisoformat(p['original_wall_start_utc']).timestamp()
def resources(native,info,p,run,out,g):
 root=info['pid'];children=native.descendants(root);sizes={pid:native.rss(pid) for pid in [root]+children+[os.getpid()]};sizes={pid:value for pid,value in sizes.items() if value is not None}
 if root not in sizes or sizes[root]<=0:raise RuntimeError('originalPID RSS unavailable')
 disk=g.output_bytes(run)+g.output_bytes(out);free=g.shutil.disk_usage(run).free;wall=elapsed(p)
 if wall<0:raise RuntimeError('wall clock before original start')
 reason=None
 if wall>p['limits']['wall_seconds_from_original_start']:reason='ORIGINAL_WALL_CAP'
 if sum(sizes.values())>p['limits']['RSS_bytes']:reason='AGGREGATE_RSS_CAP'
 if disk>p['limits']['combined_output_bytes_max']:reason='COMBINED_OUTPUT_CAP'
 if free<p['limits']['free_disk_bytes_min']:reason='FREE_DISK_CAP'
 return {'aggregate_RSS_bytes':sum(sizes.values()),'known_PID_RSS_bytes':sizes,'combined_output_bytes':disk,'free_disk_bytes':free,'wall_seconds_from_original_start':wall,'cap_reason':reason,'known_descendants':children}

def stop_verified_original(native,p,cmd,pinned,kill=os.kill,sleep=time.sleep):
 # Non-atomic Darwin PID signalling: reverify immediately before each signal.
 # Identity uncertainty or reuse => NO signal, failclosed intervention receipt.
 sent=[]
 for sig in (signal.SIGTERM,signal.SIGKILL):
  current=verify_live(native,p,cmd,pinned)
  if current is None or current.get('terminal_zombie'):return sent
  kill(current['pid'],sig);sent.append({'pid':current['pid'],'signal':int(sig),'identity':pinned})
  if sig==signal.SIGTERM:
   for _ in range(20):
    sleep(.25);current=verify_live(native,p,cmd,pinned)
    if current is None or current.get('terminal_zombie'):return sent
 return sent

def completion(run,p,inputs):
 out=run/'calibrate-v1';manifest=json.loads((out/'manifest.json').read_text());resultpath=out/'result.json';r=json.loads(resultpath.read_text())
 if manifest['code_sha256']!=p['source_sha256'] or manifest['protocol_sha256']!=p['protocol_sha256']:raise ValueError('calibration manifest source/protocol mismatch')
 hashes=manifest['files_sha256']
 if hashes.get('result.json')!=sha(resultpath):raise ValueError('completed calibration result SHA missing/mismatch')
 for name,value in hashes.items():
  if Path(name).name!=name or sha(out/name)!=value:raise ValueError('calibration output immutable manifest mismatch')
 expectedinputs={'panel':inputs['panel'],'A5_mask':inputs['A5_mask']}
 if r.get('input_sha256')!=expectedinputs or (r.get('n'),r.get('d'))!=(1896,5) or set(r.get('results',{}))!={'10','20','40'}:raise ValueError('completed full calibration scope/input mismatch')
 frozen=json.loads((Path(p['frozen_view'])/'economic-atlas/protocols/M1_PROSPECTIVE_V1.json').read_text())
 if r.get('settings_sha256')!=hashlib.sha256(json.dumps(frozen,sort_keys=True).encode()).hexdigest():raise ValueError('completed settings SHA mismatch')
 quality={}
 for k,c in r['results'].items():
  if (c.get('n'),c.get('d'),c.get('k'))!=(1896,5,int(k)):raise ValueError('completed per-k scope mismatch')
  for field,seeds in (('calibration',frozen['calibration_seeds']),('held',frozen['validation_seeds'])):
   records=c.get(field,[])
   if any(not {'m','sig','raw_gap','status'}.issubset(x) for x in records):raise ValueError('completed scientific record fields missing')
   keys={(R,s) for R in (1,3,4,5) for s in seeds}
   if len(records)!=len(keys) or {(x.get('R'),x.get('seed')) for x in records}!=keys:raise ValueError('completed exact calibration/held records missing')
  for x in c['held']:
   gaps=x.get('shuffle_raw_gaps',[]);invalid=x.get('shuffle_invalid_seeds',[]);base=frozen['shuffle_seed_base']+x['seed']*100
   if len(gaps)+len(invalid)!=99 or len(invalid)!=len(set(invalid)) or not set(invalid)<=set(range(base,base+99)):raise ValueError('completed99 null accounting invalid')
   if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in gaps):raise ValueError('completed null successful gaps not finite')
  fit=c.get('fit',{});sigstar=fit.get('sig_star')
  if sigstar is not None and (isinstance(sigstar,bool) or not isinstance(sigstar,(int,float)) or not math.isfinite(sigstar)):raise ValueError('completed sig_star nonfinite')
  if any('verdict' not in x for x in c['held']):raise ValueError('completed held verdict missing')
  neg=[x for x in c['held'] if x['R']==1];pos=[x for x in c['held'] if x['R']>1]
  passed=(all(x['m'] is not None and not x['shuffle_invalid_seeds'] for x in c['held']) and sigstar is not None and sum(x['verdict']=='REAL_GAP' for x in neg)/20<=.05 and sum(x['verdict']=='REAL_GAP' and x['m']==x['R'] for x in pos)/60>=.90)
  quality[k]=c.get('method_quality')
  if quality[k] not in ('PASS_FIXED_CONTROLS','FAIL_OR_INCONCLUSIVE_FIXED_CONTROLS'):raise ValueError('completed terminal method quality absent')
  if (quality[k]=='PASS_FIXED_CONTROLS')!=passed:raise ValueError('completed quality inconsistent with held controls')
 return {'result_sha256':sha(resultpath),'manifest_sha256':sha(out/'manifest.json'),'all_calibration_output_sha256':hashes,'quality_by_k':quality,'actual_old_child_exit_code':None,'continuous_old_guard_coverage':False,'scientific_pass':False}

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--protocol',type=Path,required=True);ap.add_argument('--outdir',type=Path,required=True);ap.add_argument('--probe',action='store_true');ap.add_argument('--probe-receipt',type=Path);ap.add_argument('--probe-sha');args=ap.parse_args()
 p,g,view,run,cmd,inputs=config(args.protocol)
 destination=args.outdir.resolve()
 if destination==run.resolve() or run.resolve() in destination.parents or destination==view.resolve() or view.resolve() in destination.parents:raise ValueError('fresh adoption output must be outside original run/frozen view')
 if os.stat(destination.parent).st_dev!=os.stat(run).st_dev:raise ValueError('adoption output and original run must share disk for resource accounting')
 native=Native(g);args.outdir.mkdir(exist_ok=False)
 record={'started_at':now(),'state':'STARTED','protocol_sha256':sha(args.protocol),'monitor_sha256':sha(__file__),'input_sha256':inputs,'original_command':cmd,'continuous_old_guard_coverage':False,'original_exit_code':None,'automatic_restart':False,'calibration_launches':0,'replay_launches':0,'coverage_gap':{'lost_guard_pid':p['lost_guard_pid'],'old_progress_sha256':sha(run/'progress.json'),'gap_start_utc':p['coverage_gap_start_utc'],'original_monotonic_context_lost':True,'new_attachment_at':None}}
 if args.probe:
  try:
   if native.info(p['lost_guard_pid']) is not None:raise ValueError('lost original guard PID present; root intervention required')
   current=verify_live(native,p,cmd)
   if current is None or current.get('terminal_zombie'):raise ValueError('original scientific process no longer live; no attach')
   record.update(state='KNOWN_ORIGINAL_LIVE_IDENTITY_VERIFIED',identity=identity(current),resources=resources(native,current,p,run,args.outdir,g),probe_only=True)
  except BaseException as exc:record.update(state='INCONCLUSIVE_IDENTITY_PROBE',error=type(exc).__name__+': '+str(exc))
  atomic(args.outdir/'probe.json',record);print(json.dumps({'state':record['state'],'probe':str(args.outdir/'probe.json')}))
  if record['state']!='KNOWN_ORIGINAL_LIVE_IDENTITY_VERIFIED':raise SystemExit(1)
  return
 signal.signal(signal.SIGTERM,g.stop_requested)
 try:
  if args.probe_receipt is None or sha(args.probe_receipt)!=args.probe_sha:raise ValueError('root reviewed actual probe SHA required before adoption')
  proof=json.loads(args.probe_receipt.read_text())
  if proof['state']!='KNOWN_ORIGINAL_LIVE_IDENTITY_VERIFIED' or proof['protocol_sha256']!=PROSPECTIVE_SHA or proof['monitor_sha256']!=sha(__file__) or proof['original_command']!=cmd or proof['input_sha256']!=inputs:raise ValueError('actual known-original probe binding mismatch')
  pinned=proof['identity'];record.update(pinned_identity=pinned,probe_sha256=args.probe_sha);record['coverage_gap']['new_attachment_at']=now()
  while True:
   current=verify_live(native,p,cmd,pinned)
   if current is None or current.get('terminal_zombie'):break
   resource=resources(native,current,p,run,args.outdir,g);record.update(state='ADOPTED_SAMPLED_MONITORING',resources=resource,last_observed_at=now());atomic(args.outdir/'progress.json',record)
   if resource['cap_reason']:
    record['stop_signals']=stop_verified_original(native,p,cmd,pinned);record['state']='INCONCLUSIVE_RESOURCE_STOP_NO_RETRY';break
   time.sleep(p['limits']['sample_seconds'])
  if record['state']!='INCONCLUSIVE_RESOURCE_STOP_NO_RETRY':
   _,actual=g.check_inputs(view)
   if actual!=inputs:raise ValueError('frozen inputs changed at completion')
   verified=completion(run,p,inputs);record.update(state='CALIBRATION_COMPLETE_ARTIFACTS_VERIFIED_EXIT_UNKNOWN',calibration=verified)
   record['replay_plan']={'calibration_sha256':verified['result_sha256'],'target':str(run/'replay-v1'),'authorized':False,'separate_one_use_command_required':True,'no_calibration_restart':True}

 except BaseException as exc:record.update(state='INCONCLUSIVE_ADOPTION_INTERVENTION_REQUIRED',error=type(exc).__name__+': '+str(exc),no_signal_on_unverified_identity=True)
 finally:
  record.update(finished_at=now(),scientific_pass=False);record['all_new_output_sha256']=g.manifest(args.outdir);atomic(args.outdir/'terminal.json',record);atomic(args.outdir/'progress.json',record)
 print(json.dumps({'state':record['state'],'terminal':str(args.outdir/'terminal.json'),'calibration_launches':0,'scientific_pass':False}))
 if record['state'].startswith('INCONCLUSIVE'):raise SystemExit(1)
if __name__=='__main__':main()
