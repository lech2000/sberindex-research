"""Nontrivial formula, future, CV boundary and permutation contracts."""
import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from sklearn.metrics import adjusted_rand_score

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('ablation', ROOT/'economic-atlas/src/atlas_radar_ablation.py')
m = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(m)


def panel():
    cats = [m.ALL, 'A', 'B', 'C', 'D', 'E']
    rows = []
    for tid in range(20):
        for year in (2023, 2024):
            for month in range(1, 13):
                for cat_ix, cat in enumerate(cats):
                    val = (1000+tid*10)*(1+month/30)*(1 if cat_ix==0 else .01*cat_ix)
                    if year==2024: val *= 1.2
                    rows.append((tid, f'{year}-{month:02d}', cat, val))
    return pd.DataFrame(rows, columns=['territory_id', 'ym', 'category', 'value'])


def test_exact_own_seasonal_scalar_and_zero_residual():
    p = panel(); ids, base, radar, raw, forecast, cats = m.features(p)
    assert m.seasonal_scalar_audit(p, forecast, ids, cats) == 20*6*6
    np.testing.assert_allclose(radar, 0, atol=1e-14)
    np.testing.assert_allclose(raw[:, :6], np.log(1.2), atol=1e-14)
    np.testing.assert_allclose(raw[:, 6:], 0, atol=1e-14)


def test_future_mutation_invariance_and_past_sensitivity():
    p = panel(); before = m.features(p)
    future = p.copy(); future.loc[future.ym>'2024-09', 'value'] *= 100
    for a,b in zip(before[:5], m.features(future)[:5]): np.testing.assert_array_equal(a,b)
    changed = p.copy(); changed.loc[(changed.ym=='2024-04') & (changed.category=='A'), 'value'] *= 1.5
    assert not np.array_equal(before[2], m.features(changed)[2])


def test_duplicate_and_missing_panel_fail_closed():
    p = panel()
    with pytest.raises(AssertionError, match='duplicate'): m.features(pd.concat([p,p.iloc[:1]]))
    with pytest.raises(AssertionError, match='missing'): m.features(p.iloc[1:])
    p.loc[0,'value']=0
    with pytest.raises(AssertionError, match='nonpositive'): m.features(p)


def test_identical_duplicates_nan_and_conflict_are_distinct():
    d = pd.DataFrame({'id':[1,1,2,2,3,3], 'value':[3,3,4,np.nan,5,6]})
    result, audit = m.unique_finite(d,['id'],'value')
    assert result.loc[1]==3 and result.loc[2]==4 and np.isnan(result.loc[3])
    assert audit['conflicting_finite_keys']==1


def test_heldout_values_cannot_change_training_scalers_and_centroids():
    rng=np.random.default_rng(7); base=rng.normal(size=(100,5)); temp=rng.normal(size=(100,12))
    one=m.fitted_clusters(base[:80],base[80:],temp[:80],temp[80:],2,m.SEED)
    two=m.fitted_clusters(base[:80],base[80:]*1e6,temp[:80],temp[80:]*1e6,2,m.SEED)
    np.testing.assert_array_equal(one[0],two[0]);np.testing.assert_array_equal(one[2].cluster_centers_,two[2].cluster_centers_)
    np.testing.assert_array_equal(one[3].mean_,base[:80].mean(axis=0))
    np.testing.assert_array_equal(one[4].mean_,temp[:80].mean(axis=0))


def test_planted_radar_signal_positive_control():
    rng=np.random.default_rng(31); n=200; labels=np.repeat([0,1],n//2)
    base=rng.normal(size=(n,5)); radar=(2*labels[:,None]-1)+rng.normal(scale=.05,size=(n,12))
    fitted=m.fitted_clusters(base,base,radar,radar,2,m.SEED)[0]
    assert adjusted_rand_score(labels,fitted)>.95


def test_permutation_preserves_whole_rows_and_region_type_cells():
    b=np.arange(48).reshape(12,4); regions=np.repeat([1,2],6);types=np.tile(['A','A','A','B','B','B'],2)
    shuffled=m.permuted(b,regions,types,99)
    for r in [1,2]:
        for t in ['A','B']:
            ix=(regions==r)&(types==t)
            assert sorted(map(tuple,b[ix]))==sorted(map(tuple,shuffled[ix]))
    assert not np.array_equal(b,shuffled)


def test_paired_region_bootstrap_same_mask_and_difference():
    rows=[]
    for tid in range(20):
        for arm,pred in [('base',1.),('radar',.5)]:
            rows.append((tid,tid//2,arm,0.,pred))
    f=pd.DataFrame(rows,columns=['territory_id','region','arm','actual_log2025','predicted_log2025'])
    result=m.paired_bootstrap(f,'radar','base',b=100)
    assert result['delta_mse_reference_minus_arm']==.75
    assert result['descriptive_region_bootstrap95']==[.75,.75]
    with pytest.raises(AssertionError):m.paired_bootstrap(f.iloc[:-1],'radar','base',b=20)
