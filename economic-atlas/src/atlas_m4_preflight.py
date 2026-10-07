"""One fixed exact-n M4 cost measurement; never auto launches the bank."""
from pathlib import Path
import argparse,hashlib,importlib.util,json,os,secrets,shutil,signal,sys,time
sys.dont_write_bytecode=True
GUARD_SHA='04b89b778bd3f1f3e5beb83edc0786c39086b249f9b74658219922958c4db93c'
PREFLIGHT_SHA='eb772e7ff9bbf33048d5ae366024e98e591e05f5a744c04415848088e0863e1b'
CHANNEL_SOURCE_SHA='86553f9d4627fbdccd51ad3f1c6a6335cb1a4b22b6401150ae4a21dd606a1fd9'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def load(p,name):
 spec=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
def setup(repo):
 source=repo/'economic-atlas/src/atlas_m4_channels.py';guard=repo/'economic-atlas/src/atlas_m1_executor.py';protocol=repo/'economic-atlas/protocols/M4_OPERATIONAL_PREFLIGHT_V1.json'
 if sha(source)!=CHANNEL_SOURCE_SHA or sha(guard)!=GUARD_SHA or sha(protocol)!=PREFLIGHT_SHA:raise ValueError('exact adopted operational source/protocol required')
 m=load(source,'fixed_m4');g=load(guard,'fixed_guard');p=json.loads(protocol.read_text());m1=m.load_m1(repo)
 if sha(repo/'economic-atlas/protocols/M4_PROSPECTIVE_V1.json')!=m.PROTOCOL_SHA or sha(repo/'economic-atlas/protocols/M4_DEPENDENCY_AMENDMENT_V1.json')!=m.AMENDMENT_SHA:raise ValueError('fixed scientific protocol/amendment required')
 return m,g,p,m1

