"""ONE prospective original-generator suite; numerical imports only after authority."""
import time
ENTRY=time.monotonic()
import argparse,hashlib,importlib.util,json,os,pathlib,sys,gzip,math,contextlib,functools
P=pathlib.Path

def sha(p):return hashlib.sha256(P(p).read_bytes()).hexdigest()
def sync_parent(p):
 fd=os.open(P(p).parent,os.O_RDONLY)
 try:os.fsync(fd)
 finally:os.close(fd)

def once(p,v):
 with P(p).open('x') as f:json.dump(v,f,allow_nan=False);f.write('\n');f.flush();os.fsync(f.fileno())
 sync_parent(p)
def consume(auth,out,repo):
 a=json.loads(P(auth).read_text());secret=os.environ.pop('A63_PRIVATE_AUTH','')
 if not secret or hashlib.sha256(secret.encode()).hexdigest()!=a['secret_SHA']:raise ValueError('parent one-use authority')
 if a['parent_pid']!=os.getppid() or os.getsid(0)!=os.getpid() or a['out']!=str(out.resolve()) or a['repo']!=str(repo.resolve()) or a['worker_SHA']!=sha(__file__):raise ValueError('scoped direct owned-session dispatch')
 if sha(repo/'economic-atlas/protocols/A63_FULL_ONE_USE_OPERATIONAL_V1.json')!=a['protocol_SHA']:raise ValueError('worker exact frozen operational protocol')
 for name,h in a['pins'].items():
  if sha(repo/name)!=h:raise ValueError('pinned source before numerical import')
 once(P(auth).with_suffix('.consumed.json'),{'worker_pid':os.getpid(),'parent_pid':os.getppid(),'authority_SHA':sha(auth),'automatic_retry':False})
 return a

def result_structure(value):
 if hasattr(value,'tobytes') and hasattr(value,'shape'):
  if str(value.dtype)=='object':
   return {'semantic_JSON_SHA':hashlib.sha256(json.dumps(value.tolist(),sort_keys=True,allow_nan=False).encode()).hexdigest(),'shape':list(value.shape),'dtype':'object','note':'semantic values, never pointer bytes'}
  return {'tensor_SHA':hashlib.sha256(value.tobytes(order='C')).hexdigest(),'shape':list(value.shape),'dtype':str(value.dtype)}
 if isinstance(value,dict):return {str(k):result_structure(v) for k,v in value.items()}
 if isinstance(value,(list,tuple)):return [result_structure(v) for v in value]
 if isinstance(value,float) and not math.isfinite(value):return {'nonfinite_explicit':str(value)}
 if value is None or isinstance(value,(str,int,float,bool)):return value
 raise TypeError('unknown result structure; no unrecorded stage commit')

def job(out,key,request,fn):
 ident=hashlib.sha256(key.encode()).hexdigest();start=out/'journals'/(ident+'.STARTED.json');response=out/'journals'/(ident+'.RESPONSE.json')
 once(start,{'key':key,'request':request,'started_monotonic':time.monotonic()})
 value=fn()
 once(response,{'key':key,'request_SHA':sha(start),'finished_monotonic':time.monotonic(),'state':'COMPLETE','result_structure_SHA':hashlib.sha256(json.dumps(result_structure(value),sort_keys=True,allow_nan=False).encode()).hexdigest(),'result_structure':result_structure(value)})
 return value

def save_lines(p,rows):
 # Fixed mtime; no dropped assignment/region or event rows.
 with P(p).open('xb') as raw:
  with gzip.GzipFile(fileobj=raw,mode='wb',mtime=0) as f:
   for row in rows:f.write((json.dumps(row,allow_nan=False)+'\n').encode())

