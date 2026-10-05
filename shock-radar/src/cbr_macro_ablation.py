"""Retrospective CBR ablation under explicitly assumed release lags, NOT live as-of."""
from __future__ import annotations
import argparse, hashlib, json, random, sys
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd

def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def canonical_cbr(d):
    if d.duplicated(['dataset','series_id','period_end_exclusive']).any(): raise ValueError('duplicate CBR series/date')
    if set(d.periodicity)!={'month'}: raise ValueError('unexpected periodicity')
    d=d.copy(); stamp=pd.to_datetime(d.period_end_exclusive,errors='raise')
    if not stamp.dt.day.eq(1).all(): raise ValueError('expected first-of-month boundary/snapshot')
    period=stamp.dt.to_period('M')
    # FX label is preceding month. M2 label is same-day point stock, not monthly flow.
    d['reference_month']=period.astype(str)
    fx=d.dataset.eq('fx_rate');d.loc[fx,'reference_month']=(period[fx]-1).astype(str)
    m=d.dataset.eq('money_supply')
    if not pd.to_datetime(d.loc[m,'period_label'].str.strip(),dayfirst=True).equals(stamp[m]):
        raise ValueError('M2 snapshot label/date disagreement')
    if not set(d.dataset)<={'fx_rate','money_supply'}: raise ValueError('unknown CBR dataset')
    if d.duplicated(['dataset','series_id','reference_month']).any(): raise ValueError('duplicate canonical month')
    # Primary-source Russian month label verifies that FX is not shifted twice.
    names=['январь','февраль','март','апрель','май','июнь','июль','август','сентябрь','октябрь','ноябрь','декабрь']
    for r in d[fx].itertuples(index=False):
        p=pd.Period(r.reference_month,freq='M')
        if r.period_label.lower().strip()!=f'{names[p.month-1]} {p.year}': raise ValueError('FX label/date disagreement')
    d['available_at']=None;d['historical_vintage_verified']=False
    d['temporal_semantics']=np.where(fx,'previous_month_end_quote','first_day_point_stock')
    return d

def macro_features(d, origins, lag):
    if lag<2: raise ValueError('only predeclared lag2/lag3 scenarios')
    selected={name:g.set_index('reference_month').value for name,g in {
        'usd':d[(d.dataset=='fx_rate')&(d.series_id==98)],
        'm2':d[(d.dataset=='money_supply')&(d.series_id==12)]}.items()}
    result={};audit=[]
    for origin in origins:
        ref=pd.Period(origin,freq='M')-lag;prev=ref-1
        vals=[]
        for name in ['usd','m2']:
            s=selected[name]
            if str(ref) not in s.index or str(prev) not in s.index: raise ValueError('missing source month; no forward fill')
            now,old=float(s[str(ref)]),float(s[str(prev)])
            if not np.isfinite([now,old]).all() or min(now,old)<=0: raise ValueError('invalid logarithm input')
            vals.extend([float(np.log(now)),float(np.log(now/old))])
        result[origin]=np.array(vals)
        audit.append({'origin':origin,'max_reference_month':str(ref),'previous_reference_month':str(prev),
                      'lag_months_assumed':lag,'availability_verified':False})
    return result,audit

def ridge_predict(train_x,train_y,weights,test_x,alpha=1.):
    if not all(np.isfinite(x).all() for x in [train_x,train_y,weights,test_x]): raise ValueError('nonfinite model input')
    if (weights<=0).any(): raise ValueError('nonpositive training weight')
    w=weights/weights.sum();mean=np.sum(w[:,None]*train_x,axis=0)
    std=np.sqrt(np.sum(w[:,None]*(train_x-mean)**2,axis=0));std=np.where(std>1e-12,std,1.)
    z=np.column_stack([np.ones(len(train_x)),(train_x-mean)/std]);t=np.column_stack([np.ones(len(test_x)),(test_x-mean)/std])
    penalty=np.eye(z.shape[1])*alpha;penalty[0,0]=0
    coef=np.linalg.solve(z.T@(w[:,None]*z)+penalty,z.T@(w*train_y))
    return t@coef

def panels(raw):
    d=pd.read_parquet(raw)
    req=['territory_id','date','category','value']
    if d[req].isna().any().any() or not np.isfinite(d.value).all(): raise ValueError('source key/value missing/nonfinite')
    d['month']=pd.to_datetime(d.date).dt.to_period('M').astype(str)
    if d.duplicated(['territory_id','category','month']).any(): raise ValueError('duplicate source series/month')
    wide=d.pivot(index=['territory_id','category'],columns='month',values='value')
    months=sorted(wide.columns)
    if months!=pd.period_range('2023-01','2024-12',freq='M').astype(str).tolist(): raise ValueError('expected exact 24-month source')
    return wide,months

