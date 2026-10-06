"""Separate scalar/normalization audit; no training-module imports."""
from pathlib import Path
from datetime import datetime,timezone
import argparse,json,math,hashlib
import numpy as np
import pandas as pd

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
    p=argparse.ArgumentParser()
    for key in ['run','reference','panel','dictionary','protocol','out']:p.add_argument('--'+key,type=Path,required=True)
    a=p.parse_args();assert not a.out.exists()
    protocol=json.loads(a.protocol.read_text());result=json.loads((a.run/'results.json').read_text());start=json.loads((a.run/'execution-start.json').read_text())
    assert result['protocol_sha256']==sha(a.protocol)==start['protocol_sha256']
    assert result['code_sha256']==sha(Path(__file__).with_name('dimensionless_scale_audit.py'))==start['code_sha256']
    assert sha(a.panel)==protocol['inputs']['panel'] and sha(a.dictionary)==protocol['inputs']['dictionary']
    assert result['reference_predictions_sha256']==sha(a.reference/'oof_predictions.parquet')
    pred=pd.read_parquet(a.run/'oof_predictions.parquet');ref=pd.read_parquet(a.reference/'oof_predictions.parquet')
    assert len(pred)==34944 and not pred.duplicated(['territory_id','method','k','seed','endpoint']).any()
    assert np.isfinite(pred[['actual_log2025','predicted_log2025']].to_numpy()).all()
    for key,g in pred.groupby(['method','k','seed','endpoint']):
        method,k,seed,endpoint=key
        c=ref[(ref.method==method)&(ref.k==k)&(ref.seed==seed)&(ref.endpoint==endpoint)&ref.arm.eq('shares')].set_index('territory_id')
        d=g.set_index('territory_id');assert set(c.index)==set(d.index) and len(d)==1248;c=c.reindex(d.index)
        np.testing.assert_array_equal(d.actual_log2025,c.actual_log2025);np.testing.assert_array_equal(d.region,c.region);np.testing.assert_array_equal(d.fold,c.fold)
    saved=json.loads((a.run/'metrics.json').read_text())
    for row in saved:
        g=pred[(pred.method==row['method'])&(pred.k==row['k'])&(pred.seed==row['seed'])&(pred.endpoint==row['endpoint'])]
        mse=math.fsum((float(t.actual_log2025)-float(t.predicted_log2025))**2 for t in g.itertuples())/len(g)
        assert math.isclose(mse,row['mse'],rel_tol=1e-12)
    comparisons=json.loads((a.run/'comparisons.json').read_text())
    for row in comparisons:
        mask=lambda f:(f.method==row['method'])&(f.k==row['k'])&(f.seed==row['seed'])&(f.endpoint==row['endpoint'])
        d=pred[mask(pred)].set_index('territory_id');c=ref[mask(ref)&ref.arm.eq(row['reference'])].set_index('territory_id').reindex(d.index)
        own=np.array([(float(t.actual_log2025)-float(t.predicted_log2025))**2 for t in d.itertuples()])
        old=np.array([(float(t.actual_log2025)-float(t.predicted_log2025))**2 for t in c.itertuples()]);delta=old-own
        cmse=math.fsum(old)/len(old);gain=math.fsum(delta)/len(delta)
        assert math.isclose(gain,row['delta_mse_reference_minus_arm'],rel_tol=1e-10,abs_tol=1e-14)
        assert math.isclose(100*gain/cmse,row['relative_mse_reduction_percent'],rel_tol=1e-10,abs_tol=1e-12)
        regions=sorted(d.region.unique());assert len(regions)==70
        sums=np.array([math.fsum(delta[d.region.to_numpy()==reg]) for reg in regions]);sizes=np.array([int(d.region.eq(reg).sum()) for reg in regions])
        draws=np.random.default_rng(row['seed']).integers(0,70,(2000,70));ci=np.quantile(sums[draws].sum(axis=1)/sizes[draws].sum(axis=1),[.025,.975])
        np.testing.assert_allclose(ci,row['descriptive_region_bootstrap95'],rtol=1e-10,atol=1e-13)
    panel=pd.read_parquet(a.panel);raw=panel[panel.ym.str.startswith('2023-')&panel.category.eq('Все категории')]
    mean={int(t):math.fsum(float(v) for v in g.value)/12 for t,g in raw.groupby('territory_id')}
    dictionary=pd.read_parquet(a.dictionary).set_index('territory_id');folds=json.loads((a.run/'folds.json').read_text())
    for fold in folds:
        tr=fold['train_ids'];te=fold['test_ids'];assert not set(tr)&set(te)
        assert not set(dictionary.loc[tr].region_code)&set(dictionary.loc[te].region_code)
        expected=float(np.median([mean[int(t)] for t in tr]));assert math.isclose(expected,fold['median_train'],rel_tol=1e-12)
        orig=np.array([math.log(v/expected) for v in mean.values()]);scaled_median=np.median([mean[int(t)]*.001 for t in tr])
        converted=np.array([math.log(v*.001/scaled_median) for v in mean.values()]);np.testing.assert_allclose(orig,converted,rtol=1e-12,atol=1e-12)
        assert fold['unit_train_ARI']==fold['unit_test_ARI']==1
    full=json.loads((a.run/'full-partitions.json').read_text());assert len(full)==14 and all(v['ruble_to_thousand_ARI']==1 for v in full)
    receipt={'status':'INDEPENDENT_DIMENSIONLESS_SCALAR_AND_NORMALIZATION_AUDIT_PASS','checked_at':datetime.now(timezone.utc).isoformat(),'checked_where':'Mac separate scalar math.fsum, region bootstrap and raw2023 normalization; no training-module imports','scientific_pass':False,'forecast_rows_and_labels_checked':len(pred),'mse_values_checked':len(saved),'paired_region_intervals_checked':len(comparisons),'train_only_medians_checked':len(folds),'unit_normalization_cells_checked':len(folds)*len(mean),'full_unit_ARI1':len(full),'run_predictions_sha256':sha(a.run/'oof_predictions.parquet'),'auditor_sha256':sha(__file__),'limits':'Numerical implementation verification on the same reviewed2025 outcomes; no independent future holdout or economic causality.'}
    a.out.parent.mkdir(parents=True,exist_ok=True);a.out.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n');print(json.dumps(receipt))
if __name__=='__main__':main()