@contextlib.contextmanager
def observe_fits(out,context,KMeans):
 """Observe the real API; forward identical estimator, X, args and kwargs.

 Original frozen selection/tracker functions and numerical parameters are
 unchanged. The wrapper records EVERY underlying fit_predict, not just the
 seven-fit select_k_for_month helper. Restore the class method on any exit.
 """
 original=KMeans.fit_predict
 @functools.wraps(original)
 def observed(estimator,X,*args,**kwargs):
  if context.get('stage') is None:raise RuntimeError('fit outside declared journal context')
  index=context['fit_index'];context['fit_index']+=1
  key='native-fit/'+context['stage']+'/'+str(index)
  request={'stage':context['stage'],'ordinal':index,'estimator':'sklearn.cluster.KMeans','params':result_structure(estimator.get_params(deep=False)),'input':result_structure(X),'positional_args':result_structure(args),'keyword_args':result_structure(kwargs)}
  def actual():
   labels=original(estimator,X,*args,**kwargs)
   return labels,estimator.cluster_centers_
  labels,centers=job(out,key,request,actual)
  return labels
 KMeans.fit_predict=observed
 try:yield
 finally:KMeans.fit_predict=original

def fit_stage(context,stage,fn,expected):
 context.update(stage=stage,fit_index=0)
 try:
  value=fn()
  if context['fit_index']!=expected:raise ValueError('exact native fit call count mismatch; no retry')
  return value
 finally:context['stage']=None

