"""Reviewed foreground ONE controller; no side effects/imports of science at import."""
import time
ENTRY=time.monotonic()
import datetime
UTC_ENTRY=datetime.datetime.now(datetime.timezone.utc).isoformat()
import argparse,hashlib,importlib.metadata,importlib.util,json,math,os,pathlib,resource,shutil,signal,socket,subprocess,sys,selectors
P=pathlib.Path
OUT=P('/private/tmp/atlas-a63-full-prospective-actual-20261008-v1')
CONTROL=P('/private/tmp/atlas-a63-full-prospective-root-control-20261008')
LEDGER=P('/private/tmp/sberindex-one-use-ledger')
APPROVAL=P('/private/tmp/atlas-a63-full-root-launch-controller-20261008/SOURCE_REGISTRATION.json')
SPEC='economic-atlas/protocols/A63_NEW_PROSPECTIVE_SYNTHETIC_V1.json'
OP='economic-atlas/protocols/A63_FULL_ONE_USE_OPERATIONAL_V1.json'
OP_SHA='be0cb5c758acd468a8d535f78335c96742e86c2d0853d7ff95c8ea1332675da6'
ACK_SHA='86b1ec486bcc607dc7479538c5e5583061db09401986821ed80eb79f18fec3ea'
KEY='A63-full-original-generator-prospective-v1-e2d16ff78bb0cf21acded09d844dd8690a10dd03d3ee466df3632c234242795d'
LIMIT=1800;WORK=1770;MAXOUT=134217728;MINFREE=1073741824;MAXRSS=1073741824;LOGCAP=8192

def sha(p):
 h=hashlib.sha256()
 with P(p).open('rb') as f:
  for chunk in iter(lambda:f.read(1<<20),b''):h.update(chunk)
 return h.hexdigest()
def sync_parent(p):
 fd=os.open(P(p).parent,os.O_RDONLY)
 try:os.fsync(fd)
 finally:os.close(fd)
def once(p,v):
 fd=os.open(p,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
 with os.fdopen(fd,'w') as f:json.dump(v,f,allow_nan=False);f.write('\n');f.flush();os.fsync(f.fileno())
 sync_parent(p)
def finite(v):
 if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v):raise ValueError('finite nonbool original anchor')
 return v
def lease(kind):return LEDGER/(str(os.getuid())+'-'+hashlib.sha256(KEY.encode()).hexdigest()+kind+'.json')
def output_size():
 roots=[OUT,CONTROL,lease(''),lease('').with_suffix('.terminal.json'),lease('-controller'),lease('-controller').with_suffix('.terminal.json')];seen=set();n=0;control_n=0
 for root in roots:
  if root.is_symlink():raise ValueError('owned output symlink')
  files=[root] if root.is_file() else root.rglob('*') if root.is_dir() else []
  for p in files:
   if p.is_symlink():raise ValueError('owned output symlink')
   if p.is_file() and p.resolve() not in seen:
    seen.add(p.resolve());size=p.stat().st_size;n+=size
    if CONTROL.resolve() in p.resolve().parents:control_n+=size
 if control_n>32768:raise InterruptedError('controller32KiB prefinal cap')
 return n

def guard(anchor=ENTRY,native=None):
 elapsed=time.monotonic()-finite(anchor)
 if not 0<=elapsed<=WORK:raise InterruptedError('controller-inclusive1770work+30finalreserve')
 if output_size()>MAXOUT-65536:raise InterruptedError('full128MiB/64KiB receiptreserve')
 if shutil.disk_usage(CONTROL.parent).free<MINFREE:raise InterruptedError('minimumfree1GiB')
 rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*(1 if sys.platform=='darwin' else 1024)
 if native is not None:rss,_=native.own_tree_rss()
 if rss>MAXRSS:raise InterruptedError('whole own controller/guardian/worker1GiB RSS')
 return WORK-elapsed

