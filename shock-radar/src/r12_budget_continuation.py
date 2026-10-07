"""Resource-only amendment after measured V3 prefix; never rewrites V3 identity."""
import argparse,copy,datetime,hashlib,importlib.util,json,os,subprocess,sys,time
from pathlib import Path

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(Path(p).read_text())
def atomic(p,value):
 p=Path(p);tmp=p.with_suffix(p.suffix+'.tmp')
 with tmp.open('w') as stream:
  os.chmod(tmp,0o600);stream.write(json.dumps(value,indent=2)+'\n');stream.flush();os.fsync(stream.fileno())
 tmp.replace(p)
 fd=os.open(p.parent,os.O_RDONLY)
 try:os.fsync(fd)
 finally:os.close(fd)
def deadline_seconds(spec,now=None):
 now=now or datetime.datetime.now(datetime.timezone.utc)
 return (datetime.datetime.fromisoformat(spec['deadline_UTC'].replace('Z','+00:00'))-now).total_seconds()
def guarded_total(spec,prior,now=None):
 remaining=deadline_seconds(spec,now)
 if remaining<=0:raise ValueError('absolute deadline expired; no next chunk')
 cap=min(spec['cumulative_wall_seconds_cap'],prior+remaining)
 if prior>=cap:raise ValueError('cumulative time exhausted; no next chunk')
 return cap

def checkpoint_receipt(out):
 result={}
 for p in sorted((out/'checkpoints').glob('*.json')):
  st=read(p)
  if st.get('uncertain_inflight'):raise ValueError('uncertain started call; no automatic retry')
  if st.get('status')!='complete':raise ValueError('open checkpoint; amendment requires a closed clean chunk')
  result[str(p.relative_to(out))]=sha(p)
 return result

def verify_preserved(out,receipt):
 for relative,expected in receipt.items():
  if sha(out/relative)!=expected:raise ValueError('completed checkpoint changed: '+relative)

def verify_counters(before,after):
 for key,value in before.items():
  if after.get(key,-1)<value:raise ValueError('counter decreased: '+key)

def validate(spec,out,view):
 for name in ['failure.json','budget-stop.json','resource-measurement-failure.json','controls-started.json']:
  if (out/name).exists():raise ValueError('failure/uncertain-control receipt blocks continuation: '+name)
 for control in out.glob('control-h*.json'):
  if not read(control).get('pass'):raise ValueError('interrupted/failed control blocks continuation')
 if sha(out/'fingerprint.json')!=spec['original_fingerprint_file_SHA']:raise ValueError('original fingerprint changed')
 for relative,expected in spec['frozen_execution_sources'].items():
  if sha(view/relative)!=expected:raise ValueError('immutable execution source changed: '+relative)
 verify_preserved(out,spec['initial_complete_checkpoint_SHAs'])
 counters=read(out/'counters.json')
 verify_counters(spec['measured_first_chunk']['counters'],counters)
 if counters.get('chronos_calls')!=counters.get('successful_native_calls') or counters.get('prophet_fits')!=counters.get('successful_Prophet_fits'):raise ValueError('attempt/success mismatch; review required')
 result=read(out/'invocation-result.json')
 if result['status'] not in ['INCONCLUSIVE_PARTIAL_RESUMABLE','FULL_TECHNICAL_EVALUATION_COMPLETED_REVIEW_REQUIRED']:raise ValueError('not a closed clean chunk')
 receipt=checkpoint_receipt(out)
 if len(receipt)<spec['initial_complete_groups']:raise ValueError('completed prefix lost')
 prior=read(out/'resource-ledger.json')['cumulative_wall_s']
 if prior<spec['measured_first_chunk']['cumulative_wall_s']:raise ValueError('historical time ledger decreased')
 cap=guarded_total(spec,prior)
 return receipt,cap

def instrument(module,spec,out):
 original=module.start_guard
 def guard(out_arg,full,counters,worker_ref,invocation_started=None):
  if Path(out_arg).resolve()!=out.resolve():raise ValueError('unexpected output identity')
  guarded=copy.deepcopy(full)
  prior=read(out/'resource-ledger.json')['cumulative_wall_s']
  guarded['prospective_resources']['wall_total_seconds_cap_proposal']=guarded_total(spec,prior)
  # Every other cap and scientific field remains byte-equivalent in value.
  return original(out_arg,guarded,counters,worker_ref,invocation_started)
 module.start_guard=guard

def run_original(spec,out,view,args):
 source=view/'shock-radar/src/r11_chronos2_full.py';sys.path.insert(0,str(source.parent))
 module_spec=importlib.util.spec_from_file_location('immutable_r11',source);module=importlib.util.module_from_spec(module_spec);module_spec.loader.exec_module(module)
 instrument(module,spec,out);sys.argv=[str(source),*args];module.main()

