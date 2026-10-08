"""Bounded foreground M4 launcher using accepted native operational guard."""
from pathlib import Path
import argparse,hashlib,importlib.util,json,os,shutil,signal,sys,time
GUARD_SHA='04b89b778bd3f1f3e5beb83edc0786c39086b249f9b74658219922958c4db93c'

def load(path,name):
 spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--repo',type=Path,required=True);ap.add_argument('--m1-calibration',type=Path,required=True);ap.add_argument('--outdir',type=Path,required=True);ap.add_argument('--wall-seconds',type=int,required=True,help='Root approved operational cap after exact-n preflight; not a scientific parameter');args=ap.parse_args()
 if args.wall_seconds<=0:raise ValueError('positive explicit operational wall cap required')
 source=args.repo/'economic-atlas/src/atlas_m4_channels.py';protocol=args.repo/'economic-atlas/protocols/M4_PROSPECTIVE_V1.json';guard=args.repo/'economic-atlas/src/atlas_m1_executor.py'
 if hashlib.sha256(guard.read_bytes()).hexdigest()!=GUARD_SHA:raise ValueError('exact accepted native executor required')
 for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS'):os.environ[k]='1'
 os.environ['PYTHONDONTWRITEBYTECODE']='1';sys.dont_write_bytecode=True
 g=load(guard,'native_executor');m=load(source,'channels')
 if m.sha(protocol)!=m.PROTOCOL_SHA:raise ValueError('M4 prospective protocol mismatch')
 dependency=m.check_dependency(args.m1_calibration);m.load_m1(args.repo)
 if shutil.disk_usage(args.outdir.parent).free<1073741824:raise RuntimeError('1GiB free required')
 args.outdir.mkdir(exist_ok=False);signal.signal(signal.SIGTERM,g.stop_requested);started=time.monotonic()
 receipt={'state':'STARTED','started_at':g.now(),'M1_dependency':dependency,'M4_source_sha256':m.sha(source),'M4_protocol_sha256':m.sha(protocol),'executor_sha256':m.sha(__file__),'native_guard_sha256':GUARD_SHA,'scientific_economic_identity_pass':False,'no_resume_or_retry':True}
 limits=dict(g.LIMITS);limits['wall']=args.wall_seconds;receipt['limits']=limits
 g.atomic(args.outdir/'progress.json',receipt)
 try:
  receipt['preflight']=g.resource_preflight(args.outdir/'native-preflight')
  command=[sys.executable,str(source),'--repo',str(args.repo),'--protocol',str(protocol),'--m1-calibration',str(args.m1_calibration),'--outdir',str(args.outdir/'full-bank-v1')]
  receipt['phase']=g.run_phase(command,args.outdir,'M4-full-bank',started,limits)
  if receipt['phase']['state']!='COMPLETE':raise RuntimeError('fullbank interrupted/inconclusive; preserve artifacts')
  receipt['M4_result']=json.loads((args.outdir/'full-bank-v1/result.json').read_text());receipt['state']='COMPUTED_FULL_BANK_NEEDS_INDEPENDENT_SCIENTIFIC_AUDIT'
 except BaseException as exc:receipt.update(state='INCONCLUSIVE_STOPPED',error=type(exc).__name__+': '+str(exc))
 finally:
  receipt.update(finished_at=g.now(),elapsed_seconds=time.monotonic()-started)
  receipt['all_output_sha256_including_failures']=g.manifest(args.outdir)
  g.atomic(args.outdir/'terminal.json',receipt);g.atomic(args.outdir/'progress.json',receipt)
 print(json.dumps({'state':receipt['state'],'receipt':str(args.outdir/'terminal.json'),'action_closed':False}))
 if receipt['state']!='COMPUTED_FULL_BANK_NEEDS_INDEPENDENT_SCIENTIFIC_AUDIT':raise SystemExit(1)
if __name__=='__main__':main()
