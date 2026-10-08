"""Prospective full E05 remaining library. Import/--plan: stdlib only.
Numerical execution is available solely to a future accepted bounded guardian;
this library/CLI is not an execution authority or a security boundary.
No mobility rerun; no M1 fit, calibration or economic-identity qualification.
"""
import argparse,hashlib,importlib.util,json,math,os,time,itertools,statistics
from pathlib import Path

def sha(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as f:
  for block in iter(lambda:f.read(65536),b''):h.update(block)
 return h.hexdigest()

def planned_cells(p):
 real=[{'kind':'real','arm':a,'K':k,'seed':s} for a in p['arms'] for k in p['K'] for s in p['seeds']]
 controls=[{'kind':'control','world':w,'gamma':g,'K':2,'seed':s} for w in p['controls']['worlds'] for g in p['controls']['gammas'] for s in p['controls']['seeds']]
 return real+controls

def validate_protocol(p):
 if p['source_action']['id']!='act_a32a69fed5be431c' or p['panel_expected_shape']!=[1896,24,6]:raise ValueError('original action/full panel scope')
 if p['K']!=[2,5] or len(p['seeds'])!=5 or len(set(p['seeds']))!=5:raise ValueError('fixed K/seeds')
 if len(p['months'])!=24 or p['months']!=[f'{y}-{m:02}' for y in [2023,2024] for m in range(1,13)]:raise ValueError('exact months')
 if p['interpretation']['positive_scientific_pass_allowed'] is not False:raise ValueError('negative M1 qualification unchanged')
 if p['mobility_reuse_only']['no_new_fits'] is not True or p['mobility_reuse_only']['n']!=101 or p['mobility_reuse_only']['weights']!=[0,.25,1]:raise ValueError('immutable completed mobility')
 arms=p['arms'];ids=[a['id'] for a in arms]
 if len(ids)!=len(set(ids)):raise ValueError('duplicate arms')
 required={'shares','volume','log_volume','shares_log_volume','growth_mom','shares_growth_mom','growth_yoy','shares_scaled','shares_logratio'}
 if not required<={a['feature'] for a in arms}:raise ValueError('feature promise narrowed')
 if {a['gamma'] for a in arms}!={0.,.5,2.} or {a['alpha_geo'] for a in arms}!={0.,.5,1.}:raise ValueError('temporal/geography promise narrowed')
 if not {(k,s) for k in [10,20,40] for s in ['union','mutual']}<={(a['knn'],a['sym']) for a in arms}:raise ValueError('original graph grid missing')
 ctl=p['controls']
 if (ctl['n'],ctl['months'],ctl['d'],ctl['K'])!=(1896,24,5,2) or ctl['full_requested_cells']!=45:raise ValueError('fullsize control scope')
 if ctl['worlds']!=['stable','abrupt_shift','seasonal_no_identity_change'] or len(ctl['seeds'])!=5 or ctl['gammas']!=[0.,.5,2.]:raise ValueError('control bank narrowed')
 return True

def available(feature,t):
 return not ((feature in ('growth_mom','shares_growth_mom') and t==0) or (feature=='growth_yoy' and t<12))

def full_status_rows(tids,months,labels,status='COMPUTED',null_status='INPUT_UNAVAILABLE'):
 if len(set(tids))!=len(tids):raise ValueError('duplicate territories')
 if len(labels)!=len(months):raise ValueError('month universe')
 rows=[]
 for t,month in enumerate(months):
  lab=labels[t]
  if lab is not None and len(lab)!=len(tids):raise ValueError('territory mask shrank')
  rows += [{'territory_id':int(tid),'month':month,'label':None if lab is None else int(lab[i]),'status':null_status if lab is None else status} for i,tid in enumerate(tids)]
 return rows

def pairing(rows,base):
 key=lambda r:(r['territory_id'],r['month'])
 a={key(r):r for r in rows};b={key(r):r for r in base}
 if len(a)!=len(rows) or len(b)!=len(base) or set(a)!=set(b):raise ValueError('paired key mismatch/duplicate')
 keys=sorted(k for k in a if a[k]['status']=='COMPUTED' and b[k]['status']=='COMPUTED')
 return {'universe':len(a),'paired_available':len(keys),'unpaired':len(a)-len(keys),'paired_keys':keys}

def align_without_truth(labels):
 if not labels:return []
 out=[list(labels[0])]
 for current in labels[1:]:
  previous=out[-1];raw=list(current);ids=sorted(set(previous));now=sorted(set(raw))
  if len(ids)!=len(now) or len(previous)!=len(raw):raise ValueError('fixedK mask for alignment')
  mappings=[dict(zip(now,perm)) for perm in itertools.permutations(ids)]
  best=max(mappings,key=lambda m:sum(m[b]==a for a,b in zip(previous,raw)))
  out.append([best[b] for b in raw])
 return out

def control_budget(metrics,world,p):
 b=p['controls']['error_budget'];checks={}
 if world=='abrupt_shift':
  checks={'miss':metrics.get('miss_fraction'),'delay':metrics.get('median_delay')}
  bounds={'miss':b['abrupt_missed_change_fraction_max'],'delay':b['abrupt_median_delay_months_max']}
 else:
  checks={'false_switch':metrics.get('false_switch_fraction')}
  bounds={'false_switch':b['stable_false_switch_fraction_max'] if world=='stable' else b['seasonal_false_switch_fraction_max']}
 if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or v<0 for v in checks.values()):return {'status':'INCONCLUSIVE_UNDEFINED','raw':checks,'bounds':bounds}
 return {'status':'CONTROL_BUDGET_PASS' if all(checks[k]<=bounds[k] for k in checks) else 'CONTROL_BUDGET_FAIL','raw':checks,'bounds':bounds,'scientific_pass':False}

