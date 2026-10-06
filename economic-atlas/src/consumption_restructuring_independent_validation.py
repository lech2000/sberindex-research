"""Independent verification; imports no study modules, changes no old outputs."""
from datetime import datetime, timezone
import argparse, hashlib, json, platform
from pathlib import Path
import numpy as np
import pandas as pd

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--repo',type=Path,required=True)
parser.add_argument('--data-dir',type=Path,required=True)
parser.add_argument('--out',type=Path,required=True)
args=parser.parse_args()
BASE=args.out.resolve()
BASE.mkdir(parents=True,exist_ok=True)
if (BASE/'independent-validation.json').exists():
    raise FileExistsError('New audit output directory required')
REPO = args.repo.resolve()
RUN = REPO/'economic-atlas/runs/Consumption_restructuring_forecast_20261005_v2'
INPUT = args.data_dir.resolve()
MONTHS = [f'{year}-{month:02d}' for year in [2023, 2024] for month in range(1, 13)]
CATS = ['Все категории','Здоровье','Маркетплейсы','Общественное питание','Продовольствие','Транспорт']
MODELS = ['profile_ses','category_seasonal','growth_naive3','calibration','own_ridge','peer_ridge']
CHECKS = {}
def check(name, n=1):
    CHECKS[name] = CHECKS.get(name,0)+int(n)
