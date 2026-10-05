"""Frozen exploratory external-data checks: national H12 and legal flood zone.

Neither a historical as-of test nor a causal effect estimator. No threshold,
lag, category or municipality is selected by the observed outcomes.
"""
from pathlib import Path
import argparse,hashlib,json
from datetime import datetime,timezone
import numpy as np
import pandas as pd
from r9_strong_baselines import predict

RAW_SHA='9833ddaaee7b2a182ed4cceeed16469031700ea87d508bd976150c6770ef8a61'
DICT_SHA='f25088539a896cdc834d77c8792d0e6ac909d8649b06d65f69215ce12a8eaf4a'

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def dump(p,x):Path(p).write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def check(p,h):
 if sha(p)!=h:raise ValueError('Frozen SHA mismatch: '+str(p))

def load_raw(path):
 check(path,RAW_SHA);d=pd.read_parquet(path)
 d['territory_id']=d.territory_id.astype(str)
 d['month']=pd.PeriodIndex(d.date,freq='M').astype(str)
 if d.duplicated(['territory_id','category','month']).any():raise ValueError('Duplicate raw keys')
 return d

def national_factor(series,origin,lag):
 op=pd.Period(origin,freq='M');a=str(op-lag);b=str(op-lag-12)
 history=series.loc[series.index<=a]
 if a not in history or b not in history or history[b]<=0:return np.nan
 return float(history[a]/history[b])

def paired(g,model,ref):
 error=np.abs(g.actual-g[model]);base=np.abs(g.actual-g[ref]);diff=base-error
 blocks=pd.DataFrame({'month':g.target,'sum':diff}).groupby('month')['sum'].agg(['sum','count'])
 ix=np.random.default_rng(20261005).integers(0,len(blocks),(10000,len(blocks)))
 boot=blocks['sum'].to_numpy()[ix].sum(1)/blocks['count'].to_numpy()[ix].sum(1)
 return {'model':model,'reference':ref,'rows':len(g),'mae_model':float(error.mean()),'mae_reference':float(base.mean()),
         'relative_improvement_percent':float(100*(1-error.mean()/base.mean())),
         'benefit_mae':float(diff.mean()),'benefit_ci95_month_blocks':np.quantile(boot,[.025,.975]).tolist(),'month_blocks':len(blocks)}

def national(a,proto,out):
 raw=load_raw(a.raw);check(a.r9,proto['r9_sha256']);check(a.national,proto['input_sha256'])
 n=pd.read_parquet(a.national)
 if set(n.unit_measure)!= {'млрд. руб.'} or set(n.freq)!= {'Месяц'}:raise ValueError('National units/frequency differ')
 n['month']=pd.to_datetime(n.period,utc=True).dt.tz_convert('Europe/Moscow').dt.tz_localize(None).dt.to_period('M').astype(str)
 n=n.loc[n.type==proto['national_type']].copy();n['value']=n.value.astype(float)
 if n.month.duplicated().any() or (n.value<=0).any():raise ValueError('Duplicate/nonpositive national observations')
 N=n.set_index('month').value.sort_index()
 allpred=pd.read_parquet(a.r9);d=allpred.loc[allpred.horizon==12].copy();d.territory_id=d.territory_id.astype(str)
 key=['territory_id','category','horizon','origin','target']
 if d.duplicated(key).any():raise ValueError('Duplicate R9 keys')
 expected=raw[['territory_id','category','month','value']]
 d=d.merge(expected.rename(columns={'month':'origin','value':'own_origin'}),on=['territory_id','category','origin'],how='left',validate='many_to_one')
 d=d.merge(expected.rename(columns={'month':'target','value':'raw_actual'}),on=['territory_id','category','target'],how='left',validate='many_to_one')
 np.testing.assert_allclose(d.own_origin,d.pred_last,rtol=0,atol=0)
 np.testing.assert_allclose(d.raw_actual,d.actual,rtol=0,atol=0)
 models=[]
 for lag in [1]+proto['sensitivity_lag_months']:
  m='national_yoy_lag'+str(lag);models.append(m)
  factor={o:national_factor(N,o,lag) for o in sorted(d.origin.unique())}
  d[m]=d.own_origin*d.origin.map(factor)
  # Actual raw mutation beyond each origin, not a mutation of cached forecasts.
  for o,g in d.groupby('origin'):
   altered=N.copy();cut=str(pd.Period(o,freq='M')-lag)
   altered.loc[altered.index>cut]=altered.loc[altered.index>cut]*100+12345
   assert national_factor(altered,o,lag)==factor[o]
   future=raw.copy();future.loc[future.month>o,'value']*=100
   own=future.loc[future.month==o].set_index(['territory_id','category']).value
   scalar=np.array([float(own.loc[(q.territory_id,q.category)])*national_factor(altered,o,lag) for q in g.itertuples()])
   np.testing.assert_allclose(scalar,g[m].to_numpy(),rtol=0,atol=0)
 finite=np.isfinite(d[models+['actual','pred_last','pred_prophet']]).all(axis=1)
 common=d.loc[finite].copy()
 if not len(common):raise ValueError('No common H12 mask')
 rows=[paired(common,m,ref) for m in models for ref in proto['controls']]
 bycat=[dict(category=c,**paired(g,m,ref)) for c,g in common.groupby('category') for m in models for ref in proto['controls']]
 bymonth=[{'target':t,'model':m,'rows':len(g),'mae':float(np.abs(g.actual-g[m]).mean())} for t,g in common.groupby('target') for m in models+proto['controls']]
 pd.DataFrame(bycat).to_csv(out/'by-category.csv',index=False);pd.DataFrame(bymonth).to_csv(out/'by-month.csv',index=False)
 result={'status':'COMPUTED_EXPLORATORY','scientific_pass':False,'original_rows':len(d),'common_rows':len(common),'excluded_rows':int((~finite).sum()),
 'national_observations':len(N),'national_range':[N.index.min(),N.index.max()],
 'results':rows,'checks':{'raw_last_and_actual_all_h12_keys':len(d),'scalar_and_future_mutation_all_forecasts':len(d)*len(models),'time_zone':'UTC source converted to Europe/Moscow calendar month'},
 'independent_holdout':False,'historical_asof_verified':False,'old_category_seasonal_h12':'still UNSUPPORTED; new national model is separate',
 'full_prophet_refit':False,'vintage':'2026-10-05, revisions unknown','national_units':'nominal billion RUB; municipal units different, only dimensionless ratio used'}
 dump(out/'metrics.json',result);print(json.dumps(result,ensure_ascii=False))

