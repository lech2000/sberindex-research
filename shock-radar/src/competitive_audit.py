"""Independent scalar audits and explicitly retrospective matched-null sensitivity."""
from pathlib import Path
import argparse, json, math
import numpy as np
import pandas as pd
import multicategory_shocks as d
import r9_strong_baselines as f


def main():
    p=argparse.ArgumentParser();p.add_argument('--raw',type=Path,required=True);p.add_argument('--r9',type=Path,required=True)
    p.add_argument('--detector',type=Path,required=True);p.add_argument('--baseline',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args()
    if a.out.exists():raise FileExistsError('new audit directory required')
    a.out.mkdir(parents=True)
    d.dump(a.out/'protocol.json',{'client_date':'2026-10-04','kind':'independent scalar audit plus post-hoc sensitivity',
        'matched_null':'Thresholds fitted on pooled held-out null noise at 3%; descriptive ROC comparison, not independent prospective calibration',
        'primary_protocol_unchanged':True,'forecast_sample':'up to 3 deterministic random rows per category/window/origin/target',
        'real_selection':'top 24/month from March2024; previous 3-month cooldown; selection budget, not measured economic false alarms'})
    raw=pd.read_parquet(a.raw);checks={}
    assert d.sha(a.raw)==d.RAW_SHA and f.sha(a.r9)==f.R9_SHA
    checks['frozen_source_hashes']=True
    old=pd.read_parquet(a.r9);old=old[old.horizon.isin([1,3,6])].copy();old.territory_id=old.territory_id.astype(str)
    preds=pd.read_parquet(a.baseline/'predictions.parquet')
    r=preds[preds.window=='R9']
    joined=old.merge(r,on=f.KEY,validate='one_to_one')
    assert len(joined)==len(old)==220962 and not preds.duplicated(f.KEY).any()
    assert np.array_equal(joined.actual_x,joined.actual_y) and np.array_equal(joined.pred_last,joined.last_value)
    checks['all_stored_keys_actual_last_value']=len(joined)
    raw['tid']=raw.territory_id.astype(str);raw['month']=pd.PeriodIndex(raw.date,freq='M').astype(str)
    own={key:g.set_index('month').value.astype(float) for key,g in raw.groupby(['tid','category'])}
    med={c:g.groupby('month').value.median().astype(float) for c,g in raw.groupby('category')}
    sample=preds.groupby(['category','window','origin','target'],group_keys=False).sample(n=3,random_state=d.SEED)
    n=0;future_n=0
    for row in sample.itertuples():
        y=own[(row.territory_id,row.category)];m=med[row.category]
        ref=f.predict(y,m,row.origin,row.target)
        for method in f.NEW+['category_seasonal']:
            expected=ref[method];actual=getattr(row,method)
            assert (pd.isna(expected) and pd.isna(actual)) or np.isclose(expected,actual,rtol=1e-12,atol=1e-9),(method,actual,expected)
            n+=1
        y=y.copy();m=m.copy();y.loc[y.index>row.origin]=1e9;m.loc[m.index>row.origin]=1e10
        after=f.predict(y,m,row.origin,row.target)
        for method in ref:
            assert (pd.isna(ref[method]) and pd.isna(after[method])) or np.isclose(ref[method],after[method],rtol=0,atol=0)
            future_n+=1
    checks['forecast_scalar_values']=n;checks['forecast_future_mutation_values']=future_n
    d.self_check();f.self_check()
    z,tids,months,cats,corr,precision,prep=d.prepare(raw)
    altered=raw.copy();altered.loc[altered.month>'2024-04','value']=60000
    zz,tt,mm,cc,rr,pp,_=d.prepare(altered)
    assert tids==tt and months==mm and cats==cc and np.array_equal(corr,rr)
    idx=months.index('2024-04')+1
    assert np.array_equal(z[:,:idx],zz[:,:idx])
    before=d.scores(z,precision);after=d.scores(zz,pp)
    assert all(np.array_equal(before[k][:,:idx],after[k][:,:idx]) for k in d.METHODS)
    checks['raw_future_mutation_all_detector_methods']=True
    rng=np.random.default_rng(d.SEED)
    random=rng.normal(size=(3,8,5));A=rng.normal(size=(5,5));P=A.T@A+np.eye(5)
    ss=d.scores(random,P)
    for i in range(3):
        for t in range(8):
            net=math.fsum(random[i,t])/math.sqrt(5)
            e=math.fsum(v*v for v in random[i,t])/5
            q=math.fsum(random[i,t,j]*P[j,k]*random[i,t,k] for j in range(5) for k in range(5))/5
            glr=max(math.fsum(math.fsum(random[i,l])/math.sqrt(5) for l in range(t-w+1,t+1))**2/w for w in [1,2,3] if w<=t+1)
            for k,v in [('stouffer_down',-net),('stouffer_two_sided',abs(net)),('energy',e),('mahalanobis',q),('glr_two_sided',glr)]:
                assert np.isclose(ss[k][i,t],v,rtol=1e-12,atol=1e-12)
    checks['independent_detector_scalar_values']=3*8*5
    cases=pd.read_csv(a.detector/'real-cases.csv')
    assert set(cases.municipality)=={'Орск','Оренбург','Новотроицк'}
    checks['exact_cyrillic_case_lookup']=True
    # Equal selection budget on real data: no economic false-alarm assertion.
    selected=[];counts=[]
    for method in d.METHODS:
        last=np.full(len(tids),-100)
        for j,month in enumerate(months):
            if month<'2024-03':continue
            eligible=np.flatnonzero(j-last>3)
            order=sorted(eligible,key=lambda i:(-before[method][i,j],tids[i]))[:24]
            last[order]=j
            counts.append({'method':method,'month':month,'selected':len(order),'budget':24,'economic_false_alarms':None})
            for tid in ['1673','1665','1672']:
                i=tids.index(tid)
                selected.append({'method':method,'month':month,'territory_id':tid,'selected':i in order,
                    'rank_among_eligible':None if i not in eligible else int(1+sum(before[method][k,j]>before[method][i,j] for k in eligible))})
    pd.DataFrame(selected).to_csv(a.out/'real-fixed-budget-cases.csv',index=False)
    pd.DataFrame(counts).to_csv(a.out/'real-fixed-budget-volume.csv',index=False)
    # Same synthetic draws/events as original primary test, thresholds re-estimated
    # from TEST nulls; explicitly post-hoc operating-point sensitivity.
    rows=[];thresholds={}
    for family in ['gaussian','student5']:
        pooled={m:[] for m in d.METHODS}
        for s in range(20):
            ns=d.scores(d.noise(np.random.default_rng(d.SEED+2000+s),1000,12,corr,family),precision)
            for method in d.METHODS:pooled[method].append(ns[method][:,3:].ravel())
        th={m:float(np.quantile(np.concatenate(v),.97)) for m,v in pooled.items()};thresholds[family]=th
        for s in range(20):
            rng=np.random.default_rng(d.SEED+2000+s);base=d.noise(rng,1000,12,corr,family)
            ns=d.scores(base,precision);ix=rng.choice(1000,200,replace=False);on=rng.integers(3,10,len(ix))
            for form in d.FORMS:
                direction=d.directions(rng,len(ix),len(corr),form)
                if form!='opposed':continue
                score=d.scores(d.inject(base,ix,on,direction,4.,form),precision)
                for m in d.METHODS:
                    hit=(score[m][ix[:,None],on[:,None]+np.arange(3)]>th[m]).any(1)
                    null=ns[m][:,3:]>th[m]
                    rows.append({'family':family,'seed':s,'form':form,'amplitude':4.,'target_fa':.03,'method':m,
                        'events':len(ix),'hits':int(hit.sum()),'null_alarm_cells':int(null.sum()),'null_cells':int(null.size)})
    d.dump(a.out/'matched-null-thresholds.json',thresholds)
    dd=pd.DataFrame(rows);dd.to_csv(a.out/'matched-null-by-seed.csv',index=False)
    agg=dd.groupby(['family','method']).agg(events=('events','sum'),hits=('hits','sum'),null_alarm_cells=('null_alarm_cells','sum'),null_cells=('null_cells','sum')).reset_index()
    agg['recall']=agg.hits/agg.events;agg['matched_null_fa']=agg.null_alarm_cells/agg.null_cells
    assert np.allclose(agg.matched_null_fa,.03,rtol=0,atol=1/180000)
    agg.to_csv(a.out/'matched-null-summary.csv',index=False)
    d.dump(a.out/'matched-null-paired.json',[d.paired_ci(rows,m,'max_absolute',fam,'opposed',4.,.03) for fam in ['gaussian','student5'] for m in ['energy','mahalanobis']])
    checks['matched_realized_pooled_null_fa']=True
    # Supplementary paired month-block CI against relevant references.
    comps=[]
    for h,g in r.groupby('horizon'):
        models=['category_seasonal']+f.NEW+['last_value','stored_prophet'];g=g[g[models].notna().all(axis=1)]
        for ref in ['category_seasonal','growth_naive3','stored_prophet','last_value']:
            delta=np.abs(g.actual-g.profile_ses)-np.abs(g.actual-g[ref])
            b=pd.DataFrame({'target':g.target,'delta':delta}).groupby('target').delta.agg(['sum','count'])
            rng=np.random.default_rng(d.SEED+h);ix=rng.integers(0,len(b),(10000,len(b)))
            samples=b['sum'].to_numpy()[ix].sum(1)/b['count'].to_numpy()[ix].sum(1)
            comps.append({'horizon':int(h),'model':'profile_ses','reference':ref,'error_delta':float(delta.mean()),
                'ci95_target_month_blocks':np.quantile(samples,[.025,.975]).tolist(),'n_month_blocks':len(b),'n':len(g)})
    d.dump(a.out/'forecast-paired.json',comps)
    d.dump(a.out/'audit.json',{'client_date':'2026-10-04','passed':True,'checks':checks,'scientific_pass':False,
        'audit_code_sha256':d.sha(__file__),'detector_code_sha256':d.sha(d.__file__),'forecast_code_sha256':d.sha(f.__file__)})
    d.dump(a.out/'manifest.json',{p.name:d.sha(p) for p in a.out.iterdir() if p.is_file() and p.name!='manifest.json'})
    print(json.dumps({'complete':True,'checks':checks,'matched_null':agg.to_dict('records')},ensure_ascii=False))

if __name__=='__main__':main()