def verify_inputs(repo,p):
 validate_protocol(p)
 for path,digest in {**p['source_pins'],**p['data_pins']}.items():
  f=Path(repo)/path
  if f.is_symlink() or sha(f)!=digest:raise ValueError('pinned input/source changed:'+path)
 return True

def _load(repo,name):
 path=Path(repo)/'economic-atlas/src'/name
 spec=importlib.util.spec_from_file_location('e05_pinned_'+name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def _deps():
 # Only an adopted future guardian may reach these numerical imports.
 import numpy as np
 import pandas as pd
 from scipy import sparse
 from scipy.sparse.linalg import eigsh
 from sklearn.cluster import KMeans
 from sklearn.metrics import adjusted_rand_score,normalized_mutual_info_score,silhouette_score,calinski_harabasz_score
 return np,pd,sparse,eigsh,KMeans,adjusted_rand_score,normalized_mutual_info_score,silhouette_score,calinski_harabasz_score

def _feature_cube(values,kind,np):
 shares=values[:,:,1:]/values[:,:,:1]
 if kind in ('shares','shares_scaled'):raw=shares
 elif kind=='shares_logratio':raw=np.log(shares)
 elif kind=='volume':raw=values.copy()
 elif kind=='log_volume':raw=np.log1p(values)
 elif kind=='shares_log_volume':raw=np.concatenate([shares,np.log1p(values[:,:,:1])],axis=2)
 elif kind in ('growth_mom','shares_growth_mom'):
  raw=np.full_like(values,np.nan);raw[:,1:,:]=values[:,1:,:]/values[:,:-1,:]-1
  if kind=='shares_growth_mom':raw=np.concatenate([shares,raw],axis=2)
 elif kind=='growth_yoy':
  raw=np.full_like(values,np.nan);raw[:,12:,:]=values[:,12:,:]/values[:,:-12,:]-1;return raw,{'fit':'IDENTITY_DIMENSIONLESS_NO2023_YOY_DISTRIBUTION','unavailable_months':12}
 else:raise ValueError('feature recipe')
 if kind=='shares':return raw,{'fit':'IDENTITY_RAW_SHARES_GRAPH_ONLY'}
 fit=raw[:,:12,:].reshape(-1,raw.shape[2]);fit=fit[np.isfinite(fit).all(axis=1)]
 if len(fit)==0:raise ValueError('no2023 calibration data')
 mu=fit.mean(axis=0);sd=fit.std(axis=0);safe=np.where(sd>0,sd,1.)
 return (raw-mu)/safe,{'fit':'ONLY2023_POOLED','mean':mu.tolist(),'std':sd.tolist(),'zero_std':(sd==0).tolist()}

def _affinity(x,k,sym,np,sparse):
 n=len(x);norm=np.linalg.norm(x,axis=1)
 if np.any(norm<=0) or not np.isfinite(x).all():raise ValueError('degenerate/zero/nonfinite profile')
 unit=x/norm[:,None];scores=unit@unit.T;np.fill_diagonal(scores,-np.inf)
 rows=[];cols=[];data=[]
 for i in range(n):
  # Stable explicit tie order by node index, no random jitter/bridges.
  order=np.lexsort((np.arange(n),-scores[i]))[:k]
  for j in order:
   if scores[i,j]>0:rows.append(i);cols.append(int(j));data.append(float(scores[i,j]))
 w=sparse.csr_matrix((data,(rows,cols)),shape=(n,n))
 return w.maximum(w.T) if sym=='union' else w.minimum(w.T)

def _normalize(w,np,sparse):
 degree=np.asarray(w.sum(axis=1)).ravel()
 if np.any(degree<=0):raise ValueError('ISOLATES_RETAIN_FULL_UNIVERSE_NO_BRIDGES')
 scale=1/np.sqrt(degree);return sparse.diags(scale)@w@sparse.diags(scale)

def _partition(w,K,seed,np,sparse,eigsh,KMeans):
 a=_normalize(w,np,sparse);lap=sparse.eye(w.shape[0],format='csr')-a
 # Explicit ARPACK settings frozen; failure retained, no fallback/retry.
 eigenvalues,v=eigsh(lap,k=K,which='SA',tol=1e-8,maxiter=5000,v0=np.random.default_rng(seed).normal(size=w.shape[0]))
 v=v[:,np.argsort(eigenvalues)];norm=np.linalg.norm(v,axis=1);v=v/np.where(norm>0,norm,1)[:,None]
 return KMeans(n_clusters=K,n_init=20,random_state=seed).fit_predict(v)

def _partitions(graphs,gamma,K,seed,np,sparse,eigsh,KMeans,guard):
 n=graphs[0].shape[0];T=len(graphs)
 if gamma==0:
  labels=[]
  for t,g in enumerate(graphs):guard();labels.append(_partition(g,K,seed+t,np,sparse,eigsh,KMeans))
  return [np.asarray(v,dtype=int) for v in align_without_truth(labels)]
 supra=sparse.block_diag(graphs,format='csr');nodes=np.arange(n)
 for t in range(T-1):
  i=t*n+nodes;j=(t+1)*n+nodes
  supra+=sparse.csr_matrix((np.full(2*n,gamma),(np.r_[i,j],np.r_[j,i])),shape=supra.shape)
 guard();lab=_partition(supra,K,seed,np,sparse,eigsh,KMeans)
 return [lab[t*n:(t+1)*n] for t in range(T)]

def _graph_diagnostics(graphs,np):
 from scipy.sparse.csgraph import connected_components
 records=[]
 for g in graphs:
  degree=np.asarray(g.sum(axis=1)).ravel();n,labels=connected_components(g,directed=False)
  records.append({'n':g.shape[0],'undirected_edges':int(g.nnz//2),'isolates':int((degree==0).sum()),'components':int(n),'component_sizes':sorted(np.bincount(labels).tolist(),reverse=True),'no_artificial_bridges':True})
 return records

def _quality(x,lab,geo,np,sw,ch,sdbw,icvi):
 if lab is None:return {'status':'INPUT_UNAVAILABLE'}
 sizes={str(int(a)):int((lab==a).sum()) for a in np.unique(lab)}
 if len(sizes)<2 or len(sizes)>=len(lab):return {'status':'NA_DEGENERATE','sizes':sizes}
 score=sdbw.s_dbw(x,lab,centre_domain='pair_union',expected_k=len(sizes))
 # No random partition null repetitions: these are deterministic reference indices.
 g=geo.toarray();net={k:f(g,lab) for k,f in [('AVI',icvi.avi),('AVU',icvi.avu),('Newman_Q',icvi.modularity_newman)]}
 return {'status':'COMPUTED','sizes':sizes,'SW':float(sw(x,lab)),'CH':float(ch(x,lab)),'S_Dbw':score,'network_reference_indices':{k:float(v) for k,v in net.items()},'MQ':'SPEC_UNRESOLVED_OWNER_EXCLUDED'}

def _temporal_summary(labels,np,ari,nmi):
 records=[]
 for t in range(1,len(labels)):
  a,b=labels[t-1],labels[t]
  if a is None or b is None:records.append({'t':t,'status':'INPUT_UNAVAILABLE'});continue
  pairs={}
  for u,v in zip(a,b):k=f'{int(u)}->{int(v)}';pairs[k]=pairs.get(k,0)+1
  records.append({'t':t,'status':'COMPUTED','ARI':float(ari(a,b)),'NMI':float(nmi(a,b)),'contingency':pairs,'switch_fraction':float(np.mean(a!=b)),'label_overlap_alignment_is_not_identity':True})
 return records

def _controls(p,world,seed,np):
 # Source-only prospective generator. Truth inaccessible to partition functions.
 c=p['controls'];n,T,d=c['n'],c['months'],c['d'];rng=np.random.default_rng(seed);initial=np.arange(n)%2;truth=np.tile(initial[:,None],(1,T));movers=np.arange(int(n*c['shift_fraction']))
 if world=='abrupt_shift':truth[movers,c['shift_month_index']:]=1-truth[movers,c['shift_month_index']:]
 x=c['raw_feature_positive_base']+c['separation']*(2*truth-1)[:,:,None]*np.array([1,-1,1,-1,1])[None,None,:]+rng.normal(0,c['noise_std'],(n,T,d))
 if world=='seasonal_no_identity_change':x+=c['seasonal_amplitude']*np.sin(2*np.pi*np.arange(T)/12)[None,:,None]
 return x,truth,movers

def _event_control_metrics(mapped,truth,movers,shift):
 """Score actual transitions after a correct baseline; stdlib only.
 Same initial truth mapping, same event month and original numeric budgets.
 Recall is immediate-at-shift, NOT easier eventual post-state accuracy.
 Entire fitted sequence can be retrospective; delays do not prove online use.
 """
 mapped=[[int(v) for v in row] for row in mapped]
 truth=[[int(v) for v in row] for row in truth]
 movers=[int(i) for i in movers]
 if not truth or len(mapped)!=len(truth):raise ValueError('full matching control universe')
 T=len(truth[0])
 if not isinstance(shift,int) or isinstance(shift,bool) or not 0<shift<T:raise ValueError('shift within observed months')
 if any(len(row)!=T for row in truth+mapped):raise ValueError('full control trajectory shape')
 if any(v not in (0,1) for row in truth+mapped for v in row):raise ValueError('binary fixed initial mapping')
 if len(movers)!=len(set(movers)) or any(i<0 or i>=len(truth) for i in movers):raise ValueError('unique mover indices')
 expected=[i for i,row in enumerate(truth) if row[shift]!=row[shift-1]]
 if not set(expected)<=set(movers):raise ValueError('truth changed outside declared movers')
 for row in truth:
  if any(row[t]!=row[0] for t in range(shift)) or any(row[t]!=row[shift] for t in range(shift,T)):raise ValueError('single frozen abrupt truth transition')
 delays=[]
 for i in expected:
  before,after=truth[i][shift-1],truth[i][shift]
  # A wrong or already-post-event baseline cannot constitute detection.
  hits=[t-shift for t in range(shift,T) if mapped[i][shift-1]==before and mapped[i][t-1]==before and mapped[i][t]==after]
  delays.append(hits[0] if hits else None)
 valid=[d for d in delays if d is not None]
 recall=sum(d==0 for d in delays)/len(delays) if delays else None
 eventual=len(valid)/len(delays) if delays else None
 changed=set(expected)
 stable=[i for i in range(len(truth)) if i not in changed]
 false_switches=[mapped[i][t]!=mapped[i][t-1] for i in stable for t in range(1,T)]
 state_accuracy=sum(mapped[i][shift]==truth[i][shift] for i in expected)/len(expected) if expected else None
 return {'recall':recall,'event_recall_at_shift':recall,'miss_fraction':None if recall is None else 1-recall,'eventual_event_recall':eventual,'post_shift_state_accuracy':state_accuracy,'baseline_state_accuracy':sum(mapped[i][shift-1]==truth[i][shift-1] for i in range(len(truth)))/len(truth),'expected_changed_entities':len(expected),'delays_months':delays,'median_delay':float(statistics.median(valid)) if valid else None,'never_detected':sum(d is None for d in delays),'false_switch_fraction':sum(false_switches)/len(false_switches) if false_switches else None,'scope':'synthetic actual transitions with correct pre-event baseline; fixed initial mapping; recall evaluated at shift; retrospective fitted labels are not online warning'}

def _control_metrics(labels,truth,movers,shift,np,ari):
 from scipy.optimize import linear_sum_assignment
 # Same initial-only mapping AFTER model output; no truth enters fitting.
 table=np.array([[np.sum((labels[0]==a)&(truth[:,0]==b)) for b in range(2)] for a in range(2)])
 row,col=linear_sum_assignment(-table);mapping=dict(zip(row,col))
 mapped=[[mapping[int(lab[i])] for lab in labels] for i in range(len(truth))]
 result=_event_control_metrics(mapped,truth,movers,shift)
 result['adjacent_ARI']=[float(ari(labels[t-1],labels[t])) for t in range(1,len(labels))]
 return result

def execute(repo,protocol,out,guard,journal):
 """Future accepted foreground guardian only. guard/journal are mandatory.
 No resume/retry. Failures retained; missing cells forbid completion.
 """
 if not callable(guard) or not callable(journal):raise ValueError('accepted resource guardian/journal required')
 started=time.monotonic();p=json.loads(Path(protocol).read_text());guard();verify_inputs(repo,p);guard()
 out=Path(out)
 if out.exists():raise FileExistsError('fresh one-use output only')
 out.mkdir(mode=0o700)
 np,pd,sparse,eigsh,KMeans,ari,nmi,sw,ch=_deps();a6=_load(repo,'a6_temporal.py');sdbw=_load(repo,'atlas_sdbw.py');icvi=_load(repo,'network_icvi.py')
 panel=pd.read_parquet(Path(repo)/'economic-atlas/data/panel_v1.parquet');tids,months,shares,_=a6.build_monthly_shares(panel)
 if len(tids)!=1896 or list(months)!=p['months']:raise ValueError('all24/1896 scope')
 # Reconstruct six source values in EXACT separate-total + five category order.
 tidcol=a6._pick(panel.columns,a6.TID_CANDS,'tid');datecol=a6._pick(panel.columns,a6.DATE_CANDS,'date');catcol=a6._pick(panel.columns,a6.CAT_CANDS,'cat');frame=panel.copy();frame[tidcol]=frame[tidcol].astype(int);frame['_month']=pd.to_datetime(frame[datecol]).dt.strftime('%Y-%m')
 pivot=frame.pivot(index=[tidcol,'_month'],columns=catcol,values='value').reindex(pd.MultiIndex.from_product([tids,months],names=[tidcol,'_month']))[a6.ALL_CATS];values=pivot.to_numpy(float).reshape(1896,24,6)
 if not np.isfinite(values).all() or (values<=0).any():raise ValueError('source full positive/no-fill grid')
 common,_=a6.standardize_frozen(shares,months);edges=pd.read_parquet(Path(repo)/'economic-atlas/runs/A5/edges.parquet');index={int(t):i for i,t in enumerate(tids)};i=[index[int(t)] for t in edges.u];j=[index[int(t)] for t in edges.v];w=edges.weight.to_numpy(float);geo=sparse.csr_matrix((np.r_[w,w],(np.r_[i,j],np.r_[j,i])),shape=(1896,1896));geo=_normalize(geo,np,sparse)
 cells=planned_cells(p);finished=[];base_partitions={};paired_comparisons=[]
 for number,cell in enumerate(cells):
  cell_started=time.monotonic();guard();journal({'key':number,'state':'STARTED','cell':cell})
  try:
   if cell['kind']=='real':
    arm=cell['arm'];cube,scaler=_feature_cube(values,arm['feature'],np);graphs=[];validmonths=[];labs=[None]*24
    for t in range(24):
     if not available(arm['feature'],t):continue
     guard();g=_normalize(_affinity(cube[:,t,:],arm['knn'],arm['sym'],np,sparse),np,sparse);g=(1-arm['alpha_geo'])*g+arm['alpha_geo']*geo;graphs.append(g);validmonths.append(t)
    predicted=_partitions(graphs,arm['gamma'],cell['K'],cell['seed'],np,sparse,eigsh,KMeans,guard)
    for t,lab in zip(validmonths,predicted):labs[t]=lab
    rows=full_status_rows(tids,months,labs)
    pairkey=(cell['K'],cell['seed'])
    if arm['id']=='shares':base_partitions[pairkey]=rows
    pairing_report=pairing(rows,base_partitions[pairkey]);pairing_report.pop('paired_keys')
    agreements=[]
    if arm['id']!='shares':
     base_rows=base_partitions[pairkey]
     for t in range(24):
      if labs[t] is None:agreements.append({'month':months[t],'status':'INPUT_UNAVAILABLE','n':0});continue
      baseline=[r['label'] for r in base_rows[t*1896:(t+1)*1896]];agreements.append({'month':months[t],'status':'COMPUTED','n':1896,'ARI_vs_sameKseed_shares':float(ari(baseline,labs[t])),'NMI_vs_sameKseed_shares':float(nmi(baseline,labs[t]))})
    paired_comparisons.append({'cell':cell,'denominators':pairing_report,'agreement':agreements})
    quality=[_quality(common[:,t,:],labs[t],geo,np,sw,ch,sdbw,icvi) for t in range(24)];summary={'cell':cell,'scaler':scaler,'graph_diagnostics':_graph_diagnostics(graphs,np),'valid_month_indices':validmonths,'quality_same_spending_space':quality,'adjacent':_temporal_summary(labs,np,ari,nmi)}
   else:
    x,truth,movers=_controls(p,cell['world'],cell['seed'],np);graphs=[]
    for t in range(24):guard();graphs.append(_normalize(_affinity(x[:,t,:],20,'union',np,sparse),np,sparse))
    labs=_partitions(graphs,cell['gamma'],2,cell['seed'],np,sparse,eigsh,KMeans,guard);rows=full_status_rows(range(1896),months,labs);metrics=_control_metrics(labs,truth,movers,p['controls']['shift_month_index'],np,ari);summary={'cell':cell,'control_metrics':metrics,'budget':control_budget(metrics,cell['world'],p),'truth_not_training':True}
   summary['elapsed_seconds_to_publication_start']=time.monotonic()-cell_started
   guard();folder=out/f'cell-{number:04}';folder.mkdir(mode=0o700);pd.DataFrame(rows).to_parquet(folder/'assignments.parquet',index=False,compression='zstd');(folder/'summary.json').write_text(json.dumps(summary,allow_nan=False,indent=2)+'\n');journal({'key':number,'state':'COMPUTED','assignmentSHA':sha(folder/'assignments.parquet'),'summarySHA':sha(folder/'summary.json')});finished.append({'key':number,'status':'COMPUTED'})
  except (InterruptedError,KeyboardInterrupt):raise
  except Exception as e:
   # Retain exact failed cell; do not run replacement seeds/models or hide NA.
   guard();folder=out/f'cell-{number:04}';folder.mkdir(mode=0o700,exist_ok=True);rows=full_status_rows(tids if cell['kind']=='real' else list(range(1896)),months,[None]*24,null_status='INCONCLUSIVE_METHOD_FAILURE');failure={'cell':cell,'status':'INCONCLUSIVE','error':type(e).__name__+': '+str(e),'full_rows_preserved':45504};pd.DataFrame(rows).to_parquet(folder/'failure-assignments.parquet',index=False,compression='zstd');(folder/'failure.json').write_text(json.dumps(failure,allow_nan=False)+'\n');journal({'key':number,'state':'INCONCLUSIVE','error':failure['error'],'failureSHA':sha(folder/'failure.json'),'rowsSHA':sha(folder/'failure-assignments.parquet')});finished.append({'key':number,'status':'INCONCLUSIVE'})
 guard();result={'state':'DESCRIPTIVE_BANK_COMPLETED_WITH_ABSTENTIONS','expected_cells':len(cells),'cells':finished,'full_technical_success':all(r['status']=='COMPUTED' for r in finished),'scientific_pass':False,'economic_identity':False,'causal':False,'historical_asof':False,'M4_dependency':'PENDING_SEPARATE_ACTUAL_ACCEPTANCE','mobility_reused_SHA':p['mobility_reuse_only']['SHA256'],'unknown_admin_population_confounds':True,'elapsed_seconds_to_finalization':time.monotonic()-started,'formal_promise_complete':False,'requires_independent_full_file_and_metric_validation':True}
 (out/'paired-comparisons.json').write_text(json.dumps(paired_comparisons,allow_nan=False,indent=2)+'\n')
 (out/'result.json').write_text(json.dumps(result,indent=2)+'\n');return result

def main():
 ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--protocol',type=Path,required=True);ap.add_argument('--plan',action='store_true',required=True);args=ap.parse_args();p=json.loads(args.protocol.read_text());validate_protocol(p);print(json.dumps({'state':'PLAN_ONLY_NO_SCIENCE','cells':len(planned_cells(p)),'real':len(p['arms'])*len(p['K'])*len(p['seeds']),'controls':45,'scientific_pass':False}))
if __name__=='__main__':main()
