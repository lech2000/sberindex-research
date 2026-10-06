import sys
from pathlib import Path
import numpy as np
import pandas as pd
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'economic-atlas/src'))
from audit_missingness_size import population2023,source_counts

def test_one_missing_sex_or_conflicting_sex_is_not_a_partial_population_total():
    d=pd.DataFrame([{'territory_id':1,'year':2023,'period':'год','age':'Всего','gender':'Женщины','value':10.},
                    {'territory_id':2,'year':2023,'period':'год','age':'Всего','gender':'Женщины','value':20.},
                    {'territory_id':2,'year':2023,'period':'год','age':'Всего','gender':'Мужчины','value':30.},
                    {'territory_id':2,'year':2023,'period':'год','age':'Всего','gender':'Мужчины','value':31.}])
    values,audit=population2023(d)
    assert values.isna().all() and audit['ambiguous_sex_cells']==1

def test_absent_cell_is_distinct_from_present_zero_and_unobserved_municipality():
    d=pd.DataFrame([{'territory_id':i,'date':m,'category':c,'value':10.} for i in [1,2] for m in pd.period_range('2023-01','2024-12',freq='M').astype(str) for c in range(6)])
    d=d.drop(index=0);d.loc[d.territory_id.eq(2)&d.date.eq('2023-01')&d.category.eq(0),'value']=0.
    counts=source_counts(d)
    assert list(counts.index)==[1,2]
    assert counts.loc[1,'missing_absent']==1 and counts.loc[1,'invalid']==0
    assert counts.loc[2,'missing_absent']==0 and counts.loc[2,'invalid']==1
