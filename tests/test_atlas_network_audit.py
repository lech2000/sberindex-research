"""Аудит AVI/AVU: построение экономической сети (economic-atlas/runs/A7_network_icvi_audit_20261005/audit.py)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest

RUN = Path(__file__).resolve().parents[1] / "economic-atlas" / "runs" / "A7_network_icvi_audit_20261005"
_spec = importlib.util.spec_from_file_location("a7_network_audit", RUN / "audit.py")
au = importlib.util.module_from_spec(_spec)
sys.modules["a7_network_audit"] = au
_spec.loader.exec_module(au)


def test_knn_union_network_is_symmetric_connected_and_counts_union_edges():
    rng = np.random.default_rng(0)
    Z = np.vstack([rng.normal(0, 0.1, (30, 3)), rng.normal(4, 0.1, (30, 3))])
    A, sigma = au.knn_union_network(Z, k=3, weighted=False)
    assert np.allclose(A, A.T) and not np.diag(A).any() and sigma > 0
    n_edges = int((A > 0).sum() // 2)
    assert 60 * 3 / 2 <= n_edges <= 60 * 3  # от «все соседства взаимны» до «ни одного взаимного»
    W, _ = au.knn_union_network(Z, k=3, weighted=True)
    assert ((W > 0) == (A > 0)).all() and W.max() <= 1.0 and W[W > 0].min() > 0


def test_two_separated_blobs_give_two_components_and_perfect_partition():
    rng = np.random.default_rng(1)
    Z = np.vstack([rng.normal(0, 0.1, (25, 2)), rng.normal(50, 0.1, (25, 2))])
    A, _ = au.knn_union_network(Z, k=4, weighted=False)
    assert au.n_components(A) == 2
    lab = np.repeat([0, 1], 25)
    rows = au.analyse(A, {"truth": lab}, B=20)
    r = rows[0]
    assert r["AVI"] == pytest.approx(1.0) and r["avi_z"] > 10 and r["uniform_avu_value"] == pytest.approx(1.0)
