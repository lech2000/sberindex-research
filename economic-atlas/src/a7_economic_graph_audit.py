"""Recover the A5 economic graph and audit frozen partitions on common networks.

Original implementation of block-weight formulae; no third-party source copied.
AVI/AVU use the convention documented in KB75/16316 and Sorooshi/Pattern
e5ff50b metrics/clustering_metrics.py. Newman Q is NOT labelled jury MQ.
This is retrospective internal validation on 2023-2024 features, not a holdout.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import connected_components


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def economic_graph(z, neighbours=5):
    z = np.asarray(z, dtype=float)
    if z.ndim != 2 or len(z) < 2 or not np.isfinite(z).all():
        raise ValueError('finite 2D features with >=2 rows required')
    if not isinstance(neighbours, int) or not 1 <= neighbours < len(z):
        raise ValueError('neighbours must be an integer in [1, n-1]')
    # Preserve A5's direct difference arithmetic and stable row-order tie rule.
    squared = np.sum((z[:, None] - z[None, :]) ** 2, axis=2)
    distance = np.sqrt(squared)
    ranking = distance.copy()
    np.fill_diagonal(ranking, np.inf)
    selected = np.argsort(ranking, axis=1, kind='stable')[:, :neighbours]
    rows = np.arange(len(z))[:, None]
    selected_distances = distance[rows, selected]
    raw_sigma = float(np.median(selected_distances))
    sigma = raw_sigma if raw_sigma > 0 else 1.0
    # A5 used scalar float exponentiation, whose rounding can differ from
    # NumPy's vector square. Keep it to reproduce the archived matrix exactly.
    weights = np.array([float(np.exp(-float(d) ** 2 / (2 * sigma ** 2)))
                        for d in selected_distances.flat]).reshape(selected.shape)
    directed = np.zeros_like(distance)
    directed[rows, selected] = weights
    adjacency = np.maximum(directed, directed.T)
    count, component = connected_components(csr_matrix(adjacency), directed=False)
    return adjacency, {
        'neighbours': neighbours, 'sigma': sigma, 'raw_sigma': raw_sigma,
        'sigma_fallback': raw_sigma <= 0,
        'directed_neighbours': int(selected.size),
        'underflow_zero_directed_weights': int(np.count_nonzero(weights == 0)),
        'nodes': len(z), 'undirected_positive_edges': int(np.count_nonzero(adjacency) // 2),
        'components': sorted(np.bincount(component).tolist(), reverse=True),
        'isolates': int(np.count_nonzero(adjacency.sum(axis=1) == 0)),
        'component_count': int(count),
    }


def network_scores(adjacency, labels):
    a = np.asarray(adjacency, dtype=float)
    labels = np.asarray(labels)
    if a.ndim != 2 or a.shape[0] != a.shape[1] or len(a) == 0:
        raise ValueError('nonempty square adjacency required')
    if labels.ndim != 1 or len(labels) != len(a) or pd.isna(labels).any():
        raise ValueError('one nonmissing label per vertex required')
    if not np.isfinite(a).all() or (a < 0).any():
        raise ValueError('weights must be finite and nonnegative')
    if not np.array_equal(a, a.T) or np.any(np.diag(a) != 0):
        raise ValueError('symmetric adjacency without loops required')
    keys, inverse = np.unique(labels, return_inverse=True)
    k = len(keys)
    blocks = np.zeros((k, k))
    # Account for each undirected edge twice; internal S_kk is twice its weight.
    u, v = np.nonzero(np.triu(a, k=1))
    np.add.at(blocks, (inverse[u], inverse[v]), a[u, v])
    np.add.at(blocks, (inverse[v], inverse[u]), a[u, v])
    internal = np.diag(blocks)
    volume = blocks.sum(axis=1)
    external = blocks.copy()
    np.fill_diagonal(external, 0)
    outward = external.sum(axis=1)
    denominator = outward[:, None] + outward[None, :] - external
    np.fill_diagonal(denominator, 0)
    isolation = np.divide(internal, volume, out=np.zeros(k), where=volume > 0)
    union = np.divide(external, denominator, out=np.zeros_like(blocks), where=denominator > 0)
    avi = float(isolation.mean())
    avu = float(union.sum() / k)
    mass = float(volume.sum())
    q = float(np.sum(internal / mass - (volume / mass) ** 2)) if mass else None
    return {
        'K': k, 'AVI': avi, 'AVU': avu,
        'ANUI': avi / (1 + avi * avu), 'modularity_newman': q,
        'MQ': None, 'MQ_status': 'SPEC_UNRESOLVED',
        'clusters_without_edges': int(np.count_nonzero(volume == 0)),
        'AVU_zero_denominator_ordered_pairs': int(np.count_nonzero(denominator == 0) - k),
        'no_edges': mass == 0, 'block_weight_matrix': blocks.tolist(),
        'cluster_sizes': np.bincount(inverse).tolist(),
    }


def run(a5, out):
    a5, out = Path(a5), Path(out)
    if out.exists():
        raise ValueError('output must be a new run directory')
    f = pd.read_parquet(a5 / 'features.parquet')
    labels = pd.read_parquet(a5 / 'assignments.parquet')
    if f.territory_id.duplicated().any() or labels.territory_id.duplicated().any():
        raise ValueError('duplicate territory keys')
    if set(f.territory_id) != set(labels.territory_id):
        raise ValueError('features and assignments must have exactly the same mask')
    data = f.merge(labels, on='territory_id', validate='one_to_one').sort_values('territory_id')
    columns = [c for c in f if c.startswith('z_')]
    z = data[columns].to_numpy(dtype=float)
    adjacency, audit = economic_graph(z, 5)
    original = json.loads((a5 / 'metrics.json').read_text())
    expected = original['feature_knn_audit']['sigma_feat']
    if not np.isclose(audit['sigma'], expected, rtol=1e-13, atol=0):
        raise ValueError('recovered sigma differs from original A5 receipt')
    tids = data.territory_id.to_numpy()
    pos = {int(t): i for i, t in enumerate(tids)}
    geo = np.zeros_like(adjacency)
    edges = pd.read_parquet(a5 / 'edges.parquet')
    for row in edges.itertuples(index=False):
        i, j = pos[int(row.u)], pos[int(row.v)]
        if i == j or geo[i, j] != 0:
            raise ValueError('geographic duplicate or self edge')
        geo[i, j] = geo[j, i] = row.weight
    details, rows = {}, []
    for name, a in [('economic_knn5', adjacency), ('geographic_A5_control', geo)]:
        details[name] = {}
        for col in labels:
            if col == 'territory_id':
                continue
            method = col.removeprefix('label_')
            score = network_scores(a, data[col].to_numpy())
            details[name][method] = score
            rows.append({'network': name, 'method': method,
                         **{key: val for key, val in score.items() if not isinstance(val, list)}})
            if name == 'geographic_A5_control':
                if not np.isclose(score['modularity_newman'], original['methods'][method]['modularity_geo'], atol=1e-12):
                    raise ValueError('Newman Q differs from frozen A5 geographic result')
    out.mkdir(parents=True)
    pd.DataFrame(rows).to_csv(out / 'validity.csv', index=False)
    u, v = np.nonzero(np.triu(adjacency, k=1))
    pd.DataFrame({'u': tids[u], 'v': tids[v], 'weight': adjacency[u, v]}).to_parquet(out / 'economic_edges.parquet', index=False)
    result = {
        'created_at': datetime.now(timezone.utc).isoformat(),
        'status': 'COMPUTED_REFERENCE_CONVENTION',
        'scientific_PASS': False, 'MQ_status': 'SPEC_UNRESOLVED',
        'scope': 'static retrospective mean 2023-2024 profiles; no new clustering or threshold selection',
        'edge_meaning': 'similarity of five standardized consumption shares, not observed economic flows',
        'graph': audit, 'feature_columns': columns,
        'input_sha256': {n: sha(a5 / n) for n in ['features.parquet', 'assignments.parquet', 'edges.parquet', 'metrics.json', 'graph_manifest.json']},
        'code_sha256': sha(__file__),
        'output_sha256': {n: sha(out / n) for n in ['validity.csv', 'economic_edges.parquet']},
        'versions': {'python': platform.python_version(), **{n: version(n) for n in ['numpy', 'pandas', 'scipy', 'pyarrow']}},
        'reference': 'https://github.com/Sorooshi/Pattern/blob/e5ff50b/metrics/clustering_metrics.py',
        'paper': 'https://doi.org/10.1016/j.eswa.2016.11.011',
        'paper_verification': 'abstract and bibliographic identity verified; full formula text not accessed',
        'conventions': ['zero-volume cluster AVI contribution 0', 'AVU 0/0 contribution 0',
                        'Newman Q undefined for edgeless graph; not labelled MQ',
                        'AVU is constant at K=2/3 only if some inter-cluster edge exists',
                        'all five frozen partitions evaluated on each common network',
                        'no inference of economic independence or persistent identity'],
        'metrics': details,
    }
    (out / 'manifest.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--a5', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    args = p.parse_args()
    result = run(args.a5, args.out)
    print(json.dumps({'status': result['status'], 'graph': result['graph']}, ensure_ascii=False, indent=2))
