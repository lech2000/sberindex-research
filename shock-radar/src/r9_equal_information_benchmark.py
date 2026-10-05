"""Bounded exploratory comparison; equal historical category inputs, no h12."""
from pathlib import Path
import argparse, hashlib, json, logging, os, sys
from datetime import datetime, timezone
import concurrent.futures as cf
import numpy as np
import pandas as pd

SEED=20261004
RAW_SHA='9833ddaaee7b2a182ed4cceeed16469031700ea87d508bd976150c6770ef8a61'
R9_SHA='b9726b7971c55e5c9f32cdfe439694ffc96f66d7b0c180725a7ad2dff68afe44'
KEY=['territory_id','category','horizon','origin','target']
MODELS=['category_seasonal','conditional_median3','prophet_yearly','conditional_prophet_yearly','stored_prophet','last_value']
CFG=dict(growth='linear',yearly_seasonality=3,weekly_seasonality=False,daily_seasonality=False,seasonality_mode='multiplicative',seasonality_prior_scale=1.0,n_changepoints=0,uncertainty_samples=0)
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def historical_inputs(raw,tid,cat,origin):
    history=raw[(raw.category==cat)&(raw.month<=origin)]
    med=history.groupby('month').value.median()
    own=history[history.territory_id==tid].sort_values('month')
    if len(own)<13 or own.month.duplicated().any():raise ValueError('Insufficient or duplicated training history')
    scale=med.reindex(own.month).to_numpy(float)
    if not np.isfinite(scale).all() or (scale<=0).any():raise ValueError('Invalid category base; no fill')
    return own,med,own.value.to_numpy(float)/scale
def references(med,origin,target):
    po=str(pd.Period(origin,freq='M')-12);pt=str(pd.Period(target,freq='M')-12)
    if pt>origin or po not in med or pt not in med:raise ValueError('Seasonal base unavailable')
    if med[po]<=0:raise ValueError('Zero base')
    return float(med[pt]/med[po]),float(med[origin])
def fit_task(item):
    from prophet import Prophet
    logging.getLogger('cmdstanpy').setLevel(logging.ERROR)
    logging.getLogger('prophet').setLevel(logging.ERROR)
    tid,cat,origin,own_values,months,med,targets=item
    train=pd.DataFrame({'ds':pd.to_datetime(months),'y':own_values})
    levels=np.array([med[m] for m in months]);conditional=train.assign(y=np.array(own_values)/levels)
    results={'raw':{},'conditional':{}};failures=[];fits=0
    future=pd.DataFrame({'ds':pd.to_datetime([t for h,t in targets])})
    for name,frame in [('raw',train),('conditional',conditional)]:
        try:
            model=Prophet(**CFG);model.fit(frame,seed=SEED);fits+=1
            vals=model.predict(future).yhat.to_numpy(float)
            if not np.isfinite(vals).all():raise ValueError('Nonfinite forecast')
            results[name]={t:float(v) for (h,t),v in zip(targets,vals)}
        except Exception as e:
            failures.append({'territory_id':tid,'category':cat,'origin':origin,'model':name,'error':str(e)})
    rows=[]
    for h,target in targets:
        ratio,mc=references(pd.Series(med),origin,target)
        rows.append({'territory_id':tid,'category':cat,'origin':origin,'target':target,'horizon':h,
            'category_seasonal':float(own_values[-1]*ratio),
            'conditional_median3':float(np.median(np.array(own_values[-3:])/levels[-3:])*mc*ratio),
            'prophet_yearly':results['raw'].get(target),
            'conditional_prophet_yearly':None if target not in results['conditional'] else results['conditional'][target]*mc*ratio})
    return rows,failures,fits
def self_check():
    rows=[]
    for tid,mult in [('a',2),('b',4)]:
        for j in range(24):rows.append({'territory_id':tid,'category':'c','month':str(pd.Period('2023-01',freq='M')+j),'value':mult*(10+j)})
    raw=pd.DataFrame(rows);own,med,z=historical_inputs(raw,'a','c','2024-01')
    changed=raw.copy();changed.loc[changed.month>'2024-01','value']=999999
    own2,med2,z2=historical_inputs(changed,'a','c','2024-01')
    assert own.equals(own2) and med.equals(med2) and np.array_equal(z,z2)
    factor,mc=references(med,'2024-01','2024-02');assert abs(factor-1.1)<1e-12
    assert abs(z[-1]*mc*factor-own.value.iloc[-1]*factor)<1e-12
    try:references(med,'2023-12','2024-12')
    except ValueError:pass
    else:raise AssertionError('Missing origin-12 accepted')
    print(json.dumps({'self_check':True,'checks':['future mutation invariance','known shared seasonal factor','conditional last equals candidate','missing annual base rejected']}))
