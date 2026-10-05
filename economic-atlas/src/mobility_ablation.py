"""Descriptive 2024 mobility ablation on an explicitly restricted source-code cohort."""
from __future__ import annotations
import argparse,hashlib,itertools,json
from datetime import datetime,timezone
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import adjusted_rand_score,silhouette_score

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def fits(z,mobility,old,seed=20261003):
    if not np.isfinite(z).all() or not np.isfinite(mobility).all() or (mobility<0).any():raise ValueError('invalid mobility/features')
    if len(z)<10 or len(z)!=len(mobility) or len(z)!=len(old):raise ValueError('bad cohort length')
    logs=np.log1p(mobility);sd=logs.std();scaled=(logs-logs.mean())/(sd if sd>0 else 1.)
    results=[];labels={};base={}
    for weight in [0.,.25,1.]:
        x=z if weight==0 else np.column_stack([z,weight*scaled])
        rows=[];labs=[]
        for s in range(seed,seed+5):
            lab=KMeans(n_clusters=2,n_init=20,random_state=s).fit_predict(x);labs.append(lab)
            if weight==0:base[s]=lab
            if len(set(lab))!=2:raise ValueError('degenerate partition')
            rows.append({'seed':s,'cluster_sizes':np.bincount(lab).tolist(),
                         'silhouette_common_spending_space':float(silhouette_score(z,lab)),
                         'ari_vs_same_seed_control':float(adjusted_rand_score(base[s],lab)),
                         'ari_vs_frozen_december_partition':float(adjusted_rand_score(old,lab))})
        results.append({'mobility_weight':weight,'runs':rows,'seed_stability_pairwise_ari':[float(adjusted_rand_score(a,b)) for a,b in itertools.combinations(labs,2)]})
        labels[str(weight)]=np.asarray(labs).tolist()
    return {'primary_mobility_weight':.25,'sensitivity_weight':1.,'n':len(z),'k':2,'seeds':list(range(seed,seed+5)),
            'same_observation_mask_all_arms':True,'common_metric_space':'five frozen-standardized spending shares',
            'spending_feature_variances_cohort':np.var(z,axis=0).tolist(),
            'mobility_squared_weight_to_spending_total_variance_ratio':{str(w):float(w*w/(np.var(z,axis=0).sum())) for w in [.25,1.]},
            'mobility_mean_log1p':float(logs.mean()),'mobility_std_log1p':float(sd),'results':results},labels

def evaluate(panel,cohort,assignments,out):
    from a6_temporal import build_monthly_shares,standardize_frozen
    c=pd.read_parquet(cohort)
    if c.territory_id.duplicated().any():raise ValueError('duplicate cohort territory')
    if not c.year.eq(2024).all() or not c.analysis_core.all() or not c.metadata_mapping_verified.all() or not c.fullname_agrees_with_native_code.all():raise ValueError('non-core/2025/name-disagreement mobility admitted')
    if not c.local_date.eq('2024-12-31').all():raise ValueError('unexpected 2024 snapshot')
    if not c.native_source_tid.eq(c.territory_id).all():raise ValueError('native code disagreement')
    tids,months,shares,_=build_monthly_shares(pd.read_parquet(panel));z,_=standardize_frozen(shares,months)
    mapping={int(t):i for i,t in enumerate(tids)};mi=[str(m)[:7] for m in months].index('2024-12')
    if not c.territory_id.isin(mapping).all():raise ValueError('cohort absent from frozen Atlas panel')
    c=c.sort_values('territory_id');idx=[mapping[int(t)] for t in c.territory_id]
    old=pd.read_parquet(assignments).query('month == "2024-12"')[['territory_id','label','status']]
    if old.territory_id.duplicated().any():raise ValueError('duplicate frozen assignments')
    v=c[['territory_id','value','native_region']].merge(old,on='territory_id',validate='one_to_one')
    r,labels=fits(z[idx,mi,:],v.value.to_numpy(float),v.label.to_numpy(int))
    r.update({'checked_at':datetime.now(timezone.utc).isoformat(),'status':'computed_descriptive_restricted_cohort_ablation',
              'n_ambiguous_frozen_identity':int(v.status.eq('ambiguous').sum()),
              'region_cohort_counts':v.native_region.value_counts().to_dict(),
              'source_snapshot':'2024-12-31','future_2025_mobility_rows_admitted':0,
              'scientific_pass':False,'historical_asof_verified':False,'independent_new_holdout':False,
              'sha256':{'panel':sha(panel),'cohort':sha(cohort),'assignments':sha(assignments),'code':sha(__file__)},
              'limits':['Descriptive December 2024 partitions, not causal effects or forecast validation',
                        'Official source native code binding checked today; historical legal boundaries not independently proved',
                        '82 source/dictionary name/type discrepancies excluded; half-open year eligibility remains an assumption',
                        'Restricted NW cohort is not nationally representative; no missing mobility filled',
                        'Fixed K=2, five seeds; no dynamic birth/merge claim; ambiguous A6 identity kept explicit',
                        'Mobility log transform fit on the 2024 descriptive cohort; never backdated to Radar',
                        'Silhouette is measured in the SAME spending space across arms; not evidence of economic validity',
                        'Primary .25/sensitivity1 weights fixed before calculation; no cherry-picking']})
    out.mkdir(parents=True)
    (out/'labels-internal.json').write_text(json.dumps({'territory_ids':v.territory_id.tolist(),'labels':labels})+'\n')
    (out/'metrics.json').write_text(json.dumps(r,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    return r

def self_check():
    rng=np.random.default_rng(5);z=np.r_[rng.normal(-2,.1,(20,5)),rng.normal(2,.1,(20,5))];m=np.tile(np.arange(20),2).astype(float);old=np.r_[np.zeros(20),np.ones(20)]
    r,_=fits(z,m,old,3);rr,_=fits(z,m,old,3)
    assert r==rr and all(v['n']==40 if 'n' in v else True for v in r['results'])
    for arm in r['results']:
        for x in arm['runs']:
            assert sum(x['cluster_sizes'])==40 and -1<=x['silhouette_common_spending_space']<=1
    for bad in [np.full(40,np.nan),np.full(40,-1.)]:
        try:fits(z,bad,old)
        except ValueError:pass
        else:raise AssertionError('invalid mobility accepted')
    print(json.dumps({'self_check':True,'checks':['deterministic repeated seeds','same cohort and common metric space','nonfinite/negative mobility rejection']}))

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--panel',type=Path);p.add_argument('--cohort',type=Path);p.add_argument('--assignments',type=Path);p.add_argument('--out',type=Path);p.add_argument('--self-check',action='store_true');a=p.parse_args()
    if a.self_check:self_check();return
    if not all([a.panel,a.cohort,a.assignments,a.out]):p.error('panel/cohort/assignments/out required')
    if a.out.exists():raise FileExistsError('new run only')
    r=evaluate(a.panel,a.cohort,a.assignments,a.out)
    print(json.dumps({k:r[k] for k in ['status','n','n_ambiguous_frozen_identity','region_cohort_counts','results']},ensure_ascii=False))
if __name__=='__main__':main()
