"""Независимая проверка расчёта AVI/AVU на восстановленной экономической сети (05.10.2026).

Сеть: объединение k = 5 ближайших соседей в пространстве z-признаков A5 (`k_feat = 5` в metrics.json A5), вес ребра — гауссов
exp(−d²/(2σ²)), σ = медиана расстояний до k соседей (вариант без весов — для сравнения). Разбиения — пять сохранённых меток A5.
К ним добавлены: контроль числа групп (k-means с K = 33 на тех же признаках), «потолок» (Louvain на самой экономической сети) и нулевая модель
(случайная перестановка меток с сохранением размеров групп).

Запуск: python audit.py [--a5 ../A5] [--outdir .]
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("network_icvi", HERE.parents[1] / "src" / "network_icvi.py")
icvi = importlib.util.module_from_spec(_spec)
sys.modules["network_icvi"] = icvi
_spec.loader.exec_module(icvi)

K_NEIGHBOURS = 5
SEED = 20261005


def knn_union_network(Z: np.ndarray, k: int = K_NEIGHBOURS, weighted: bool = True):
    """Симметричная матрица смежности: ребро, если один из узлов входит в k ближайших другого; вес гауссов (или 1)."""
    from sklearn.neighbors import NearestNeighbors

    n = len(Z)
    d, ix = NearestNeighbors(n_neighbors=k + 1).fit(Z).kneighbors(Z)
    sigma = float(np.median(d[:, 1:]))
    A = np.zeros((n, n))
    for i in range(n):
        for dist, j in zip(d[i, 1:], ix[i, 1:]):
            w = float(np.exp(-(dist ** 2) / (2 * sigma ** 2))) if weighted else 1.0
            A[i, j] = max(A[i, j], w)
            A[j, i] = max(A[j, i], w)
    return A, sigma


def n_components(A: np.ndarray) -> int:
    from scipy.sparse import csr_matrix
    from scipy.sparse.csgraph import connected_components

    return int(connected_components(csr_matrix(A > 0), directed=False)[0])


def analyse(A: np.ndarray, parts: dict[str, np.ndarray], B: int = 300) -> list[dict]:
    rows = []
    n = len(A)
    for name, lab in parts.items():
        K = int(len(np.unique(lab)))
        big = float(np.bincount(np.unique(lab, return_inverse=True)[1]).max() / n)
        r = icvi.compute_network_indices(A, lab)
        nl = icvi.random_partition_null(A, lab, B=B, seed=SEED)
        rows.append({"partition": name, "K": K, "largest_group_share": round(big, 3),
                     **{k: round(r[k], 4) for k in ("AVI", "AVU", "ANUI", "modularity_newman")},
                     "avi_null_mean": round(nl["AVI"]["null_mean"], 4), "avi_z": round(nl["AVI"]["z"], 1),
                     "uniform_avu_value": round((K - 1) / (2 * K - 3), 4) if K >= 2 else None})
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--a5", default=str(HERE.parent / "A5"))
    ap.add_argument("--outdir", default=str(HERE))
    a = ap.parse_args(argv)
    a5 = Path(a.a5)
    f = pd.read_parquet(a5 / "features.parquet").sort_values("territory_id").reset_index(drop=True)
    asg = pd.read_parquet(a5 / "assignments.parquet").set_index("territory_id").loc[f["territory_id"]]
    Z = f[[c for c in f.columns if c.startswith("z_")]].to_numpy(float)
    parts = {c.replace("label_", ""): asg[c].to_numpy() for c in asg.columns}
    from sklearn.cluster import KMeans

    parts["kmeans_K33_контроль_числа_групп"] = KMeans(33, n_init=10, random_state=1).fit_predict(Z)
    out = {"n_nodes": int(len(Z)), "features": [c for c in f.columns if c.startswith("z_")], "networks": {}}
    for weighted in (True, False):
        A, sigma = knn_union_network(Z, weighted=weighted)
        key = "gaussian_weights" if weighted else "unweighted"
        p = dict(parts)
        try:
            import networkx as nx

            G = nx.from_numpy_array(A)
            comms = nx.community.louvain_communities(G, weight="weight", seed=1)
            lab = np.zeros(len(Z), int)
            for c, nodes in enumerate(comms):
                lab[list(nodes)] = c
            p["louvain_на_экономической_сети_потолок"] = lab
        except ImportError:
            pass
        out["networks"][key] = {"edges": int((A > 0).sum() // 2), "components": n_components(A), "sigma": round(sigma, 4), "rows": analyse(A, p)}
    prov = {"run_id": "A7-network-icvi-audit-20261005", "status": "AUDIT_NOT_SCIENTIFIC_RESULT",
            "code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "network_icvi_sha256": hashlib.sha256((HERE.parents[1] / "src" / "network_icvi.py").read_bytes()).hexdigest(),
            "a5_features_sha256": hashlib.sha256((a5 / "features.parquet").read_bytes()).hexdigest(),
            "a5_assignments_sha256": hashlib.sha256((a5 / "assignments.parquet").read_bytes()).hexdigest(), "seed": SEED, "k_neighbours": K_NEIGHBOURS}
    Path(a.outdir, "results.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    Path(a.outdir, "provenance.json").write_text(json.dumps(prov, ensure_ascii=False, indent=1), encoding="utf-8")
    for key, net in out["networks"].items():
        print(f"\n== {key}: рёбер {net['edges']}, компонент {net['components']}")
        for r in net["rows"]:
            print(f"{r['partition']:<42}K={r['K']:>2} макс.доля={r['largest_group_share']:.2f} AVI={r['AVI']:.3f} (нуль {r['avi_null_mean']:.3f}, z={r['avi_z']:.0f}) AVU={r['AVU']:.3f} ANUI={r['ANUI']:.3f} Q={r['modularity_newman']:.3f}")


if __name__ == "__main__":
    main()