def canonical_paths(out,receipt_dir):
 out=out.resolve();canonical=out.parent/(out.name+'-continuation')
 if receipt_dir.resolve()!=canonical:raise ValueError('noncanonical receipt directory prohibited')
 return out,canonical,out.parent/(out.name+'.r12-output.lock')

def continuity(spec,out,receipts):
 state_path=receipts/'driver-state.json';latest_path=receipts/'latest-closed.json'
 if state_path.exists():
  state=read(state_path)
  if state['status']!='CLOSED':raise ValueError('STARTED/failed transaction; review required')
  if not latest_path.exists():raise ValueError('latest closed receipt lost')
  latest=read(latest_path)
  if sha(latest_path)!=state['latest_closed_SHA'] or latest['count']!=state['count']:raise ValueError('latest closed continuity mismatch')
  history=sorted(receipts.glob('invocation-*.json'))
  if len(history)!=state['count']:raise ValueError('invocation history lost/added')
  for n,file in enumerate(history,1):
   record=read(file)
   if record['count']!=n or record['status']!='CLOSED':raise ValueError('nonclosed invocation history')
  expected=latest
 else:
  if latest_path.exists() or list(receipts.glob('invocation-*.json')):raise ValueError('transaction state lost')
  expected={'count':0,'checkpoints':spec['initial_complete_checkpoint_SHAs'],'counters':spec['measured_first_chunk']['counters'],'wall':spec['measured_first_chunk']['cumulative_wall_s']}
 actual=checkpoint_receipt(out)
 if actual!=expected['checkpoints']:raise ValueError('latest completed checkpoint set changed/lost/added')
 if read(out/'counters.json')!=expected['counters'] or read(out/'resource-ledger.json')['cumulative_wall_s']!=expected['wall']:raise ValueError('latest counter/time ledger changed or rolled back')
 return expected

def reserve(receipts,previous,maximum):
 count=previous['count']+1
 if count>maximum:raise ValueError('cumulative invocation cap exhausted')
 path=receipts/f'invocation-{count:04d}.json'
 if path.exists():raise ValueError('invocation collision')
 atomic(receipts/'driver-state.json',{'status':'STARTED','count':count})
 atomic(path,{'status':'STARTED_REVIEW_IF_INTERRUPTED','count':count})
 return count,path

def dispatch_auth(token,out,receipts,view,args,lock):
 import stat
 if not token.is_file() or token.stat().st_mode & 0o077:raise ValueError('private dispatch authorization required')
 auth=read(token);owner=read(lock)
 expected={'parent_pid':os.getppid(),'out':str(out),'receipts':str(receipts),'view':str(view.resolve()),'args_SHA':hashlib.sha256(json.dumps(args).encode()).hexdigest(),'driver_SHA':sha(__file__),'nonce':owner['nonce']}
 if any(auth.get(k)!=v for k,v in expected.items()) or owner['pid']!=os.getppid():raise ValueError('external child dispatch prohibited')
 if auth['expires_monotonic']<time.monotonic():raise ValueError('dispatch authorization expired')
 state=read(receipts/'driver-state.json')
 if state['status']!='STARTED' or state['count']!=auth['count']:raise ValueError('unreserved dispatch')
 if token.parent.resolve()!=receipts.resolve():raise ValueError('dispatch outside canonical receipts')
 used=token.with_suffix('.used')
 if used.exists():raise ValueError('dispatch already consumed')
 token.rename(used) # atomic one-use consumption; second dispatch has no token.
 return auth

def terminate_owned(process,view):
 # Native known-parent discovery, only descendants of THIS driver.
 source=view/'shock-radar/src/r11_chronos2_full.py';sys.path.insert(0,str(source.parent));ms=importlib.util.spec_from_file_location('cleanup_r11',source);m=importlib.util.module_from_spec(ms);ms.loader.exec_module(m)
 import signal
 owned=m.own_descendants(os.getpid())
 for sig in [signal.SIGTERM,signal.SIGKILL]:
  for pid in reversed(owned):
   try:os.kill(pid,sig)
   except ProcessLookupError:pass
  if sig==signal.SIGTERM:
   try:process.wait(timeout=.5)
   except subprocess.TimeoutExpired:pass
 try:process.wait(timeout=2)
 except subprocess.TimeoutExpired:raise RuntimeError('owned dispatch not reaped')

