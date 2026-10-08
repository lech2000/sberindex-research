"""Private authorized persistent worker; exact old estimator and durable response-before-pipe."""
from pathlib import Path
import argparse,hashlib,importlib.util,json,math,os,sys,tempfile,contextlib,importlib.metadata
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parent));import r13_registry_core as core
ENV='R13_WORKER_SECRET'
def load(path,name):
 s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

def authorize(path):
 token=os.environ.pop(ENV,None)
 if token is None:raise ValueError('unauthorized worker before numerical imports')
 a=core.read(path)
 if a['parent_pid']!=os.getppid() or a['secret_SHA']!=hashlib.sha256(token.encode()).hexdigest() or a['worker_SHA']!=core.sha(__file__) or os.getpgrp()!=os.getpid():raise ValueError('worker scoped ownership/source mismatch')
 view=Path(a['view']);source=view/'shock-radar/src/r11_chronos2_full.py'
 if core.sha(source)!=a['original_runner_SHA']:raise ValueError('native known-parent source mismatch')
 b=load(source,'authorized_native')
 if os.getpid() not in b.own_child_pids(os.getppid()):raise ValueError('worker is not direct known-parent child')
 used=path.with_suffix('.consumed');fd=os.open(used,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd);path.unlink()
 return a

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--authority',type=Path,required=True);a=authorize(ap.parse_args().authority)
 for key in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS']:
  if os.environ.get(key)!='1':raise ValueError('CPU1 before imports')
 source=Path(a['view'])/'shock-radar/src/r8_prophet_batch.py'
 if core.sha(source)!=a['prophet_source_SHA']:raise ValueError('exact original Prophet source')
 versions={n:importlib.metadata.version(n) for n in ['prophet','cmdstanpy','pandas','numpy']}
 if versions!={'prophet':'1.4.0','cmdstanpy':'1.3.0','pandas':'3.0.6','numpy':'2.5.3'}:raise ValueError('exact estimator dependencies')
 wrapper=Path(a['view'])/'shock-radar/src/r11_prophet_worker.py'
 if core.sha(wrapper)!='7ca3c5df48dca2ee63aefb1ca07a8f43e3acb76c5d96e1babddd1c5f0520fea6':raise ValueError('original estimator wrapper SHA')
 original=load(wrapper,'original_worker');model=load(source,'frozen_estimator')
 print(json.dumps({'ready':True,'versions':versions,'source_sha256':core.sha(source)}),flush=True)
 for line in sys.stdin:
  wire=json.loads(line);attempt=Path(wire['journal']).resolve()
  if attempt.parent!=Path(a['out']).resolve()/'attempts':raise ValueError('attempt outside authorized namespace')
  q=core.read(attempt/'request.json')
  if wire['request'].get('seed')!=20260927:raise ValueError('seed unchanged')
  if q['fingerprint']!=a['fingerprint'] or q['model']!='prophet' or q['request']['fit']!=wire['request']:raise ValueError('exact durable fit request mismatch')
  if (attempt/'response.json').exists():raise ValueError('successful response must be reused without worker refit')
  native=attempt/'native';native.mkdir(exist_ok=False);tempfile.tempdir=str(native);os.environ['TMPDIR']=str(native)
  try:
   with contextlib.redirect_stdout(sys.stderr):values=original.fit(wire['request'],model.prophet_fit_predict)
   gid=next(iter(q['target_dates']));r=core.response(attempt,q,values={gid:values})
  except Exception as exc:r=core.response(attempt,q,error=type(exc).__name__+': '+str(exc))
  core.atomic(attempt/'native-manifest.json',{'request_SHA':core.sha(attempt/'request.json'),'source_SHA':core.sha(source),'native_files_SHA':{str(p.relative_to(attempt)):core.sha(p) for p in native.rglob('*') if p.is_file()}})
  print(json.dumps({'ok':r['ok'],'response_SHA':core.sha(attempt/'response.json'),'predictions':values if r['ok'] else None,'error':r['error']},allow_nan=False),flush=True)
if __name__=='__main__':main()
