"""Prospective recovery source/key layer. NO CLI, executor or launch authority.
This library cannot provide the missing native/global one-use lifecycle guard.
A separately adopted foreground executor must call admission before each dispatch.
Old334 remain byte immutable; this namespace has no resume/retry operation.
"""
import copy,hashlib,json,math,os
from pathlib import Path
PROTOCOL_SHA='516ca1cf068dd420ddbd560a8329c27ca9ab4cc9f582375a770e02bc93ff302e'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read_protocol(path):
 if sha(path)!=PROTOCOL_SHA:raise ValueError('recovery amendment changed')
 return json.loads(Path(path).read_text())
def atomic_once(path,value):
 # One immutable journal file. Existing STARTED is UNKNOWN, never a retry permit.
 path=Path(path);fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
 with os.fdopen(fd,'w') as f:json.dump(value,f,allow_nan=False,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
 fd=os.open(path.parent,os.O_RDONLY)
 try:os.fsync(fd)
 finally:os.close(fd)
def token(key):return hashlib.sha256(json.dumps(key,separators=(',',':')).encode()).hexdigest()
class Journal:
 def __init__(self,out,authority):
  self.out=Path(out);self.out.mkdir(parents=False,exist_ok=False)
  self.authority=authority
 def dispatch(self,key,function,admission):
  admission() # accepted global guard must fail closed before STARTED/science.
  folder=self.out/token(key);folder.mkdir(exist_ok=False)
  atomic_once(folder/'STARTED.json',{'key':key,'authority':self.authority,'state':'STARTED_UNKNOWN_UNTIL_RESPONSE','automatic_retry':False})
  try:value=function()
  except BaseException as exc:
   atomic_once(folder/'ERROR.json',{'key':key,'error':type(exc).__name__+': '+str(exc),'state':'STOP_NO_RETRY'});raise
  atomic_once(folder/'RESPONSE.json',{'key':key,'value':value,'state':'RESPONSE_RECORDED'})
  admission();return value

def ancestral_records(protocol,frozen):
 """Exact saved progress receipts only; no synthesis of missing row/quality."""
 output={};known=0
 for k in (10,20,40):
  ref=protocol['ancestral_progress'][str(k)];path=Path(ref['file'])
  if sha(path)!=ref['SHA']:raise ValueError('old progress SHA changed')
  j=json.loads(path.read_text());cal=j['calibration'];held=j['held']
  expectedcal=[(R,s) for R in (1,3,4,5) for s in frozen['calibration_seeds']]
  expectedheld=[(R,s) for R in (1,3,4,5) for s in frozen['validation_seeds']]
  if [(r['R'],r['seed']) for r in cal]!=expectedcal:raise ValueError('exact original120cal required')
  if [(r['R'],r['seed']) for r in held]!=expectedheld[:ref['held']] or len(held)!=ref['held']:raise ValueError('exact saved held prefix required')
  if j['fit']!=ref['fit'] or j['fit']['sig_star'] is not None:raise ValueError('ancestral negative fits cannot retune')
  if any(len(r['shuffle_raw_gaps'])+len(r['shuffle_invalid_seeds'])!=99 for r in held):raise ValueError('old null accounting corrupted')
  output[str(k)]={'n':1896,'d':5,'k':k,'calibration':copy.deepcopy(cal),'held':copy.deepcopy(held),'fit':copy.deepcopy(j['fit']),'method_quality':'FAIL_OR_INCONCLUSIVE_FIXED_CONTROLS'}
  known+=len(cal)+len(held)
 if known!=334:raise ValueError('full known334 required')
 missing=[['held',k,R,s] for k in (10,20,40) for R,s in [(R,s) for R in (1,3,4,5) for s in frozen['validation_seeds']][len(output[str(k)]['held']):]]
 if missing!=protocol['remaining_control_keys'] or len(missing)!=26:raise ValueError('exact remaining26 required; no selected subset')
 return output,missing

def remaining26(engine,journal,protocol,frozen,admission):
 """Actual methods only future accepted executor; no native/lifecycle implemented here."""
 import numpy as np
 results,missing=ancestral_records(protocol,frozen)
 for key in missing:
  _,k,R,seed=key
  def control():
   x=engine.world(1896,5,R,seed)
   def observed():
    stats,vals,vec=engine.spectrum(engine.graph(x,k),frozen['tau_lambda'])
    return {'stats':engine.clean(stats),'driver':'evd','full_eigenvalues_SHA':hashlib.sha256(np.asarray(vals,dtype='<f8').tobytes()).hexdigest() if vals is not None else None,'full_vectors_SHA':hashlib.sha256(np.asarray(vec,dtype='<f8').tobytes()).hexdigest() if vec is not None else None}
   r=journal.dispatch([*key,'observed'],observed,admission)['stats']
   gaps=[];invalid=[];base=frozen['shuffle_seed_base']+seed*100
   for ns in range(base,base+99):
    def null():
     rng=np.random.default_rng(ns);shuffled=np.column_stack([rng.permutation(x[:,j]) for j in range(5)])
     stats,_,_=engine.spectrum(engine.graph(shuffled,k),frozen['tau_lambda'])
     return engine.clean(stats)
    stats=journal.dispatch([*key,'null',ns],null,admission)
    if stats['raw_gap'] is None:invalid.append(ns)
    else:gaps.append(stats['raw_gap'])
   return {'R':R,'seed':seed,**engine.clean(r),'verdict':engine.verdict(r,results[str(k)]['fit']['sig_star'],np.asarray(gaps),invalid),'shuffle_raw_gaps':gaps,'shuffle_invalid_seeds':invalid,'shuffle_p95':float(np.quantile(gaps,.95)) if gaps else None}
  row=journal.dispatch(key,control,admission);results[str(k)]['held'].append(row)
 if sum(len(r['calibration'])+len(r['held']) for r in results.values())!=360:raise ValueError('never publish partial360')
 for k,c in results.items():
  neg=[r for r in c['held'] if r['R']==1];pos=[r for r in c['held'] if r['R']>1]
  c['negative_false_structured_fraction']=sum(r['verdict']=='REAL_GAP' for r in neg)/20
  c['positive_exact_R_fraction']=sum(r['verdict']=='REAL_GAP' and r['m']==r['R'] for r in pos)/60
 return {'n':1896,'d':5,'results':results,'settings_sha256':hashlib.sha256(json.dumps(frozen,sort_keys=True).encode()).hexdigest(),'base_source_SHA':protocol['base_source_SHA'],'amendment_protocol_SHA':PROTOCOL_SHA,'actual_recovery_source_SHA':sha(__file__),'actual_evd_engine_SHA':sha(engine.__file__),'numerical_driver_new':'evd','mixed_ancestral_numerics':True,'record_origin':{'old334':protocol['ancestral_progress'],'new26':missing},'economic_identity_pass':False,'scientific_pass':False}

if __name__=='__main__':raise SystemExit('No executable recovery until separate accepted native/global one-use executor + strict publication verifier')

def journalled_replay(engine,journal,repo,frozen,calibration,out,admission):
 """Hook exactly72*(observed+99null) original calls, not labels/metrics semantics."""
 import numpy as np
 months=[f'{y}-{m:02d}' for y in (2023,2024) for m in range(1,13)]
 old=engine.spectrum;index=0
 def hooked(W,tau=.95):
  nonlocal index
  row,offset=divmod(index,100)
  if row>=72:raise ValueError('unexpected extra replay spectrum dispatch')
  t,kindex=divmod(row,3);k=(10,20,40)[kindex];month=months[t]
  key=['replay',month,k,'observed'] if offset==0 else ['replay',month,k,'null',frozen['shuffle_seed_base']+t*100+offset-1]
  holder=[]
  def call():
   result=old(W,tau);holder.append(result);stats,vals,vec=result
   return {'stats':engine.clean(stats),'full_eigenvalues_SHA':hashlib.sha256(np.asarray(vals,dtype='<f8').tobytes()).hexdigest() if vals is not None else None,'full_vectors_SHA':hashlib.sha256(np.asarray(vec,dtype='<f8').tobytes()).hexdigest() if vec is not None else None,'driver':'evd'}
  journal.dispatch(key,call,admission);index+=1;return holder[0]
 engine.spectrum=hooked
 try:result=engine.replay(repo,frozen,calibration,out)
 finally:engine.spectrum=old
 if index!=7200 or len(result['monthly'])!=72:raise ValueError('all72 observed+99null required; no subset')
 result.update(scientific_pass=False,numerical_driver='evd',amendment_protocol_SHA=PROTOCOL_SHA)
 return result


def solver_preflight(engine,journal,frozen,admission):
 """Fixed same-size solver comparison, operational only; no scientific fitting."""
 import numpy as np
 x=engine.world(1896,5,1,999999);W=engine.graph(x,20)
 degree=W.sum(axis=1);normal=W/np.sqrt(np.maximum(degree,1)[:,None]*np.maximum(degree,1)[None,:])
 if W.shape!=(1896,1896) or not np.allclose(W,W.T) or np.diag(W).any() or np.count_nonzero(np.triu(W,1))!=1896*20//2:raise ValueError('literal preflight graph invariants')
 norms={};values={}
 for driver in ('evr','evd'):
  def solve():
   vals,vec=engine.eigh(normal,driver=driver,check_finite=False)
   if vals.shape!=(1896,) or vec.shape!=(1896,1896) or not np.isfinite(vals).all() or not np.isfinite(vec).all():raise ValueError('full finite eigenspectrum/vectors required')
   residual=float(np.linalg.norm(normal@vec-vec*vals[None,:],'fro')/max(np.linalg.norm(normal,'fro'),1e-300))
   orthogonality=float(np.linalg.norm(vec.T@vec-np.eye(1896),'fro')/np.sqrt(1896))
   if residual>1e-10 or orthogonality>1e-10 or not np.isclose(vals[-1],1.,rtol=0,atol=1e-10) or np.any(np.diff(vals)<0):raise ValueError('preflight residual/orthogonality/lambda/order failed')
   values[driver]=vals
   return {'driver':driver,'n':1896,'d':5,'seed':999999,'R':1,'k':20,'graph_SHA':hashlib.sha256(np.asarray(W,dtype='<f8').tobytes()).hexdigest(),'isolates':int(np.count_nonzero(degree==0)),'zero_degree_extension':'degree1 ONLY operational solver probe, science abstention unchanged','residual':residual,'orthogonality':orthogonality,'eigenvalues_SHA':hashlib.sha256(np.asarray(vals,dtype='<f8').tobytes()).hexdigest(),'positive_scientific_qualification':False}
  norms[driver]=journal.dispatch(['operational_preflight',1896,5,1,999999,20,driver],solve,admission)
 if not np.allclose(values['evr'],values['evd'],rtol=0,atol=1e-10):raise ValueError('fixed solver-pair eigenvalue invariance failed')
 return {'state':'OPERATIONAL_NUMERICAL_PREFLIGHT_PASS_ONLY','solvers':norms,'eigenvalue_pair_max_abs_difference':float(np.max(np.abs(values['evr']-values['evd']))),'scientific_pass':False}
