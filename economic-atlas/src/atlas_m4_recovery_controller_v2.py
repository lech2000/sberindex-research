"""Root-reviewed ONE M4 controller. Preparation/bootstrapping never runs by import."""
import time
ENTRY=time.monotonic()
import datetime
UTC_ENTRY=datetime.datetime.now(datetime.timezone.utc).isoformat()
import argparse,hashlib,importlib.util,json,os,pathlib,plistlib,socket,subprocess,sys,signal,resource,shutil,functools
for _key in ("OMP_NUM_THREADS","OPENBLAS_NUM_THREADS","MKL_NUM_THREADS","VECLIB_MAXIMUM_THREADS","NUMEXPR_NUM_THREADS"):os.environ[_key]="1"
P=pathlib.Path
ROOT=P('/private/tmp/atlas-m4-operational-recovery-root-control-20261008-v2/runtime')
REPO=P('/private/tmp/sberindex-official-laws-20261007')
ACTUAL=P('/private/tmp/atlas-m4-fullbank-actual-20261008-v1')
M1=P('/private/tmp/atlas-m1-evd-recovery-20261008-v1/science')
ACCEPT=P('/private/tmp/atlas-m1-actual-independent-acceptance-20261008/ACTUAL_FULL_ACCEPTANCE.json')
ACCEPT_SHA='94c366e4fefe3857ac0ccd4719a7912b859d56018327c684209ca51cd58e5649'
EXPECTED_DURABLE_SHA='376bbb2ab3985a7f0d5e8fab215bb5a7c9816d895221d6c8386c70baadaed1d5'
LABEL='local.sergey.sberindex.m4.fullbank.operationalRecoveryV2'
KEY='M4fullbank:6220a61fcaefe60ecc872f5c930023bb6453d0c60059c3f66721199882330969'
def sha(path):return hashlib.sha256(P(path).read_bytes()).hexdigest()
def sync_dir(path):
 fd=os.open(path,os.O_RDONLY)
 try:os.fsync(fd)
 finally:os.close(fd)

def once(path,value):
 fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
 with os.fdopen(fd,'w') as f:json.dump(value,f,ensure_ascii=False,allow_nan=False);f.write('\n');f.flush();os.fsync(f.fileno())
 sync_dir(P(path).parent)
def copy_raw_once(source, target, expected_sha):
 data=P(source).read_bytes()
 if hashlib.sha256(data).hexdigest()!=expected_sha:raise ValueError('raw proof input SHA')
 fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
 with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
 sync_dir(P(target).parent)
 if sha(target)!=expected_sha:raise ValueError('raw proof SHA readback')
 return json.loads(data)

def load_durable():
 file=REPO/'economic-atlas/src/atlas_m4_recovery_v2.py'
 if sha(file)!=EXPECTED_DURABLE_SHA:raise ValueError('future adopted operational sourceSHA required')
 spec=importlib.util.spec_from_file_location('accepted_whole_m4_durable',file);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
def quiescence(proof,now=None):
 now=now or datetime.datetime.now(datetime.timezone.utc)
 if proof.get('state')!='AUTHORITATIVE_M1_OWNED_PARENTS_GONE' or proof.get('signals')!=0:raise ValueError('root authoritative M1 tree quiescence required')
 stamp=datetime.datetime.fromisoformat(proof['checked_at_UTC'])
 if stamp.tzinfo is None or not 0<=(now-stamp).total_seconds()<=60:raise ValueError('root fresh UTC quiescence')
 if set(proof['known_pids'])!={'72250','72253'}:raise ValueError('exact actual M1 parent/worker handles')
 for r in proof['known_pids'].values():
  if r.get('ps_exit')!=1 or r.get('stdout')!='' or r.get('stderr')!='':raise ValueError('existing M1 handles not gone')
 return True