def main():
 import secrets
 parser=argparse.ArgumentParser();parser.add_argument('--amendment',type=Path,required=True);parser.add_argument('--receipt-dir',type=Path,required=True);parser.add_argument('--view',type=Path,required=True);parser.add_argument('--out',type=Path,required=True);parser.add_argument('--check',action='store_true');parser.add_argument('--dispatch-token',type=Path,help=argparse.SUPPRESS);opts,args=parser.parse_known_args();args=args[1:] if args[:1]==['--'] else args
 if '--one-child' in args:raise ValueError('external child dispatch prohibited')
 if sha(opts.amendment)!='f78c9a18e8aeb5096a20be12fa3d9bdc1379003aa4883d86cc3203e8fac51133':raise ValueError('frozen amendment SHA changed')
 spec=read(opts.amendment);out,receipts,lock=canonical_paths(opts.out,opts.receipt_dir);view=opts.view.resolve()
 if spec['schema']!='r12-resource-only-v1':raise ValueError('schema')
 if opts.dispatch_token:
  dispatch_auth(opts.dispatch_token,out,receipts,view,args,lock)
  # Parent already reserved transaction and pinned the clean state. Recheck immutable scientific sources.
  validate(spec,out,view);run_original(spec,out,view,args);return
 if lock.exists():raise ValueError('actual-output identity locked; check/run refused')
 if opts.check:
  validate(spec,out,view);previous=continuity(spec,out,receipts)
  if previous['count']>=spec['maximum_continuation_invocations'] and read(out/'invocation-result.json')['status']!='FULL_TECHNICAL_EVALUATION_COMPLETED_REVIEW_REQUIRED':raise ValueError('cumulative invocation cap exhausted')
  print(json.dumps({'status':'READY_NO_MODEL_CALLS','complete_groups':len(previous['checkpoints']),'cumulative_continuation_invocations':previous['count'],'effective_total_wall_cap':guarded_total(spec,previous['wall']),'forecast_metrics_read':False}));return
 if '--resume' not in args or '--mode' not in args or args[args.index('--mode')+1]!='run':raise ValueError('original run --resume invocation required')
 if args.count('--out')!=1 or Path(args[args.index('--out')+1]).resolve()!=out:raise ValueError('original output required')
 receipts.mkdir(parents=True,exist_ok=True)
 nonce=secrets.token_hex(32);fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.write(fd,json.dumps({'pid':os.getpid(),'out':str(out),'nonce':nonce}).encode());os.fsync(fd);os.close(fd)
 child=None
 import signal
 def interrupted(signum,frame):raise KeyboardInterrupt('owned driver interrupted')
 signal.signal(signal.SIGTERM,interrupted)
 try:
  while True:
   validate(spec,out,view);previous=continuity(spec,out,receipts)
   if read(out/'invocation-result.json')['status']=='FULL_TECHNICAL_EVALUATION_COMPLETED_REVIEW_REQUIRED':break
   count,path=reserve(receipts,previous,spec['maximum_continuation_invocations'])
   token=receipts/('dispatch-'+secrets.token_hex(16)+'.json')
   auth={'parent_pid':os.getpid(),'out':str(out),'receipts':str(receipts),'view':str(view),'args_SHA':hashlib.sha256(json.dumps(args).encode()).hexdigest(),'driver_SHA':sha(__file__),'nonce':nonce,'count':count,'expires_monotonic':time.monotonic()+45}
   fd=os.open(token,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.write(fd,json.dumps(auth).encode());os.fsync(fd);os.close(fd)
   cmd=[sys.executable,str(Path(__file__).resolve()),'--amendment',str(opts.amendment),'--receipt-dir',str(receipts),'--view',str(view),'--out',str(out),'--dispatch-token',str(token),'--',*args]
   started=time.time();child=subprocess.Popen(cmd,start_new_session=True)
   try:exitcode=child.wait(timeout=min(600,deadline_seconds(spec)))
   except BaseException:
    terminate_owned(child,view);child=None;raise
   child=None;token.unlink(missing_ok=True)
   if exitcode:raise RuntimeError('original chunk failed; STARTED receipt blocks automatic retry')
   verify_preserved(out,previous['checkpoints']);after=read(out/'counters.json');verify_counters(previous['counters'],after);wall=read(out/'resource-ledger.json')['cumulative_wall_s']
   if wall<previous['wall']:raise ValueError('cumulative wall decreased')
   complete=checkpoint_receipt(out);delta={k:v for k,v in complete.items() if k not in previous['checkpoints']}
   latest={'count':count,'checkpoints':complete,'counters':after,'wall':wall,'amendment_SHA':sha(opts.amendment),'driver_SHA':sha(__file__)}
   atomic(path,{'status':'CLOSED','count':count,'checkpoint_delta':delta,'counters':after,'cumulative_wall':wall,'wall_this_dispatch':time.time()-started,'amendment_SHA':sha(opts.amendment),'driver_SHA':sha(__file__)})
   atomic(receipts/'latest-closed.json',latest)
   atomic(receipts/'driver-state.json',{'status':'CLOSED','count':count,'latest_closed_SHA':sha(receipts/'latest-closed.json')})
 finally:
  if child is not None:terminate_owned(child,view)
  lock.unlink(missing_ok=True)
if __name__=='__main__':main()
