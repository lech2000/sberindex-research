"""Prospective complete M4 3-world x3-channel bank; verified complete M1 receipt; upstream quality retained.

C is km-index augmentation, never an invented OD flow. Ground truth only scores
own-world count; no truth enters graph/spectrum/calibration. No real input fits.
"""
from pathlib import Path
import argparse,hashlib,importlib.util,json,os,sys
sys.dont_write_bytecode=True
import numpy as np
PROTOCOL_SHA='6220a61fcaefe60ecc872f5c930023bb6453d0c60059c3f66721199882330969'
M1_SHA='5ad14f6e2df75ac89d2285e3a09c304e7894ce6c42a363334a1d568115c1758b'
M1_PROTOCOL_SHA='fd3133bbda35fb7183908e4c3bd4697f5651962adaf8c0cccf74eb4b15c0dc30'
AMENDMENT_SHA='e1c5b21b445c3ef408e9061ae023f706997abe5ebf397ffadeb39a74b0c7f163'
CHANNELS=('A','B','C')

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def clean(x):
 if isinstance(x,dict):return {str(k):clean(v) for k,v in x.items()}
 if isinstance(x,(list,tuple,np.ndarray)):return [clean(v) for v in x]
 if isinstance(x,np.generic):return clean(x.item())
 if isinstance(x,float) and not np.isfinite(x):return None
 return x