def seed_inventory(repo,spec):
 old_path=repo/'economic-atlas/runs/A6_frozen_controls_20261003/runs.json';old=json.loads(old_path.read_text())
 old_seeds=sorted({r['seed'] for r in old});old_worlds=sorted({r['world'] for r in old});new=spec['seeds'];worlds=spec['worlds']
 expected={(s,w,m,f) for s in range(20261003,20261008) for w in worlds for m in ['oracle','unsupervised'] for f in [.75,1.,1.25]};actual=[(r['seed'],r['world'],r['mode'],r['margin_factor']) for r in old]
 if len(actual)!=210 or len(set(actual))!=210 or set(actual)!=expected:raise ValueError('old210 exact inventory')
 if len(new)!=5 or len(set(new))!=5 or set(new)&set(old_seeds):raise ValueError('prospective seed keys not independent old keys')
 old_effective={s+1000*i for s in old_seeds for i in range(7)};new_effective={s+1000*i for s in new for i in range(7)}
 if len(new_effective)!=35 or old_effective&new_effective:raise ValueError('effective generator RNG key collision')
 return {'old210_SHA':sha(old_path),'old_seeds':old_seeds,'new_seeds':new,'old_effective_rng_keys':sorted(old_effective),'new_effective_rng_keys':sorted(new_effective),'disjoint':True,'old_runs':210,'scope':'Exact frozen original-generator210 only; no world generation. Alternative M2/M3 uses another generator/thresholds and is not this inventory. Does not prove universal absence of hidden/off-repository prior uses.'}

def validate(repo,approval):
 st=approval.lstat()
 if approval.resolve()!=APPROVAL or approval.is_symlink() or st.st_uid!=os.getuid():raise ValueError('trusted fixed root source registration')
 a=json.loads(approval.read_text())
 if a.get('root_reviewed') is not True or a.get('one_use_key')!=KEY or a.get('controller_SHA')!=sha(__file__) or a.get('operational_protocol_SHA')!=OP_SHA or a.get('uid')!=os.getuid() or a.get('host')!=socket.gethostname():raise ValueError('actual root accepted controller/protocol/UID/host')
 if sha(repo/OP)!=OP_SHA:raise ValueError('new accepted operational protocol')
 op=json.loads((repo/OP).read_text());pins=op['pins']
 if a.get('pins')!=pins:raise ValueError('root exact14 pins')
 for name,h in pins.items():
  if sha(repo/name)!=h:raise ValueError('pinned sources')
 if a.get('python_binary_SHA')!=sha(P(sys.executable).resolve()):raise ValueError('root pinned interpreter binary')
 versions={pkg:importlib.metadata.version(pkg) for pkg in ['numpy','pandas','scipy','scikit-learn']}
 if a.get('dependency_versions')!=versions:raise ValueError('metadata dependency versions without scientific imports')
 spec=json.loads((repo/SPEC).read_text());inventory=seed_inventory(repo,spec)
 digest=hashlib.sha256(json.dumps(inventory,sort_keys=True,allow_nan=False).encode()).hexdigest()
 if a.get('seed_inventory_SHA')!=digest or a.get('seed_prior_nonuse_root_attested') is not True:raise ValueError('root prior seednonuse authority required, no self ACK')
 if a.get('independent_source_ACK_SHA')!=ACK_SHA:raise ValueError('independent source ACK exactSHA')
 return a,op,inventory,versions

def drain_logs(selector,streams):
 # Bounded read and bounded on-disk logs, never communicate/capture_output.
 # No inherited RLIMIT_FSIZE that would accidentally cap scientific NPZ.
 for key,_ in selector.select(timeout=.1):
  chunk=os.read(key.fileobj.fileno(),4096)
  if not chunk:selector.unregister(key.fileobj);continue
  target=streams[key.data]
  if target.tell()+len(chunk)>LOGCAP:raise InterruptedError('bounded guardian stdout/stderr8KiB each')
  target.write(chunk);target.flush()

