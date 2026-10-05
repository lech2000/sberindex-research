"""A9 economic graph grid, with canonical undirected edges and frozen annual z."""
from __future__ import annotations

import networkx as nx
import numpy as np
import pandas as pd
from scipy.spatial.distance import cdist
from sklearn.metrics import adjusted_rand_score

from atlas_common import (CONFIGS, SEED, annual_features, check_inputs, config_name,
                          load_features, provenance, run_dir, write_json)


def build_network(x, k, mode="union", weight="gaussian", ids=None):
    x = np.asarray(x, float)
    n = len(x)
    if x.ndim != 2 or not np.isfinite(x).all() or not 0 < k < n:
        raise ValueError("Invalid kNN data/k")
    if mode not in {"union", "mutual"} or weight not in {"gaussian", "binary"}:
        raise ValueError("Unknown graph configuration")
    ids = np.arange(n) if ids is None else np.asarray(ids)
    if len(ids) != n or len(np.unique(ids)) != n:
        raise ValueError("Nonunique node IDs")
    distance = cdist(x, x)
    np.fill_diagonal(distance, np.inf)
    directed = np.zeros((n, n), bool)
    neighbor_distances = []
    for i in range(n):
        neighbors = np.lexsort((ids, distance[i]))[:k]
        directed[i, neighbors] = True
        neighbor_distances.extend(distance[i, neighbors])
    sigma = float(np.median(neighbor_distances))
    selected = directed | directed.T if mode == "union" else directed & directed.T
    u, v = np.where(np.triu(selected, 1))
    if weight == "gaussian":
        if sigma <= 0:
            raise ValueError("Gaussian graph undefined for sigma=0")
        weights = np.exp(-distance[u, v] ** 2 / (2 * sigma ** 2))
        if (weights == 0).any():
            raise ValueError("Gaussian weight underflow; no silent edge removal")
    else:
        weights = np.ones(len(u))
    a = np.zeros((n, n), float)
    a[u, v] = a[v, u] = weights
    src, dst = np.minimum(ids[u], ids[v]), np.maximum(ids[u], ids[v])
    edges = pd.DataFrame({"src": src, "dst": dst, "weight": weights}).sort_values(["src", "dst"]).reset_index(drop=True)
    return a, edges, sigma


def louvain_labels(a, seed=SEED):
    g = nx.from_numpy_array(a)
    communities = nx.community.louvain_communities(g, weight="weight", resolution=1, seed=seed)
    labels = np.empty(len(a), int)
    for label, nodes in enumerate(sorted(communities, key=lambda group: min(group))):
        labels[list(nodes)] = label
    return labels


def read_network(window="A5", config="k7_union_gaussian", ids=None):
    ids = load_features()[0] if ids is None else np.asarray(ids)
    edge = pd.read_parquet(run_dir(9) / f"edges_{window}_{config}.parquet")
    index = pd.Index(ids)
    u, v = index.get_indexer(edge.src), index.get_indexer(edge.dst)
    if (u < 0).any() or (v < 0).any():
        raise ValueError("Unknown edge node")
    a = np.zeros((len(ids), len(ids)), float)
    a[u, v] = a[v, u] = edge.weight
    return a


def main():
    out = run_dir(9)
    ids, base = load_features()
    _, annual, transform = annual_features()
    geo = pd.read_parquet(check_inputs()["geo_edges"])
    geo_set = {tuple(sorted((int(u), int(v)))) for u, v in zip(geo.u, geo.v)}
    pd.DataFrame({"territory_id": ids}).to_parquet(out / "nodes.parquet", index=False)
    summaries, edge_sets, partitions, degrees = [], {}, {}, []
    for window, x in {"A5": base, **annual}.items():
        for k, mode, weight in CONFIGS:
            config = config_name(k, mode, weight)
            a, edges, sigma = build_network(x, k, mode, weight, ids)
            edges.to_parquet(out / f"edges_{window}_{config}.parquet", index=False)
            eset = set(zip(edges.src.astype(int), edges.dst.astype(int)))
            edge_sets[window, config] = eset
            degree = (a > 0).sum(1)
            lab = louvain_labels(a)
            partitions[window, config] = lab
            pd.DataFrame({"territory_id": ids, "label": lab}).to_parquet(out / f"louvain_{window}_{config}.parquet", index=False)
            degrees.extend({"window": window, "config": config, "degree": int(d), "count": int(c)}
                           for d, c in zip(*np.unique(degree, return_counts=True)))
            summaries.append({"window": window, "config": config, "n_nodes": len(ids),
                              "edges": len(edges), "components": nx.number_connected_components(nx.from_numpy_array(a)),
                              "isolates": int((degree == 0).sum()), "sigma": sigma,
                              "geo_overlap_fraction": len(eset & geo_set) / len(eset),
                              "degree_min": int(degree.min()), "degree_p25": float(np.quantile(degree, .25)),
                              "degree_median": float(np.median(degree)), "degree_p75": float(np.quantile(degree, .75)),
                              "degree_max": int(degree.max()), "louvain_K": len(np.unique(lab))})
            print("A9", window, config, len(edges), "edges", flush=True)
    temporal = []
    for k, mode, weight in CONFIGS:
        name = config_name(k, mode, weight)
        a, b = edge_sets["annual2023", name], edge_sets["annual2024", name]
        temporal.append({"config": name, "edge_jaccard": len(a & b) / len(a | b)})
    robust = []
    for window in ("A5", "annual2023", "annual2024"):
        for mode in ("union", "mutual"):
            for weight in ("gaussian", "binary"):
                ari = adjusted_rand_score(partitions[window, config_name(5, mode, weight)], partitions[window, config_name(10, mode, weight)])
                robust.append({"window": window, "mode": mode, "weight": weight, "ari_k5_k10": ari,
                               "stable": bool(ari >= .5)})
    pd.DataFrame(summaries).to_csv(out / "networks_summary.csv", index=False)
    pd.DataFrame(degrees).to_csv(out / "degree_distribution.csv", index=False)
    pd.DataFrame(temporal).to_csv(out / "temporal_edges.csv", index=False)
    pd.DataFrame(robust).to_csv(out / "edge_definition_stability.csv", index=False)
    write_json(out / "results.json", {"n_nodes": len(ids), "n_definitions": 12, "n_networks": 36,
        "networks": summaries, "temporal": temporal, "stability": robust, "frozen_transform": transform})
    lines = ["# A9 — экономическая сеть", "", "12 определений × 3 окна = 36 сохранённых сетей, 1896 узлов в каждой.", "",
             "Проверка ARI(k5,k10), граница0.5; отсутствие рёбер не удаляет узлы:", ""]
    lines.extend(f"- {r['window']} {r['mode']} {r['weight']}: ARI={r['ari_k5_k10']:.4f}, " + ("устойчиво" if r['stable'] else "неустойчиво: вывод зависит от определения ребра") for r in robust)
    lines += ["", "Жаккар рёбер между годами: " + ", ".join(f"{r['config']}={r['edge_jaccard']:.3f}" for r in temporal),
              "", "Основная сеть A10: k7 union Gaussian заранее. Сеть — экономическая близость профилей, не поток товаров/людей и не причинная связь."]
    (out / "README.md").write_text("\n".join(lines) + "\n")
    provenance(9)


if __name__ == "__main__":
    main()
