"""A7: S_Dbw on frozen A5 assignments; no clustering or rescaling.

Halkidi & Vazirgiannis (ICDM 2001), DOI 10.1109/ICDM.2001.989517,
section 3, equations 1--5; visually checked against author tutorial
PKDD 2002, PDF pages 69--71. Protocol selects pair-union centre counts
(literal common sample domain in eq. 2). Own-cluster centre counts are
reported separately as a sensitivity convention, never selected by score.
Variance vectors use population variance, Euclidean norm; radius is
sqrt(sum(norm(cluster_variance)))/k, NOT sqrt(mean(norm(...))).

For undefined denominators return null + reason/pair counts, never epsilon
or zero. Singleton clusters are retained and flagged. k=1, k=n, missing
labels, non-finite features or zero global variance are rejected.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
from datetime import datetime, timezone
from importlib.metadata import version
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import (
    calinski_harabasz_score, davies_bouldin_score, silhouette_score,
)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def s_dbw(x, labels, centre_domain="pair_union"):
    x = np.asarray(x, dtype=np.float64)
    labels = np.asarray(labels)
    if x.ndim != 2 or x.shape[1] == 0 or len(x) < 3:
        raise ValueError("expected >=3 rows and >=1 feature")
    if labels.ndim != 1 or len(labels) != len(x):
        raise ValueError("label length/shape mismatch")
    if not np.isfinite(x).all() or pd.isna(labels).any():
        raise ValueError("non-finite features or missing labels; no imputation")
    if centre_domain not in {"pair_union", "own_cluster"}:
        raise ValueError("unknown centre-count convention")
    unique, inverse = np.unique(labels, return_inverse=True)
    k = len(unique)
    if not 2 <= k < len(x):
        raise ValueError("require 2 <= k < n; all-singleton partition excluded")
    groups = [x[inverse == i] for i in range(k)]
    centres = np.array([g.mean(axis=0) for g in groups])
    variances = np.array([g.var(axis=0, ddof=0) for g in groups])
    norms = np.linalg.norm(variances, axis=1)
    global_norm = float(np.linalg.norm(x.var(axis=0, ddof=0)))
    if global_norm == 0:
        raise ValueError("zero global variance")
    radius = float(np.sqrt(norms.sum()) / k)
    scat = float(norms.mean() / global_norm)

    def count(points, centre):
        return int(np.count_nonzero(np.linalg.norm(points - centre, axis=1) <= radius))

    own_counts = [count(g, c) for g, c in zip(groups, centres)]
    pairs = []
    for i, j in combinations(range(k), 2):
        union = np.concatenate([groups[i], groups[j]], axis=0)
        midpoint_count = count(union, (centres[i] + centres[j]) / 2)
        if centre_domain == "pair_union":
            di, dj = count(union, centres[i]), count(union, centres[j])
        else:
            di, dj = own_counts[i], own_counts[j]
        denominator = max(di, dj)
        pairs.append({"i": i, "j": j, "density_midpoint": midpoint_count,
                      "density_i": di, "density_j": dj,
                      "ratio": midpoint_count / denominator if denominator else None})
    undefined = sum(p["ratio"] is None for p in pairs)
    dens = None if undefined else float(np.mean([p["ratio"] for p in pairs]))
    return {
        "status": "NA_ZERO_DENSITY_DENOMINATOR" if undefined else "COMPUTED",
        "s_dbw": None if dens is None else scat + dens,
        "scat": scat, "dens_bw": dens, "radius": radius,
        "centre_domain": centre_domain, "n": len(x), "k": k,
        "sizes": [len(g) for g in groups],
        "singleton_clusters": sum(len(g) == 1 for g in groups),
        "zero_variance_clusters": int(np.count_nonzero(norms == 0)),
        "zero_own_centre_density_clusters": own_counts.count(0),
        "undefined_pairs": undefined, "n_unordered_pairs": len(pairs),
        "cluster_variance_norms": norms.tolist(),
        "global_variance_norm": global_norm, "pairs": pairs,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--a5", type=Path, required=True)
    p.add_argument("--protocol", type=Path, required=True)
    p.add_argument("--outdir", type=Path, required=True)
    args = p.parse_args()
    protocol = json.loads(args.protocol.read_text())
    expected = protocol["input_sha256"]
    for name, digest in expected.items():
        if sha(args.a5 / name) != digest:
            raise ValueError("frozen input hash mismatch: " + name)
    if protocol["implementation_sha256"] != sha(__file__):
        raise ValueError("implementation differs from frozen protocol")
    f = pd.read_parquet(args.a5 / "features.parquet")
    a = pd.read_parquet(args.a5 / "assignments.parquet")
    if not f.territory_id.is_unique or not a.territory_id.is_unique:
        raise ValueError("duplicate territory keys")
    if set(f.territory_id) != set(a.territory_id) or len(f) != protocol["n_municipalities"]:
        raise ValueError("mask mismatch; no intersection silently taken")
    merged = f.merge(a, on="territory_id", validate="one_to_one").sort_values("territory_id")
    x = merged[protocol["feature_columns"]].to_numpy(dtype=float)
    old = json.loads((args.a5 / "metrics.json").read_text())
    results, rows = {}, []
    for method in protocol["methods"]:
        labels = merged["label_" + method].to_numpy()
        primary = s_dbw(x, labels, "pair_union")
        alternate = s_dbw(x, labels, "own_cluster")
        sw = float(silhouette_score(x, labels, metric="euclidean"))
        ch = float(calinski_harabasz_score(x, labels))
        db = float(davies_bouldin_score(x, labels))
        recomputed = {"silhouette": sw, "calinski_harabasz": ch, "davies_bouldin": db}
        differences = {}
        for metric, value in recomputed.items():
            differences[metric] = value - old["methods"][method][metric]
            tolerance = protocol["A5_metric_absolute_tolerance"][metric]
            if not np.isclose(value, old["methods"][method][metric], rtol=0, atol=tolerance):
                raise ValueError("A5 metric mismatch: " + method + "/" + metric)
        results[method] = {"primary": primary, "own_cluster_sensitivity": alternate,
                           "recomputed_A5_metrics": recomputed,
                           "A5_metric_differences": differences}
        rows.append({"method": method, "n": len(x), "k": primary["k"],
                     "smallest_cluster": min(primary["sizes"]),
                     "largest_cluster_fraction": max(primary["sizes"]) / len(x),
                     "singleton_clusters": primary["singleton_clusters"],
                     "SW": sw, "CH": ch, "DB_diagnostic": db,
                     "S_Dbw": primary["s_dbw"], "Scat": primary["scat"],
                     "Dens_bw": primary["dens_bw"], "radius": primary["radius"],
                     "S_Dbw_status": primary["status"],
                     "S_Dbw_own_cluster_sensitivity": alternate["s_dbw"],
                     "own_cluster_status": alternate["status"],
                     "AVI": None, "AVU": None, "MQ": None,
                     "unresolved_index_status": "SPEC_UNRESOLVED"})
    if args.outdir.exists():
        raise ValueError("output exists; choose a new version, do not overwrite")
    args.outdir.mkdir(parents=True)
    output = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "COMPUTED_DESCRIPTIVE", "full_A7_gate_pass": False,
        "economic_validity_pass": False, "protocol_sha256": sha(args.protocol),
        "implementation_sha256": sha(__file__), "input_sha256": expected,
        "feature_window": "2023-01..2024-12 time-averaged shares; retrospective",
        "methods": results,
        "jury_indices_computed": ["SW", "CH", "S_Dbw"],
        "jury_indices_SPEC_UNRESOLVED": ["AVI", "AVU", "MQ"],
        "limits": ["no reclustering, no rescaling or model selection",
                   "in-sample descriptive indices, not economic ground truth",
                   "cross-method K differs (Louvain 33, others 5)",
                   "geographic communities need not be convex in spending feature space"],
        "versions": {n: version(n) for n in ["numpy", "pandas", "scipy", "scikit-learn", "pyarrow"]},
        "python": platform.python_version(),
    }
    (args.outdir / "metrics.json").write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    pd.DataFrame(rows).to_csv(args.outdir / "validity.csv", index=False, na_rep="NA")
    (args.outdir / "protocol.json").write_text(args.protocol.read_text())
    print(pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    main()
