"""Root-reviewed one-use numerical recovery guardian; no resume or paid APIs.
Worker dispatch is internal one-use parent authority; reject before numerical imports.
Sampled resource guards disclose old monitor gap and unmeasured final receipt fsync.
"""
from pathlib import Path
import argparse,datetime,hashlib,importlib.util,json,math,os,shutil,signal,sys,time
sys.dont_write_bytecode=True
START=datetime.datetime.fromisoformat('2026-10-07T15:47:45.854058+00:00');TOTAL=77881;RESERVE=30;OUT_RESERVE=65536
VIEW=Path('/private/tmp/atlas-m1-frozen-execution-view-20261007');OLD=Path('/private/tmp/atlas-m1-full-baseline-20261007-v1');LEDGER=Path('/private/tmp/sberindex-one-use-ledger')
KNOWN_ELAPSED_FLOOR=(datetime.datetime.fromisoformat('2026-10-07T23:15:48+00:00')-START).total_seconds()
PROTO_SHA='516ca1cf068dd420ddbd560a8329c27ca9ab4cc9f582375a770e02bc93ff302e';GUARD_SHA='04b89b778bd3f1f3e5beb83edc0786c39086b249f9b74658219922958c4db93c'
KEY='M1:fd3133bbda35fb7183908e4c3bd4697f5651962adaf8c0cccf74eb4b15c0dc30:EXPLICIT_NUMERICAL_RECOVERY_EVD_V1'
THREADS=('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS')
BASE_PINS={'economic-atlas/src/atlas_m1_spectral.py':'5ad14f6e2df75ac89d2285e3a09c304e7894ce6c42a363334a1d568115c1758b','economic-atlas/src/atlas_m1_executor.py':GUARD_SHA,'economic-atlas/protocols/M1_PROSPECTIVE_V1.json':'fd3133bbda35fb7183908e4c3bd4697f5651962adaf8c0cccf74eb4b15c0dc30','economic-atlas/src/a6_temporal.py':'c498d5a7d145264e0182e589a7dedb2b733fb9854cb5c167227e42f2eb3c9474','economic-atlas/src/atlas_sdbw.py':'fc9a83fc430028452a8a88622337df605574518baf2044f0ab068f142edfd9fa','economic-atlas/frozen_inputs.json':'16e2a5e2bdc63c264551d823a9e8ec11573b297cecf530392227fa845ed88099','economic-atlas/data/panel_v1.parquet':'8716a802fb6e25ef4103406cca927de80ce3693a7ff243411cda765b732bcd93','economic-atlas/runs/A5/features.parquet':'12f40b15ee8f119cba7f386b5c9adf4babb5cff1bca2721dc04551d672f5e5d6'}

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def load(path,name):
 s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def atomic(p,value):
 p=Path(p);temp=p.with_name(p.name+'.tmp')
 with temp.open('w') as f:json.dump(value,f,indent=2,allow_nan=False);f.write('\n');f.flush();os.fsync(f.fileno())
 os.replace(temp,p)