def descriptor(acceptance):
 if sha(ACCEPT)!=ACCEPT_SHA or acceptance['state']!='M1_FULL_RECOVERY_INDEPENDENTLY_VERIFIED' or (acceptance['calibration_records'],acceptance['monthly_records'],acceptance['nulls_per_held_or_month'],acceptance['journals'])!=(360,72,99,9828) or acceptance['scientific_pass'] is not False:raise ValueError('exact actual independent fullM1 receipt')
 fields={'global_result_sha256':M1/'result.json','global_manifest_sha256':M1/'manifest.json','calibration_result_sha256':M1/'calibration/result.json','calibration_manifest_sha256':M1/'calibration/manifest.json','replay_result_sha256':M1/'replay/result.json','replay_manifest_sha256':M1/'replay/manifest.json','terminal_sha256':M1.parent/'receipts/terminal.json'}
 for name,file in fields.items():
  if sha(file)!=acceptance[name]:raise ValueError('actual M1 artifact SHA mismatch')
 return dict(authority=acceptance['authority'],recovery_root=str(M1),calibration_result=str(M1/'calibration/result.json'),result_sha256=acceptance['calibration_result_sha256'],manifest_sha256=acceptance['calibration_manifest_sha256'],replay_result_sha256=acceptance['replay_result_sha256'],global_result_sha256=acceptance['global_result_sha256'],global_manifest_sha256=acceptance['global_manifest_sha256'],calibration_manifest_sha256=acceptance['calibration_manifest_sha256'],replay_manifest_sha256=acceptance['replay_manifest_sha256'],terminal=str(fields['terminal_sha256']),terminal_sha256=acceptance['terminal_sha256'],independent_acceptance=str(ACCEPT),independent_acceptance_sha256=ACCEPT_SHA,bank_source_sha256=acceptance['authority']['base_source'],bank_numerical_driver='evr',mixed_dependency_numerical_driver='evd',root_independent_actual_M1_acceptance=True)

HISTORY=131.42791020799494
TOTAL=93600
DEADLINE=datetime.datetime(2026,10,9,9,tzinfo=datetime.timezone.utc)
LOG_CAP=8192

def output_sizes():
 roots=[ROOT,ACTUAL,P('/private/tmp/atlas-m4-root-launch-controller-20261008/runtime'),P('/private/tmp/atlas-m4-fullbank-actual-20261008-v1')]
 ledger=P('/private/tmp/sberindex-one-use-ledger')
 for phase in ('M4','M4-bootstrap-recovery-v2','M4-bootstrap'):
  lease=ledger/(str(os.getuid())+'-'+phase+'-'+hashlib.sha256(KEY.encode()).hexdigest()+'.json')
  roots += [lease,lease.with_name(lease.stem+'-terminal.json')]
 seen=set();total=supervisory=0;science=(ACTUAL/'science').resolve()
 for root in roots:
  if root.is_symlink():raise ValueError('owned output symlink')
  files=[root] if root.is_file() else root.rglob('*') if root.is_dir() else []
  for file in files:
   if file.is_symlink():raise ValueError('owned output symlink')
   if file.is_file() and file.resolve() not in seen:
    seen.add(file.resolve());n=file.stat().st_size;total+=n
    if science not in file.resolve().parents:supervisory+=n
 return total,supervisory

def controller_guard(anchor):
 elapsed=time.monotonic()-anchor
 if not 0<=elapsed<=120:raise InterruptedError('controller inclusive120s handoff bound')
 if HISTORY+elapsed>TOTAL-30 or datetime.datetime.now(datetime.timezone.utc)>DEADLINE:raise InterruptedError('whole93600/deadline including controller')
 total,supervisory=output_sizes()
 if total>268435456-65536 or supervisory>32768:raise InterruptedError('whole256MiB/supervisory32KiB prefinal reserve')
 if shutil.disk_usage(ROOT.parent if ROOT.parent.exists() else ROOT.parent.parent).free<1073741824:raise InterruptedError('whole minimumfree1GiB')
 # macOS reports ru_maxrss in bytes; Linux in KiB. Sampled self RSS only.
 rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*(1 if sys.platform=='darwin' else 1024)
 if rss>1073741824:raise InterruptedError('controller1GiB selfRSS')
 return min(120-elapsed,TOTAL-HISTORY-elapsed-30,(DEADLINE-datetime.datetime.now(datetime.timezone.utc)).total_seconds()-30)

