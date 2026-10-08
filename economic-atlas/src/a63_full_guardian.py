"""Root-bound ONE full prospective A6.3 guardian. Import is stdlib-only."""
import time
ENTRY=time.monotonic()
import argparse,datetime,hashlib,importlib.util,json,math,os,pathlib,resource,secrets,shutil,signal,socket,sys
P=pathlib.Path
OUT=P('/private/tmp/atlas-a63-full-prospective-actual-20261008-v1')
CONTROL=P('/private/tmp/atlas-a63-full-prospective-root-control-20261008')
LEDGER=P('/private/tmp/sberindex-one-use-ledger')
SPEC='economic-atlas/protocols/A63_NEW_PROSPECTIVE_SYNTHETIC_V1.json'
OP='economic-atlas/protocols/A63_FULL_ONE_USE_OPERATIONAL_V1.json'
KEY='A63-full-original-generator-prospective-v1-e2d16ff78bb0cf21acded09d844dd8690a10dd03d3ee466df3632c234242795d'
LIMITS={'rss':1073741824,'wall':1770,'free':1073741824,'output':134217728-65536,'sample':.25,'disk_sample':1}

def sha(p):return hashlib.sha256(P(p).read_bytes()).hexdigest()
def sync_parent(p):
 fd=os.open(P(p).parent,os.O_RDONLY)
 try:os.fsync(fd)
 finally:os.close(fd)

def once(p,v):
 fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
 with os.fdopen(fd,'w') as f:json.dump(v,f,allow_nan=False);f.write('\n');f.flush();os.fsync(f.fileno())
 sync_parent(p)
def finite(x):
 if isinstance(x,bool) or not isinstance(x,(float,int)) or not math.isfinite(x):raise ValueError('finite nonbool anchor')
 return x

def lease_path():return LEDGER/(str(os.getuid())+'-'+hashlib.sha256(KEY.encode()).hexdigest()+'.json')
def sizes():
 seen=set();total=0
 for root in [OUT,CONTROL,lease_path(),lease_path().with_suffix('.terminal.json')]:
  if root.is_symlink():raise ValueError('owned output symlink')
  files=[root] if root.is_file() else root.rglob('*') if root.is_dir() else []
  for f in files:
   if f.is_symlink():raise ValueError('owned output symlink')
   if f.is_file() and f.resolve() not in seen:seen.add(f.resolve());total+=f.stat().st_size
 return total

def admission(anchor):
 elapsed=time.monotonic()-finite(anchor)
 if elapsed<0 or elapsed>1770:raise InterruptedError('inclusive1800s minus30reserve')
 if sizes()>LIMITS['output']:raise InterruptedError('whole128MiB reserve')
 if shutil.disk_usage(OUT.parent).free<LIMITS['free']:raise InterruptedError('minimumfree1GiB')
 rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*(1 if sys.platform=='darwin' else 1024)
 if rss>LIMITS['rss']:raise InterruptedError('self1GiB RSS')
 return elapsed

def validate(repo,binding):
 st=CONTROL.lstat()
 if CONTROL.is_symlink() or st.st_uid!=os.getuid() or st.st_mode&0o077 or binding.is_symlink():raise ValueError('UIDprivate0700 trusted root control')
 if sum(x.stat().st_size for x in CONTROL.rglob('*') if x.is_file())>32768:raise ValueError('rootcontrol32KiB within128MiB')
 b=json.loads(binding.read_text())
 if binding.resolve()!=CONTROL/'ROOT_BINDING.json' or b.get('root_reviewed') is not True or b.get('one_use_key')!=KEY or b.get('out')!=str(OUT):raise ValueError('fixed root-controlled namespace and review')
 anchor=finite(b['controller_monotonic_entry']);age=ENTRY-anchor
 stamp=datetime.datetime.fromisoformat(b['controller_utc_entry']);now=datetime.datetime.now(datetime.timezone.utc)
 if stamp.tzinfo is None or not 0<=age<=120 or abs((now-stamp).total_seconds()-(time.monotonic()-anchor))>5 or b['uid']!=os.getuid() or b['host']!=socket.gethostname():raise ValueError('samehost inclusive controller anchor')
 if b['protocol_SHA']!=sha(repo/OP):raise ValueError('operational protocol rootSHA')
 op=json.loads((repo/OP).read_text());pins=op['pins'];spec=json.loads((repo/SPEC).read_text())
 if spec['schema']!='A63_PROSPECTIVE_DESIGN_V1' or spec['configuration_count']!=210 or spec['postinitial_month_count']!=4830:raise ValueError('full frozen science specification')
 for name,h in pins.items():
  if sha(repo/name)!=h:raise ValueError('scientific/operational inputSHA')
 if b['pins']!=pins or b.get('seed_keys_prior_nonuse_verified') is not True:raise ValueError('exact root source+prospective seed inventory')
 return anchor,pins

