"""Exploratory pre-event expense profiles and fixed-origin flood residuals.

No causal effect, economic sovereignty index, as-of or unseen-holdout claim.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def dump(p, x):
    Path(p).write_text(json.dumps(x, ensure_ascii=False, indent=2, allow_nan=False)+'\n')


def pre_features(panel, population):
    """Everything here is restricted to 2023, including population."""
    d=panel.loc[panel.ym.between('2023-01','2023-12')].copy()
    grid=d.pivot(index=['territory_id','ym'], columns='category', values='value')
    if grid.isna().any().any() or (grid<=0).any().any():
        raise ValueError('Incomplete or nonpositive pre-event panel')
    categories=sorted(c for c in grid if c!='Все категории')
    if len(categories)!=5:
        raise ValueError('Five nonaggregate categories required')
    ratios=grid[categories].div(grid['Все категории'],axis=0)
    f=ratios.groupby(level='territory_id').mean().rename(columns=lambda c:'share_'+c)
    allv=grid['Все категории'].unstack('ym').sort_index(axis=1)
    if allv.shape[1]!=12:
        raise ValueError('Exactly 12 pre-event months required')
    log=np.log(allv.to_numpy(float))
    t=np.arange(12)-5.5
    f['log_mean_all_2023']=np.log(allv.mean(axis=1))
    f['log_all_slope_2023']=log@t/np.sum(t*t)
    f['log_all_std_2023']=log.std(axis=1,ddof=0)
    pop=population.loc[(population.year==2023)&(population.age=='Всего')&(population.period=='год')]
    if pop.duplicated(['territory_id','gender']).any():
        raise ValueError('Duplicate population keys')
    pv=pop.pivot(index='territory_id',columns='gender',values='value')
    if set(pv.columns)!={'Мужчины','Женщины'}:
        raise ValueError('Two population sexes expected; no age summing')
    total=pv.sum(axis=1,min_count=2)
    f['population_2023']=total.where(total>0)
    f['log_population_2023']=np.log(f['population_2023'])
    return f, categories


def match(f, dictionary, proto):
    if dictionary.territory_id.duplicated().any():
        raise ValueError('Dictionary territory_id not unique')
    f=f.join(dictionary.set_index('territory_id')[['name_short','type','region_code','year_from','year_to']],validate='one_to_one')
    eligible=f.loc[(f.year_from<=2023)&(f.year_to>=2024)].dropna()
    cols=[c for c in f if c.startswith('share_')]+['log_population_2023','log_mean_all_2023','log_all_slope_2023','log_all_std_2023']
    scaler=StandardScaler().fit(eligible[cols])
    z=pd.DataFrame(scaler.transform(eligible[cols]),index=eligible.index,columns=cols)
    records=[]
    for a in proto['anchors']:
        tid=a['territory_id']
        if tid not in eligible.index:
            raise ValueError('Anchor lacks complete pre-event covariates')
        row=eligible.loc[tid]
        if row.name_short!=a['name'] or int(row.region_code)!=a['region_code']:
            raise ValueError('Anchor identity mismatch')
        pool=eligible.loc[~eligible.region_code.isin(proto['comparison']['exclude_regions'])&(eligible.type==row.type)]
        pool=pool.loc[(pool.log_population_2023-row.log_population_2023).abs()<=np.log(2)]
        distances=np.sqrt(np.square(z.loc[pool.index]-z.loc[tid]).sum(axis=1))
        ranked=pd.DataFrame({'territory_id':pool.index,'distance':distances.to_numpy()})
        ranked=ranked.loc[ranked.distance<=proto['comparison']['max_standardized_distance']].sort_values(['distance','territory_id'])
        if len(ranked)<proto['comparison']['minimum_peers']:
            records.append({'anchor':a['name'],'anchor_tid':tid,'status':'NO_MATCH_SUPPORT','candidate_count':len(ranked)})
            continue
        for rank,r in enumerate(ranked.head(proto['comparison']['nearest']).itertuples(),1):
            peer=eligible.loc[r.territory_id]
            records.append({'anchor':a['name'],'anchor_tid':tid,'status':'MATCHED_DESCRIPTIVE','rank':rank,'peer_tid':int(r.territory_id),
                'peer_name':peer.name_short,'peer_region':int(peer.region_code),'distance':float(r.distance),
                'population_ratio_peer_to_anchor':float(peer.population_2023/row.population_2023),'exposure_status':'UNKNOWN'})
    return pd.DataFrame(records), eligible, z


def recovery(residuals, band=10):
    r=np.asarray(residuals,float)
    if len(r)!=9 or not np.isfinite(r).all():
        raise ValueError('Nine finite Apr-Dec residuals required')
    if r[0]>-10:
        return 'NOT_APPLICABLE_NO_INITIAL_DROP', None
    for i in range(1,len(r)-1):
        if abs(r[i])<=band and abs(r[i+1])<=band:
            return 'REENTERED_MODEL_BAND', i
    return 'RIGHT_CENSORED_AT_DECEMBER', None


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for name in ['repo','population','dictionary','protocol','out']:
        ap.add_argument('--'+name,type=Path,required=True)
    a=ap.parse_args();proto=json.loads(a.protocol.read_text())
    if a.out.exists():
        raise FileExistsError('New run directory required')
    paths={'panel':a.repo/'economic-atlas/data/panel_v1.parquet','population':a.population,'dictionary':a.dictionary,
           'forecast_code':a.repo/'shock-radar/src/r9_strong_baselines.py','protocol':a.protocol,'code':Path(__file__)}
    for k,h in proto['input_sha256'].items():
        if sha(paths[k])!=h:
            raise ValueError('Frozen SHA mismatch: '+k)
    panel=pd.read_parquet(paths['panel']);pop=pd.read_parquet(a.population);dictionary=pd.read_parquet(a.dictionary)
    if panel.duplicated(['territory_id','ym','category']).any() or len(panel)!=273024:
        raise ValueError('Frozen panel keys/size differ')
    f,categories=pre_features(panel,pop)
    clustering_cols=['share_'+c for c in categories]
    x=StandardScaler().fit_transform(f[clustering_cols])
    km=KMeans(n_clusters=2,random_state=proto['cluster_method']['seed'],n_init=20).fit(x)
    f['profile_2023']=km.labels_
    peers,eligible,z=match(f,dictionary,proto)
    sys.path.insert(0,str(a.repo/'shock-radar/src'))
    from r9_strong_baselines import predict_block,predict
    months=sorted(panel.ym.unique());origin=months.index(proto['forecast_origin'])
    tids=f.index.to_numpy();models=[proto['primary_model'],proto['sensitivity_model']]
    selected=set(a['territory_id'] for a in proto['anchors'])
    if 'peer_tid' in peers:
        selected.update(peers.peer_tid.dropna().astype(int))
    rows=[];all_forecasts={};scalar_checks=0;future_checks=0;profile_rows=[];placebo_rows=[]
    altered=panel.copy();altered.loc[altered.ym>'2023-12','value']=altered.loc[altered.ym>'2023-12','value']*100+1234
    fp,_=pre_features(altered,pop)
    np.testing.assert_array_equal(fp[clustering_cols],f[clustering_cols])
    np.testing.assert_array_equal(km.predict(StandardScaler().fit_transform(fp[clustering_cols])),km.labels_)
    altered_pop=pop.copy();altered_pop.loc[altered_pop.year>2023,'value']*=100
    fpop,_=pre_features(altered,altered_pop)
    np.testing.assert_allclose(fpop[f.columns.drop('profile_2023')],f[f.columns.drop('profile_2023')],equal_nan=True)
    fpop['profile_2023']=km.labels_
    mutated_peers,_,_=match(fpop,dictionary,proto)
    pd.testing.assert_frame_equal(mutated_peers,peers)
    for category in sorted(panel.category.unique()):
        grid=panel.loc[panel.category==category].pivot(index='territory_id',columns='ym',values='value').reindex(index=tids,columns=months)
        values=grid.to_numpy(float); med=np.median(values,axis=0)
        if not np.isfinite(values).all() or (values<=0).any():
            raise ValueError('Positive complete forecast panel required')
        changed=values.copy();changed[:,origin+1:]=changed[:,origin+1:]*100+1234
        changed_med=np.median(changed,axis=0)
        for model in models:
            predictions=[]
            for target in proto['targets']:
                ti=months.index(target)
                pred=predict_block(values,med,origin,ti)[model]
                np.testing.assert_array_equal(pred,predict_block(changed,changed_med,origin,ti)[model]);future_checks+=len(pred)
                predictions.append(pred)
            forecast=np.column_stack(predictions);actual=values[:,[months.index(t) for t in proto['targets']]]
            if not np.isfinite(forecast).all() or (forecast<=0).any():
                raise ValueError('Invalid forecasts; no silent removal')
            residual=100*(actual/forecast-1)
            quarter=100*(actual[:,:3].sum(1)/forecast[:,:3].sum(1)-1)
            all_forecasts[(category,model)]={'actual':actual,'forecast':forecast,'residual':residual,'quarter':quarter}
            for group in sorted(f.profile_2023.unique()):
                ix=f.profile_2023.to_numpy()==group
                profile_rows.append({'category':category,'model':model,'profile_2023':int(group),'n':int(ix.sum()),
                    'April_median_residual_percent':float(np.median(residual[ix,0])),
                    'April_iqr_residual_percent':np.quantile(residual[ix,0],[.25,.75]).tolist(),
                    'quarter_median_residual_percent':float(np.median(quarter[ix])),'aggregate':category=='Все категории','causal':False})
            for i,tid in enumerate(tids):
                if tid not in selected:
                    continue
                own=pd.Series(values[i],index=months);M=pd.Series(med,index=months)
                for j,target in enumerate(proto['targets']):
                    scalar=predict(own,M,proto['forecast_origin'],target)[model]
                    np.testing.assert_allclose(scalar,forecast[i,j],rtol=1e-12,atol=1e-9);scalar_checks+=1
                    rows.append({'territory_id':int(tid),'category':category,'model':model,'origin':proto['forecast_origin'],'target':target,
                        'actual':float(actual[i,j]),'forecast':float(forecast[i,j]),'residual_percent':float(residual[i,j])})
        for po,pt in zip(proto['placebo']['origins'],proto['placebo']['dates']):
            pi=months.index(po);ti=months.index(pt)
            q=predict_block(values,med,pi,ti)
            for model in models:
                for i,tid in enumerate(tids):
                    if tid in selected:
                        placebo_rows.append({'territory_id':int(tid),'category':category,'model':model,'origin':po,'target':pt,
                            'residual_percent':float(100*(values[i,ti]/q[model][i]-1))})
    summary=[];tid_index={int(t):i for i,t in enumerate(tids)}
    for anchor in proto['anchors']:
        tid=anchor['territory_id'];i=tid_index[tid];g=peers.loc[(peers.anchor_tid==tid)&(peers.status=='MATCHED_DESCRIPTIVE')]
        peer_ix=[tid_index[int(t)] for t in g.get('peer_tid',[])]
        for (category,model),d in all_forecasts.items():
            peer_april=d['residual'][peer_ix,0] if peer_ix else np.array([])
            status,offset=recovery(d['residual'][i])
            sens={str(b):recovery(d['residual'][i],b) for b in proto['recovery']['sensitivity_bands']}
            summary.append({'municipality':anchor['name'],'territory_id':tid,'profile_2023':int(f.loc[tid,'profile_2023']),
                'category':category,'aggregate':category=='Все категории','model':model,'April_residual_percent':float(d['residual'][i,0]),
                'quarter_residual_percent':float(d['quarter'][i]),'comparison_count':len(peer_ix),
                'comparison_April_median_percent':float(np.median(peer_april)) if peer_ix else None,
                'comparison_April_range_percent':[float(peer_april.min()),float(peer_april.max())] if peer_ix else None,
                'anchor_minus_comparison_April_pp':float(d['residual'][i,0]-np.median(peer_april)) if peer_ix else None,
                'recovery_status':status,'reentry_month':proto['targets'][offset] if offset is not None else None,
                'reentry_confirmed_month':proto['targets'][offset+1] if offset is not None else None,
                'recovery_sensitivity':sens})
    a.out.mkdir(parents=True)
    dump(a.out/'protocol.json',proto);f.reset_index().to_parquet(a.out/'pre-event-features.parquet',index=False)
    peers.to_csv(a.out/'comparisons.csv',index=False);pd.DataFrame(rows).to_parquet(a.out/'selected-residuals.parquet',index=False)
    pd.DataFrame(placebo_rows).to_csv(a.out/'pre-event-placebos.csv',index=False)
    dump(a.out/'case-summary.json',summary);dump(a.out/'profile-summary.json',profile_rows)
    metrics={'status':'COMPUTED_EXPLORATORY','scientific_pass':False,'causal_effect_estimated':False,'independent_holdout':False,
        'feature_period':'2023 only','forecast_origin':proto['forecast_origin'],'n_panel':len(f),'profile_sizes':f.profile_2023.value_counts().sort_index().to_dict(),
        'n_matching_eligible':len(eligible),'n_selected_unique':len(selected),'matching_rows':len(peers),'summary_rows':len(summary),
        'checks':{'future_value_mutation_forecasts':future_checks,'scalar_forecasts':scalar_checks,'future_mutation_features_labels_peers':True},
        'limits':proto['limits'],'external_2025_source':'KB75/16427, prior completed A8; not independently recomputed by this script'}
    dump(a.out/'metrics.json',metrics)
    dump(a.out/'manifest.json',{'created_at':datetime.now(timezone.utc).isoformat(),'input_sha256':{k:sha(p) for k,p in paths.items()},
        'files':{p.name:sha(p) for p in sorted(a.out.iterdir()) if p.is_file()},'scientific_pass':False})
    print(json.dumps(metrics,ensure_ascii=False))

if __name__=='__main__':
    main()
