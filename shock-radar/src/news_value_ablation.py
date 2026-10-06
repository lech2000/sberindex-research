"""Bounded retrospective official-event ablation; publication proxy is NOT as-of."""
import argparse
from datetime import datetime,timezone
import hashlib,json
from pathlib import Path
import numpy as np
import pandas as pd
from cbr_macro_ablation import ridge_predict,intervals

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

ARMS=('control','strict','publication_proxy','delayed_one_month','shifted_twelve_months')

def compile_events(registry,dictionary):
    if dictionary.territory_id.duplicated().any():raise ValueError('ambiguous dictionary')
    events=[];seen=set()
    for source in registry['events']:
        eid=source['event_id']
        if eid in seen:raise ValueError('duplicate event')
        seen.add(eid)
        pub=source.get('source_claimed_published_date',source.get('source_claimed_published_at'))
        month=str(pd.Period(str(pub)[:10],freq='M'))
        if source['scope']=='municipality':
            match=dictionary.loc[dictionary.name_short.eq(source['entity_name'])]
            if len(match)!=1:raise ValueError('ambiguous municipal event geography')
            tid=int(match.territory_id.iloc[0]);delta=0.
        elif source['scope']=='national':
            tid=None;delta=float(source['new_rate_pct'])-float(source['old_rate_pct'])
        else:raise ValueError('unexpected event scope')
        events.append({**source,'publication_month':month,'tid':tid,'rate_delta':delta})
    return events


def event_features(ids,origin,events,mode):
    origin=pd.Period(origin,freq='M');out=np.zeros((len(ids),2));ids=np.asarray(ids,int)
    for e in events:
        if mode=='strict':
            end=(origin+1).to_timestamp().tz_localize('UTC')
            if not e.get('historical_asof_verified') or not e.get('available_at'):continue
            if pd.Timestamp(e['available_at'])>=end or pd.Timestamp(e['first_seen_at'])>=end:continue
        event_month=pd.Period(e['publication_month'],freq='M')
        delay={'strict':0,'publication_proxy':0,'delayed_one_month':1,'shifted_twelve_months':12}[mode]
        elapsed=origin.ordinal-event_month.ordinal-delay
        if 0<=elapsed<3:
            if e['tid'] is None:out[:,1]+=e['rate_delta']
            else:out[ids==e['tid'],0]+=1.
    return out


def design(panel,h,events):
    if panel.duplicated(['territory_id','ym','category']).any():raise ValueError('duplicate panel key')
    wide=panel.pivot(index=['territory_id','category'],columns='ym',values='value').sort_index()
    months=pd.period_range('2023-01','2024-12',freq='M').astype(str).tolist()
    if list(wide.columns)!=months or len(wide)!=1896*6:raise ValueError('wrong frozen panel')
    v=wide.to_numpy(float)
    if not np.isfinite(v).all() or (v<=0).any():raise ValueError('missing/nonpositive data')
    cats=sorted(wide.index.get_level_values('category').unique());catidx={c:i for i,c in enumerate(cats)}
    onehot=np.eye(len(cats))[[catidx[c] for c in wide.index.get_level_values('category')]]
    ids=wide.index.get_level_values('territory_id').to_numpy(int)
    rows=[];features={a:[] for a in ARMS};targets=[]
    for oi in range(7,len(months)-h):
        cutoff=oi-2;last=v[:,cutoff];scale=np.maximum(last,1.)
        x=np.column_stack([(last-v[:,cutoff-k])/scale for k in (1,3,5)]+[np.full(len(v),np.sin(2*np.pi*(oi%12)/12)),np.full(len(v),np.cos(2*np.pi*(oi%12)/12)),onehot])
        meta=wide.index.to_frame(index=False).reset_index(drop=True)
        meta['origin']=months[oi];meta['cutoff']=months[cutoff];meta['target']=months[oi+h];meta['horizon']=h
        meta['last']=last;meta['scale']=scale;meta['actual']=v[:,oi+h]
        rows.append(meta);targets.append((v[:,oi+h]-last)/scale);features['control'].append(x)
        for arm in ARMS[1:]:features[arm].append(np.column_stack([x,event_features(ids,months[oi],events,arm)]))
    return pd.concat(rows,ignore_index=True),{a:np.vstack(x) for a,x in features.items()},np.concatenate(targets)


def fit_origin(meta,x,y,origin,target):
    cutoff=str(pd.Period(origin,freq='M')-2)
    train=meta.target.le(cutoff).to_numpy();test=meta.target.eq(target).to_numpy()
    counts=meta.loc[train].groupby('origin').size()
    if len(counts)<4:raise ValueError('insufficient training origin blocks')
    weights=meta.loc[train,'origin'].map(1/counts).to_numpy(float)
    prediction=meta.loc[test,'last'].to_numpy()+meta.loc[test,'scale'].to_numpy()*ridge_predict(x[train],y[train],weights,x[test],alpha=1.)
    return prediction,{'origin':origin,'target':target,'cutoff':cutoff,'max_training_target':meta.loc[train,'target'].max(),'training_origins':len(counts),'train_rows':int(train.sum()),'nonzero_news_train_rows':int((np.any(x[train,-2:]!=0,axis=1)).sum()) if x.shape[1]==13 else None}