def flood(a,proto,out):
 raw=load_raw(a.raw);check(a.dictionary,DICT_SHA);dictionary=pd.read_parquet(a.dictionary)
 candidates=dictionary.loc[dictionary.region_code==proto['region_code']].copy()
 cross=[];accepted=[]
 for name in proto['cohort']:
  g=candidates.loc[candidates.name_short==name]
  record={'act_name':name,'region_code':proto['region_code'],'dictionary_candidates':g[['territory_id','name_short','type','year_from','year_to','oktmo']].to_dict('records')}
  valid=g.loc[(g.year_from<=2024)&(g.year_to>=2024)]
  # The act names municipal okrugs. A historical municipal district is not an exact identity match.
  if name!='Курган':valid=valid.loc[valid.type=='муниципальный округ']
  else:valid=valid.loc[valid.type=='городской округ']
  if len(valid)==1:
   tid=str(valid.iloc[0].territory_id);accepted.append((name,tid));record.update(status='EXACT_VALID_IDENTITY',territory_id=tid)
  else:record.update(status='BLOCKED_HISTORICAL_IDENTITY',reason='No unique valid2024 legal type; district-to-okrug crosswalk needed')
  cross.append(record)
 dump(out/'crosswalk.json',cross)
 categories=sorted(raw.category.unique());rows=[];missing=[]
 med=raw.groupby(['category','month']).value.median()
 for name,tid in accepted:
  for category in categories:
   own=raw.loc[(raw.territory_id==tid)&(raw.category==category)].set_index('month').value
   M=med.loc[category]
   for target in proto['targets']:
    forecast=predict(own,M,proto['forecast_origin'],target)
    for model in [proto['primary_model'],proto['sensitivity_model']]:
     pred=forecast[model]
     if target not in own or not np.isfinite(pred) or pred<=0:
      missing.append({'municipality':name,'category':category,'target':target,'model':model});continue
     rows.append({'municipality':name,'territory_id':tid,'category':category,'origin':proto['forecast_origin'],'target':target,'model':model,'actual':float(own[target]),'forecast':pred,'residual_percent':100*(float(own[target])/pred-1),'aggregate':category=='Все категории'})
 pd.DataFrame(rows).to_csv(out/'seasonal-residuals.csv',index=False)
 # A descriptive peer contrast, no matching on outcomes, no causal inference.
 peers=[];excluded={tid for _,tid in accepted}
 for (tid,category),g in raw.groupby(['territory_id','category']):
  if tid in excluded:continue
  own=g.set_index('month').value;M=med.loc[category]
  for target in proto['targets']:
   if target not in own:continue
   f=predict(own,M,proto['forecast_origin'],target)
   for model in [proto['primary_model'],proto['sensitivity_model']]:
    q=f[model]
    if np.isfinite(q) and q>0:peers.append({'category':category,'target':target,'model':model,'residual':100*(float(own[target])/q-1)})
 controls=pd.DataFrame(peers).groupby(['category','target','model']).residual.agg(['median','count'])
 controls.to_csv(out/'descriptive-peer-residuals.csv')
 result={'status':'PARTIAL_IDENTITY_BLOCKED','scientific_pass':False,'act_territories':len(proto['cohort']),'strict_matches':len(accepted),'identity_blocked':len(proto['cohort'])-len(accepted),'rows':len(rows),'missing_predictions':missing,
 'labels':'legal administrative emergency zone, not ground truth of economic damage or inundation','causal_effect_estimated':False,'precision_recall':None,'independent_holdout':False,'unpublished_30_list_used':False,
 'warning':'Governor act original PDF unavailable from Mac and joe; act text retrieved from legal mirror; regional type changes not silently joined'}
 dump(out/'metrics.json',result);print(json.dumps(result,ensure_ascii=False))

def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--mode',choices=['national','flood'],required=True)
 for name in ['raw','r9','national','dictionary','protocol','out']:p.add_argument('--'+name,type=Path)
 a=p.parse_args();proto=json.loads(a.protocol.read_text())
 a.out.mkdir(parents=True,exist_ok=False)
 dump(a.out/'protocol.json',proto)
 if a.mode=='national':national(a,proto,a.out)
 else:flood(a,proto,a.out)
 dump(a.out/'manifest.json',{'checked_at':datetime.now(timezone.utc).isoformat(),'scientific_pass':False,'source_sha256':sha(Path(__file__)),'files':{q.name:sha(q) for q in a.out.iterdir() if q.is_file()}})
if __name__=='__main__':main()