def install_owned_interrupts():
 previous={sig:signal.getsignal(sig) for sig in (signal.SIGTERM,signal.SIGINT)}
 def interrupt(signum,frame):
  # Unwind through accepted run_phase BaseException/finally; it alone owns
  # the newly spawned PG. Disable repeated signals during bounded cleanup.
  signal.setitimer(signal.ITIMER_REAL,0)
  signal.signal(signal.SIGTERM,signal.SIG_IGN);signal.signal(signal.SIGINT,signal.SIG_IGN)
  raise InterruptedError('owned guardian interruption '+str(signum))
 for sig in previous:signal.signal(sig,interrupt)
 return previous

def restore_owned_interrupts(previous):
 for sig,handler in previous.items():signal.signal(sig,handler)

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--repo',type=P,required=True);ap.add_argument('--binding',type=P,required=True);args=ap.parse_args();repo=args.repo.resolve();anchor,pins=validate(repo,args.binding);admission(anchor)
 if OUT.exists() or lease_path().exists():raise ValueError('fresh namespace, no retry/alternate output')
 LEDGER.mkdir(mode=0o700,exist_ok=True);sync_parent(LEDGER);s=LEDGER.lstat()
 if LEDGER.is_symlink() or s.st_uid!=os.getuid() or s.st_mode&0o077:raise ValueError('canonicalUIDprivate0700')
 once(lease_path(),{'state':'STARTED','key':KEY,'out':str(OUT),'root_binding_SHA':sha(args.binding),'pins':pins,'original_anchor':anchor,'automatic_retry':False})
 previous_interrupts=install_owned_interrupts()
 owned=False;record={'state':'INCONCLUSIVE','scientific_pass':False,'independent_saved_error_audit':'PENDING','continuous_resource_pass':False,'automatic_retry':False};g=None;native=None
 try:
  OUT.mkdir(mode=0o700,exist_ok=False);owned=True;sync_parent(OUT)
  for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS','NUMEXPR_NUM_THREADS'):os.environ[key]='1'
  os.environ['PYTHONDONTWRITEBYTECODE']='1'
  def alarm(*unused):
   try:admission(anchor)
   except BaseException:
    signal.setitimer(signal.ITIMER_REAL,0);raise
  signal.signal(signal.SIGALRM,alarm);signal.setitimer(signal.ITIMER_REAL,.25,.25)
  src=repo/'economic-atlas/src/atlas_m1_executor.py';s=importlib.util.spec_from_file_location('pinned_original_guard',src);g=importlib.util.module_from_spec(s);s.loader.exec_module(g)
  native=g.NativeMac();admission(anchor);g.resource_preflight(OUT/'native-preflight',native)
  admission(anchor)
  secret=secrets.token_hex(32);os.environ['A63_PRIVATE_AUTH']=secret;auth=OUT/'WORKER_AUTHORITY.json'
  once(auth,{'secret_SHA':hashlib.sha256(secret.encode()).hexdigest(),'parent_pid':os.getpid(),'repo':str(repo),'out':str(OUT),'worker_SHA':pins['economic-atlas/src/a63_full_worker.py'],'protocol_SHA':sha(repo/OP),'pins':pins})
  phase=g.run_phase([sys.executable,str(repo/'economic-atlas/src/a63_full_worker.py'),'--authority',str(auth),'--repo',str(repo),'--out',str(OUT)],OUT,'full-suite',anchor,limits=LIMITS,native=native)
  os.environ.pop('A63_PRIVATE_AUTH',None);admission(anchor)
  remaining=native.descendants(os.getpid())
  if remaining:raise RuntimeError('knownowned descendants remain; no completed acceptance')
  if phase['state']!='COMPLETE':raise RuntimeError('bounded full-suite incomplete; no scientific retries')
  for filename in ('runs.json','months.json','metrics.json','manifest.json','truth.json','events.json'):
   if not (OUT/filename).is_file():raise ValueError('full artifacts missing')
  # This parent checks key completeness without scoring or extra fits.
  runs=json.loads((OUT/'runs.json').read_text());months=json.loads((OUT/'months.json').read_text())
  if len(runs)!=210 or len(months)!=4830:raise ValueError('fullscope210/4830 required')
  record.update(state='FULL_SUITE_ARTIFACTS_COMPLETE_INDEPENDENT_AUDIT_PENDING',phase=phase,metrics_SHA=sha(OUT/'metrics.json'),manifest_SHA=sha(OUT/'manifest.json'))
 except BaseException as e:record.update(error=type(e).__name__+': '+str(e)[:512])
 finally:
  signal.setitimer(signal.ITIMER_REAL,0);os.environ.pop('A63_PRIVATE_AUTH',None)
  try:
   elapsed=time.monotonic()-anchor;record.update(inclusive_elapsed_before_final_receipt=elapsed,full_budget_seconds=1800,final_receipt_reserve_seconds=30,final_receipt_IO_unmeasured=True,whole_output_observed_bytes=sizes())
   if elapsed>1800 or sizes()>134217728:record['state']='INCONCLUSIVE_FINAL_BUDGET'
   if owned:once(OUT/'guardian-terminal.json',record)
   once(lease_path().with_suffix('.terminal.json'),record)
  finally:restore_owned_interrupts(previous_interrupts)
 if record['state']!='FULL_SUITE_ARTIFACTS_COMPLETE_INDEPENDENT_AUDIT_PENDING':raise SystemExit(1)
if __name__=='__main__':main()
