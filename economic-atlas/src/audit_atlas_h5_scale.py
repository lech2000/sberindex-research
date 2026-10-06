"""Independent scalar audit of H5 external errors, pair intervals and partitions."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import numpy as np
import pandas as pd


def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def main():
    p=argparse.ArgumentParser()
    for key in ['run','dictionary','wages','employment','out']:
        p.add_argument('--'+key,type=Path,required=True)
    a=p.parse_args()
    if a.out.exists():raise FileExistsError('New independent audit only')
    results=json.loads((a.run/'results.json').read_text())
    for key in ['dictionary','wages','employment']:assert sha(getattr(a,key))==results['input_sha256'][key]
    d=pd.read_parquet(a.dictionary).set_index('territory_id')
    codes=d.oktmo.str.replace('-','',regex=False).str[:8].to_dict()
    lookups={}
    for endpoint,path in [('wage',a.wages),('employment',a.employment)]:
        source=pd.read_parquet(path)
        f=source.loc[(source.year==2025)&source.okved2.str.startswith('Всего',na=False)&source.mun_level.str.contains('верхнего',na=False)&source.indicator_period.eq('Январь-декабрь')]
        values={}
        for code,g in f.groupby('oktmo'):
            finite=g.indicator_value[np.isfinite(g.indicator_value)].unique()
            if len(finite)==1 and finite[0]>0:values[code]=math.log(float(finite[0]))
        lookups[endpoint]=values
    pred=pd.read_parquet(a.run/'oof_predictions.parquet')
    assert len(pred)==244608 and pred.territory_id.nunique()==1248 and pred.region.nunique()==70
    assert not pred.duplicated(['territory_id','endpoint','arm','method','k','seed']).any()
    scalar=0
    for row in pred.itertuples():
        assert math.isclose(row.actual_log2025,lookups[row.endpoint][codes[row.territory_id]],rel_tol=1e-14)
        assert row.region==d.loc[row.territory_id,'region_code']
        scalar+=2
    metrics=pd.read_csv(a.run/'external_metrics.csv')
    count=0
    for row in metrics.itertuples():
        f=pred.loc[(pred.method==row.method)&(pred.k==row.k)&(pred.seed==row.seed)&(pred.endpoint==row.endpoint)&(pred.arm==row.arm)]
        actual=math.fsum((float(t.actual_log2025)-float(t.predicted_log2025))**2 for t in f.itertuples())/len(f)
        assert math.isclose(actual,row.mse_log2025,rel_tol=1e-12)
        count+=1
    for c in results['comparisons']:
        f=pred.loc[(pred.method==c['method'])&(pred.k==c['k'])&(pred.seed==c['seed'])&(pred.endpoint==c['endpoint'])]
        cand=f.loc[f.arm==c['arm']].set_index('territory_id')
        ref=f.loc[f.arm==c['reference']].set_index('territory_id').reindex(cand.index)
        assert len(cand)==len(ref)==1248 and cand.index.is_unique and np.array_equal(cand.actual_log2025,ref.actual_log2025)
        groups={};delta=[];ref_losses=[]
        for tid in cand.index:
            aa,bb=cand.loc[tid],ref.loc[tid]
            ce=(float(aa.actual_log2025)-float(aa.predicted_log2025))**2
            re=(float(bb.actual_log2025)-float(bb.predicted_log2025))**2
            delta.append(re-ce);ref_losses.append(re)
            groups.setdefault(int(aa.region),[]).append(re-ce)
        benefit=math.fsum(delta)/len(delta);rmse=math.fsum(ref_losses)/len(ref_losses)
        assert math.isclose(benefit,c['delta_mse_reference_minus_arm'],rel_tol=1e-10,abs_tol=1e-15)
        assert math.isclose(100*benefit/rmse,c['relative_mse_reduction_percent'],rel_tol=1e-10,abs_tol=1e-12)
        totals=np.array([math.fsum(groups[g]) for g in sorted(groups)]);sizes=np.array([len(groups[g]) for g in sorted(groups)])
        draws=np.random.default_rng(c['seed']).integers(0,70,(2000,70))
        boots=totals[draws].sum(axis=1)/sizes[draws].sum(axis=1)
        np.testing.assert_allclose(np.quantile(boots,[.025,.975]),c['descriptive_region_bootstrap95'],rtol=1e-10,atol=1e-15)
    parts=pd.read_parquet(a.run/'partitions.parquet')
    assert len(parts)==84*1896 and not parts.duplicated(['territory_id','arm','method','k','seed']).any()
    size_checks=0
    for item in json.loads((a.run/'full_metrics.json').read_text()):
        f=parts.loc[(parts.arm==item['arm'])&(parts.method==item['method'])&(parts.k==item['k'])&(parts.seed==item['seed'])]
        assert len(f)==1896 and np.bincount(f.label,minlength=item['k']).tolist()==item['sizes']
        size_checks+=item['k']
    for entry in json.loads((a.run/'fold_receipts.json').read_text()):
        used=[]
        for fold in entry['folds']:
            assert not set(fold['train_regions'])&set(fold['test_regions'])
            assert fold['train']+fold['test']==1248
            used+=fold['test_regions']
        assert len(used)==len(set(used))==70
    receipt={'status':'INDEPENDENT_H5_NUMERICAL_AUDIT_PASS','checked_at':datetime.now(timezone.utc).isoformat(),'scientific_pass':False,'raw_2025_outcome_and_region_scalar_checks':scalar,'independent_MSE_checks':count,'independent_paired_comparison_and_interval_checks':len(results['comparisons']),'partition_size_checks':size_checks,'disjoint_region_fold_sets_checked':14,'oof_sha256':sha(a.run/'oof_predictions.parquet'),'partitions_sha256':sha(a.run/'partitions.parquet'),'code_sha256':sha(__file__),'scope':'Different numerical code, same viewed raw snapshots. Not external scientific review or unseen holdout.'}
    a.out.write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt))


if __name__=='__main__':main()