DISPATCH_ENV='ATLAS_M4_PREFLIGHT_DISPATCH'
def create_authority(out,repo,started,probe):
 # Called only by fresh parent after successful native child/grandchild probe.
 if probe.get('state')!='PASS':raise ValueError('native preflight PASS required for dispatch')
 token=secrets.token_hex(32);authority=out/'dispatch-authority.json'
 data={'parent_pid':os.getpid(),'repo':str(repo.resolve()),'outdir':str((out/'measurement-v1').resolve()),
       'executor_sha256':sha(__file__),'source_sha256':CHANNEL_SOURCE_SHA,'protocol_sha256':PREFLIGHT_SHA,
       'secret_sha256':hashlib.sha256(token.encode()).hexdigest(),'deadline_monotonic':started+600,
       'resource_limits':{'wall':600,'rss':1073741824,'free':1073741824,'output':268435456},
       'native_preflight_sha256':sha(out/'native-preflight/resource-preflight.json')}
 fd=os.open(authority,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
 with os.fdopen(fd,'w') as f:json.dump(data,f);f.flush();os.fsync(f.fileno())
 os.environ[DISPATCH_ENV]=token
 return authority

def consume_authority(args):
 # All checks are stdlib/native-only and precede setup/numerical module imports.
 authority=args.dispatch_authority;token=os.environ.pop(DISPATCH_ENV,None)
 if authority is None or not token:raise ValueError('unauthorized internal worker dispatch')
 authority=authority.resolve();out=args.outdir.resolve();repo=args.repo.resolve()
 if authority.name!='dispatch-authority.json' or authority.parent!=out.parent or out.name!='measurement-v1' or out.exists():raise ValueError('dispatch output/fresh binding mismatch')
 data=json.loads(authority.read_text())
 expected={'parent_pid':os.getppid(),'repo':str(repo),'outdir':str(out),'executor_sha256':sha(__file__),'source_sha256':CHANNEL_SOURCE_SHA,'protocol_sha256':PREFLIGHT_SHA,
           'secret_sha256':hashlib.sha256(token.encode()).hexdigest(),'resource_limits':{'wall':600,'rss':1073741824,'free':1073741824,'output':268435456}}
 if any(data.get(k)!=v for k,v in expected.items()) or time.monotonic()>=data.get('deadline_monotonic',0):raise ValueError('dispatch parent/source/args/limits/deadline binding mismatch')
 proof=out.parent/'native-preflight/resource-preflight.json'
 if sha(proof)!=data['native_preflight_sha256'] or json.loads(proof.read_text()).get('state')!='PASS':raise ValueError('dispatch native proof mismatch')
 guard=repo/'economic-atlas/src/atlas_m1_executor.py'
 if sha(guard)!=GUARD_SHA:raise ValueError('dispatch guard source mismatch')
 g=load(guard,'dispatch_native_guard')
 if os.getpgrp()!=os.getpid() or os.getpid() not in g.NativeMac().children(os.getppid()):raise ValueError('dispatch must be own isolated native-known child')
 consumed=authority.with_name('dispatch-consumed.json')
 fd=os.open(consumed,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
 with os.fdopen(fd,'w') as f:json.dump({**data,'owned_worker_pid':os.getpid(),'owned_pgid':os.getpgrp(),'consumed':True},f);f.flush();os.fsync(f.fileno())
 authority.unlink()
 return data

def worker(m,g,p,m1,out):
 out.mkdir(exist_ok=False);native=g.NativeMac();started=time.monotonic();records=[];r={'state':'STARTED','operational_only':True,'scientific_pass':False,'protocol_sha256':PREFLIGHT_SHA,'source_sha256':CHANNEL_SOURCE_SHA}
 try:
  t=time.monotonic();data=m.world(p['n'],p['R'],p['world'],p['seed']);W=m.graph(data,p['channel'],p['k']);r['graph_seconds']=time.monotonic()-t;r['edges']=int(W.sum()/2)
  t=time.monotonic();original,vals,vectors=m1.spectrum(W,.95);r['original_spectrum_seconds']=time.monotonic()-t;r['original_meta']=original;r['original_full_eigenvalues_count']=None if vals is None else len(vals);r['original_eigenvectors_shape']=None if vectors is None else list(vectors.shape);r['RSS_after_original_bytes']=native.rss(os.getpid());del vals,vectors
  m.atomic(out/'measurement.json',r)
  for seed in range(p['null_seeds_start'],p['null_seeds_start']+p['null_replicates']):
   t=time.monotonic();null,meta=m.degree_null(W,seed);swap_seconds=time.monotonic()-t
   t=time.monotonic();nr,nvals,nvectors=m1.spectrum(null,.95);eigen_seconds=time.monotonic()-t
   records.append({**meta,'swap_seconds':swap_seconds,'spectrum_seconds':eigen_seconds,'spectrum_status':nr['status'],'m':nr['m'],'raw_gap':nr['raw_gap'],'eigenvalues_count':None if nvals is None else len(nvals),'eigenvectors_shape':None if nvectors is None else list(nvectors.shape),'self_RSS_bytes':native.rss(os.getpid())});del null,nvals,nvectors
   r.update(completed_nulls=len(records),null_records=records,elapsed_seconds=time.monotonic()-started);m.atomic(out/'measurement.json',r)
  r['measured_cost_totals']={'swap_seconds':sum(x['swap_seconds'] for x in records),'null_spectrum_seconds':sum(x['spectrum_seconds'] for x in records),'successful_swaps':sum(x['successful_swaps'] for x in records),'attempts':sum(x['attempts'] for x in records)}
  r['full_bank_fixed_workload']={'spectra_upper':162360,'successful_swap_targets':5557167000,'attempt_cap':55571670000,'cost_budget_status':'REQUIRES_ROOT_REVIEW_NOT_A_BOUND_FROM_ONE_REPRESENTATIVE'}
  r['state']='COMPLETE_OPERATIONAL_MEASUREMENT';r['null_inconclusive_count']=sum(not x['complete'] or x['raw_gap'] is None for x in records)
 except BaseException as exc:r.update(state='INCONCLUSIVE_OPERATIONAL_EXCEPTION',error=type(exc).__name__+': '+str(exc));raise
 finally:r.update(elapsed_seconds=time.monotonic()-started,null_records=records,completed_nulls=len(records));m.atomic(out/'measurement.json',r)

def main():
 started=time.monotonic()
 ap=argparse.ArgumentParser();ap.add_argument('--repo',type=Path,required=True);ap.add_argument('--outdir',type=Path,required=True);ap.add_argument('--worker',action='store_true',help=argparse.SUPPRESS);ap.add_argument('--dispatch-authority',type=Path,help=argparse.SUPPRESS);args=ap.parse_args()
 if args.worker:consume_authority(args)
 elif args.dispatch_authority is not None or os.environ.get(DISPATCH_ENV):raise ValueError('internal dispatch authority is worker-only')
 for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS'):
  if os.environ.get(key)!='1':raise ValueError('CPU1 thread environment required before imports')
 m,g,p,m1=setup(args.repo)
 if args.worker:return worker(m,g,p,m1,args.outdir)
 if shutil.disk_usage(args.outdir.parent).free<1073741824:raise RuntimeError('1GiB free required')
 args.outdir.mkdir(exist_ok=False);signal.signal(signal.SIGTERM,g.stop_requested);r={'state':'STARTED','operational_only':True,'scientific_pass':False,'fullbank_launches':0,'protocol_sha256':PREFLIGHT_SHA,'source_sha256':CHANNEL_SOURCE_SHA,'executor_sha256':sha(__file__),'no_restart':True}
 limits=dict(g.LIMITS);limits['wall']=p['resource_limits']['wall_seconds'];r['limits']=limits;g.atomic(args.outdir/'progress.json',r)
 try:
  r['native_preflight']=g.resource_preflight(args.outdir/'native-preflight')
  authority=create_authority(args.outdir,args.repo,started,r['native_preflight'])
  command=[sys.executable,str(Path(__file__).resolve()),'--repo',str(args.repo.resolve()),'--outdir',str((args.outdir/'measurement-v1').resolve()),'--worker','--dispatch-authority',str(authority.resolve())]
  r['phase']=g.run_phase(command,args.outdir,'M4-cost-preflight',started,limits)
  r['state']='COMPLETE_OPERATIONAL_NEEDS_COST_REVIEW' if r['phase']['state']=='COMPLETE' else 'INCONCLUSIVE_OPERATIONAL_STOPPED'
 except BaseException as exc:r.update(state='INCONCLUSIVE_OPERATIONAL_EXCEPTION',error=type(exc).__name__+': '+str(exc))
 finally:
  os.environ.pop(DISPATCH_ENV,None)
  r.update(elapsed_seconds=time.monotonic()-started,finished_at=g.now());r['all_output_sha256_including_failures']=g.manifest(args.outdir);g.atomic(args.outdir/'terminal.json',r);g.atomic(args.outdir/'progress.json',r)
 print(json.dumps({'state':r['state'],'receipt':str(args.outdir/'terminal.json'),'scientific_pass':False,'fullbank_launches':0}))
 if r['state']!='COMPLETE_OPERATIONAL_NEEDS_COST_REVIEW':raise SystemExit(1)
if __name__=='__main__':main()