def design(wide,months,h,macro):
    cats=sorted(wide.index.get_level_values('category').unique());catidx={c:i for i,c in enumerate(cats)}
    onehot=np.eye(len(cats))[[catidx[c] for c in wide.index.get_level_values('category')]]
    values=wide.to_numpy(float);parts=[]
    for oi in range(5,len(months)-h):
        prefix=values[:,oi-5:oi+1];last=values[:,oi];actual=values[:,oi+h]
        mask=np.isfinite(prefix).all(axis=1)&np.isfinite(actual)&(prefix>=0).all(axis=1)
        scale=np.maximum(last[mask],1.)
        origin=months[oi];target=months[oi+h]
        features=np.column_stack([(last[mask]-values[mask,oi-l])/scale for l in [1,3,5]]+
                                  [np.full(mask.sum(),np.sin(2*np.pi*(oi%12)/12)),np.full(mask.sum(),np.cos(2*np.pi*(oi%12)/12)),onehot[mask]])
        full=np.column_stack([features,np.tile(macro[origin],(mask.sum(),1))])
        keys=wide.index[mask].to_frame(index=False).reset_index(drop=True)
        keys['origin']=origin;keys['target']=target;keys['horizon']=h;keys['actual']=actual[mask];keys['last']=last[mask];keys['scale']=scale
        parts.append((keys,features,full,(actual[mask]-last[mask])/scale))
    return pd.concat([x[0] for x in parts],ignore_index=True),np.vstack([x[1] for x in parts]),np.vstack([x[2] for x in parts]),np.concatenate([x[3] for x in parts])

def intervals(g, column,reps=10000):
    v=g.assign(benefit=(g.actual-g.pred_control).abs()-(g.actual-g[column]).abs()).groupby('target').benefit.agg(['sum','count'])
    rng=np.random.default_rng(20261003);draws=rng.integers(0,len(v),size=(reps,len(v)))
    b=v['sum'].to_numpy()[draws].sum(1)/v['count'].to_numpy()[draws].sum(1)
    point=float(v['sum'].sum()/v['count'].sum());lo,hi=np.quantile(b,[.025,.975])
    return {'point':point,'ci95':[float(lo),float(hi)],'reps':reps,'target_month_blocks':len(v),
            'per_month':[{'month':str(k),'n':int(r['count']),'benefit':float(r['sum']/r['count'])} for k,r in v.iterrows()],
            'drop_one_month':{str(k):float((v['sum'].sum()-r['sum'])/(v['count'].sum()-r['count'])) for k,r in v.iterrows()}}

