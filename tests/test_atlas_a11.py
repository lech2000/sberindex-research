from pathlib import Path
import sys
import numpy as np
import pytest
from sklearn.datasets import make_blobs

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"economic-atlas/src"))
from atlas_sdbw import s_dbw


def test_sdbw_six_points_independent_hand_calculation():
    # Groups{-1,0,1},{15,16,17}; centres0,16; group variance2/3;
    # total variance64+2/3=194/3; radius=sqrt(4/3)/2=sqrt(1/3).
    # Each centre contains1 point, midpoint8 contains0: Scat=1/97, Dens=0.
    x=np.array([-1,0,1,15,16,17.])[:,None]
    r=s_dbw(x,[0,0,0,1,1,1])
    assert r["radius"]==pytest.approx(np.sqrt(1/3))
    assert r["Scat"]==pytest.approx(1/97) and r["Dens_bw"]==0
    assert r["S_Dbw"]==pytest.approx(1/97)


def test_sdbw_true_separated_groups_better_than_fixed_random_labels():
    # Finite centre densities for both partitions; extremely thin separated
    # blobs give undefined random-label densities and cannot be ordered.
    x,truth=make_blobs(n_samples=200,centers=[[-3,0],[3,0]],cluster_std=.8,random_state=9)
    random=np.random.default_rng(3).permutation(truth)
    assert s_dbw(x,truth)["S_Dbw"]<s_dbw(x,random)["S_Dbw"]


def test_zero_density_is_na_without_epsilon_and_k1_is_outside_domain():
    x=np.array([-10,10,90,110.])[:,None]
    r=s_dbw(x,[0,0,1,1])
    assert r["status"]=="NA_ZERO_DENSITY_DENOMINATOR" and r["S_Dbw"] is None
    assert s_dbw(x,[0,0,0,0])["status"]=="NA_K_DOMAIN"
    with pytest.raises(ValueError,match="Empty declared"):
        s_dbw(x,[0,0,1,1],expected_k=3)


def test_sdbw_label_and_row_permutation_invariance():
    x=np.array([-1,0,1,15,16,17.])[:,None]
    labels=np.array([5,5,5,9,9,9])
    p=np.array([5,1,3,0,4,2])
    assert s_dbw(x,labels)["S_Dbw"]==pytest.approx(s_dbw(x[p],100-labels[p])["S_Dbw"])


def test_avu_k3_constant_when_any_cross_edge_and_zero_when_no_cross_edge():
    import network_icvi as icvi
    rng=np.random.default_rng(41)
    a=rng.uniform(.1,2,size=(9,9))
    a=np.triu(a,1);a=a+a.T
    labels=np.repeat([0,1,2],3)
    # For K3 every off-diagonal denominator is a+b+c; summing all
    # ordered cross-cluster terms gives2 and dividing by3 gives2/3.
    assert icvi.avu(a,labels)==pytest.approx(2/3)
    a[labels[:,None]!=labels[None,:]]=0
    assert icvi.avu(a,labels)==0
