"""Independent formula implementation, Halkidi/Vazirgiannis 2001 eq.1--5.

No external repository code used. Counts use Ci union Cj; own-cluster
denominators are a separately labelled sensitivity convention.
"""
from __future__ import annotations

from itertools import combinations

import numpy as np
import pandas as pd


def s_dbw(x, labels, centre_domain="pair_union", expected_k=None):
    x, labels = np.asarray(x, float), np.asarray(labels)
    if x.ndim != 2 or labels.shape != (len(x),) or x.shape[1] == 0:
        raise ValueError("Invalid feature/label shape")
    if not np.isfinite(x).all() or pd.isna(labels).any():
        raise ValueError("Nonfinite features or missing labels")
    if centre_domain not in {"pair_union", "own_cluster"}:
        raise ValueError("Unknown centre domain")
    unique, inverse = np.unique(labels, return_inverse=True)
    k = len(unique)
    if expected_k is not None and k != expected_k:
        raise ValueError("Empty declared cluster")
    if k < 2 or k >= len(x):
        return {"status": "NA_K_DOMAIN", "S_Dbw": None, "K": k}
    groups = [x[inverse == i] for i in range(k)]
    centres = [g.mean(0) for g in groups]
    varnorms = np.array([np.linalg.norm(g.var(0, ddof=0)) for g in groups])
    global_norm = np.linalg.norm(x.var(0, ddof=0))
    if global_norm == 0:
        return {"status": "NA_ZERO_GLOBAL_VARIANCE", "S_Dbw": None, "K": k}
    radius = float(np.sqrt(varnorms.sum()) / k)
    scat = float(varnorms.mean() / global_norm)
    ratios, details = [], []
    for i, j in combinations(range(k), 2):
        pool = np.concatenate((groups[i], groups[j]))
        count = lambda points, c: int(np.count_nonzero(np.linalg.norm(points - c, axis=1) <= radius))
        di = count(pool if centre_domain == "pair_union" else groups[i], centres[i])
        dj = count(pool if centre_domain == "pair_union" else groups[j], centres[j])
        middle = count(pool, (centres[i] + centres[j]) / 2)
        den = max(di, dj)
        ratios.append(middle / den if den else None)
        details.append({"i": i, "j": j, "midpoint_count": middle,
                        "centre_i_count": di, "centre_j_count": dj})
    undefined = sum(r is None for r in ratios)
    density = None if undefined else float(np.mean(ratios))
    return {"status": "NA_ZERO_DENSITY_DENOMINATOR" if undefined else "COMPUTED",
            "S_Dbw": None if density is None else scat + density, "Scat": scat,
            "Dens_bw": density, "radius": radius, "K": k, "centre_domain": centre_domain,
            "undefined_pairs": undefined, "singleton_clusters": sum(len(g) == 1 for g in groups),
            "zero_variance_clusters": int((varnorms == 0).sum()), "pairs": details}

