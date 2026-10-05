from pathlib import Path
import sys
import numpy as np
import pandas as pd
import unittest
from math import isclose
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'economic-atlas/src'))
from atlas_radar_joint import pre_features,recovery,match


def sample():
    cats=['Все категории','Здоровье','Маркетплейсы','Общественное питание','Продовольствие','Транспорт']
    rows=[{'territory_id':tid,'ym':f'{y}-{m:02d}','category':c,'value':100 if c=='Все категории' else 10+m}
          for tid in range(1,8) for y in [2023,2024] for m in range(1,13) for c in cats]
    population=pd.DataFrame([{'territory_id':tid,'year':y,'age':'Всего','period':'год','gender':g,'value':500}
                            for tid in range(1,8) for y in [2023,2024] for g in ['Мужчины','Женщины']])
    return pd.DataFrame(rows),population


def test_features_ignore_future_and_age_parts():
    panel,pop=sample();f,c=pre_features(panel,pop)
    assert isclose(f.at[1,'share_Маркетплейсы'],.165)
    assert f.at[1,'population_2023']==1000
    changed=panel.copy();changed.loc[changed.ym>'2023-12','value']*=10**6
    p=pop.copy();p.loc[p.year==2024,'value']*=10**6
    p=pd.concat([p,p.assign(age='1',value=999999)])
    altered,_=pre_features(changed,p)
    pd.testing.assert_frame_equal(f,altered)


def test_population_exact_duplicates_missing_and_conflicts():
    panel,pop=sample();male=pop.loc[(pop.territory_id==1)&(pop.year==2023)&(pop.gender=='Мужчины')]
    f,_=pre_features(panel,pd.concat([pop,male,male.assign(value=np.nan)]));assert f.at[1,'population_2023']==1000
    f,_=pre_features(panel,pd.concat([pop,male.assign(value=501)]));assert pd.isna(f.at[1,'population_2023'])


def test_matching_enforces_population_region_type_and_support():
    panel,pop=sample();f,_=pre_features(panel,pop)
    dictionary=pd.DataFrame([{'territory_id':t,'name_short':'Anchor' if t==1 else str(t),'type':'city',
                              'region_code':56 if t==1 else 1,'year_from':2010,'year_to':9999} for t in range(1,8)])
    proto={'anchors':[{'name':'Anchor','territory_id':1,'region_code':56}],
           'comparison':{'exclude_regions':[56,45,72],'minimum_peers':5,'nearest':10,'max_standardized_distance':3}}
    peers,_,_=match(f,dictionary,proto);assert list(peers.peer_tid)==[2,3,4,5,6,7]
    dictionary.loc[dictionary.territory_id.isin([6,7]),'region_code']=72
    peers,_,_=match(f,dictionary,proto);assert list(peers.status)==['NO_MATCH_SUPPORT']


def test_recovery_requires_initial_decline_and_confirming_month():
    assert recovery([-9,0,0,0,0,0,0,0,0])==('NOT_APPLICABLE_NO_INITIAL_DROP',None)
    assert recovery([-15,-20,4,5,-30,0,0,0,0])==('REENTERED_MODEL_BAND',2)
    assert recovery([-15,-20,0,-20,0,-20,0,-20,0])==('RIGHT_CENSORED_AT_DECEMBER',None)
    with unittest.TestCase().assertRaises(ValueError):recovery([-15,0])


if __name__=="__main__":
    tests=[v for k,v in globals().items() if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
    print(f"{len(tests)} meaningful checks passed")
