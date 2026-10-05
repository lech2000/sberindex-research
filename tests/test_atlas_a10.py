from pathlib import Path
import sys
import numpy as np
import pytest
from sklearn.datasets import make_blobs
from sklearn.metrics import adjusted_rand_score

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"economic-atlas/src"))
from atlas_a10 import METHODS,fit_method
from atlas_a9 import louvain_labels


@pytest.mark.parametrize("method",METHODS)
def test_known_well_separated_groups_and_seed_reproduction(method):
    x,truth=make_blobs(n_samples=120,centers=[[-8,0],[0,8],[8,0]],cluster_std=.08,random_state=13)
    a,info=fit_method(x,method,3,seed=13)
    b,_=fit_method(x,method,3,seed=13)
    assert info["valid_fixed_K"] and adjusted_rand_score(a,b)==1
    assert adjusted_rand_score(a,truth)>.95


def test_ari_ignores_permutation_of_arbitrary_label_ids():
    lab=np.array([0,0,1,1,2,2])
    assert adjusted_rand_score(lab,np.array([99,99,7,7,42,42]))==1


def test_louvain_on_known_disconnected_dense_blocks():
    truth=np.repeat(np.arange(3),10)
    a=(truth[:,None]==truth[None,:]).astype(float)
    np.fill_diagonal(a,0)
    labels=louvain_labels(a,seed=13)
    assert adjusted_rand_score(labels,truth)==1