def atomic(path,data):
 path=Path(path);temp=path.with_name(path.name+'.tmp')
 with temp.open('w') as f:json.dump(clean(data),f,ensure_ascii=False,allow_nan=False,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
 os.replace(temp,path)

def load_m1(repo):
 p=Path(repo)/'economic-atlas/src/atlas_m1_spectral.py'
 if sha(p)!=M1_SHA:raise ValueError('exact accepted baseline M1 source required')
 spec=importlib.util.spec_from_file_location('fixed_m1',p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def world(n,R,structured,seed):
 if n<41 or R not in (1,3,4,5) or structured not in ('A','B','C','NONE'):raise ValueError('world scope mismatch')
 group=np.arange(n)%R
 # Every channel gets a separate stream, shared across worlds for paired comparison.
 a,b,c=(np.random.default_rng(s) for s in np.random.SeedSequence(seed).spawn(3))
 initial=.72*a.dirichlet(np.ones(5),size=n)
 if structured=='A':
  initial=.02+np.eye(5)[group]+np.abs(a.normal(0,.015,(n,5)))
  initial=.72*initial/initial.sum(1,keepdims=True)
 increments=b.normal(0,.03,(n,23,5))
 if structured=='B':
  frequency=group[:,None,None]+1;time=np.arange(115).reshape(1,23,5)
  increments=.03*(np.sin(2*np.pi*frequency*time/115)+b.normal(0,.10,(n,23,5)))
  increments-=increments.mean(axis=(1,2),keepdims=True)
 panel=initial[:,None,:]*np.exp(np.concatenate([np.zeros((n,1,5)),np.cumsum(increments,axis=1)],axis=1))
 logmob=5+c.normal(0,.5,n)
 if structured=='C':logmob=5+1.5*group+c.normal(0,.10,n)
 mobility=np.expm1(logmob)
 if not np.isfinite(panel).all() or not (panel>0).all() or not np.isfinite(mobility).all() or (mobility<0).any():raise ValueError('invalid synthetic world; never repair after results')
 return {'panel':panel,'mobility_km_index':mobility,'truth':group,'structured':structured,'R':R,'seed':seed,'n':n}

def zscore(x):
 sd=np.std(x,axis=0);mu=np.mean(x,axis=0)
 if np.any(sd<=1e-12):raise ValueError('degenerate feature variance, not filled')
 return (x-mu)/sd

def channel_features(data,channel):
 panel=data['panel']
 if panel.ndim!=3 or panel.shape[1:]!=(24,5) or not np.isfinite(panel).all() or not (panel>0).all():raise ValueError('24x5 positive source panel required')
 if channel=='A':return panel[:,0,:].copy(),'cosine'
 if channel=='B':
  x=np.log(panel[:,1:,:]/panel[:,:-1,:]).reshape(len(panel),115)
  x-=x.mean(1,keepdims=True)
  return x,'cosine'
 if channel=='C':
  mob=np.asarray(data['mobility_km_index'],float)
  if mob.shape!=(len(panel),) or not np.isfinite(mob).all() or (mob<0).any():raise ValueError('km index, not an OD matrix, required')
  return np.column_stack([zscore(panel[:,0,:]),.25*zscore(np.log1p(mob[:,None]))]),'euclidean'
 raise ValueError('unknown channel')

def feature_graph(x,k,metric):
 x=np.asarray(x,float);n=len(x)
 if x.ndim!=2 or not np.isfinite(x).all() or not 1<=k<n:raise ValueError('invalid graph input')
 if metric=='cosine':
  norm=np.linalg.norm(x,axis=1)
  if np.any(norm<=1e-12):raise ValueError('zero cosine profile')
  unit=x/norm[:,None];distance=1-np.clip(unit@unit.T,-1,1)
 elif metric=='euclidean':distance=np.maximum((x*x).sum(1)[:,None]+(x*x).sum(1)[None,:]-2*x@x.T,0)
 else:raise ValueError('unsupported source-compatible metric')
 np.fill_diagonal(distance,np.inf);near=np.argsort(distance,axis=1,kind='stable')[:,:k]
 candidates={(min(i,int(j)),max(i,int(j))) for i,row in enumerate(near) for j in row}
 ordered=sorted(candidates,key=lambda edge:(distance[edge],edge[0],edge[1]));budget=n*k//2
 if len(ordered)<budget:raise ValueError('union budget unavailable')
 W=np.zeros((n,n),float)
 for i,j in ordered[:budget]:W[i,j]=W[j,i]=1
 return W

def graph(data,channel,k):
 x,metric=channel_features(data,channel);return feature_graph(x,k,metric)

def degree_null(W,seed):
 W=np.asarray(W,float)
 if not np.array_equal(W,W.T) or np.diag(W).any() or not np.isin(W,[0,1]).all():raise ValueError('simple binary symmetric graph required')
 edges=[tuple(map(int,pair)) for pair in np.argwhere(np.triu(W,1))];E=len(edges)
 if E<2:raise ValueError('insufficient rewiring edges')
 available=set(edges);rng=np.random.default_rng(seed);target=10*E;attempt_cap=100*E;success=0;attempts=0
 # Bulk random draw only changes computation overhead, not proposed swap law.
 choices=rng.integers(0,E,size=(attempt_cap,2));orient=rng.integers(0,2,size=(attempt_cap,2))
 for idx,(i,j) in enumerate(choices):
  attempts=idx+1;i=int(i);j=int(j)
  if i==j:continue
  a,b=edges[i];c,d=edges[j]
  if orient[idx,0]:a,b=b,a
  if orient[idx,1]:c,d=d,c
  if len({a,b,c,d})!=4:continue
  first=tuple(sorted((a,d)));second=tuple(sorted((c,b)))
  if first in available or second in available:continue
  available.remove(edges[i]);available.remove(edges[j]);available.add(first);available.add(second)
  edges[i]=first;edges[j]=second;success+=1
  if success==target:break
 null=np.zeros_like(W)
 for i,j in edges:null[i,j]=null[j,i]=1
 if not np.array_equal(null.sum(1),W.sum(1)):raise AssertionError('degree preservation failure')
 return null,{'successful_swaps':success,'target_swaps':target,'attempts':attempts,'attempt_cap':attempt_cap,'complete':success==target,'seed':seed}

def evaluate_graph(data,channel,k,m1,sig_star,nullseeds):
 W=graph(data,channel,k);r,vals,vectors=m1.spectrum(W,.95);gaps=[];details=[];invalid=[]
 for seed in nullseeds:
  if r['m'] is None:
   invalid.append(seed);details.append({'seed':seed,'state':'INCONCLUSIVE_ORIGINAL_GRAPH_ISOLATE'});continue
  null,meta=degree_null(W,seed);nr,_,_=m1.spectrum(null,.95)
  details.append({**meta,'m':nr['m'],'raw_gap':nr['raw_gap'],'state':nr['status']})
  if not meta['complete'] or nr['raw_gap'] is None:invalid.append(seed)
  else:gaps.append(nr['raw_gap'])
 outcome=m1.verdict(r,sig_star,np.asarray(gaps),invalid)
 partition=None;partition_status='ABSTAIN_M1' if r['m']==1 else 'NA_GRAPH_OR_K_DOMAIN'
 if vectors is not None and r['m'] is not None and 2<=r['m']<len(W):
  partition=m1.labels(vectors,r['m'],data['seed']).tolist()
  partition_status='COMPUTED_TRUTH_BLIND_M1' if len(set(partition))==r['m'] else 'NA_EMPTY_CLUSTER'
 return {**r,'verdict':outcome,'predicted_partition':partition,'partition_status':partition_status,'null_raw_gaps':gaps,'null_details':details,'null_invalid_seeds':invalid,
         'null_p95':float(np.quantile(gaps,.95)) if len(gaps) else None}

def calibrate(p,m1):
 result={}
 for channel in CHANNELS:
  for k in p['k']:
   records=[];positive=[];negative=[]
   for R in (1,3,4,5):
    for seed in p['calibration_seeds']:
     data=world(p['n'],R,channel if R>1 else 'NONE',seed)
     r,_,_=m1.spectrum(graph(data,channel,k),.95);records.append({'R':R,'seed':seed,**r});(positive if R>1 else negative).append(r['sig'])
   fit=m1.threshold(positive,negative)
   if any(r['m']!=r['R'] for r in records if r['R']>1):fit={'status':'INCONCLUSIVE_CALIBRATION','sig_star':None,'reason':'own_positive_R_not_recovered'}
   result[f'{channel}-k{k}']={'n':p['n'],'channel':channel,'k':k,'records':records,'fit':fit}
 return result

def score_cell(cell):
 if cell.get('null_invalid_seeds') or cell.get('partition_status')=='NA_EMPTY_CLUSTER':return False
 own=cell['channel']==cell['world']
 return cell['m']==cell['R'] and cell['verdict']=='REAL_GAP' if own else cell['m']==1

def complete(p,calibration,m1,out):
 cells=[]
 for R in p['R']:
  for seed in p['held_seeds']:
   for worldname in p['structured_worlds']:
    data=world(p['n'],R,worldname,seed)
    for channel in CHANNELS:
     for k in p['k']:
      # Null IDs independent of unknown output or predicted labels.
      offset=(R*100000+seed*1000+CHANNELS.index(worldname)*300+CHANNELS.index(channel)*100+k)*100
      nullseeds=range(p['null_seeds_base']+offset,p['null_seeds_base']+offset+99)
      c=evaluate_graph(data,channel,k,m1,calibration[f'{channel}-k{k}']['fit']['sig_star'],nullseeds)
      cell={'R':R,'seed':seed,'world':worldname,'channel':channel,'k':k,'own_world':channel==worldname,**c}
      cell['passes_original_cell_requirement']=bool(score_cell(cell));cells.append(cell)
      # Preserve every failed/inconclusive cell as its own artifact, no selected winner.
      name=f'R{R}-seed{seed}-world{worldname}-channel{channel}-k{k}.json'
      atomic(out/'cells'/name,cell);atomic(out/'progress.json',{'state':'RUNNING','completed_cells':len(cells),'expected_cells':1620,'last_cell':name})
 summaries=[]
 for R in p['R']:
  for k in p['k']:
   for worldname in CHANNELS:
    for channel in CHANNELS:
     selected=[c for c in cells if c['R']==R and c['k']==k and c['world']==worldname and c['channel']==channel]
     summaries.append({'R':R,'k':k,'world':worldname,'channel':channel,'n_cells':len(selected),'pass_cells':sum(c['passes_original_cell_requirement'] for c in selected),'all_pass':all(c['passes_original_cell_requirement'] for c in selected)})
 passed=len(cells)==1620 and all(c['passes_original_cell_requirement'] for c in cells) and all(c['fit']['sig_star'] is not None for c in calibration.values())
 return {'state':'M4_CONFIRMED_SYNTHETIC_FIXED_BANK' if passed else 'M4_NOT_CONFIRMED_FIXED_BANK','full_3_worlds_x_3_channels':True,'completed_cells':len(cells),'summaries':summaries,'scientific_economic_identity_pass':False,'causal_pass':False,'real_method_run':False,'real_OD_flows_available':False,'independent_new_holdout':False}

def check_dependency(path):
 path=Path(path);m=json.loads((path.parent/'manifest.json').read_text());r=json.loads(path.read_text())
 if 'authority' in m:
  gatepath=Path(__file__).with_name('atlas_m4_mixed_dependency.py')
  if sha(gatepath)!='12eb13f3a6fb725d93a9c1f26a895649d1695abbf1f0b7b3e7a448e3e55db127':raise ValueError('mixed dependency gate source mismatch')
  spec=importlib.util.spec_from_file_location('explicit_mixed_dependency',gatepath);gate=importlib.util.module_from_spec(spec);spec.loader.exec_module(gate)
  return gate.check(path)
 if m['code_sha256']!=M1_SHA or m['protocol_sha256']!=M1_PROTOCOL_SHA:raise ValueError('M1 receipt source/protocol mismatch')
 if m.get('files_sha256',{}).get('result.json')!=sha(path):raise ValueError('actual M1 calibration output hash not verified')
 if r['n']!=1896 or r['d']!=5 or set(r['results'])!={'10','20','40'}:raise ValueError('full baseline dependency scope mismatch')
 if r.get('settings_sha256')!='238ee8746c9de5b56033e00f41b3523ce41e2d2fb3fd15787cf73f4e08d14891':raise ValueError('M1 exact settings hash missing/mismatch')
 if r.get('input_sha256')!={'panel':'8716a802fb6e25ef4103406cca927de80ce3693a7ff243411cda765b732bcd93','A5_mask':'12f40b15ee8f119cba7f386b5c9adf4babb5cff1bca2721dc04551d672f5e5d6'}:raise ValueError('M1 exact input hashes missing/mismatch')
 quality={}
 for k in ('10','20','40'):
  c=r['results'][k]
  if (c.get('n'),c.get('d'),c.get('k'))!=(1896,5,int(k)):raise ValueError('per-k M1 scope mismatch')
  for field,seeds in (('calibration',range(20261008,20261018)),('held',range(20261108,20261128))):
   records=c.get(field,[]);expected={(R,seed) for R in (1,3,4,5) for seed in seeds}
   if len(records)!=len(expected) or {(x.get('R'),x.get('seed')) for x in records}!=expected:raise ValueError('full M1 calibration/held exact seed records missing')
   if any(not {'m','sig','raw_gap','status'}.issubset(x) for x in records):raise ValueError('M1 scientific record fields missing')
  for x in c['held']:
   invalid=x.get('shuffle_invalid_seeds',[]);gaps=x.get('shuffle_raw_gaps',[])
   base=20261208+x['seed']*100;expected=set(range(base,base+99))
   if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not np.isfinite(v) for v in gaps):raise ValueError('M1 successful null gaps must be finite numeric')
   if 'verdict' not in x or len(invalid)!=len(set(invalid)) or not set(invalid)<=expected or len(gaps)+len(invalid)!=99:raise ValueError('M1 complete99 null accounting missing')
  quality[k]=c.get('method_quality')
  if quality[k] not in ('PASS_FIXED_CONTROLS','FAIL_OR_INCONCLUSIVE_FIXED_CONTROLS'):raise ValueError('M1 terminal quality missing')
  fit=c.get('fit',{});held=c['held'];negative=[x for x in held if x['R']==1];positive=[x for x in held if x['R']>1]
  passed=(all(x['m'] is not None and not x['shuffle_invalid_seeds'] for x in held) and fit.get('sig_star') is not None
          and sum(x['verdict']=='REAL_GAP' for x in negative)/20<=.05
          and sum(x['verdict']=='REAL_GAP' and x['m']==x['R'] for x in positive)/60>=.90)
  if (quality[k]=='PASS_FIXED_CONTROLS')!=passed:raise ValueError('M1 quality disagrees with fixed held records')
 return {'result_sha256':sha(path),'manifest_sha256':sha(path.parent/'manifest.json'),'source_sha256':M1_SHA,'protocol_sha256':M1_PROTOCOL_SHA,
         'quality_by_k':quality,'positive_scientific_qualification_allowed':all(v=='PASS_FIXED_CONTROLS' for v in quality.values()),'complete_verified_records':True}

def qualify(result,dependency):
 result=dict(result);result['M1_dependency']=dependency
 result['bank_cell_requirements_all_pass']=result['state']=='M4_CONFIRMED_SYNTHETIC_FIXED_BANK'
 allowed=dependency['positive_scientific_qualification_allowed']
 result['positive_scientific_qualification']=bool(allowed and result['bank_cell_requirements_all_pass'])
 if not allowed:result['state']='M4_DESCRIPTIVE_ONLY_UPSTREAM_FAIL_OR_INCONCLUSIVE'
 result['scientific_economic_identity_pass']=False;result['causal_pass']=False
 return result

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--repo',type=Path,required=True);ap.add_argument('--protocol',type=Path,required=True);ap.add_argument('--m1-calibration',type=Path,required=True);ap.add_argument('--outdir',type=Path,required=True);args=ap.parse_args()
 if sha(args.protocol)!=PROTOCOL_SHA:raise ValueError('modified prospective M4 protocol')
 amendment=args.protocol.with_name('M4_DEPENDENCY_AMENDMENT_V1.json')
 if sha(amendment)!=AMENDMENT_SHA:raise ValueError('prospective dependency amendment mismatch')
 p=json.loads(args.protocol.read_text());dependency=check_dependency(args.m1_calibration);m1=load_m1(args.repo)
 for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS'):
  if os.environ.get(k)!='1':raise ValueError('fixedCPU1 thread environment required')
 args.outdir.mkdir(exist_ok=False);(args.outdir/'cells').mkdir()
 atomic(args.outdir/'freeze.json',{'protocol_sha256':sha(args.protocol),'source_sha256':sha(__file__),'M1_source_sha256':M1_SHA,'M1_dependency':dependency,'dependency_amendment_sha256':AMENDMENT_SHA,'real_data_read':False})
 cal=calibrate(p,m1);atomic(args.outdir/'calibration.json',cal)
 r=qualify(complete(p,cal,m1,args.outdir),dependency);atomic(args.outdir/'result.json',r)
 atomic(args.outdir/'manifest.json',{'files_sha256':{str(x.relative_to(args.outdir)):sha(x) for x in args.outdir.rglob('*') if x.is_file()},'source_action':'act_a0d924d8af6548e2','no_action_closed':True})
 print(json.dumps({'state':r['state'],'completed_cells':r['completed_cells'],'economic_identity_pass':False}))
if __name__=='__main__':main()