def summaries(p):
    rng=np.random.default_rng(SEED);out=[]
    for (window,h),g in p.groupby(['window','horizon']):
        if g[MODELS].isna().any().any():raise ValueError('Unpaired failure; do not silently remove rows')
        errors={m:np.abs(g.actual-g[m]) for m in MODELS};mae={m:float(e.mean()) for m,e in errors.items()}
        comp={}
        for ref in [m for m in MODELS if m!='category_seasonal']:
            diff=errors[ref]-errors['category_seasonal'];blocks=pd.DataFrame({'target':g.target,'diff':diff}).groupby('target')['diff'].agg(['sum','count'])
            ix=rng.integers(0,len(blocks),(10000,len(blocks)));vals=blocks['sum'].to_numpy()[ix].sum(1)/blocks['count'].to_numpy()[ix].sum(1)
            comp[ref]={'benefit':float(diff.mean()),'ci95_target_months':np.quantile(vals,[.025,.975]).tolist(),'n_blocks':len(blocks)}
        out.append({'window':window,'horizon':int(h),'n':len(g),'mae':mae,'category_seasonal_benefit_vs':comp,
            'by_month':[{'target':t,'n':len(x),'mae':{m:float(np.abs(x.actual-x[m]).mean()) for m in MODELS}} for t,x in g.groupby('target')],
            'by_category':[{'category':c,'n':len(x),'mae':{m:float(np.abs(x.actual-x[m]).mean()) for m in MODELS}} for c,x in g.groupby('category')]})
    return out
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--raw',type=Path);ap.add_argument('--r9',type=Path);ap.add_argument('--out',type=Path);ap.add_argument('--workers',type=int,default=4);ap.add_argument('--self-check',action='store_true');a=ap.parse_args()
    if a.self_check:self_check();return
    if a.out.exists():raise FileExistsError('New output directory required')
    if sha(a.raw)!=RAW_SHA or sha(a.r9)!=R9_SHA:raise ValueError('Frozen inputs mismatch')
    raw=pd.read_parquet(a.raw);raw['territory_id']=raw.territory_id.astype(str);raw['month']=pd.PeriodIndex(raw.date,freq='M').astype(str)
    if raw.duplicated(['territory_id','category','month']).any() or not np.isfinite(raw.value).all():raise ValueError('Invalid source')
    r9=pd.read_parquet(a.r9);r9['territory_id']=r9.territory_id.astype(str);r9=r9[r9.horizon.isin([1,3,6])]
    counts=r9.groupby(['territory_id','category']).size();complete=raw.groupby(['territory_id','category']).agg(n=('month','size'),train_mean=('value',lambda s:float(s.iloc[:12].mean())))
    # Sorting is explicit; selection magnitudes use 2023 only, availability uses the frozen exploratory mask.
    means=raw[raw.month<='2023-12'].groupby(['territory_id','category']).value.mean()
    eligible=complete[(complete.n==24)&(counts.reindex(complete.index)==18)].copy();eligible['train_mean']=means.reindex(eligible.index)
    rng=np.random.default_rng(SEED);selected=[]
    for cat,g in eligible.reset_index().groupby('category',sort=True):
        g=g.sort_values(['train_mean','territory_id']).reset_index(drop=True)
        for stratum,part in enumerate(np.array_split(np.arange(len(g)),4)):
            if len(part)<5:raise ValueError('Stratum smaller than frozen quota')
            for idx in sorted(rng.choice(part,size=5,replace=False)):selected.append({'territory_id':str(g.iloc[idx].territory_id),'category':cat,'size_stratum_2023':stratum})
    assert len(selected)==120
    keys={(x['territory_id'],x['category']) for x in selected};mask=r9[[KEY[0],KEY[1]]].apply(tuple,axis=1).isin(keys);mainmask=r9[mask].copy()
    ownmap=raw.set_index(['territory_id','category','month']).value
    early=[]
    for tid,cat in sorted(keys):
        for h in [1,3]:
            for target in ['2024-02','2024-03','2024-04','2024-05','2024-06']:
                origin=str(pd.Period(target,freq='M')-h)
                if origin<'2024-01':continue
                early.append(dict(territory_id=tid,category=cat,horizon=h,origin=origin,target=target,actual=float(ownmap[tid,cat,target]),pred_last=float(ownmap[tid,cat,origin]),pred_prophet=np.nan,window='pre_R9'))
    base=pd.concat([mainmask.assign(window='R9'),pd.DataFrame(early)],ignore_index=True)
    tasks=[]
    for (tid,cat,origin),g in base.groupby(['territory_id','category','origin'],sort=True):
        own,med,z=historical_inputs(raw,tid,cat,origin)
        assert float(own.value.iloc[-1])==float(g.pred_last.iloc[0])
        tasks.append((tid,cat,origin,own.value.tolist(),own.month.tolist(),med.to_dict(),list(g[['horizon','target']].itertuples(index=False,name=None))))
    assert 2*len(tasks)==2640
    a.out.mkdir(parents=True)
    protocol={'recorded_before_fits':datetime.now(timezone.utc).isoformat(),'seed':SEED,'n_series':120,'selection':'2023 mean quartiles within six categories, 5 per quartile; complete 24 months and all 18 R9 points; no selection by model error',
        'selection_manifest':selected,'raw_sha256':RAW_SHA,'r9_sha256':R9_SHA,'code_sha256':sha(__file__),'expected_fits':2640,'max_fits':3600,'prophet_config':CFG,
        'information_contract':'Both main comparisons can use own observations and all observed category medians only through origin. Conditional Prophet fits own/category median and scales its target forecast by median(category,origin)*prior-year category ratio. Pure yearly Prophet is an information-poorer secondary comparator.',
        'primary_comparator':'conditional_prophet_yearly','secondary_comparator':'conditional_median3','other_comparator':'prophet_yearly','windows':'pre_R9 Feb-Jun2024 h1/h3; R9 Jul-Dec2024 h1/h3/h6; h12 unsupported',
        'no_tuning':True,'no_clipping':True,'asof_verified':False,'independent_holdout':False,'scientific_pass':False,
        'limits':['Both windows already viewed; specifications now frozen but post-discovery','One prior annual cycle, explicit yearly Fourier order 3 is a limited seasonal benchmark, not optimally tuned Prophet','Aggregate category overlaps other five; no six independent replications','No actual historical release times; observation clock only','Equal-information comparison addresses access to category pooling; complete-case cohort is not full Russia','No prior error budget or confirmatory threshold; new computation is exploratory']}
    (a.out/'protocol.json').write_text(json.dumps(protocol,ensure_ascii=False,indent=2)+'\n')
    rows=[];failures=[];nfits=0
    with cf.ProcessPoolExecutor(max_workers=a.workers) as ex:
        for j,(rr,ee,n) in enumerate(ex.map(fit_task,tasks),1):
            rows.extend(rr);failures.extend(ee);nfits+=n
            if j%40==0:print(json.dumps({'tasks_done':j,'tasks_total':len(tasks),'fits_done':nfits,'failures':len(failures)}),flush=True)
    pred=pd.DataFrame(rows);assert not pred.duplicated(KEY).any()
    p=base[KEY+['actual','pred_last','pred_prophet','window']].merge(pred,on=KEY,how='left',validate='one_to_one')
    p=p.rename(columns={'pred_last':'last_value','pred_prophet':'stored_prophet'})
    # Stored Prophet was never run for pre_R9; report NA there, never impute its prediction.
    p.to_parquet(a.out/'predictions.parquet',index=False)
    (a.out/'failures.json').write_text(json.dumps(failures,indent=2)+'\n')
    supported=[]
    for window,g in p.groupby('window'):
        global MODELS
        original=MODELS
        if window=='pre_R9':MODELS=[m for m in original if m!='stored_prophet']
        supported+=summaries(g);MODELS=original
    import prophet
    metrics={'checked_at':datetime.now(timezone.utc).isoformat(),'status':'EXPLORATORY_NOT_GATE_PASS','n_series':120,'n_fits_success':nfits,'n_fits_expected':2640,'failures':len(failures),'rows':len(p),'negative_predictions':{m:int((p[m]<0).sum()) for m in MODELS},'results':supported,
        'sha256':{'raw':RAW_SHA,'r9':R9_SHA,'code':sha(__file__),'protocol':sha(a.out/'protocol.json'),'predictions':sha(a.out/'predictions.parquet')},'versions':{'python':sys.version,'prophet':prophet.__version__,'pandas':pd.__version__},'scientific_pass':False}
    (a.out/'metrics.json').write_text(json.dumps(metrics,ensure_ascii=False,indent=2)+'\n');print(json.dumps({k:v for k,v in metrics.items() if k not in ['results','sha256','negative_predictions','versions']}),flush=True)
if __name__=='__main__':main()