def once(p,value):
 fd=os.open(p,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
 with os.fdopen(fd,'w') as f:json.dump(value,f,allow_nan=False,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
 fd=os.open(Path(p).parent,os.O_RDONLY)
 try:os.fsync(fd)
 finally:os.close(fd)
def remaining(now=None):
 now=now or datetime.datetime.now(datetime.timezone.utc)
 if now.tzinfo is None:raise ValueError('UTC aware time required')
 elapsed=(now-START).total_seconds()
 if not math.isfinite(elapsed) or elapsed<0 or elapsed>=TOTAL-RESERVE:raise ValueError('original total exhausted/noreset')
 return math.floor(TOTAL-RESERVE-elapsed)
def elapsed(record):return max((datetime.datetime.now(datetime.timezone.utc)-START).total_seconds(),record['historical_seconds']+time.monotonic()-record['monotonic_entry'])
def files_size(roots):
 total=0
 for root in map(Path,roots):
  if root.is_file():total+=root.stat().st_size
  elif root.is_dir():total+=sum(p.stat().st_size for p in root.rglob('*') if p.is_file())
 return total
def roots(record):return [OLD,Path(record['out']),Path(record['receipts'])]+[Path(p) for p in record['extra_accounting_roots']]
def admit(record,native=None,force_disk=False):
 remaining()
 if elapsed(record)>=TOTAL-RESERVE:raise RuntimeError('inclusive original wall exhausted')
 now=time.monotonic()
 if force_disk or now-record.get('last_disk_check',-math.inf)>=1.:
  if shutil.disk_usage(record['out_parent']).free<1073741824 or files_size(roots(record))>=268435456-OUT_RESERVE:raise RuntimeError('combined disk/output admission')
  record['last_disk_check']=now
 if native is not None:
  total,_=native.own_tree_rss()
  if total>1073741824:raise RuntimeError('aggregate own RSS')

def destinations(out,receipts):
 out=out.resolve();receipts=receipts.resolve()
 if out.exists() or receipts.exists():raise ValueError('fresh outputs only/noresume')
 for target in (out,receipts):
  for protected in (OLD.resolve(),VIEW.resolve()):
   if target==protected or target in protected.parents or protected in target.parents:raise ValueError('old output/view immutable')
 if out==receipts or out in receipts.parents or receipts in out.parents:raise ValueError('distinct nonnested outputs')
 if any(os.stat(p.parent).st_dev!=os.stat(OLD).st_dev for p in (out,receipts)):raise ValueError('same disk required')
 return out,receipts

def authority(protocol):
 here=Path(__file__).parent
 return {'engine':sha(here/'atlas_m1_evd_engine.py'),'recovery':sha(here/'atlas_m1_recovery_keys.py'),'guardian':sha(__file__),'validator':sha(here/'atlas_m1_recovery_validate.py'),'amendment':sha(protocol),'base_source':BASE_PINS['economic-atlas/src/atlas_m1_spectral.py'],'base_protocol':BASE_PINS['economic-atlas/protocols/M1_PROSPECTIVE_V1.json']}
def check_pins():
 if any(sha(VIEW/p)!=v for p,v in BASE_PINS.items()):raise ValueError('base source/input dependency SHA changed')
def binding(path,digest,protocol):
 if sha(path)!=digest or sha(protocol)!=PROTO_SHA:raise ValueError('root binding/amendment SHA changed')
 b=json.loads(Path(path).read_text())
 if b.get('key')!=KEY or b.get('authority')!=authority(protocol) or b.get('original_start_UTC')!=START.isoformat() or b.get('original_total_seconds')!=TOTAL or b.get('source_action')!='act_4d0536caf3a546ac' or b.get('root_authorized_EVD_transition') is not True:raise ValueError('explicit root numerical transition binding required')
 proof=Path(b['old_process_gone_receipt'])
 if sha(proof)!=b['old_process_gone_receipt_SHA']:raise ValueError('reviewed old lifecycle proof changed')
 q=json.loads(proof.read_text())
 if q.get('old_processes_authoritatively_gone') is not True or q.get('original_scientific_pid')!=53084 or q.get('original_guard_pid')!=53072 or q.get('old_exit_code') is not None or q.get('continuous_old_guard_coverage') is not False:raise ValueError('honest root-known old terminal/gap proof required')
 if (OLD/'calibrate-v1/result.json').exists() or (OLD/'calibrate-v1/manifest.json').exists():raise ValueError('ancestral partial state unexpectedly changed')
 return b

def private_lease():
 LEDGER.mkdir(mode=0o700,exist_ok=True);s=LEDGER.lstat()
 if LEDGER.is_symlink() or s.st_uid!=os.getuid() or s.st_mode&0o077:raise ValueError('global UID0700 ledger required')
 return LEDGER/(str(os.getuid())+'-'+hashlib.sha256(KEY.encode()).hexdigest()+'.json')

def worker_authority(args):
 # Public --worker without literal parent one-use descriptor aborts before any
 # scientific/numpy/scipy imports, native query, eigen/model or output creation.
 if args.worker is None or args.dispatch_sha is None:raise ValueError('private parent dispatch required')
 path=args.worker
 if sha(path)!=args.dispatch_sha or path.is_symlink():raise ValueError('dispatch descriptor changed')
 d=json.loads(path.read_text())
 if d.get('parent_pid')!=os.getppid() or type(d.get('parent_pid')) is not int or d.get('uid')!=os.getuid() or d.get('key')!=KEY or d.get('phase')!='FULL_NUMERICAL_RECOVERY' or d.get('native_preflight_pass') is not True:raise ValueError('one-use native parent dispatch required')
 if d.get('authority')!=authority(Path(d['protocol'])) or sha(d['protocol'])!=PROTO_SHA:raise ValueError('active worker sources changed')
 if any(os.environ.get(k)!='1' for k in THREADS):raise ValueError('CPU1 before imports required')
 lease=Path(d['lease']);record=json.loads(lease.read_text())
 if record.get('parent_pid')!=d['parent_pid'] or record.get('uid')!=d['uid'] or record.get('state')!='STARTED' or record.get('authority')!=d['authority']:raise ValueError('original parent lease mismatch')
 if path.parent.resolve()!=Path(d['receipts']).resolve() or lease.resolve()!=LEDGER/(str(os.getuid())+'-'+hashlib.sha256(KEY.encode()).hexdigest()+'.json'):raise ValueError('canonical parent descriptor/lease location')
 nativeproof=Path(d['native_preflight_receipt'])
 if sha(nativeproof)!=d['native_preflight_receipt_SHA'] or json.loads(nativeproof.read_text()).get('state')!='PASS':raise ValueError('actual native preflight receipt required')
 once(path.with_name('worker-consumed.json'),{'parent_pid':os.getppid(),'child_pid':os.getpid(),'descriptor_SHA':args.dispatch_sha})
 return d

def phase_manifest(out,auth):
 atomic(out/'manifest.json',{'authority':auth,'code_sha256':auth['engine'],'protocol_sha256':auth['amendment'],'files_sha256':{p.name:sha(p) for p in out.iterdir() if p.is_file() and p.name!='manifest.json'}})
def freeze(out,auth,phase):
 out.mkdir(exist_ok=False);atomic(out/'protocol-freeze.json',{'phase':phase,'authority':auth,'scientific_pass':False})
def worker(args):
 d=worker_authority(args);check_pins();here=Path(__file__).parent
 keys=load(here/'atlas_m1_recovery_keys.py','recovery_keys');p=keys.read_protocol(d['protocol']);frozen=json.loads((VIEW/'economic-atlas/protocols/M1_PROSPECTIVE_V1.json').read_text())
 guard=load(VIEW/'economic-atlas/src/atlas_m1_executor.py','accepted_resource');native=guard.NativeMac();record=d['budget_record'];admission=lambda:admit(record,native)
 admission();engine=load(here/'atlas_m1_evd_engine.py','evd_engine');validate=load(here/'atlas_m1_recovery_validate.py','publication_validate');out=Path(d['out']);out.mkdir(exist_ok=False)
 journal=keys.Journal(out/'journals',d['authority']);nums=keys.solver_preflight(engine,journal,frozen,admission);atomic(out/'numerical-preflight.json',nums)
 ids,months,shares,audit,inputsha=engine.load_panel(VIEW,frozen);admission()
 calout=out/'calibration';freeze(calout,d['authority'],'recovery_calibration')
 result=keys.remaining26(engine,journal,p,frozen,admission);result.update(state='COMPUTED_DESCRIPTIVE_MIXED_NUMERICAL_RECOVERY',authority=d['authority'],input_sha256=inputsha)
 for k,c in result['results'].items():atomic(calout/f'calibration-progress-k{k}.json',{x:c[x] for x in ('calibration','fit','held')})
 atomic(calout/'result.json',result);phase_manifest(calout,d['authority']);old,_=keys.ancestral_records(p,frozen);validate.calibration(calout,d['authority'],p,frozen,old,admission)
 repl=out/'replay';freeze(repl,d['authority'],'replay');r=keys.journalled_replay(engine,journal,VIEW,frozen,result,repl,admission);r.update(authority=d['authority'],calibration_sha256=sha(calout/'result.json'));atomic(repl/'result.json',r);phase_manifest(repl,d['authority']);validate.replay(repl,d['authority'],frozen,sha(calout/'result.json'),ids,inputsha,admission)
 admission();atomic(out/'result.json',{'state':'FULL_MIXED_RECOVERY_REPLAY_DESCRIPTIVE','authority':d['authority'],'calibration_SHA':sha(calout/'result.json'),'replay_SHA':sha(repl/'result.json'),'scientific_pass':False,'economic_identity_pass':False,'source_actions_closed':0})
 atomic(out/'manifest.json',{'authority':d['authority'],'files_sha256':{str(p.relative_to(out)):sha(p) for p in out.rglob('*') if p.is_file() and p!=out/'manifest.json'}})
 admission()

def main(argv=None):
 started=time.monotonic();historical=max(KNOWN_ELAPSED_FLOOR,(datetime.datetime.now(datetime.timezone.utc)-START).total_seconds())
 parser=argparse.ArgumentParser();parser.add_argument('--worker',type=Path);parser.add_argument('--dispatch-sha')
 for k in ('protocol','binding','outdir','receipt-dir'):parser.add_argument('--'+k,type=Path)
 parser.add_argument('--binding-sha');args=parser.parse_args(argv)
 if args.worker is not None:return worker(args)
 if args.dispatch_sha is not None:raise ValueError('no public internal worker bypass')
 if any(getattr(args,k) is None for k in ('protocol','binding','outdir','receipt_dir','binding_sha')):parser.error('root binding/protocol/fresh output/receipts required')
 remaining();out,receipt=destinations(args.outdir,args.receipt_dir)
 record={'historical_seconds':historical,'monotonic_entry':started,'out':str(out),'receipts':str(receipt),'out_parent':str(out.parent),'extra_accounting_roots':[]}
 # Include canonical lease+terminal and exact own launchd log paths throughout.
 lease=private_lease();terminal=lease.with_name(lease.stem+'-terminal.json');record['extra_accounting_roots']=[str(lease),str(terminal)]
 # File roots are explicitly accounted by admission wrapper below.
 logs=[receipt.parent/'M1-recovery-launchd.stdout.log',receipt.parent/'M1-recovery-launchd.stderr.log']
 record['extra_accounting_roots']+=[str(x) for x in logs]
 admit(record);check_pins();b=binding(args.binding,args.binding_sha,args.protocol)
 keys=load(Path(__file__).parent/'atlas_m1_recovery_keys.py','recovery_preflight_metadata');p=keys.read_protocol(args.protocol);frozen=json.loads((VIEW/'economic-atlas/protocols/M1_PROSPECTIVE_V1.json').read_text());old,missing=keys.ancestral_records(p,frozen)
 auth=authority(args.protocol);entry={'state':'STARTED','key':KEY,'parent_pid':os.getpid(),'uid':os.getuid(),'authority':auth,'binding_SHA':args.binding_sha,'budget_record':record,'old334_SHA':p['ancestral_progress'],'known334':334,'missing26':missing,'scientific_pass':False,'continuous_old_guard_coverage':False,'no_retry':True}
 once(lease,entry);status=dict(entry);previous_alarm=signal.getsignal(signal.SIGALRM);previous_term=signal.getsignal(signal.SIGTERM)
 g=None;native=None
 try:
  g=load(VIEW/'economic-atlas/src/atlas_m1_executor.py','accepted_guard')
  receipt.mkdir(mode=0o700,exist_ok=False);atomic(receipt/'reservation.json',entry)
  signal.signal(signal.SIGTERM,g.stop_requested);signal.signal(signal.SIGALRM,g.stop_requested);signal.setitimer(signal.ITIMER_REAL,min(remaining(),max(0,TOTAL-RESERVE-elapsed(record))))
  for k in THREADS:os.environ[k]='1'
  native=g.NativeMac();admit(record,native,True);probe=g.resource_preflight(receipt/'native-preflight',native);admit(record,native,True)
  check_pins();binding(args.binding,args.binding_sha,args.protocol);keys.ancestral_records(p,frozen)
  desc={'key':KEY,'parent_pid':os.getpid(),'uid':os.getuid(),'phase':'FULL_NUMERICAL_RECOVERY','native_preflight_pass':True,'native_preflight_receipt':str(receipt/'native-preflight/resource-preflight.json'),'native_preflight_receipt_SHA':sha(receipt/'native-preflight/resource-preflight.json'),'authority':auth,'protocol':str(args.protocol.resolve()),'lease':str(lease),'out':str(out),'receipts':str(receipt),'budget_record':record}
  admit(record,native,True)
  dispatch=receipt/'worker-authority.json';once(dispatch,desc)
  # Accepted guard samples aggregate own parent+science tree and owns ONLY its Popen PG.
  g.output_bytes=lambda ignored:files_size(roots(record))
  limits=dict(g.LIMITS,wall=TOTAL-RESERVE,output=268435456-OUT_RESERVE,disk_sample=10)
  command=[sys.executable,str(Path(__file__).resolve()),'--worker',str(dispatch),'--dispatch-sha',sha(dispatch)]
  phase=g.run_phase(command,receipt,'recovery',started-historical,limits=limits,native=native);status['phase']=phase
  if native.descendants(os.getpid()):raise RuntimeError('owned descendants unresolved; nocompletion')
  status['owned_lifecycle_tree_empty']=True
  if phase['state']!='COMPLETE' or phase.get('exit_code')!=0:raise RuntimeError('partial/error recovery STOP never retry')
  admit(record,native);check_pins();keys.ancestral_records(p,frozen);binding(args.binding,args.binding_sha,args.protocol)
  validate=load(Path(__file__).parent/'atlas_m1_recovery_validate.py','final_validate');engine=load(Path(__file__).parent/'atlas_m1_evd_engine.py','final_engine');ids,_,_,_,inputsha=engine.load_panel(VIEW,frozen)
  admission=lambda:admit(record,native)
  validate.calibration(out/'calibration',auth,p,frozen,old,admission);validate.replay(out/'replay',auth,frozen,sha(out/'calibration/result.json'),ids,inputsha,admission)
  verify_whole(out,auth,p,frozen,admission)
  admit(record,native,True)
  status['state']='FULL_MIXED_RECOVERY_DESCRIPTIVE_VERIFIED_NEEDS_INDEPENDENT_AUDIT'
 except BaseException as exc:status.update(state='INCONCLUSIVE_RECOVERY_STOP_NO_RETRY',error=type(exc).__name__+': '+str(exc))
 finally:
  signal.setitimer(signal.ITIMER_REAL,0);signal.signal(signal.SIGALRM,previous_alarm);signal.signal(signal.SIGTERM,previous_term)
  try:check_pins();keys.ancestral_records(p,frozen);binding(args.binding,args.binding_sha,args.protocol)
  except BaseException as exc:status.update(state='INCONCLUSIVE_ANCESTRY_CHANGED',ancestry_error=repr(exc))
  status.update(inclusive_elapsed_seconds=elapsed(record),continuous_total_resource_pass=False,last_receipt_fsync_independently_timed=False,original_exit_code=None,scientific_pass=False,economic_identity_pass=False,source_actions_closed=0)
  if status['inclusive_elapsed_seconds']>TOTAL:status['state']='INCONCLUSIVE_ORIGINAL_TOTAL_EXCEEDED'
  atomic(terminal,status)
  if receipt.is_dir():atomic(receipt/'terminal.json',status)
  combined=files_size(roots(record));status.update(combined_output_bytes=combined,inclusive_elapsed_seconds=elapsed(record))
  if combined>268435456:status['state']='INCONCLUSIVE_COMBINED_OUTPUT_LIMIT'
  if status['inclusive_elapsed_seconds']>TOTAL:status['state']='INCONCLUSIVE_ORIGINAL_TOTAL_EXCEEDED'
  atomic(terminal,status)
  if receipt.is_dir():atomic(receipt/'terminal.json',status)
 if status['state'].startswith('INCONCLUSIVE'):raise SystemExit(1)
 return status

def verify_whole(out,auth,p,frozen,admission):
 token=lambda key:hashlib.sha256(json.dumps(key,separators=(',',':')).encode()).hexdigest()
 expected_keys=[['operational_preflight',1896,5,1,999999,20,d] for d in ('evr','evd')]
 for key in p['remaining_control_keys']:
  expected_keys.append(key);expected_keys.append([*key,'observed']);expected_keys.extend([*key,'null',frozen['shuffle_seed_base']+key[3]*100+j] for j in range(99))
 for t,m in enumerate([f'{y}-{j:02d}' for y in (2023,2024) for j in range(1,13)]):
  for k in (10,20,40):
   expected_keys.append(['replay',m,k,'observed']);expected_keys.extend(['replay',m,k,'null',frozen['shuffle_seed_base']+t*100+j] for j in range(99))
 if {x.name for x in (out/'journals').iterdir()}!={token(k) for k in expected_keys}:raise ValueError('full9828 immutable dispatch journal keys')
 for key in expected_keys:
  admission();folder=out/'journals'/token(key)
  if {x.name for x in folder.iterdir()}!={'STARTED.json','RESPONSE.json'}:raise ValueError('UNKNOWN/errorjournal preventsfullcompletion')
  if json.loads((folder/'STARTED.json').read_text()).get('key')!=key or json.loads((folder/'RESPONSE.json').read_text()).get('key')!=key:raise ValueError('journal exact dispatchkey')
 if {x.name for x in out.iterdir()}!={'calibration','replay','journals','numerical-preflight.json','result.json','manifest.json'}:raise ValueError('exact global top universe')
 preflight=json.loads((out/'numerical-preflight.json').read_text())
 if preflight.get('state')!='OPERATIONAL_NUMERICAL_PREFLIGHT_PASS_ONLY' or preflight.get('scientific_pass') is not False or set(preflight.get('solvers',{}))!={'evr','evd'}:raise ValueError('strict solverpreflight report')
 for driver,report in preflight['solvers'].items():
  if (report.get('driver'),report.get('n'),report.get('d'),report.get('seed'),report.get('R'),report.get('k'))!=(driver,1896,5,999999,1,20) or report.get('positive_scientific_qualification') is not False:raise ValueError('fixed preflight scope')
  for field in ('residual','orthogonality'):
   value=report.get(field)
   if isinstance(value,bool) or not isinstance(value,(float,int)) or not math.isfinite(value) or not 0<=value<=1e-10:raise ValueError('strict preflight residual')
 diff=preflight.get('eigenvalue_pair_max_abs_difference')
 if isinstance(diff,bool) or not isinstance(diff,(float,int)) or not math.isfinite(diff) or not 0<=diff<=1e-10:raise ValueError('solverpair invariant')
 # Compare durable dispatch responses with published scientific records.
 cal=json.loads((out/'calibration/result.json').read_text());rep=json.loads((out/'replay/result.json').read_text())
 def response(key):return json.loads((out/'journals'/token(key)/'RESPONSE.json').read_text())['value']
 validator=load(Path(__file__).parent/'atlas_m1_recovery_validate.py','journal_validator')
 def check_nulls(keybase,base,row,is_replay=False):
  gaps=[];invalid=[]
  for seed in range(base,base+99):
   admission();value=response([*keybase,'null',seed]);stats=value['stats'] if is_replay else value
   validator.statistics(stats);validator.graph_metadata(stats,keybase[2] if is_replay else keybase[1])
   if stats['raw_gap'] is None:invalid.append(seed)
   else:gaps.append(stats['raw_gap'])
  if gaps!=row['shuffle_raw_gaps'] or invalid!=row['shuffle_invalid_seeds']:raise ValueError('journal99null/result mismatch')
 for key in p['remaining_control_keys']:
  row=next(x for x in cal['results'][str(key[1])]['held'] if (x['R'],x['seed'])==(key[2],key[3]))
  if response(key)!=row:raise ValueError('remaining26 control response mismatch')
  observed=response([*key,'observed'])['stats']
  if any(row.get(k)!=v for k,v in observed.items()):raise ValueError('remaining observed/result mismatch')
  check_nulls(key,frozen['shuffle_seed_base']+key[3]*100,row)
 for t,month in enumerate([f'{y}-{j:02d}' for y in (2023,2024) for j in range(1,13)]):
  for k in (10,20,40):
   row=next(x for x in rep['monthly'] if (x['month'],x['kNN'])==(month,k));key=['replay',month,k]
   observed=response([*key,'observed'])['stats']
   if any(row.get(k)!=v for k,v in observed.items()):raise ValueError('replay observed/result mismatch')
   check_nulls(key,frozen['shuffle_seed_base']+t*100,row,True)
 for driver in ('evr','evd'):
  if response(['operational_preflight',1896,5,1,999999,20,driver])!=preflight['solvers'][driver]:raise ValueError('preflight journal/report mismatch')
 manifest=json.loads((out/'manifest.json').read_text())
 if manifest.get('authority')!=auth:raise ValueError('globalauthority')
 actual={str(x.relative_to(out)) for x in out.rglob('*') if x.is_file() and x!=out/'manifest.json'}
 if set(manifest['files_sha256'])!=actual:raise ValueError('global full file universe')
 for name,digest in manifest['files_sha256'].items():
  admission();path=Path(name)
  if path.is_absolute() or '..' in path.parts or sha(out/path)!=digest:raise ValueError('global artifactSHA')
 r=json.loads((out/'result.json').read_text())
 if r.get('state')!='FULL_MIXED_RECOVERY_REPLAY_DESCRIPTIVE' or r.get('authority')!=auth or any(r.get(k) is not False for k in ('scientific_pass','economic_identity_pass')) or r.get('source_actions_closed')!=0:raise ValueError('globalflags')
 if r.get('calibration_SHA')!=sha(out/'calibration/result.json') or r.get('replay_SHA')!=sha(out/'replay/result.json'):raise ValueError('globalresultlink')

def launchd_plist(python,launcher,protocol,binding,binding_sha,out,receipts):
 import plistlib
 return plistlib.dumps({'Label':'local.sergey.sberindex.m1.explicit-evd-recovery.v1','ProgramArguments':[str(python),str(launcher),'--protocol',str(protocol),'--binding',str(binding),'--binding-sha',binding_sha,'--outdir',str(out),'--receipt-dir',str(receipts)],'RunAtLoad':True,'KeepAlive':False,'StandardOutPath':str(Path(receipts).parent/'M1-recovery-launchd.stdout.log'),'StandardErrorPath':str(Path(receipts).parent/'M1-recovery-launchd.stderr.log'),'EnvironmentVariables':{**{k:'1' for k in THREADS},'PYTHONDONTWRITEBYTECODE':'1'}})

if __name__=='__main__':main()