def run(a):
    protocol=json.loads(a.protocol.read_text())
    paths={'panel':a.panel,'dictionary':a.dictionary,'events':a.events,'r9':a.r9}
    assert {k:sha(p) for k,p in paths.items()}==protocol['input_sha256']
    if a.out.exists():raise FileExistsError('new run only')
    panel=pd.read_parquet(a.panel);dictionary=pd.read_parquet(a.dictionary)
    events=compile_events(json.loads(a.events.read_text()),dictionary)
    ref=pd.read_parquet(a.r9);key=['territory_id','category','origin','target','horizon']
    ref['territory_id']=pd.to_numeric(ref.territory_id,errors='raise').astype(int)
    if ref.duplicated(key).any():raise ValueError('duplicate comparator mask')
    a.out.mkdir(parents=True);predictions=[];fits=[];future_checks=[]
    for h in (1,3):
        meta,x,y=design(panel,h,events)
        for target in protocol['targets']:
            origin=str(pd.Period(target,freq='M')-h);test=meta.target.eq(target).to_numpy();part=meta.loc[test].copy()
            for arm in ARMS:
                raw,receipt=fit_origin(meta,x[arm],y,origin,target)
                part['pred_'+arm]=np.maximum(raw,0.);receipt.update(arm=arm,horizon=h,negative_clipped=int((raw<0).sum()));fits.append(receipt)
            observed=ref.loc[ref.horizon.eq(h)&ref.target.eq(target),key+['actual']]
            part=part.merge(observed,on=key,how='inner',validate='one_to_one',suffixes=('','_reference'))
            assert np.array_equal(part.actual,part.actual_reference)
            part=part.drop(columns='actual_reference');predictions.append(part)
            np.testing.assert_allclose(part.pred_control,part.pred_strict,rtol=1e-12,atol=1e-9)
            np.testing.assert_allclose(part.pred_control,part.pred_shifted_twelve_months,rtol=1e-12,atol=1e-9)
            print(json.dumps({'horizon':h,'target':target,'common_rows':len(part)}),flush=True)
        # Full-path mutation for first target, including future target labels.
        target=protocol['targets'][0];origin=str(pd.Period(target,freq='M')-h);cutoff=str(pd.Period(origin,freq='M')-2)
        mutated=panel.copy();mutated.loc[mutated.ym.gt(cutoff),'value']*=1e5
        later=[e for e in events if e['publication_month']>origin]
        edited=[{**e,'rate_delta':99999.,'tid':None} if e in later else e for e in events]
        m2,x2,y2=design(mutated,h,edited)
        for arm in ARMS:
            original,_=fit_origin(meta,x[arm],y,origin,target);changed,_=fit_origin(m2,x2[arm],y2,origin,target)
            np.testing.assert_allclose(original,changed,rtol=0,atol=0)
            future_checks.append({'arm':arm,'horizon':h,'rows':len(original),'future_spending_and_event_mutation_invariant':True})
    pred=pd.concat(predictions,ignore_index=True);pred.to_parquet(a.out/'predictions.parquet',index=False)
    metrics=[]
    for h,g in pred.groupby('horizon'):
        control=float((g.actual-g.pred_control).abs().mean())
        for arm in ARMS:
            mae=float((g.actual-g['pred_'+arm]).abs().mean());normalized=float(((g.actual-g['pred_'+arm]).abs()/g.scale).mean())
            metrics.append({'horizon':int(h),'arm':arm,'n':len(g),'n_municipalities':int(g.territory_id.nunique()),'mae':mae,'normalized_mae':normalized,'relative_mae_reduction_vs_control_percent':100*(1-mae/control),'month_block':intervals(g,'pred_'+arm),'categories':[{'category':str(c),'n':len(f),'mae':float((f.actual-f['pred_'+arm]).abs().mean())} for c,f in g.groupby('category')]})
    result={'checked_at':datetime.now(timezone.utc).isoformat(),'status':'MEASURED_BOUNDED_RETROSPECTIVE_OFFICIAL_NEWS_SENSITIVITY','scientific_pass':False,'historical_asof_verified':False,'independent_holdout':False,'events_total':len(events),'strict_historically_eligible_events':0,'sources':len(json.loads(a.events.read_text())['sources']),'independent_event_families':['spring_flood_2024','national_rate_decisions_2024'],'unique_publication_months':len(set(e['publication_month'] for e in events)),'predictions_rows':len(pred),'fits':fits,'metrics':metrics,'future_checks':future_checks,'max_strict_control_prediction_difference':float((pred.pred_control-pred.pred_strict).abs().max()),'max_shifted_control_prediction_difference':float((pred.pred_control-pred.pred_shifted_twelve_months).abs().max()),'protocol_sha256':sha(a.protocol),'code_sha256':sha(__file__),'input_sha256':protocol['input_sha256'],'prediction_sha256':sha(a.out/'predictions.parquet'),'limits':protocol['limits']}
    (a.out/'metrics.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n');(a.out/'event_feature_dictionary.json').write_text(json.dumps(events,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'rows':len(pred),'fits':len(fits),'metrics':[{k:x[k] for k in ['horizon','arm','mae','relative_mae_reduction_vs_control_percent']} for x in metrics]}),flush=True)


def main():
    p=argparse.ArgumentParser()
    for key in ['panel','dictionary','events','r9','protocol','out']:p.add_argument('--'+key,type=Path,required=True)
    run(p.parse_args())

if __name__=='__main__':main()