def guarded(fn):
 @functools.wraps(fn)
 def wrapped(*args,**kwargs):
  anchor=ENTRY
  if fn.__name__=='bootstrap':
   anchor=json.loads((ROOT/'entry.json').read_text())['monotonic_entry']
   if isinstance(anchor,bool) or not isinstance(anchor,(int,float)) or not __import__('math').isfinite(anchor):raise ValueError('finite original entry')
  controller_guard(anchor)
  oldterm=signal.getsignal(signal.SIGTERM)
  signal.signal(signal.SIGTERM,lambda *unused:(_ for _ in ()).throw(InterruptedError('controller TERM STOP no retry')))
  old=signal.getsignal(signal.SIGALRM)
  signal.signal(signal.SIGALRM,lambda *unused:controller_guard(anchor))
  signal.setitimer(signal.ITIMER_REAL,.1,.1)
  try:
   value=fn(*args,**kwargs);controller_guard(anchor);return value
  finally:
   signal.setitimer(signal.ITIMER_REAL,0);signal.signal(signal.SIGALRM,old);signal.signal(signal.SIGTERM,oldterm)
 return wrapped

def cap_launchctl_files():
 resource.setrlimit(resource.RLIMIT_FSIZE,(LOG_CAP,LOG_CAP))

@guarded
def prepare(proof,proof_sha,old_proof,old_proof_sha):
 if sha(proof)!=proof_sha:raise ValueError('root quiescence SHA')
 q=json.loads(P(proof).read_text());quiescence(q)
 m=load_durable()
 if sha(old_proof)!=old_proof_sha:raise ValueError('oldjob proof SHA')
 m.check_recovery_authority(json.loads(P(old_proof).read_text()))
 if (ACTUAL/'science').exists() or (ACTUAL/'receipts').exists() or ROOT.exists():raise ValueError('fresh single controller/fullbank namespace required')
 if not ROOT.parent.exists():
  ROOT.parent.mkdir(mode=0o700,exist_ok=False);sync_dir(ROOT.parent.parent)
 st=ROOT.parent.lstat()
 if ROOT.parent.is_symlink() or st.st_uid!=os.getuid() or st.st_mode&0o077:raise ValueError('private owned recovery parent')
 ROOT.mkdir(mode=0o700,exist_ok=False);sync_dir(ROOT.parent)
 capsule={'origin':'M4_ROOT_OPERATIONAL_RECOVERY_V2','monotonic_entry':ENTRY,'utc_entry':UTC_ENTRY,'uid':os.getuid(),'host':socket.gethostname(),'controller_source_sha256':sha(__file__),'quiescence_sha256':proof_sha}
 once(ROOT/'entry.json',capsule);copy_raw_once(proof,ROOT/'ROOT_M1_GONE.json',proof_sha);copy_raw_once(old_proof,ROOT/'ROOT_OLD_M4_GONE.json',old_proof_sha)
 a=json.loads(ACCEPT.read_text());d=descriptor(a);once(ROOT/'MIXED_DESCRIPTOR.json',d)
 if ACTUAL.exists():
  st=ACTUAL.lstat()
  if ACTUAL.is_symlink() or st.st_uid!=os.getuid() or st.st_mode&0o077:raise ValueError('original scientific parent ownership/privacy')
 else:ACTUAL.mkdir(mode=0o700,parents=True,exist_ok=False);sync_dir(ACTUAL.parent)
 bootstrap=m.LEDGER_ROOT/(str(os.getuid())+'-M4-bootstrap-recovery-v2-'+hashlib.sha256(KEY.encode()).hexdigest()+'.json')
 binding={'one_use_key':KEY,'historical_seconds':HISTORY,'source_action':'act_a0d924d8af6548e2','launcher_sha256':sha(REPO/'economic-atlas/src/atlas_m4_recovery_v2.py'),'result_sha256':d['result_sha256'],'manifest_sha256':d['manifest_sha256'],'mixed_dependency_binding':str(ROOT/'MIXED_DESCRIPTOR.json'),'mixed_dependency_binding_sha256':sha(ROOT/'MIXED_DESCRIPTOR.json'),'controller_monotonic_entry':ENTRY,'controller_utc_entry':UTC_ENTRY,'controller_entry_sha256':sha(ROOT/'entry.json'),'bootstrap_reservation':str(bootstrap),'quiescence_sha256':proof_sha,'oldjob_sha256':old_proof_sha,'controller_source_sha256':sha(__file__)}
 once(ROOT/'ROOT_BINDING.json',binding)
 m.verify_dependency_files(M1/'calibration/result.json',binding)
 m.admission(m.utcnow(),startup=time.monotonic()-ENTRY)
 job=m.plist(sys.executable,REPO/'economic-atlas/src/atlas_m4_recovery_v2.py',REPO,M1/'calibration/result.json',ROOT/'ROOT_BINDING.json',sha(ROOT/'ROOT_BINDING.json'),ACTUAL/'receipts',ACTUAL/'science')
 with (ROOT/'ONE_JOB.plist').open('xb') as f:f.write(job);f.flush();os.fsync(f.fileno())
 sync_dir(ROOT)
 once(ROOT/'PREPARATION.json',{'state':'PREPARED_ONE_FULL_M4_NO_SCIENCE_LAUNCH','entry_sha256':sha(ROOT/'entry.json'),'binding_sha256':sha(ROOT/'ROOT_BINDING.json'),'plist_sha256':sha(ROOT/'ONE_JOB.plist'),'controller_elapsed_seconds':time.monotonic()-ENTRY,'scientific_pass':False})
 if sum(f.stat().st_size for f in ROOT.iterdir() if f.is_file())>32768:raise ValueError('controller live metadata32KiB pre-finalization reservation')
 return ROOT/'PREPARATION.json'