def cleanup(process,native):
 # TERM invokes adopted guardian own-worker cleanup. Only known owned PGs
 # observed in our descendant tree may be signalled on bounded fallback.
 if process is None:return {'immediate_reaped':True,'known_remaining':[]}
 if process.pid==os.getpgrp():raise RuntimeError('refuse own/user foreground processgroup')
 known=({process.pid}|set(native.descendants(process.pid))) if native is not None else {process.pid}
 if process.poll() is None:
  try:os.killpg(process.pid,signal.SIGTERM)
  except ProcessLookupError:pass
 try:process.wait(timeout=10)
 except subprocess.TimeoutExpired:
  # A nested worker uses a separate session. Its PID must be in our known
  # owned descendant tree and have that same PID as its process-group ID.
  for pid in sorted(known-{process.pid},reverse=True):
   try:
    if os.getpgid(pid)==pid:os.killpg(pid,signal.SIGTERM)
   except ProcessLookupError:pass
  try:process.wait(timeout=5)
  except subprocess.TimeoutExpired:
   for pid in sorted(known,reverse=True):
    try:
     if os.getpgid(pid)==pid:os.killpg(pid,signal.SIGKILL)
    except ProcessLookupError:pass
   process.wait(timeout=5)
 for name in ['stdout','stderr']:
  stream=getattr(process,name,None)
  if stream is not None:stream.close()
 remaining=native.descendants(os.getpid()) if native is not None else []
 return {'immediate_reaped':True,'known_remaining':remaining,'continuous_resource_pass':False}

