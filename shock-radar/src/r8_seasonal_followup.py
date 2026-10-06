"""Independent R8 cache audit and fixed R9 baseline transfer; never scientific PASS."""
from pathlib import Path
import argparse,json,hashlib,datetime,itertools,sys,math,csv
import numpy as np
import pandas as pd

KEY=['territory_id','category','origin','target','horizon']
MODELS=['growth_naive1','growth_naive3','category_seasonal','conditional_ses','profile_ses']
CONTROLS=['pred_prophet','pred_lastavailable','pred_seasonal_naive','pred_tsfm']
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def dump(p,d):Path(p).write_text(json.dumps(d,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def exact_interval(g,model,control):
 d=pd.DataFrame({'target':g.target,'benefit':np.abs(g.actual-g[control])-np.abs(g.actual-g[model])})
 blocks=d.groupby('target',sort=True).benefit.agg(['sum','count']); sums=blocks['sum'].to_numpy(); counts=blocks['count'].to_numpy()
 ix=np.asarray(list(itertools.product(range(len(blocks)),repeat=len(blocks))),dtype=int)
 draws=np.sort(sums[ix].sum(1)/counts[ix].sum(1))
 return {'point':float(d.benefit.mean()),'lo':float(draws[int(.025*(len(draws)-1))]),'hi':float(draws[int(.975*(len(draws)-1))]),'target_blocks':len(blocks),'draws':len(draws),'method':'exact month-block all k^k; ratio-of-sums nearest-rank percentiles; descriptive'}
def summaries(df,models):
 out=[]
 for label,g in [('all',df)]+[(f'h{h}',g) for h,g in df.groupby('horizon',sort=True)]:
  if g.empty:continue
  out.append({'scope':label,'rows':len(g),'months':sorted(g.target.unique().tolist()),'mae':{m:float(np.abs(g.actual-g[m]).mean()) for m in models},'benefit_vs_last':{m:exact_interval(g,m,'pred_lastavailable') for m in models if m!='pred_lastavailable'},'benefit_vs_prophet':{m:exact_interval(g,m,'pred_prophet') for m in models if m not in ('pred_prophet','pred_lastavailable')}})
 return out

def run(repo,out,protocol):
 repo=repo.resolve();out.mkdir(parents=True,exist_ok=True);p=json.loads(protocol.read_text());initial_protocol_sha=sha(protocol)
 paths={'raw':repo/'data/raw/sberindex-data-sense-2025/8_consumption.parquet','prophet':repo/'shock-radar/runs/R8_prophet_full_20260927/predictions.parquet','tsfm':repo/'shock-radar/runs/R8_tsfm_deterministic_20260928/predictions.parquet','frozen_models':repo/'shock-radar/src/r9_strong_baselines.py','old_decision':repo/'shock-radar/runs/R8_closeout_20260929/decision.json'}
 assert {k:sha(v) for k,v in paths.items()}==p['input_sha256']
 old=json.loads(paths['old_decision'].read_text());a=pd.read_parquet(paths['prophet']);b=pd.read_parquet(paths['tsfm'])
 for d in (a,b):
  d['territory_id']=d.territory_id.astype(str)
  for k in ('category','origin','target'):d[k]=d[k].astype(str)
  assert not d.duplicated(KEY).any();assert len(d)==171150
 x=a.merge(b,on=KEY,validate='one_to_one',suffixes=('','_tsfm'),how='outer',indicator=True)
 assert (x['_merge']=='both').all() and len(x)==171150
 for c in ('actual','pred_prophet','pred_lastavailable','pred_seasonal_naive'):
  assert np.array_equal(x[c].to_numpy(),x[c+'_tsfm'].to_numpy()),c
 assert np.isfinite(x[['actual']+CONTROLS].to_numpy(float)).all()
 old_metrics={m:float(np.abs(x.actual-x[col]).mean()) for m,col in [('prophet','pred_prophet'),('lastavailable','pred_lastavailable'),('seasonal_naive','pred_seasonal_naive'),('tsfm','pred_tsfm')]}
 assert all(np.isclose(v,old['mae'][k],rtol=0,atol=1e-8) for k,v in old_metrics.items())
 original_ci=exact_interval(x,'pred_prophet','pred_lastavailable')
 for k in ('point','lo','hi'):assert np.isclose(original_ci[k],old['month_block_benefit_95pct']['prophet_vs_lastavailable'][k],rtol=0,atol=1e-8)
 raw=pd.read_parquet(paths['raw']);raw['territory_id']=raw.territory_id.astype(str);raw['month']=pd.PeriodIndex(raw.date,freq='M').astype(str)
 assert not raw.duplicated(['territory_id','category','month']).any();assert np.isfinite(raw.value.to_numpy(float)).all() and (raw.value>0).all()
 months=[str(pd.Period('2023-01',freq='M')+j) for j in range(24)]
 tables={c:g.pivot(index='territory_id',columns='month',values='value').reindex(columns=months).astype(float) for c,g in raw.groupby('category')}
 medmap={c:g.groupby('month').value.median().reindex(months).to_numpy(float) for c,g in raw.groupby('category')}
 sys.path.insert(0,str(repo/'shock-radar/src'));from r9_strong_baselines import predict_block
 prediction=[];future_checked=0;own_scalar_checked=0;cutoff_checked=0;truth_checked=0
 for (cat,origin,target),g in x.groupby(['category','origin','target'],sort=True):
  origin_idx=months.index(origin);oi=origin_idx-2;ti=months.index(target);table=tables[cat];v=table.to_numpy(float);med=medmap[cat]
  ix=table.index.get_indexer(g.territory_id);assert (ix>=0).all()
  assert np.array_equal(v[ix,ti],g.actual.to_numpy(float));truth_checked+=len(g)
  # The historical baseline used exactly the last OBSERVED value before cutoff, including gaps.
  known=v[ix,:oi+1];idx=np.where(np.isfinite(known),np.arange(oi+1)[None,:],-1).max(1)
  assert (idx>=0).all();assert np.array_equal(known[np.arange(len(g)),idx],g.pred_lastavailable.to_numpy(float));cutoff_checked+=len(g)
  assert (g.horizon.to_numpy()==ti-origin_idx).all()
  pp=predict_block(v,med,oi,ti)
  changed=v.copy();changed[:,oi+1:]=1_000_000.+np.arange(24-oi-1);mm=med.copy();mm[oi+1:]=2_000_000.+np.arange(24-oi-1)
  qq=predict_block(changed,mm,oi,ti)
  for name in MODELS:
   assert np.array_equal(pp[name][ix],qq[name][ix],equal_nan=True),name
   future_checked+=int(np.isfinite(pp[name][ix]).sum())
  # Scalar ratio checks independently implement only own-series formulas, not the imported vector function.
  k=min(3,oi-11)
  for j in ix:
   vj=v[j]
   if np.isfinite(pp['growth_naive1'][j]):
    expected=vj[ti-12]*vj[oi]/vj[oi-12];assert np.isclose(pp['growth_naive1'][j],expected,rtol=1e-12,atol=1e-8);own_scalar_checked+=1
   if np.isfinite(pp['growth_naive3'][j]):
    expected=vj[ti-12]*sum(vj[q] for q in range(oi-k+1,oi+1))/sum(vj[q-12] for q in range(oi-k+1,oi+1))
    assert np.isclose(pp['growth_naive3'][j],expected,rtol=1e-12,atol=1e-8);own_scalar_checked+=1
  prediction.append(g[KEY].assign(**{m:pp[m][ix] for m in MODELS}))
 q=pd.concat(prediction,ignore_index=True);assert not q.duplicated(KEY).any();x=x.merge(q,on=KEY,how='left',validate='one_to_one')
 x[KEY+['actual']+CONTROLS+MODELS].to_parquet(out/'predictions.parquet',index=False)
 common=x[MODELS].notna().all(1); own_common=x[['growth_naive1','growth_naive3']].notna().all(1)
 assert np.isfinite(x.loc[common,MODELS].to_numpy(float)).all()
 original=summaries(x,CONTROLS);all_common=summaries(x.loc[common],CONTROLS+MODELS);own_results=summaries(x.loc[own_common],CONTROLS+['growth_naive1','growth_naive3'])
 loo=[]
 for target in sorted(x.target.unique()):
  g=x[x.target!=target];loo.append({'excluded_target':target,'rows':len(g),'prophet_benefit':float((np.abs(g.actual-g.pred_lastavailable)-np.abs(g.actual-g.pred_prophet)).mean())})
 modelwise=[]
 for m in MODELS:
  g=x[x[m].notna()]; modelwise.append({'model':m,'rows':len(g),'missing_rows':int(x[m].isna().sum()),'mae':float(np.abs(g.actual-g[m]).mean()),'mae_prophet_same_rows':float(np.abs(g.actual-g.pred_prophet).mean()),'mae_last_same_rows':float(np.abs(g.actual-g.pred_lastavailable).mean()),'benefit_vs_last':exact_interval(g,m,'pred_lastavailable'),'benefit_vs_prophet':exact_interval(g,m,'pred_prophet')})
 results={'checked_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'status':'COMPUTED_EXPLORATORY_FIXED_MODEL_TRANSFER','scientific_pass':False,'historical_asof':False,'independent_holdout':False,'original_R8_gate_pass':False,'original_R8_unchanged':True,'protocol_sha256':initial_protocol_sha,'versions':{'python':sys.version.split()[0],'numpy':np.__version__,'pandas':pd.__version__},'original_full_mask':original,'original_exact_interval':original_ci,'original_leave_one_month_out':loo,'same_own_information_models':['growth_naive1','growth_naive3'],'broader_category_information_models':['category_seasonal','conditional_ses','profile_ses'],'all_models_common_rows':int(common.sum()),'all_models_excluded_rows':int((~common).sum()),'all_models_common_mask':all_common,'own_models_common_mask':own_results,'per_model_full_valid_mask':modelwise,'checks':{'raw_target_truth_rows':truth_checked,'stored_last_actual_cutoff_rows':cutoff_checked,'future_mutation_valid_forecasts':future_checked,'independent_scalar_own_forecasts':own_scalar_checked,'exact_join_rows':len(x),'stored_controls_identical':True},'limits':['Post hoc inspected six-month window, no preregistration or independent test','Two-month lag assumed; historical revision/vintage unknown','Month bootstrap uses few shared shock/seasonal blocks; descriptive CIs only','No news effects or early-warning conclusion; no new fits of Prophet/Chronos','Own information comparators receive own history only; category models receive more information','No subgroup/model winner chosen after observing results; all five fixed transfers shown']}
 assert sha(protocol)==initial_protocol_sha;assert {k:sha(v) for k,v in paths.items()}==p['input_sha256']
 dump(out/'results.json',results)
 with (out/'summary.csv').open('w',newline='') as f:
  w=csv.DictWriter(f,fieldnames=['scope','rows','model','mae','benefit_vs_last','ci_lo','ci_hi','month_blocks','information_set']);w.writeheader()
  for y in all_common:
   for m in MODELS:
    ci=y['benefit_vs_last'][m];w.writerow({'scope':y['scope'],'rows':y['rows'],'model':m,'mae':y['mae'][m],'benefit_vs_last':ci['point'],'ci_lo':ci['lo'],'ci_hi':ci['hi'],'month_blocks':ci['target_blocks'],'information_set':'own' if m.startswith('growth') else 'category_panel'})
 dump(out/'manifest.json',{'code_sha256':sha(__file__),'protocol_sha256':initial_protocol_sha,'inputs':p['input_sha256'],'outputs':{f.name:sha(f) for f in out.iterdir() if f.is_file() and f.name!='manifest.json'}})
 print(json.dumps({'status':results['status'],'checks':results['checks'],'common_rows':results['all_models_common_rows'],'models':modelwise,'old_interval':original_ci,'scientific_pass':False},ensure_ascii=False),flush=True)
if __name__=='__main__':
 a=argparse.ArgumentParser();a.add_argument('--repo',type=Path,required=True);a.add_argument('--out',type=Path,required=True);a.add_argument('--protocol',type=Path,required=True);args=a.parse_args();run(args.repo,args.out,args.protocol)