def intervals(spec,runs,controls,np):
 # Five independent seed blocks, paired same draws across all six cells.
 draws=np.random.default_rng(spec['uncertainty']['bootstrap_seed']).integers(0,5,size=(10000,5))
 rows=[]
 for mode in spec['modes']:
  for factor in spec['margin_factors']:
   block=[]
   for seed in spec['seeds']:
    selected=[r for r in runs if r['seed']==seed and r['mode']==mode and r['margin_factor']==factor]
    c={k:sum(r['recognition'][k] for r in selected) for k in selected[0]['recognition']};e={k:sum(r['events'][k] for r in selected) for k in ['tp','fp','fn']}
    block.append((c,e))
   nums={'recognition_FDR':[c['fp_known']+c['fp_unknown'] for c,e in block],'recognition_FNR':[c['fn'] for c,e in block],'event_FDR':[e['fp'] for c,e in block],'event_FNR':[e['fn'] for c,e in block],'coverage':[c['decided_clusters'] for c,e in block]}
   dens={'recognition_FDR':[c['tp']+c['fp_known']+c['fp_unknown'] for c,e in block],'recognition_FNR':[c['tp']+c['fn'] for c,e in block],'event_FDR':[e['tp']+e['fp'] for c,e in block],'event_FNR':[e['tp']+e['fn'] for c,e in block],'coverage':[c['cluster_decisions'] for c,e in block]}
   ci={}
   for metric in nums:
    n=np.asarray(nums[metric])[draws].sum(axis=1);d=np.asarray(dens[metric])[draws].sum(axis=1);v=n[d>0]/d[d>0]
    ci[metric]={'lo':float(np.quantile(v,.025)) if len(v) else None,'hi':float(np.quantile(v,.975)) if len(v) else None,'valid_draws':len(v)}
   rows.append(dict(mode=mode,margin_factor=factor,intervals=ci))
 return rows

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--authority',type=P,required=True);ap.add_argument('--repo',type=P,required=True);ap.add_argument('--out',type=P,required=True);args=ap.parse_args();out=args.out.resolve();repo=args.repo.resolve();authority=consume(args.authority,out,repo)
 spec=json.loads((repo/'economic-atlas/protocols/A63_NEW_PROSPECTIVE_SYNTHETIC_V1.json').read_text())
 import numpy as np
 sys.path.insert(0,str(repo/'economic-atlas/src'))
 import a6_frozen_controls as controls
 import a6_identities as atlas
 import a63_prospective_acceptance as evaluation
 from sklearn.cluster import KMeans
 context={'stage':None,'fit_index':0}
 for sub in ['journals','inputs','histories','configs']:
  folder=out/sub;folder.mkdir(mode=0o700);sync_parent(folder)
 runs=[];months=[];all_events=[];worldproof=[]
 for seed in spec['seeds']:
  for world in spec['worlds']:
   request={'seed':seed,'world':world,'generator_SHA':authority['pins']['economic-atlas/src/a6_frozen_controls.py']}
   z,truth,expected=job(out,f'world/{seed}/{world}',request,lambda:controls.world(world,seed))
   cube=out/'inputs'/f'{seed}-{world}.npz';np.savez_compressed(cube,z=z,truth=np.asarray(truth,dtype=str));worldproof.append(dict(request,NPZ_SHA=sha(cube),tensor_SHA=hashlib.sha256(z.tobytes(order='C')).hexdigest(),truth_events=expected))
   for mode in spec['modes']:
    labels=[];centers=[];kgrid=[]
    if mode=='oracle':labels,centers,kgrid=controls.labels_for(z,truth,seed,mode,atlas)
    else:
     for m in range(24):
      req=dict(request,mode=mode,month_index=m,tensor_SHA=hashlib.sha256(z[:,m,:].tobytes()).hexdigest())
      with observe_fits(out,context,KMeans):
       k,rows,note=job(out,f'select/{seed}/{world}/{m}',req,lambda:fit_stage(context,f'select/{seed}/{world}/{m}',lambda:atlas.select_k_for_month(z[:,m,:],m,seed),7))
      with observe_fits(out,context,KMeans):
       lab,cen=job(out,f'fit/{seed}/{world}/{m}',dict(req,K=k),lambda:fit_stage(context,f'selected/{seed}/{world}/{m}',lambda:atlas.fit_month(z[:,m,:],m,seed,k),1))
      labels.append(lab);centers.append(cen)
      kgrid.extend({'month':controls.MONTHS[m],'K':int(k0),'silhouette':float(s) if np.isfinite(s) else None,'chosen':int(k0)==k,'note':note} for k0,s,_ in rows)
    history=out/'histories'/f'{seed}-{world}-{mode}.npz';np.savez_compressed(history,labels=np.stack(labels),**{f'centers_{i}':x for i,x in enumerate(centers)})
    once(history.with_suffix('.json'),{'NPZ_SHA':sha(history),'K_grid':kgrid,'truth_consumed_by_fit':mode=='oracle','mode':mode})
    for factor in spec['margin_factors']:
     key={'seed':seed,'world':world,'mode':mode,'margin_factor':factor};prefix=f'{seed}-{world}-{mode}-{factor}'
     def compute():
      T=spec['thresholds'];ar,rr,ev=atlas.track_identities(controls.MONTHS,labels,centers,z,np.arange(200),T['T'],T['M']*factor,T['Tc']);controls.consistent_region_status(ar,rr)
      sm,sens=atlas.detect_split_merge(controls.MONTHS,labels,z,ar,rr)
      c,e,bm,er,miss=controls.score(labels,truth,expected,rr,ev+sm)
      save_lines(out/'configs'/(prefix+'-assignments.jsonl.gz'),ar);save_lines(out/'configs'/(prefix+'-regions.jsonl.gz'),rr);save_lines(out/'configs'/(prefix+'-events.jsonl.gz'),ev+sm)
      run=dict(key,execution_status='COMPLETE',recognition=c,events=e,missed_events=miss,negative_M3_false_events=sum(not x['matched_truth'] and x['kind'] in ['split_candidate','merge_candidate'] for x in er) if world in ['stable','drift','proximity'] else 0,m3_sensitivity_counts=sens,selected_k=[len(set(x)) for x in labels],history_SHA=sha(history),input_NPZ_SHA=sha(cube))
      once(out/'configs'/(prefix+'.json'),run)
      return run,[dict(key,month_index=controls.MONTHS.index(x['month']),**x) for x in bm],[dict(key,**x) for x in er]
     run,bm,er=job(out,'config/'+prefix,dict(key,history_SHA=sha(history),input_NPZ_SHA=sha(cube)),compute);runs.append(run);months.extend(bm);all_events.extend(er)
 once(out/'runs.json',runs);once(out/'months.json',months);once(out/'events.json',all_events);once(out/'truth.json',worldproof)
 once(out/'metrics.json',{'acceptance':evaluation.acceptance(spec,runs,months),'seed_block_intervals':intervals(spec,runs,controls,np),'scientific_pass':False,'independent_audit':'PENDING','seed_bootstrap_note':'New paired seed-block draws use the exact frozen design seed2026100813; descriptive only'})
 once(out/'manifest.json',{str(p.relative_to(out)):sha(p) for p in sorted(out.rglob('*')) if p.is_file()})
if __name__=='__main__':main()