def evaluate(raw,cbr,paired,out):
    c=canonical_cbr(pd.read_csv(cbr));wide,months=panels(raw)
    ref=pd.read_parquet(paired); key=['territory_id','category','origin','target','horizon']
    # Archived R9 uses string IDs, source uses integer IDs. Reject lossy aliases.
    text_id=ref.territory_id.astype(str)
    if not text_id.str.fullmatch(r'[1-9][0-9]*').all():raise ValueError('noncanonical source territory ID')
    ref['territory_id']=pd.to_numeric(text_id,errors='raise').astype('int64')
    if ref.duplicated(key).any(): raise ValueError('duplicate audited comparator key')
    reports=[];all_preds=[];all_audits=[]
    for lag in [2,3]:
        macro,audit=macro_features(c,months[5:],lag);all_audits+=audit
        for h in [1,3]:
            meta,x0,x1,y=design(wide,months,h,macro);preds=[];fit_audit=[]
            for target in months[-6:]:
                origin=str(pd.Period(target,freq='M')-h)
                test=meta.target.eq(target).to_numpy();train=meta.target.le(origin).to_numpy()
                counts=meta.loc[train].groupby('origin').size()
                if len(counts)<6: raise ValueError('fewer than six training origin months')
                if not meta.loc[train,'target'].le(origin).all(): raise AssertionError('training target leakage')
                # Equal total contribution per training origin, then normalize objective.
                w=meta.loc[train,'origin'].map(1./counts).to_numpy(float)
                part=meta.loc[test].copy()
                for name,x in [('control',x0),('macro',x1)]:
                    prediction=part['last'].to_numpy()+part.scale.to_numpy()*ridge_predict(x[train],y[train],w,x[test])
                    part['raw_negative_'+name]=prediction<0
                    part['pred_'+name]=np.maximum(prediction,0.)
                part['lag_assumption']=lag
                mask=ref[ref.horizon.eq(h)&ref.target.eq(target)][key+['actual','pred_last']]
                part=part.merge(mask,on=key,how='inner',validate='one_to_one',suffixes=('','_audited'))
                if not np.equal(part.actual,part.actual_audited).all() or not np.equal(part['last'],part.pred_last).all(): raise ValueError('source vs audited R9 values disagree')
                expected=len(mask)
                fit_audit.append({'origin':origin,'target':target,'n_train':int(train.sum()),'training_origin_months':len(counts),
                                  'max_train_target':meta.loc[train,'target'].max(),'expected_r9_mask':expected,
                                  'common_n':len(part),'extra_exclusions_for_contiguous_six_month_history':expected-len(part)})
                preds.append(part)
            g=pd.concat(preds,ignore_index=True)
            if g.duplicated(key).any():raise ValueError('duplicate predictions')
            mae={k:float((g.actual-g['pred_'+k]).abs().mean()) for k in ['control','macro','last']}
            r={'horizon':h,'lag_months_assumed':lag,'n_common':len(g),'n_territories':int(g.territory_id.nunique()),
               'mae':mae,'benefit_macro_vs_control':mae['control']-mae['macro'],
               'relative_mae_change_macro_vs_control_pct':100*(mae['macro']/mae['control']-1),
               'month_block':intervals(g,'pred_macro'), 'fits':fit_audit,
               'negative_clipped':{k:int(g['raw_negative_'+k].sum()) for k in ['control','macro']},
               'row_win_share':float(((g.actual-g.pred_macro).abs()<(g.actual-g.pred_control).abs()).mean()),
               'category_mae':[{'category':str(k),'n':len(v),**{z:float((v.actual-v['pred_'+z]).abs().mean()) for z in ['control','macro']}} for k,v in g.groupby('category')]}
            reports.append(r);all_preds.append(g)
    pred=pd.concat(all_preds,ignore_index=True);pred.to_parquet(out/'predictions.parquet',index=False)
    c.to_parquet(out/'macro-canonical.parquet',index=False)
    (out/'origin-macro-cutoffs.json').write_text(json.dumps(all_audits,ensure_ascii=False,indent=2)+'\n')
    result={'checked_at':datetime.now(timezone.utc).isoformat(),'status':'computed_ex_post_assumed_lag_scenarios',
      'primary':{'horizons':[1,3],'lag_months':2,'ridge_alpha_normalized_objective':1.,'macro_series':[98,12],
                 'features':['USD log level','USD log month change','M2 log snapshot level','M2 log snapshot change'],
                 'train_min_contiguous_months':6,'min_training_origins':6,'targets':months[-6:]},
      'source_rows':len(c),'future_cbr_rows_excluded_from_any_feature':int(c.reference_month.gt('2024-12').sum()),
      'strict_historical_asof_eligible_rows':0,'historical_asof_verified':False,'independent_new_holdout':False,
      'scientific_pass':False,'results':reports,'prediction_rows':len(pred),
      'sha256':{'raw':sha(raw),'cbr':sha(cbr),'r9_mask':sha(paired),'code':sha(__file__),'predictions':sha(out/'predictions.parquet')},
      'limits':['Lag2 and lag3 are assumptions, NOT historical release receipts or verified data vintages',
                'Current CBR vintage can contain revisions; this is exploratory ex-post model comparison',
                'Only six target months, adjacent dependence remains; intervals are descriptive within viewed window',
                'National features repeat across territories; row count is not independent macro sample size',
                'M2 is a point stock; FX is preceding-month end quote. No future target macro or 2025/26 input',
                'h6/h12 not fitted: insufficient independent temporal history for new supervised ablation',
                'No tuning, causal effect, new Prophet fit, production deployment or revision of frozen R9']}
    (out/'metrics.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    return result

def self_check():
    dates=pd.date_range('2022-01-01','2024-12-01',freq='MS');rows=[]
    names=['Январь','Февраль','Март','Апрель','Май','Июнь','Июль','Август','Сентябрь','Октябрь','Ноябрь','Декабрь']
    for i,t in enumerate(dates):
        for ds,sid in [('fx_rate',98),('money_supply',12)]:
            label=(f'{names[(t-pd.offsets.MonthBegin(1)).month-1]} {(t-pd.offsets.MonthBegin(1)).year}' if ds=='fx_rate' else t.strftime('%d.%m.%Y'))
            rows.append(dict(dataset=ds,series_id=sid,period_end_exclusive=t.strftime('%Y-%m-%d'),period_label=label,periodicity='month',value=50.+i))
    d=pd.DataFrame(rows);c=canonical_cbr(d)
    a,_=macro_features(c,['2024-07'],2)
    assert a['2024-07'][0]==np.log(float(c[(c.dataset=='fx_rate')&c.reference_month.eq('2024-05')].value.iloc[0]))
    d2=d.copy();d2.loc[pd.to_datetime(d2.period_end_exclusive).ge('2024-07-01'),'value']=99999.
    b,_=macro_features(canonical_cbr(d2),['2024-07'],2)
    assert np.array_equal(a['2024-07'],b['2024-07'])
    try:canonical_cbr(pd.concat([d,d.iloc[:1]]))
    except ValueError:pass
    else:raise AssertionError('duplicate accepted')
    x=np.arange(30,dtype=float).reshape(10,3);y=np.ones(10)*2
    assert np.allclose(ridge_predict(x,y,np.ones(10),x[:2]),2.)
    f=pd.DataFrame({'target':['a','b','b','b'],'actual':[10.,10.,10.,10.],'pred_control':[0.,10.,10.,10.],'pred_macro':[10.,10.,10.,10.]})
    assert intervals(f,'pred_macro',100)['point']==2.5
    # Target/past invariance: unseen future spending must not change July prediction.
    months=pd.period_range('2023-01','2024-12',freq='M').astype(str).tolist()
    wide=pd.DataFrame([np.arange(24)*2+50.,np.arange(24)*3+70.],index=pd.MultiIndex.from_tuples([(1,'a'),(2,'b')],names=['territory_id','category']),columns=months)
    mf,_=macro_features(c,months[5:],2)
    def forecast(wide):
        meta,x0,x1,y=design(wide,months,1,mf)
        train=meta.target.le('2024-06').to_numpy();test=meta.target.eq('2024-07').to_numpy()
        counts=meta.loc[train].groupby('origin').size();weights=meta.loc[train,'origin'].map(1./counts).to_numpy(float)
        return ridge_predict(x1[train],y[train],weights,x1[test])
    w2=wide.copy();w2.loc[:,[m for m in months if m>'2024-06']]=999999.
    assert np.array_equal(forecast(wide),forecast(w2))
    print(json.dumps({'self_check':True,'checks':['FX vs M2 date semantics','future macro perturbation invariance','future spending target perturbation invariance','duplicate rejection','train-only ridge constant outcome','weighted unequal month blocks']}))

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--raw',type=Path);p.add_argument('--cbr',type=Path);p.add_argument('--r9-predictions',type=Path);p.add_argument('--out',type=Path);p.add_argument('--self-check',action='store_true');a=p.parse_args()
    if a.self_check:self_check();return
    if not all([a.raw,a.cbr,a.r9_predictions,a.out]):p.error('raw/cbr/r9-predictions/out required')
    if a.out.exists():raise FileExistsError('new run only')
    a.out.mkdir(parents=True)
    protocol={'recorded_before_calculation':datetime.now(timezone.utc).isoformat(),'horizons':[1,3],'primary_lag':2,'sensitivity_lag':3,'ridge_alpha':1.,'selected_series':[98,12],'target_months':['2024-07','2024-08','2024-09','2024-10','2024-11','2024-12'],'strict_asof_admitted':False,'new_independent_holdout':False,'tuning':False,'source_sha256':{'raw':sha(a.raw),'cbr':sha(a.cbr),'r9_mask':sha(a.r9_predictions)}}
    (a.out/'protocol.json').write_text(json.dumps(protocol,ensure_ascii=False,indent=2)+'\n')
    r=evaluate(a.raw,a.cbr,a.r9_predictions,a.out)
    print(json.dumps({'status':r['status'],'rows':r['prediction_rows'],'scientific_pass':False,
                      'results':[{k:z[k] for k in ['horizon','lag_months_assumed','n_common','mae','relative_mae_change_macro_vs_control_pct','month_block']} for z in r['results']]},ensure_ascii=False))
if __name__=='__main__':main()