def save(path,x):
    path.write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def hash_file(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

manifest=json.loads((RUN/'release-manifest.json').read_text())
for p,h in manifest['files'].items():
    assert hash_file(REPO/p)==h,p
check('release_file_hashes',len(manifest['files']))
proto=json.loads((RUN/'protocol.json').read_text())
for name,path in [('panel',REPO/'economic-atlas/data/panel_v1.parquet'),('population',INPUT/'2_bdmo_population.parquet'),('dictionary',INPUT/'municipal_dictionary.parquet')]:
    assert hash_file(path)==proto['input_sha256'][name],name
check('frozen_input_hashes',3)
panel=pd.read_parquet(REPO/'economic-atlas/data/panel_v1.parquet')
raw=pd.read_parquet(INPUT/'8_consumption.parquet').rename(columns={'date':'ym'})
tids=np.sort(panel.territory_id.unique())
truth=panel.set_index(['territory_id','ym','category']).value.sort_index()
original=raw[raw.territory_id.isin(tids)].set_index(['territory_id','ym','category']).value.sort_index()
np.testing.assert_array_equal(truth.to_numpy(),original.to_numpy())
assert truth.index.equals(original.index)
assert len(truth)==1896*24*6 and truth.index.is_unique
check('panel_raw_records',len(truth))
values=np.stack([panel[panel.category==c].pivot(index='territory_id',columns='ym',values='value').loc[tids,MONTHS].to_numpy(float) for c in CATS],axis=2)
assert np.isfinite(values).all() and (values>0).all()
population=pd.read_parquet(INPUT/'2_bdmo_population.parquet')
dictionary=pd.read_parquet(INPUT/'municipal_dictionary.parquet').set_index('territory_id')
pop=population.loc[(population.year==2023)&(population.period=='год')&(population.age=='Всего')]
def distinct_value(s):
    unique=s.dropna().unique()
    return float(unique[0]) if len(unique)==1 else np.nan
pop=pop.groupby(['territory_id','gender']).value.agg(distinct_value).unstack()
population_total=pop[['Мужчины','Женщины']].sum(axis=1,min_count=2)
population_total=population_total.where(population_total>0)
# Rebuild every 2023 covariate from raw numbers.
share=100*values[:,:,1:]/values[:,:,0,None]
f=pd.DataFrame(index=pd.Index(tids,name='territory_id'))
f['population_2023']=population_total.reindex(tids)
for j,c in enumerate(CATS[1:]):
    f['share_'+c]=(share[:,:12,j]/100).mean(1)
f['log_population_2023']=np.log(population_total.reindex(tids))
f['log_mean_all_2023']=np.log(values[:,:12,0].mean(1))
times=np.arange(12)-5.5
f['log_all_slope_2023']=(np.log(values[:,:12,0])*times).sum(1)/(times**2).sum()
f['log_all_std_2023']=np.log(values[:,:12,0]).std(1)
cols=['share_'+c for c in CATS[1:]]+['log_population_2023','log_mean_all_2023','log_all_slope_2023','log_all_std_2023']
stored=pd.read_parquet(RUN/'pre-2024-features.parquet').set_index('territory_id').loc[tids]
np.testing.assert_allclose(f[cols],stored[cols],equal_nan=True,atol=1e-12,rtol=1e-12)
check('pre_2024_covariates',len(f)*len(cols))
f=f.join(dictionary)
eligible=f.loc[(f.year_from<=2023)&(f.year_to>=2024)].dropna(subset=cols+['type'])
z=(eligible[cols]-eligible[cols].mean())/eligible[cols].std(ddof=0).replace(0,1)
matching=pd.read_csv(RUN/'peers.csv')
peers=np.full((len(tids),10),-1,int)
supported=np.zeros(len(tids),bool)
positions={int(t):i for i,t in enumerate(tids)}
peer_rows=0
for tid,row in eligible.iterrows():
    pool=eligible[(eligible.type==row.type)&(eligible.population_2023>=.5*row.population_2023)&(eligible.population_2023<=2*row.population_2023)&(eligible.index!=tid)]
    distances=((z.loc[pool.index]-z.loc[tid])**2).sum(1)**.5
    ranked=pd.DataFrame({'tid':pool.index,'distance':distances.to_numpy()})
    ranked=ranked[ranked.distance<=3].sort_values(['distance','tid'])
    actual=matching[matching.territory_id==tid]
    i=positions[int(tid)]
    if len(ranked)<5:
        assert actual.status.tolist()==['NO_MATCH_SUPPORT']
        continue
    supported[i]=True
    actual=actual.sort_values('rank')
    selected=ranked.head(10)
    assert actual.peer_tid.astype(int).tolist()==selected.tid.astype(int).tolist(),tid
    np.testing.assert_allclose(actual.distance,selected.distance,atol=1e-11,rtol=1e-11)
    for rank,pt in enumerate(selected.tid):
        peers[i,rank]=positions[int(pt)]
    peer_rows+=len(selected)
assert len(eligible)==1586 and supported.sum()==1539
check('independent_peer_pairs',peer_rows)
dy=share[:,12:]-share[:,:12]
logs=np.log(values[:,12:]/values[:,:12])
nominal=100*(values[:,12:]/values[:,:12]-1)
common_dy=np.empty_like(dy)
common_log=np.empty_like(logs)
# Deliberately simpler algorithm than production's rank-based leave-one-out.
for i in range(len(tids)):
    common_dy[i]=np.median(np.delete(dy,i,axis=0),axis=0)
    common_log[i]=np.median(np.delete(logs,i,axis=0),axis=0)
common_gap=dy-common_dy
gap=np.full_like(dy,np.nan);mad=np.full_like(dy,np.nan)
log_gap=np.full_like(logs,np.nan);nominal_gap=np.full_like(nominal,np.nan)
for i in np.flatnonzero(supported):
    pp=peers[i][peers[i]>=0]
    m=np.median(dy[pp],axis=0)
    gap[i]=dy[i]-m
    mad[i]=np.median(np.abs(dy[pp]-m),axis=0)
    log_gap[i]=logs[i]-np.median(logs[pp],axis=0)
    nominal_gap[i]=nominal[i]-np.median(nominal[pp],axis=0)
score=gap/np.maximum(1.4826*mad,.25)
flag=(abs(gap)>=1)&(abs(score)>=3)&(gap*common_gap>0)
saved=np.load(RUN/'deviations.npz')
for name,value in [('share',share),('dy',dy),('gap',gap),('common_gap',common_gap),('score',score),('flag',flag),('nominal',nominal),('nominal_gap',nominal_gap)]:
    np.testing.assert_allclose(saved[name],value,equal_nan=True,atol=2e-11,rtol=2e-11)
    check('independent_deviation_cells',value.size)
persistent=np.zeros((len(tids),5),bool)
for i in range(len(tids)):
    for j in range(5):
        for start in range(6,10):
            if flag[i,start:start+3,j].all() and len(set(np.sign(gap[i,start:start+3,j])))==1:
                persistent[i,j]=True
records=json.loads((RUN/'anomalies.json').read_text())
assert [r['territory_id'] for r in records]==tids.tolist()
for i,r in enumerate(records):
    assert r['supported']==bool(supported[i])
    for j,c in enumerate(CATS[1:]):
        if not supported[i]:
            assert r[c] is None
            continue
        expected={'share_2023':share[i,:12,j].mean(),'share_2024':share[i,12:,j].mean(),
            'annual_change_pp':dy[i,:,j].mean(),'q4_peer_gap_pp':np.median(gap[i,9:,j]),
            'q4_common_gap_pp':np.median(common_gap[i,9:,j]),'persistent':bool(persistent[i,j]),
            'flagged_h2_months':int(flag[i,6:,j].sum()),'max_abs_score':abs(score[i,:,j]).max(),
            'nominal_confirmation_months':int((abs(nominal_gap[i,6:,j+1])>=5).sum())}
        for k,v in expected.items():
            assert np.isclose(r[c][k],v,atol=2e-11,rtol=2e-11),(r['territory_id'],c,k)
        check('anomaly_summary_fields',len(expected))
assert persistent[:,1].sum()==25
assert sum(any(persistent[i,j] for j in [0,2,3,4]) for i in np.flatnonzero(persistent[:,1]))==2
print(json.dumps({'phase':'independent raw, peers, anomalies passed','checks':CHECKS}),flush=True)
# Original equations implemented independently, with no imported baseline.
category_median=np.median(values,axis=0)
def baseline(c,origin,target):
    history=values[:,:origin+1,c]
    m=category_median[:origin+1,c]
    u=np.log(history/m)
    season=.7*(u[:,:12]-u[:,:12].mean(1,keepdims=True))
    x=u-season[:,np.arange(origin+1)%12]
    # Solve each alpha separately rather than production's alpha-matrix path.
    candidates=[];losses=[]
    for a in np.linspace(.05,.95,19):
        level=x[:,0].copy();loss=np.zeros(len(tids))
        for j in range(1,origin+1):
            loss+=abs(x[:,j]-level)
            level=(1-a)*level+a*x[:,j]
        candidates.append(level);losses.append(loss)
    candidates=np.stack(candidates,axis=1);losses=np.stack(losses,axis=1)
    level=candidates[np.arange(len(tids)),losses.argmin(1)]
    recent=np.arange(max(12,origin-2),origin+1)
    factor=m[target-12]*np.exp(np.mean(np.log(m[recent]/m[recent-12])))
    profile=np.exp(level+season[:,target%12])*factor
    seasonal=history[:,origin]*m[target-12]/m[origin-12]
    growth3=history[:,target-12]*history[:,recent].sum(1)/history[:,recent-12].sum(1)
    return {'profile_ses':profile,'category_seasonal':seasonal,'growth_naive3':growth3}
pred=pd.read_parquet(RUN/'predictions.parquet')
forecast_groups={(c,o,t):g for (c,o,t),g in pred.groupby(['category','origin','target'])}
cache={}
for (cat,origin,target),group in pred.groupby(['category','origin','target']):
    c,oi,ti=CATS.index(cat),MONTHS.index(origin),MONTHS.index(target)
    b=baseline(c,oi,ti);cache[c,oi,ti]=b
    assert np.array_equal(group.territory_id.to_numpy(),tids)
    np.testing.assert_array_equal(group.actual,values[:,ti,c])
    for name,val in b.items():
        np.testing.assert_allclose(group[name],val,atol=1e-7,rtol=1e-10)
        check('independent_baseline_values',len(val))
# Rebuild both feature matrices and every stored regression fit.
own_x=np.stack([common_gap[:,:,1],(logs-common_log)[:,:,2],
                (logs-common_log)[:,:,0],common_gap[:,:,3],(logs-common_log)[:,:,4]],axis=2)
peer_x=np.concatenate([own_x,np.stack([gap[:,:,1],log_gap[:,:,2],
                     log_gap[:,:,0],gap[:,:,3],log_gap[:,:,4]],axis=2)],axis=2)
ix=np.flatnonzero(supported)
for c in range(6):
    for oi in range(12,23):
        if (c,oi,oi+1) not in cache:
            cache[c,oi,oi+1]=baseline(c,oi,oi+1)
fits=json.loads((RUN/'fits.json').read_text())
for fit in fits:
    c,oi,ti=CATS.index(fit['category']),MONTHS.index(fit['origin']),MONTHS.index(fit['target'])
    group=forecast_groups[fit['category'],fit['origin'],fit['target']].set_index('territory_id').loc[tids[ix]]
    if fit['status']=='COLD_START':
        assert oi<14
        np.testing.assert_array_equal(group[fit['model']],group.profile_ses)
        check('cold_start_values',len(ix))
        continue
    assert fit['last_training_target']==MONTHS[oi]
    assert fit['training_origins']==MONTHS[12:oi]
    assert fit['training_rows']==len(ix)*(oi-12)
    y=np.concatenate([np.log(values[ix,u+1,c]/cache[c,u,u+1]['profile_ses'][ix]) for u in range(12,oi)])
    if fit['model']=='calibration':
        np.testing.assert_allclose(y.mean(),fit['intercept'],atol=1e-12)
        correction=np.full(len(ix),np.clip(y.mean(),-.1,.1))
    else:
        matrix=own_x if fit['model']=='own_ridge' else peer_x
        x=np.concatenate([matrix[ix,u-12] for u in range(12,oi)])
        mean=x.mean(0);scale=x.std(0);scale[scale==0]=1
        design=np.c_[np.ones(len(x)),(x-mean)/scale]
        penalty=np.zeros((x.shape[1],x.shape[1]+1));penalty[:,1:]=np.sqrt(.1*len(x))*np.eye(x.shape[1])
        coef=np.linalg.lstsq(np.r_[design,penalty],np.r_[y,np.zeros(x.shape[1])],rcond=None)[0]
        np.testing.assert_allclose(mean,fit['mean'],atol=1e-11,rtol=1e-11)
        np.testing.assert_allclose(scale,fit['scale'],atol=1e-11,rtol=1e-11)
        np.testing.assert_allclose(coef,[fit['intercept']]+fit['beta'],atol=1e-10,rtol=1e-8)
        current=np.c_[np.ones(len(ix)),(matrix[ix,oi-12]-mean)/scale]
        correction=np.clip(current@coef,-.1,.1)
        check('independent_regression_fits')
    expected=cache[c,oi,ti]['profile_ses'][ix]*np.exp(correction)
    np.testing.assert_allclose(expected,group[fit['model']],atol=1e-6,rtol=1e-10)
    check('independent_corrected_predictions',len(ix))
# Direct metrics, with fixed mask, no study summarize() call.
metrics=json.loads((RUN/'metrics.json').read_text())
summary=[]
for q in metrics['results']:
    group=pred[pred.supported&(pred.category==q['category'])&(pred.horizon==q['horizon'])]
    assert len(group)==9234 and group.territory_id.nunique()==1539
    for name in MODELS:
        error=float(np.mean(abs(group.actual.to_numpy()-group[name].to_numpy())))
        assert np.isclose(error,q['mae'][name],atol=1e-10)
        check('independent_metrics')
    for comparison in q['comparisons']:
        gain=abs(group.actual-group[comparison['reference']])-abs(group.actual-group[comparison['model']])
        for label,seed,key in [('target',20261005,'ci95_month_blocks'),('region_code',20261006,'ci95_region_blocks_sensitivity')]:
            _,inverse=np.unique(group[label].to_numpy(),return_inverse=True)
            sums=np.bincount(inverse,weights=gain.to_numpy());counts=np.bincount(inverse)
            draws=np.random.default_rng(seed).integers(0,len(sums),(10000,len(sums)))
            distribution=sums[draws].sum(1)/counts[draws].sum(1)
            np.testing.assert_allclose(np.quantile(distribution,[.025,.975]),comparison[key],atol=1e-8,rtol=1e-10)
            check('independent_bootstrap_intervals')
    if q['category'] in ['Все категории','Маркетплейсы']:
        summary.append({'category':q['category'],'horizon':q['horizon'],'mae':q['mae']})
# Static artifact data checks, no browser execution or blocked URL access.
html=(REPO/'economic-atlas/site/consumption-restructuring-20261005/index.html').read_text()
data=json.loads(html.split('const DATA=',1)[1].split(';\nconst $',1)[0])
assert data['metrics']==metrics and len(data['territories'])==1896
map_groups={(int(t),int(h)):g.sort_values('target') for (t,h),g in pred[pred.category=='Все категории'].groupby(['territory_id','horizon'])}
for i,row in enumerate(data['territories']):
    tid=row['territory_id'];assert tid==int(tids[i])
    assert row['peers']==tids[peers[i][peers[i]>=0]].tolist() if supported[i] else row['peers']==[]
    for key,source in [('name','name_short'),('region_name','region_name'),('type','type'),('lat','lat'),('lon','lon')]:
        assert row[key]==dictionary.loc[tid,source],(tid,key)
    for c in CATS[1:]:
        assert row[c]==records[i][c]
        j=CATS[1:].index(c)
        for name,value in [('dy',dy[i,:,j]),('gap',gap[i,:,j]),('common_gap',common_gap[i,:,j]),('score',score[i,:,j]),('nominal_gap',nominal_gap[i,:,j+1])]:
            actual=np.array([np.nan if v is None else v for v in row['series'][c][name]])
            np.testing.assert_allclose(actual,np.round(value,4),equal_nan=True,atol=0,rtol=0)
            check('map_monthly_values',len(actual))
        assert row['series'][c]['flag']==flag[i,:,j].astype(int).tolist()
        check('map_monthly_flags',12)
    for h in [1,3,6]:
        p=map_groups[tid,h]
        for field,column in [('actual','actual'),('base','profile_ses'),('peer','peer_ridge')]:
            expected=np.round(p[column].to_numpy(),4)
            actual=np.array([np.nan if v is None else v for v in row['forecast'][str(h)][field]])
            np.testing.assert_allclose(expected,actual,equal_nan=True,atol=0,rtol=0)
            check('map_forecast_values',len(expected))
# Diagnose errors without fitting or selecting an alternative model.
diagnostics=[]
for (cat,h),g in pred[pred.supported&pred.category.isin(['Все категории','Маркетплейсы'])].groupby(['category','horizon']):
    error={m:abs(g.actual-g[m]) for m in ['profile_ses','calibration','own_ridge','peer_ridge']}
    diagnostics.append({'category':cat,'horizon':int(h),
        'calibration_mae':float(error['calibration'].mean()),
        'bias_corrected_with_own_features_mae':float(error['own_ridge'].mean()),
        'bias_corrected_with_peers_mae':float(error['peer_ridge'].mean()),
        'feature_gain_vs_calibration_percent':float(100*(error['calibration'].mean()-error['peer_ridge'].mean())/error['calibration'].mean()),
        'peer_increment_vs_own_percent':float(100*(error['own_ridge'].mean()-error['peer_ridge'].mean())/error['own_ridge'].mean()),
        'profile_ses_mae':float(error['profile_ses'].mean())})
result={'status':'PASS_NUMERICAL','checked_at_utc':datetime.now(timezone.utc).isoformat(),
    'code_sha256':hash_file(Path(__file__)),
    'versions':{'python':platform.python_version(),'numpy':np.__version__,'pandas':pd.__version__},
    'source_release_sha256':hash_file(RUN/'release-manifest.json'),'checks':CHECKS,
    'independent_imports':'Only numpy/pandas/stdlib; no study source imported',
    'summary':summary,'calibration_diagnostic':diagnostics,
    'live_browser_rechecked':False,'browser_limit':'Browser tool security policy rejected localhost tab; no workaround used',
    'scientific_scope':'Already viewed 2024, retrospective complete panel and dictionary; no asof or independent holdout verification'}
save(BASE/'independent-validation.json',result)
print(json.dumps({'status':result['status'],'checks':CHECKS,'summary':summary},ensure_ascii=False),flush=True)