def execute(repo,approval=APPROVAL,popen=subprocess.Popen):
 process=None;native=None;owned=False;consumed=False;handlers={};record={'state':'INCONCLUSIVE_CONTROLLER','scientific_pass':False,'continuous_resource_pass':False,'automatic_retry':False}
 def interrupt(signum,frame):
  signal.setitimer(signal.ITIMER_REAL,0)
  signal.signal(signal.SIGTERM,signal.SIG_IGN);signal.signal(signal.SIGINT,signal.SIG_IGN)
  raise InterruptedError('controller scopedinterrupt '+str(signum))
 for sig in [signal.SIGTERM,signal.SIGINT,signal.SIGALRM]:handlers[sig]=signal.getsignal(sig)
 signal.signal(signal.SIGTERM,interrupt);signal.signal(signal.SIGINT,interrupt)
 def watchdog(*unused):
  try:guard(native=native)
  except BaseException:signal.setitimer(signal.ITIMER_REAL,0);raise
 signal.signal(signal.SIGALRM,watchdog);signal.setitimer(signal.ITIMER_REAL,.25,.25)
 try:
  # An initial stdlib-only admission precedes source reading, runtime mkdir,
  # permanent lease, native module and guardian process dispatch.
  guard();a,op,inventory,versions=validate(repo,approval);guard()
  if CONTROL.exists() or OUT.exists() or lease('').exists() or lease('-controller').exists():raise ValueError('fresh fixed namespace/permanentleases; no retry')
  LEDGER.mkdir(mode=0o700,exist_ok=True);sync_parent(LEDGER);st=LEDGER.lstat()
  if LEDGER.is_symlink() or st.st_uid!=os.getuid() or st.st_mode&0o077:raise ValueError('canonicalUID0700')
  once(lease('-controller'),{'state':'STARTED','original_monotonic_entry':ENTRY,'original_UTC_entry':UTC_ENTRY,'root_registration_SHA':sha(approval),'protocol_SHA':OP_SHA,'controller_SHA':sha(__file__),'automatic_retry':False});consumed=True
  CONTROL.mkdir(mode=0o700,exist_ok=False);owned=True;sync_parent(CONTROL)
  once(CONTROL/'ENTRY.json',{'monotonic_entry':ENTRY,'UTC_entry':UTC_ENTRY,'uid':os.getuid(),'host':socket.gethostname(),'controller_SHA':sha(__file__)})
  once(CONTROL/'PRIOR_SEED_NONUSE_INVENTORY.json',inventory)
  binding={'root_reviewed':True,'one_use_key':KEY,'out':str(OUT),'controller_monotonic_entry':ENTRY,'controller_utc_entry':UTC_ENTRY,'uid':os.getuid(),'host':socket.gethostname(),'protocol_SHA':OP_SHA,'pins':op['pins'],'seed_keys_prior_nonuse_verified':True,'root_source_registration_SHA':sha(approval),'python_binary_SHA':a['python_binary_SHA'],'dependency_versions':versions,'controller_SHA':sha(__file__)}
  once(CONTROL/'ROOT_BINDING.json',binding);guard()
  if time.monotonic()-ENTRY>120:raise InterruptedError('guardian rootbinding handoff<=120s')
  spec=importlib.util.spec_from_file_location('accepted_a63_native_guard',repo/'economic-atlas/src/atlas_m1_executor.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);native=m.NativeMac();guard(native=native)
  env=dict(os.environ);env['PYTHONDONTWRITEBYTECODE']='1'
  for k in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS','NUMEXPR_NUM_THREADS']:env[k]='1'
  with (CONTROL/'guardian.stdout').open('xb') as stdout,(CONTROL/'guardian.stderr').open('xb') as stderr:
   process=popen([sys.executable,str(repo/'economic-atlas/src/a63_full_guardian.py'),'--repo',str(repo),'--binding',str(CONTROL/'ROOT_BINDING.json')],stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env,start_new_session=True)
   once(CONTROL/'OWNED_GUARDIAN.json',{'pid':process.pid,'owned_pgid':process.pid,'binding_SHA':sha(CONTROL/'ROOT_BINDING.json')})
   with selectors.DefaultSelector() as selector:
    selector.register(process.stdout,selectors.EVENT_READ,'stdout');selector.register(process.stderr,selectors.EVENT_READ,'stderr')
    while process.poll() is None:
     guard(native=native);drain_logs(selector,{'stdout':stdout,'stderr':stderr})
    # Drain final bounded pipe bytes before terminal, not unbounded capture.
    while selector.get_map():guard(native=native);drain_logs(selector,{'stdout':stdout,'stderr':stderr})
   guard(native=native)
  record.update(state='GUARDIAN_RETURNED_INDEPENDENT_AUDIT_PENDING' if process.returncode==0 else 'INCONCLUSIVE_GUARDIAN_EXIT_NO_RETRY',guardian_exit=process.returncode)
 except BaseException as e:record['error']=type(e).__name__+': '+str(e)[:512]
 finally:
  signal.setitimer(signal.ITIMER_REAL,0)
  # Any stop path protects bounded own-child cleanup from repeated TERM/INT.
  signal.signal(signal.SIGTERM,signal.SIG_IGN);signal.signal(signal.SIGINT,signal.SIG_IGN)
  try:
   if consumed:
    try:
     record['cleanup']=cleanup(process,native)
     if record['cleanup']['known_remaining']:record['state']='INCONCLUSIVE_OWNERSHIP_REMAINS_NO_RETRY'
    except BaseException as e:record.update(state='INCONCLUSIVE_CLEANUP_NO_RETRY',cleanup_error=str(e)[:256])
    elapsed=time.monotonic()-ENTRY;record.update(inclusive_elapsed_before_final_receipt=elapsed,whole_budget_seconds=1800,final_receipt_IO_unmeasured=True)
    record['whole_output_bytes_observed']=output_size()
    if elapsed>LIMIT or record['whole_output_bytes_observed']>MAXOUT:record['state']='INCONCLUSIVE_CONTROLLER_FINAL_BUDGET'
    if owned:once(CONTROL/'CONTROLLER_TERMINAL.json',record)
    once(lease('-controller').with_suffix('.terminal.json'),record)
  finally:
   for sig,old in handlers.items():signal.signal(sig,old)
 return record
if __name__=='__main__':
 ap=argparse.ArgumentParser();ap.add_argument('--repo',type=P,required=True);args=ap.parse_args();r=execute(args.repo.resolve());raise SystemExit(0 if r['state']=='GUARDIAN_RETURNED_INDEPENDENT_AUDIT_PENDING' else 1)
