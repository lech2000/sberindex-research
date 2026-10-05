from pathlib import Path
import sys
import numpy as np
import pandas as pd
import pytest
from sklearn.metrics import adjusted_rand_score

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"economic-atlas/src"))
from atlas_a12 import coassociation,consensus_cores,passports,regional_bootstrap,population_by_year


def test_consistent_groups_form_full_cores_and_config_order_does_not_matter():
    truth=np.repeat([0,1],5)
    configurations=np.array([truth,10-truth,truth*3+7])
    c=coassociation(configurations)
    lab,score,core=consensus_cores(c,k=2)
    ll,ss,cc=consensus_cores(coassociation(configurations[::-1]),k=2)
    assert adjusted_rand_score(lab,truth)==1 and core.all() and np.all(score==1)
    assert np.array_equal(score,ss) and np.array_equal(core,cc)


def test_self_is_excluded_and_threshold_uses_full_group():
    c=np.array([[1,.8,.8],[.8,1,.8],[.8,.8,1]])
    _,score,core=consensus_cores(c,k=1,threshold=.9)
    assert np.allclose(score,.8) and not core.any()


def test_singleton_cannot_claim_certain_core():
    _,score,core=consensus_cores(np.eye(3),k=3)
    assert np.isnan(score).all() and not core.any()


def test_ambiguous_nodes_cannot_enter_core_passport_or_typical_examples():
    ids=np.arange(8)
    x=np.arange(8.)[:,None]/10
    labels=np.repeat([0,1],4)
    score=np.array([1,1,1,.5,.5,.5,.5,.5])
    p=passports(ids,x,x,labels,score,np.array([1,1,2,2,1,1,2,2]),ids.astype(str),np.ones(8)*100)
    assert len(p)==1 and p[0]["n_core"]==3
    assert {r["territory_id"] for r in p[0]["typical_MO"]}=={0,1,2}


def test_region_bootstrap_reproduces_constant_and_retains_missing_resamples():
    r=regional_bootstrap(np.ones(4)*7,np.array([1,1,2,2]),np.array([True,True,False,False]),seed=7)
    assert r[0]["ci95"]==[7,7] and r[0]["NA_resamples"]>0


def test_population_exact_duplicate_not_double_counted_conflicts_rejected():
    d=pd.DataFrame({"territory_id":[1,1,1],"year":[2023]*3,"age":["Всего"]*3,
                    "gender":["Женщины","Мужчины","Женщины"],"value":[100.,80.,100.]})
    assert population_by_year(d).loc[1,2023]==180
    d.loc[2,"value"]=101
    with pytest.raises(ValueError,match="Duplicate population"):
        population_by_year(d)
