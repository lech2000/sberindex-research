import importlib.util
from pathlib import Path
import sys
import numpy as np
import pandas as pd
import pytest

src=Path(__file__).parents[1]/'economic-atlas/src'
sys.path.insert(0,str(src))
spec=importlib.util.spec_from_file_location('h5',src/'atlas_h5_scale_audit.py')
h5=importlib.util.module_from_spec(spec);spec.loader.exec_module(h5)


def panel():
    rows=[]
    for tid in range(1,5):
        for m in range(1,13):
            total=1000*tid+10*m
            for category, value in [(h5.TOTAL,total)]+[(c,total*(i+1)/25) for i,c in enumerate(h5.CATS)]:
                rows.append((tid,f'2023-{m:02d}',category,value))
    return pd.DataFrame(rows,columns=['territory_id','ym','category','value'])


def test_per_territory_currency_conversion_preserves_structure():
    d=panel();ids,a=h5.feature_sets(d)
    d.value*=d.territory_id.map({1:1.,2:1e3,3:1e-3,4:7.})
    ids2,b=h5.feature_sets(d)
    np.testing.assert_array_equal(ids,ids2)
    np.testing.assert_allclose(a['shares'],b['shares'],rtol=1e-14,atol=1e-14)
    assert not np.allclose(a['volume'],b['volume'])


def test_legacy_shares_are_not_budget_shares():
    d=panel();_,f=h5.feature_sets(d)
    np.testing.assert_allclose(f['shares'].sum(axis=1),.6)
    np.testing.assert_allclose(f['legacy_shares6'].sum(axis=1),1.)
    np.testing.assert_allclose(f['legacy_shares6'][:,0],1/1.6)


def test_future_spending_and_outcome_columns_cannot_enter_features():
    d=panel();_,a=h5.feature_sets(d)
    future=d.copy();future.ym=future.ym.str.replace('2023','2024');future.value*=1e6
    d=pd.concat([d,future]);d['wage2025']=float('inf');d['region_code']=range(len(d))
    _,b=h5.feature_sets(d)
    assert all(np.array_equal(a[k],b[k]) for k in h5.ARMS)


def test_incomplete_month_duplicate_and_zero_rejected():
    d=panel()
    with pytest.raises(ValueError,match='Incomplete'):
        h5.feature_sets(d.iloc[1:])
    with pytest.raises(ValueError,match='Duplicate'):
        h5.feature_sets(pd.concat([d,d.iloc[:1]]))
    d.loc[0,'value']=0
    with pytest.raises(ValueError,match='nonpositive'):
        h5.feature_sets(d)


def test_test_region_cannot_change_training_scaler_or_partition():
    a=np.array([[0.,1.],[1.,0.],[10.,12.],[12.,10.]])
    t=np.array([[3.,4.],[8.,9.]])
    for method in ('kmeans','ward'):
        first=h5.fit(a,t,method,2,42)
        second=h5.fit(a,t*1e10,method,2,42)
        np.testing.assert_array_equal(first[0],second[0])
        np.testing.assert_array_equal(first[2].mean_,second[2].mean_)
        np.testing.assert_array_equal(first[2].scale_,second[2].scale_)
