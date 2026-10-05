"""Сетевые индексы Атласа: AVI, AVU, ANUI, модулярность Ньюмана (economic-atlas/src/network_icvi.py).

Игрушечные графы с ответом, посчитанным вручную; сверка с networkx; сверка с эталоном Shalileh (Sorooshi/Pattern,
GPL-3.0) — только если файл эталона указан в SBERINDEX_PATTERN_REF (в репозиторий он не входит).
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[1] / "economic-atlas" / "src"
_spec = importlib.util.spec_from_file_location("network_icvi", SRC / "network_icvi.py")
icvi = importlib.util.module_from_spec(_spec)
sys.modules["network_icvi"] = icvi
_spec.loader.exec_module(icvi)


def two_cliques(n=6):
    A = np.zeros((2 * n, 2 * n))
    A[:n, :n] = 1
    A[n:, n:] = 1
    np.fill_diagonal(A, 0)
    return A, np.repeat([0, 1], n)


def hand_graph():
    """Узлы 0–1 (вес 2) и 2–3 (вес 2), мост 1–2 (вес 1); кластеры {0,1} и {2,3}.
    S = [[4, 1], [1, 4]]; I = 4/5 = 0,8; AVI = 0,8; U_AB = U_BA = 1/(1+1−1) = 1; AVU = 1;
    ANUI = 1/(1 + 1/0,8) = 4/9; 2m = 10, d = 5 и 5: Q = 2·(4/10 − 1/4) = 0,3."""
    A = np.zeros((4, 4))
    A[0, 1] = A[1, 0] = 2
    A[2, 3] = A[3, 2] = 2
    A[1, 2] = A[2, 1] = 1
    return A, np.array([0, 0, 1, 1])


def test_perfect_partition_of_two_cliques():
    A, lab = two_cliques()
    r = icvi.compute_network_indices(A, lab)
    assert r["AVI"] == pytest.approx(1.0) and r["AVU"] == pytest.approx(0.0)
    assert r["ANUI"] == pytest.approx(1.0) and r["modularity_newman"] == pytest.approx(0.5)
    assert r["clusters_without_edges"] == 0


def test_hand_computed_values():
    A, lab = hand_graph()
    S = icvi.block_sums(A, lab)
    assert S.tolist() == [[4.0, 1.0], [1.0, 4.0]]
    assert icvi.avi(A, lab) == pytest.approx(0.8)
    assert icvi.avu(A, lab) == pytest.approx(1.0)
    assert icvi.anui(A, lab) == pytest.approx(4 / 9)
    assert icvi.modularity_newman(A, lab) == pytest.approx(0.3)


def test_mq_is_not_silently_replaced_by_modularity():
    """Определение MQ не установлено: ключ «MQ» несёт статус, а не число."""
    A, lab = hand_graph()
    r = icvi.compute_network_indices(A, lab)
    assert r["MQ"] == "SPEC_UNRESOLVED" and isinstance(r["modularity_newman"], float)


def test_modularity_matches_networkx_weighted():
    nx = pytest.importorskip("networkx")
    rng = np.random.default_rng(20261004)
    n = 40
    A = rng.random((n, n)) * (rng.random((n, n)) < 0.2)
    A = np.triu(A, 1)
    A = A + A.T
    lab = rng.integers(0, 4, n)
    g = nx.from_numpy_array(A)
    comms = [set(np.flatnonzero(lab == c)) for c in np.unique(lab)]
    assert icvi.modularity_newman(A, lab) == pytest.approx(nx.community.modularity(g, comms, weight="weight"))


def test_invariant_to_relabeling_and_node_permutation():
    rng = np.random.default_rng(1)
    n = 30
    A = rng.random((n, n)) * (rng.random((n, n)) < 0.25)
    A = np.triu(A, 1)
    A = A + A.T
    lab = rng.integers(0, 3, n)
    base = icvi.compute_network_indices(A, lab)
    perm = rng.permutation(n)
    shuffled = icvi.compute_network_indices(A[np.ix_(perm, perm)], lab[perm])
    renamed = icvi.compute_network_indices(A, np.array([10, 20, 30])[lab])
    for k in ("AVI", "AVU", "ANUI", "modularity_newman"):
        assert shuffled[k] == pytest.approx(base[k]) and renamed[k] == pytest.approx(base[k])


def test_direction_planted_partition_beats_random_labels():
    rng = np.random.default_rng(7)
    n, k = 100, 5
    truth = np.repeat(np.arange(k), n // k)
    P = np.where(truth[:, None] == truth[None, :], 0.5, 0.05)
    A = np.triu((rng.random((n, n)) < P).astype(float), 1)
    A = A + A.T
    good = icvi.compute_network_indices(A, truth)
    bad = icvi.compute_network_indices(A, rng.integers(0, k, n))
    # AVU намеренно не проверяется на направление: см. test_avu_measures_evenness_not_strength_of_separation
    assert good["AVI"] > bad["AVI"]
    assert good["ANUI"] > bad["ANUI"] and good["modularity_newman"] > bad["modularity_newman"]


@pytest.mark.parametrize("K,expected", [(2, 1.0), (3, 2 / 3)])
def test_avu_is_constant_for_two_and_three_clusters_on_undirected_networks(K, expected):
    """Свойство определения, а не ошибка кода. K = 2: знаменатель U_12 = S_12 + S_12 − S_12 = S_12, значит U = 1.
    K = 3: знаменатель каждой пары равен D = S_12 + S_13 + S_23, сумма по упорядоченным парам = 2D, значит AVU = 2/3.
    Поэтому AVU различает разбиения только при K ≥ 4 — при K = 2 (число групп Атласа) он ничего не говорит."""
    for seed in range(5):
        rng = np.random.default_rng(seed)
        n = 60
        A = rng.random((n, n)) * (rng.random((n, n)) < 0.3)
        A = np.triu(A, 1)
        A = A + A.T
        lab = rng.integers(0, K, n)
        assert icvi.avu(A, lab) == pytest.approx(expected)


@pytest.mark.parametrize("K", [2, 3, 4, 5, 8])
@pytest.mark.parametrize("cross", [0.01, 0.5])
def test_avu_measures_evenness_not_strength_of_separation(K, cross):
    """При равных связях между всеми парами кластеров U_kl = 1/(2K−3), AVU = (K−1)/(2K−3) — НЕЗАВИСИМО от силы
    межкластерных связей. AVU не мера силы разделения, а мера того, насколько связи кластера сосредоточены на одном
    соседе («кандидат на слияние»). Выбирать по нему число групп нельзя; читать его надо вместе с AVI и модулярностью."""
    m = 6
    lab = np.repeat(np.arange(K), m)
    A = np.where(lab[:, None] == lab[None, :], 1.0, cross)
    np.fill_diagonal(A, 0.0)
    assert icvi.avu(A, lab) == pytest.approx((K - 1) / (2 * K - 3))


def test_avu_varies_for_four_or_more_clusters():
    vals = set()
    for seed in range(5):
        rng = np.random.default_rng(100 + seed)
        n = 80
        A = rng.random((n, n)) * (rng.random((n, n)) < 0.3)
        A = np.triu(A, 1)
        A = A + A.T
        vals.add(round(icvi.avu(A, rng.integers(0, 4, n)), 6))
    assert len(vals) > 1


def test_single_cluster_and_empty_cluster_conventions():
    A, _ = two_cliques()
    one = icvi.compute_network_indices(A, np.zeros(len(A), int))
    assert one["AVI"] == pytest.approx(1.0) and one["AVU"] == pytest.approx(0.0) and one["ANUI"] == pytest.approx(1.0)
    # кластер из двух узлов без единого ребра: I = 0 по соглашению, и это видно в служебном поле
    A2 = np.zeros((4, 4))
    A2[0, 1] = A2[1, 0] = 1
    r = icvi.compute_network_indices(A2, np.array([0, 0, 1, 1]))
    assert r["clusters_without_edges"] == 1 and r["AVI"] == pytest.approx(0.5)


@pytest.mark.parametrize("bad", ["asym", "neg", "diag", "nan"])
def test_invalid_input_is_rejected(bad):
    A, lab = two_cliques(3)
    if bad == "asym":
        A[0, 1] = 5
    elif bad == "neg":
        A[0, 1] = A[1, 0] = -1
    elif bad == "diag":
        A[0, 0] = 1
    else:
        A[0, 1] = A[1, 0] = np.nan
    with pytest.raises(ValueError):
        icvi.compute_network_indices(A, lab)


def test_matches_shalileh_reference_when_provided():
    ref_path = os.environ.get("SBERINDEX_PATTERN_REF")
    if not ref_path or not Path(ref_path).exists():
        pytest.skip("SBERINDEX_PATTERN_REF не задан (эталон под GPL-3.0 в репозиторий не входит)")
    spec = importlib.util.spec_from_file_location("clustering_metrics_ref", ref_path)
    ref = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ref)
    rng = np.random.default_rng(42)
    for _ in range(20):
        n = int(rng.integers(20, 60))
        A = rng.random((n, n)) * (rng.random((n, n)) < 0.2)
        A = np.triu(A, 1)
        A = A + A.T
        lab = rng.integers(0, int(rng.integers(2, 6)), n)
        r = ref.AdjacencyClusteringMetrics().get_metric(A, lab)
        mine = icvi.compute_network_indices(A, lab)
        assert mine["AVI"] == pytest.approx(r["AVI"]) and mine["AVU"] == pytest.approx(r["AVU"])
        assert mine["ANUI"] == pytest.approx(r["ANUI"]) and mine["modularity_newman"] == pytest.approx(r["modularity"])


def test_random_partition_null_matches_the_one_over_k_rule_and_exposes_a_giant_cluster():
    """Для K равных групп и случайных меток AVI ≈ 1/K; настоящее разбиение должно быть далеко выше нуля; гигант поднимает AVI без качества."""
    rng = np.random.default_rng(11)
    n, k = 300, 5
    truth = np.repeat(np.arange(k), n // k)
    P = np.where(truth[:, None] == truth[None, :], 0.2, 0.01)
    A = np.triu((rng.random((n, n)) < P).astype(float), 1)
    A = A + A.T
    r = icvi.random_partition_null(A, truth, B=60, seed=1)
    assert r["AVI"]["null_mean"] == pytest.approx(1 / k, abs=0.03) and r["AVI"]["z"] > 20
    assert r["modularity_newman"]["z"] > 20 and r["B"] == 60
    # слияние настоящих групп в гиганта: AVI растёт, модулярность падает (AVI «любит» крупные группы)
    merged = np.where(truth < 3, 0, truth - 2)
    t_ = icvi.compute_network_indices(A, truth)
    m_ = icvi.compute_network_indices(A, merged)
    assert m_["AVI"] > t_["AVI"] and m_["modularity_newman"] < t_["modularity_newman"] - 0.1