@guarded
def bootstrap(invoke=subprocess.run):
 m=load_durable();m.check_recovery_authority(json.loads((ROOT/'ROOT_OLD_M4_GONE.json').read_text()));entry=json.loads((ROOT/'entry.json').read_text());b=json.loads((ROOT/'ROOT_BINDING.json').read_text());prep=json.loads((ROOT/'PREPARATION.json').read_text());quiescence(json.loads((ROOT/'ROOT_M1_GONE.json').read_text()))
 if entry['controller_source_sha256']!=sha(__file__) or entry['uid']!=os.getuid() or entry['host']!=socket.gethostname() or time.monotonic()-entry['monotonic_entry']<0 or time.monotonic()-entry['monotonic_entry']>120:raise ValueError('samehost bounded originalcontroller entry, no reset')
 if prep['binding_sha256']!=sha(ROOT/'ROOT_BINDING.json') or prep['plist_sha256']!=sha(ROOT/'ONE_JOB.plist') or b['controller_entry_sha256']!=sha(ROOT/'entry.json'):raise ValueError('prepared original controller SHA')
 if (ACTUAL/'science').exists() or (ACTUAL/'receipts').exists():raise ValueError('preexisting actualrun cannot restart')
 model=m.LEDGER_ROOT/(str(os.getuid())+'-M4-'+hashlib.sha256(KEY.encode()).hexdigest()+'.json');lease=P(b['bootstrap_reservation'])
 expected=m.LEDGER_ROOT/(str(os.getuid())+'-M4-bootstrap-recovery-v2-'+hashlib.sha256(KEY.encode()).hexdigest()+'.json')
 if lease.resolve()!=expected.resolve():raise ValueError('canonical bootstrap key/namespace only')
 if model.exists():raise ValueError('original globalM4 model lease already consumed')
 m.LEDGER_ROOT.mkdir(mode=0o700,exist_ok=True);sync_dir(m.LEDGER_ROOT.parent);s=m.LEDGER_ROOT.lstat()
 if m.LEDGER_ROOT.is_symlink() or s.st_uid!=os.getuid() or s.st_mode&0o077:raise ValueError('canonical UID0700')
 m.admission(m.utcnow(),startup=time.monotonic()-entry['monotonic_entry'])
 timeout=controller_guard(entry['monotonic_entry'])-1
 if timeout<=0:raise InterruptedError('no bounded handoff time remains')
 try:
  once(lease,{'state':'STARTED','one_use_key':KEY,'controller_entry_sha256':sha(ROOT/'entry.json'),'binding_sha256':sha(ROOT/'ROOT_BINDING.json'),'outdir':str(ACTUAL/'science'),'receipt_dir':str(ACTUAL/'receipts'),'automatic_retry':False})
 except BaseException as exc:
  # No handoff occurred. Retain created one-use file; do not claim crash durability.
  try:once(lease.with_name(lease.stem+'-terminal.json'),{'state':'BOOTSTRAP_STOP_DURABILITY_UNPROVEN_NO_RETRY','error':type(exc).__name__+': '+str(exc)[:256],'handoff_invoked':False,'models_by_controller':0,'automatic_retry':False,'durable_publication_proven':False})
  except BaseException:pass
  raise
 started=time.monotonic()
 code=None;error=None
 try:
  with (ROOT/'launchctl.stdout').open('xb') as stdout,(ROOT/'launchctl.stderr').open('xb') as stderr:
   r=invoke(['/bin/launchctl','bootstrap','gui/'+str(os.getuid()),str(ROOT/'ONE_JOB.plist')],stdout=stdout,stderr=stderr,timeout=timeout,preexec_fn=cap_launchctl_files)
   code=r.returncode
   controller_guard(entry['monotonic_entry'])
 except Exception as e:error=type(e).__name__+': '+str(e)[:256]
 finally:
  signal.setitimer(signal.ITIMER_REAL,0)
  # run(timeout) kills and reaps only its own launchctl child. Bootstrap may
  # already have handed off the accepted job: this consumed lease never retries.
  once(lease.with_name(lease.stem+'-terminal.json'),{'state':'BOOTSTRAP_RETURNED_NO_RETRY' if error is None else 'BOOTSTRAP_STOP_NO_RETRY_HANDOFF_UNKNOWN','exit':code,'error':error,'stdout_SHA':sha(ROOT/'launchctl.stdout') if (ROOT/'launchctl.stdout').exists() else None,'stderr_SHA':sha(ROOT/'launchctl.stderr') if (ROOT/'launchctl.stderr').exists() else None,'controller_elapsed_seconds':time.monotonic()-entry['monotonic_entry'],'bootstrap_seconds':time.monotonic()-started,'models_by_controller':0,'final_receipt_IO_unmeasured':True,'continuous_resource_pass':False})
 if error is not None:raise RuntimeError(error)
 return code
if __name__=='__main__':
 ap=argparse.ArgumentParser();ap.add_argument('--old-proof',type=P);ap.add_argument('--old-proof-sha');ap.add_argument('--mode',choices=['prepare','bootstrap'],required=True);ap.add_argument('--proof',type=P);ap.add_argument('--proof-sha');a=ap.parse_args()
 if a.mode=='prepare':
  if a.proof is None or a.proof_sha is None or a.old_proof is None or a.old_proof_sha is None:ap.error('root actual fresh proof/SHA required')
  print(prepare(a.proof,a.proof_sha,a.old_proof,a.old_proof_sha))
 else:raise SystemExit(bootstrap())
