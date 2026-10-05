from pathlib import Path
import sys
import numpy as np
import pytest

SRC=Path(__file__).resolve().parents[1]/"economic-atlas/src"
sys.path.insert(0,str(SRC))
from atlas_a9 import build_network


@pytest.mark.parametrize("mode",["union","mutual"])
@pytest.mark.parametrize("weight",["gaussian","binary"])
def test_graph_contract_and_same_input_reproducibility(mode,weight):
    x=np.random.default_rng(11).normal(size=(40,3))
    a,e,sigma=build_network(x,5,mode,weight)
    b,ee,_=build_network(x,5,mode,weight)
    assert np.array_equal(a,b) and e.equals(ee)
    assert np.array_equal(a,a.T) and not np.diag(a).any() and (a>=0).all()
    assert (e.src<e.dst).all() and not e.duplicated(["src","dst"]).any()


def test_duplicate_coordinates_do_not_create_self_loop_or_drop_neighbor():
    x=np.array([[0.],[0.],[1.],[3.]])
    a,e,_=build_network(x,1,weight="binary",ids=np.array([50,10,30,20]))
    assert not np.diag(a).any() and (10,50) in set(zip(e.src,e.dst))
    assert (a>0).sum(1).min()>=1


def test_mutual_graph_preserves_isolated_nodes_and_noncontiguous_ids():
    x=np.array([[0.],[.1],[50.]])
    a,e,_=build_network(x,1,mode="mutual",weight="binary",ids=[101,202,303])
    assert a.shape==(3,3) and (a[2]==0).all()
    assert e[["src","dst"]].values.tolist()==[[101,202]]


def test_frozen_mask_has_1896_unique_nodes():
    from atlas_common import load_features
    ids,x=load_features()
    assert len(ids)==len(set(ids))==1896 and x.shape==(1896,5)

