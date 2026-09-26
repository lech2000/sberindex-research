"""A5: geographic graph + joint feature/network typology (economic-atlas).

Reads the frozen panel (data/panel_v1.parquet, 1896 tid x 24 months x 6 cats)
and the distance table (5_connection.parquet: territory_id_x/y, distance),
then runs three experiments on ONE explicit territory mask:

  E01  k-means on z-scored time-averaged shares (k=5, n_init=10, seed)
  E02  Louvain on the observed geographic graph (resolution=1.0, seed;
       number of communities is NOT forced)
  E03  spectral clustering on A = 0.5*geo_affinity + 0.5*feature_kNN_affinity
       (feature kNN k=5, Gaussian kernel), plus alpha=0/1 ablations

Features follow features/spec.yaml FROZEN v1 strictly:
  share(cat,tid,m) = value(cat,tid,m) / value('All categories',tid,m)
for the 5 non-total categories. The 'All categories' row is a separate
total, NOT the sum of the five (median sum5/total ~ 0.72) -- never divide
by sum6. No fillna(0): any non-finite cell or non-positive total excludes
the whole tid (audited). Shares are averaged over time, then z-scored
across tids (population std); means/stds are saved in the feature audit.

Geographic graph rules:
  - only positive finite distances between selected tids; x==y rows dropped
  - duplicate unordered pairs collapse to MIN distance (repeats are repeated
    measurements, NOT flows)
  - k=8 nearest neighbours per node, weight = exp(-d / median_knn_distance)
    where the median is over the selected positive directed kNN distances
  - symmetrisation by MAX weight, no self-loops, no artificial bridges:
    isolates (no positive finite edge to a selected tid) are excluded from
    the mask and audited, never bridged

All methods run on the SAME mask (feature-valid tids INTERSECT tids with
geo coverage -- the intersection is explicit in the audit). Quality metrics
(silhouette, Calinski-Harabasz, Davies-Bouldin) are computed in ONE feature
space (z-scored shares); modularity is computed on the geographic graph;
pairwise ARI/NMI plus cluster sizes are reported for every labelling.

Mobility: the 594-row mobility index (297 MO x 2 dates) is a per-territory
km index, NOT an origin-destination matrix, and has no verified crosswalk
to panel tids -- mobility_status=excluded_no_OD_no_verified_crosswalk.
No mobility edges are invented.

Usage (run from economic-atlas/ or anywhere; defaults resolve from here):
  python src/a5_graph.py --panel data/panel_v1.parquet \\
      --distance ../data/raw/sberindex-data-sense-2025/5_connection.parquet \\
      --outdir runs/A5 --seed 20260921 --k 5
  python src/a5_graph.py --self-check   # toy-data checks, no inputs needed

Outputs in --outdir: vertices.parquet, features.parquet, edges.parquet,
assignments.parquet, metrics.json, graph_manifest.json.

Deps: numpy, pandas, scipy, networkx, scikit-learn.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ATLAS_DIR = Path(__file__).resolve().parents[1]
DEFAULT_PANEL = ATLAS_DIR / "data" / "panel_v1.parquet"
DEFAULT_DISTANCE = (
    ATLAS_DIR.parent / "data" / "raw" / "sberindex-data-sense-2025"
    / "5_connection.parquet"
)
DEFAULT_OUTDIR = ATLAS_DIR / "runs" / "A5"

TOTAL_CAT = "Все категории"
SHARE_CATS = [
    "Здоровье",
    "Маркетплейсы",
    "Общественное питание",
    "Продовольствие",
    "Транспорт",
]
ALL_CATS = [TOTAL_CAT] + SHARE_CATS

TID_CANDS = ["territory_id", "tid", "mo", "municipality_id"]
DATE_CANDS = ["date", "month", "ym", "period"]
CAT_CANDS = ["category", "cat", "category_15"]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def pkg_version(name: str) -> str | None:
    try:
        from importlib.metadata import version

        return version(name)
    except Exception:
        return None


def _pick(columns, candidates: list[str], what: str) -> str:
    for c in candidates:
        if c in columns:
            return c
    raise ValueError(f"panel: no {what} column among {candidates}; got {list(columns)}")


def build_features(panel: pd.DataFrame):
    """Time-averaged share features per A3 spec.yaml. Returns (feat, audit).

    feat: DataFrame indexed by tid with 5 share_mean_* and 5 z_* columns
    (mask tids only). audit: dict with month set, zscore stats, exclusions.
    """
    tid_c = _pick(panel.columns, TID_CANDS, "territory id")
    date_c = _pick(panel.columns, DATE_CANDS, "date")
    cat_c = _pick(panel.columns, CAT_CANDS, "category")
    if "value" not in panel.columns:
        raise ValueError("panel: missing 'value' column")

    df = panel[[tid_c, date_c, cat_c, "value"]].copy()
    df["tid"] = df[tid_c].astype(int)
    df["month"] = pd.to_datetime(df[date_c]).dt.strftime("%Y-%m")
    df["value"] = df["value"].astype(float)
    months = sorted(df["month"].unique().tolist())

    dup_mask = df.duplicated(subset=["tid", "month", cat_c], keep=False)
    if bool(dup_mask.any()):
        bad = df.loc[dup_mask, ["tid", "month", cat_c]].head().to_dict(orient="records")
        raise ValueError(f"panel: duplicate (tid, month, category) rows rejected: {bad}")

    pivot = df.pivot_table(
        index=["tid", "month"], columns=df[cat_c], values="value", aggfunc="mean"
    )
    missing_cats = [c for c in ALL_CATS if c not in pivot.columns]
    if missing_cats:
        raise ValueError(f"panel: missing categories {missing_cats}")

    exclusions: dict[str, str] = {}
    share_rows = []
    for tid, g in pivot.groupby(level=0):
        tid = int(tid)
        if len(g) != len(months) or g.isna().any(axis=None):
            exclusions[str(tid)] = "incomplete_grid_or_nan_no_fillna"
            continue
        block = g[ALL_CATS]
        total = block[TOTAL_CAT].to_numpy(dtype=float)
        if not np.all(np.isfinite(total)) or np.any(total <= 0):
            exclusions[str(tid)] = "nonpositive_or_nonfinite_total"
            continue
        vals = block[SHARE_CATS].to_numpy(dtype=float)
        if not np.all(np.isfinite(vals)):
            exclusions[str(tid)] = "nonfinite_category_value_no_fillna"
            continue
        shares = vals / total[:, None]
        if not np.all(np.isfinite(shares)):
            exclusions[str(tid)] = "nonfinite_share"
            continue
        share_rows.append((tid, shares.mean(axis=0)))

    if not share_rows:
        raise ValueError("panel: no tid passed feature validation")

    tids = np.array([t for t, _ in share_rows], dtype=int)
    order = np.argsort(tids)
    tids = tids[order]
    means = np.vstack([s for _, s in share_rows])[order]

    mu = means.mean(axis=0)
    sigma = means.std(axis=0, ddof=0)
    zero_std = sigma == 0
    sigma_safe = np.where(zero_std, 1.0, sigma)
    z = (means - mu) / sigma_safe
    z[:, zero_std] = 0.0

    feat = pd.DataFrame(
        {
            "territory_id": tids,
            **{f"share_mean_{c}": means[:, i] for i, c in enumerate(SHARE_CATS)},
            **{f"z_{c}": z[:, i] for i, c in enumerate(SHARE_CATS)},
        }
    )
    audit = {
        "formula": "share(cat,tid,m)=value(cat,tid,m)/value('Все категории',tid,m); "
        "feature=mean_m(share); z=(feature-mean_tids)/std_tids(ddof=0). "
        "Denominator is the 'Все категории' row, never sum6. No fillna(0).",
        "n_months": len(months),
        "months": months,
        "n_feature_valid": int(len(tids)),
        "n_excluded": len(exclusions),
        "excluded_tids": exclusions,
        "zscore_mean": {c: float(mu[i]) for i, c in enumerate(SHARE_CATS)},
        "zscore_std": {c: float(sigma[i]) for i, c in enumerate(SHARE_CATS)},
        "zero_variance_features": [c for i, c in enumerate(SHARE_CATS) if zero_std[i]],
    }
    return feat, audit


def build_geo_graph(dist: pd.DataFrame, tids: list[int], k_geo: int):
    """Observed geographic graph. Returns (edges, audit, directed_pairs).

    edges: undirected DataFrame [u, v] (u<v) with distance/weight.
    directed_pairs: DataFrame [u, v, distance] of selected kNN darts.
    """
    for c in ("territory_id_x", "territory_id_y", "distance"):
        if c not in dist.columns:
            raise ValueError(f"distance table: missing column {c!r}")
    sel = set(int(t) for t in tids)
    d = dist[["territory_id_x", "territory_id_y", "distance"]].copy()
    d["x"] = d["territory_id_x"].astype(int)
    d["y"] = d["territory_id_y"].astype(int)
    d["dst"] = d["distance"].astype(float)
    raw_rows = len(d)
    d = d[np.isfinite(d["dst"]) & (d["dst"] > 0)]
    d = d[d["x"].isin(sel) & d["y"].isin(sel)]
    d = d[d["x"] != d["y"]]
    d["u"] = np.minimum(d["x"].to_numpy(), d["y"].to_numpy()).astype(int)
    d["v"] = np.maximum(d["x"].to_numpy(), d["y"].to_numpy()).astype(int)
    n_dup = int(d.duplicated(["u", "v"]).sum())
    pair_min = d.groupby(["u", "v"], as_index=False)["dst"].min()

    adj: dict[int, list[tuple[float, int]]] = {t: [] for t in sel}
    for u, v, dst in zip(
        pair_min["u"].tolist(), pair_min["v"].tolist(), pair_min["dst"].tolist()
    ):
        adj[u].append((dst, v))
        adj[v].append((dst, u))
    for t in adj:
        adj[t].sort(key=lambda p: (p[0], p[1]))

    darts = []
    for t in sorted(sel):
        for dst, nb in adj[t][:k_geo]:
            darts.append((t, nb, dst))
    if not darts:
        raise ValueError("distance table: no positive finite edge between selected tids")
    dart_dist = np.array([x[2] for x in darts], dtype=float)
    med = float(np.median(dart_dist))

    w_dart = np.exp(-dart_dist / med)
    wmap: dict[tuple[int, int], float] = {}
    dmap: dict[tuple[int, int], float] = {}
    for (u, v, dst), w in zip(darts, w_dart.tolist()):
        key = (min(u, v), max(u, v))
        wmap[key] = max(w, wmap.get(key, 0.0))
        if key not in dmap or dst < dmap[key]:
            dmap[key] = float(dst)
    edges = pd.DataFrame(
        {
            "u": [k[0] for k in wmap],
            "v": [k[1] for k in wmap],
            "distance": [dmap[k] for k in wmap],
            "weight": [wmap[k] for k in wmap],
        }
    ).sort_values(["u", "v"]).reset_index(drop=True)
    covered = set(edges["u"].tolist()) | set(edges["v"].tolist())
    isolates = sorted(sel - covered)
    audit = {
        "raw_rows": int(raw_rows),
        "positive_finite_selected_rows": int(len(d)),
        "duplicate_unordered_pairs_min_collapsed": n_dup,
        "k_geo": k_geo,
        "n_directed_kNN_darts": len(darts),
        "median_positive_knn_distance": med,
        "weight_formula": "w=exp(-distance/median_positive_knn_distance), "
        "symmetrisation=max, no self-loops",
        "n_undirected_edges": int(len(edges)),
        "n_covered_tids": len(covered),
        "isolated_tids_no_positive_edge": isolates,
    }
    dart_df = pd.DataFrame(darts, columns=["u", "v", "distance"])
    return edges, audit, dart_df


def graph_from_edges(edges: pd.DataFrame):
    import networkx as nx

    G = nx.Graph()
    for u, v, w in zip(
        edges["u"].tolist(), edges["v"].tolist(), edges["weight"].tolist()
    ):
        G.add_edge(int(u), int(v), weight=float(w))
    return G


def connected_components(G) -> list[int]:
    import networkx as nx

    return sorted((len(c) for c in nx.connected_components(G)), reverse=True)


def _label_communities(tids: list[int], communities) -> np.ndarray:
    lab = np.empty(len(tids), dtype=int)
    idx = {t: i for i, t in enumerate(tids)}
    for ci, comm in enumerate(communities):
        for t in comm:
            lab[idx[int(t)]] = ci
    return lab


def run_pipeline(
    panel: pd.DataFrame,
    dist: pd.DataFrame,
    outdir: Path,
    seed: int,
    k: int,
    k_geo: int = 8,
    k_feat: int = 5,
    resolution: float = 1.0,
    alphas: tuple[float, ...] = (0.0, 0.5, 1.0),
) -> dict:
    from sklearn.cluster import KMeans, SpectralClustering
    from sklearn.metrics import (
        adjusted_rand_score,
        calinski_harabasz_score,
        davies_bouldin_score,
        normalized_mutual_info_score,
        silhouette_score,
    )
    from networkx.algorithms.community import (
        louvain_communities,
        modularity as nx_modularity,
    )

    feat_all, feat_audit = build_features(panel)
    f_tids = feat_all["territory_id"].tolist()
    edges_all, geo_audit, _ = build_geo_graph(dist, f_tids, k_geo)
    mask = sorted(set(feat_all["territory_id"].tolist()) & (
        set(edges_all["u"].tolist()) | set(edges_all["v"].tolist())
    ))
    if len(mask) < k + 1:
        raise ValueError(f"mask too small for k={k}: n={len(mask)}")
    geo_excluded = sorted(set(f_tids) - set(mask))

    edges = edges_all[
        edges_all["u"].isin(mask) & edges_all["v"].isin(mask)
    ].reset_index(drop=True)
    feat = feat_all[feat_all["territory_id"].isin(mask)].reset_index(drop=True)
    zcols = [f"z_{c}" for c in SHARE_CATS]
    Z = feat[zcols].to_numpy(dtype=float)
    G = graph_from_edges(edges)
    for t in mask:
        if t not in G:
            G.add_node(int(t))
    comp_sizes = connected_components(G)

    labels: dict[str, np.ndarray] = {}
    labels["E01_kmeans"] = KMeans(
        n_clusters=k, n_init=10, random_state=seed
    ).fit_predict(Z)
    louv = louvain_communities(
        G, weight="weight", resolution=resolution, seed=seed
    )
    labels["E02_louvain"] = _label_communities(mask, louv)

    D2 = ((Z[:, None, :] - Z[None, :, :]) ** 2).sum(axis=2)
    D = np.sqrt(D2)
    n = len(mask)
    k_eff = min(k_feat, n - 1)
    Dcopy = D.copy()
    np.fill_diagonal(Dcopy, np.inf)
    order = np.argsort(Dcopy, axis=1, kind="stable")[:, :k_eff]
    fd = D[np.arange(n)[:, None], order]
    sigma_f = float(np.median(fd))
    if not np.isfinite(sigma_f) or sigma_f <= 0:
        sigma_f = 1.0
    F = np.zeros_like(D2)
    for i in range(n):
        for j, dd in zip(order[i].tolist(), fd[i].tolist()):
            F[i, j] = max(F[i, j], float(np.exp(-dd**2 / (2 * sigma_f**2))))
    F = np.maximum(F, F.T)
    np.fill_diagonal(F, 0.0)
    assert bool(np.allclose(F, F.T))
    assert bool((np.diag(F) == 0.0).all())

    W = np.zeros_like(D2)
    pos = {t: i for i, t in enumerate(mask)}
    for u, v, w in zip(
        edges["u"].tolist(), edges["v"].tolist(), edges["weight"].tolist()
    ):
        W[pos[int(u)], pos[int(v)]] = W[pos[int(v)], pos[int(u)]] = float(w)

    for a in alphas:
        A = float(a) * W + (1.0 - float(a)) * F
        tag = f"E03_spectral_a{a:g}"
        labels[tag] = SpectralClustering(
            n_clusters=k, affinity="precomputed", random_state=seed
        ).fit_predict(A)

    def sizes(lab: np.ndarray) -> list[int]:
        return [int((lab == c).sum()) for c in sorted(set(lab.tolist()))]

    def communities_of(lab: np.ndarray):
        comms = []
        for c in sorted(set(lab.tolist())):
            comms.append({mask[i] for i in np.where(lab == c)[0].tolist()})
        return comms

    methods = {}
    for name, lab in labels.items():
        n_c = len(set(lab.tolist()))
        methods[name] = {
            "n_clusters": n_c,
            "sizes": sizes(lab),
            "silhouette": float(silhouette_score(Z, lab)),
            "calinski_harabasz": float(calinski_harabasz_score(Z, lab)),
            "davies_bouldin": float(davies_bouldin_score(Z, lab)),
            "modularity_geo": float(nx_modularity(G, communities_of(lab), weight="weight")),
        }

    names = list(labels)
    ari = {a: {b: float(adjusted_rand_score(labels[a], labels[b])) for b in names}
           for a in names}
    nmi = {a: {b: float(normalized_mutual_info_score(labels[a], labels[b])) for b in names}
           for a in names}

    outdir.mkdir(parents=True, exist_ok=True)
    all_panel_tids = sorted(
        panel[_pick(panel.columns, TID_CANDS, "territory id")].astype(int).unique().tolist()
    )
    excl = dict(feat_audit["excluded_tids"])
    for t in geo_excluded:
        excl[str(t)] = "no_positive_finite_distance_to_selected_tid"
    vertices = pd.DataFrame(
        {
            "territory_id": all_panel_tids,
            "in_mask": [t in set(mask) for t in all_panel_tids],
            "exclusion_reason": [excl.get(str(t)) for t in all_panel_tids],
        }
    )
    vertices.to_parquet(outdir / "vertices.parquet", index=False)
    feat.to_parquet(outdir / "features.parquet", index=False)
    edges.to_parquet(outdir / "edges.parquet", index=False)
    assign = pd.DataFrame({"territory_id": mask})
    for name, lab in labels.items():
        assign[f"label_{name}"] = lab
    assign.to_parquet(outdir / "assignments.parquet", index=False)

    metrics = {
        "gate": "A5",
        "seed": seed,
        "k": k,
        "k_geo": k_geo,
        "k_feat": k_feat,
        "resolution_louvain": resolution,
        "alphas": list(alphas),
        "mask": {
            "n": len(mask),
            "rule": "feature-valid tids INTERSECT tids with >=1 positive finite "
            "distance edge to a selected tid; isolates excluded, never bridged",
            "n_feature_valid": feat_audit["n_feature_valid"],
            "n_geo_excluded": len(geo_excluded),
            "geo_excluded_tids": geo_excluded,
        },
        "feature_audit": feat_audit,
        "graph_audit": {**geo_audit, "components": comp_sizes,
                        "n_components": len(comp_sizes)},
        "feature_knn_audit": {"k_feat": k_feat, "sigma_feat": sigma_f,
                              "kernel": "exp(-d^2/(2*sigma^2)), symmetrisation=max"},
        "methods": methods,
        "agreement": {"ARI": ari, "NMI": nmi},
        "note_A4": "A4 labels (2190 tids, 6 share features incl. "
        "'share:Все категории') use a different feature definition and a "
        "different mask -- they are NOT a same-mask comparison. E01 above is "
        "recomputed on the 1896-mask with the 5-share A3 definition.",
        "mobility": {
            "status": "excluded_no_OD_no_verified_crosswalk",
            "note": "mobility-index (594 rows: 297 MO x 2 dates) is a "
            "per-territory km index, not an OD matrix; no verified crosswalk "
            "to panel tids. No mobility edges invented.",
        },
    }
    with open(outdir / "metrics.json", "w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, sort_keys=True, indent=2)
        f.write("\n")

    manifest = {
        "gate": "A5",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "command": " ".join(sys.argv),
        "code": {"file": Path(__file__).name, "sha256": sha256_file(Path(__file__))},
        "seed": seed,
        "params": {"k": k, "k_geo": k_geo, "k_feat": k_feat,
                   "resolution_louvain": resolution, "alphas": list(alphas)},
        "inputs": {
            "panel": {"sha256": "see-operator-run", "rows": "see-operator-run"},
            "distance": {"sha256": "see-operator-run", "rows": "see-operator-run"},
        },
        "formulas": {
            "share": feat_audit["formula"],
            "geo_weight": geo_audit["weight_formula"],
            "affinity": "A(alpha)=alpha*W_geo+(1-alpha)*F_feat; E03 alpha=0.5",
        },
        "versions": {
            "python": sys.version.split()[0],
            "numpy": pkg_version("numpy"),
            "pandas": pkg_version("pandas"),
            "scipy": pkg_version("scipy"),
            "networkx": pkg_version("networkx"),
            "scikit-learn": pkg_version("scikit-learn"),
        },
        "graph": {"nodes": len(mask), "undirected_edges": int(len(edges)),
                  "components": comp_sizes},
        "mobility_status": "excluded_no_OD_no_verified_crosswalk",
    }
    with open(outdir / "graph_manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, sort_keys=True, indent=2)
        f.write("\n")
    return {"metrics": metrics, "manifest": manifest, "outdir": str(outdir)}


def _toy_data(seed: int = 20260921):
    rng = np.random.default_rng(seed)
    tids = list(range(1, 13))
    months = [f"2023-0{m}" for m in range(1, 7)]
    rows = []
    for t in tids:
        base = rng.uniform(0.5, 2.0)
        for m in months:
            total = 10000.0 * base * rng.uniform(0.9, 1.1)
            parts = rng.dirichlet([2, 3, 1, 4, 2]) * total * 0.72
            rows.append((t, m, TOTAL_CAT, total))
            for c, v in zip(SHARE_CATS, parts):
                rows.append((t, m, c, float(v)))
    panel = pd.DataFrame(rows, columns=["territory_id", "date", "category", "value"])
    ring = []
    for t in tids:
        ring.append((t, t % 12 + 1, float(t)))
    ring.append((12, 1, 5.0))
    ring += [
        (3, 4, 10.0),
        (4, 3, 7.0),
        (5, 5, 3.0),
        (6, 7, 0.0),
        (7, 8, -2.0),
        (8, 9, float("nan")),
        (99, 1, 4.0),
    ]
    dist = pd.DataFrame(ring, columns=["territory_id_x", "territory_id_y", "distance"])
    return panel, dist


def self_check() -> int:
    ok = True

    def check(name: str, cond: bool, detail: str = ""):
        nonlocal ok
        print(f"self-check {name}: {'PASS' if cond else 'FAIL'} {detail}")
        if not cond:
            ok = False

    panel, dist = _toy_data()
    with tempfile.TemporaryDirectory() as t1, tempfile.TemporaryDirectory() as t2:
        r1 = run_pipeline(panel, dist, Path(t1), seed=20260921, k=3)
        r2 = run_pipeline(panel, dist, Path(t2), seed=20260921, k=3)
        e1 = pd.read_parquet(Path(t1) / "edges.parquet")
        e2 = pd.read_parquet(Path(t2) / "edges.parquet")
        a1 = pd.read_parquet(Path(t1) / "assignments.parquet")
        a2 = pd.read_parquet(Path(t2) / "assignments.parquet")
        f1 = pd.read_parquet(Path(t1) / "features.parquet")

        check("no_selfloops", bool((e1["u"] != e1["v"]).all()),
              f"n_edges={len(e1)}")
        n = len(a1)
        W = np.zeros((n, n))
        pos = {t: i for i, t in enumerate(a1['territory_id'].tolist())}
        for u, v, w in zip(e1["u"], e1["v"], e1["weight"]):
            W[pos[int(u)], pos[int(v)]] = float(w)
            W[pos[int(v)], pos[int(u)]] = float(w)
        check("symmetric_adjacency", bool(np.allclose(W, W.T)))
        row34 = e1[(e1["u"] == 3) & (e1["v"] == 4)]
        check("dup_min_not_flow", len(row34) == 1 and abs(row34["distance"].iloc[0] - 3.0) < 1e-12,
              "duplicate (3,4): ring 3.0 vs repeats 10.0/7.0 -> min 3.0")
        check("bad_distances_dropped", 99 not in pos and 5 not in e1[e1["u"] == e1["v"]]["u"].tolist())
        lab_cols = [c for c in a1.columns if c.startswith("label_")]
        same_mask = (a1["territory_id"].tolist() == f1["territory_id"].tolist()
                     and len(a1) == r1["metrics"]["mask"]["n"] and len(lab_cols) == 5)
        check("single_mask_ids", same_mask, f"n={len(a1)} methods={len(lab_cols)}")
        check("repro_edges", e1.equals(e2))
        check("repro_labels", a1.equals(a2))
        m1 = json.dumps(r1["metrics"], sort_keys=True)
        m2 = json.dumps(r2["metrics"], sort_keys=True)
        check("repro_metrics", m1 == m2)
        methods = r1["metrics"]["methods"]
        finite = all(
            bool(np.isfinite([v["silhouette"], v["calinski_harabasz"],
                              v["davies_bouldin"], v["modularity_geo"]]).all())
            for v in methods.values()
        )
        check("metrics_finite", finite)
        Ztoy = np.array([[0.0], [1.0], [2.0], [10.0]])
        Dtoy = np.sqrt(((Ztoy[:, None, :] - Ztoy[None, :, :]) ** 2).sum(axis=2))
        Dcopy = Dtoy.copy()
        np.fill_diagonal(Dcopy, np.inf)
        check("knn_no_nan_offdiag", bool(np.isfinite(Dcopy[~np.eye(4, dtype=bool)]).all()))
        order_toy = np.argsort(Dcopy, axis=1, kind="stable")[:, :2]
        check("feat_knn_toy_nn", order_toy[0].tolist() == [1, 2]
              and order_toy[3].tolist() == [2, 1]
              and order_toy[1].tolist() == [0, 2],
              f"order={order_toy.tolist()}")
        Ftoy = np.zeros((4, 4))
        fd_toy = Dtoy[np.arange(4)[:, None], order_toy]
        sig_toy = float(np.median(fd_toy))
        for i in range(4):
            for j, dd in zip(order_toy[i].tolist(), fd_toy[i].tolist()):
                Ftoy[i, j] = max(Ftoy[i, j], float(np.exp(-dd**2 / (2 * sig_toy**2))))
        Ftoy = np.maximum(Ftoy, Ftoy.T)
        np.fill_diagonal(Ftoy, 0.0)
        check("F_symmetric_no_diag", bool(np.allclose(Ftoy, Ftoy.T))
              and bool((np.diag(Ftoy) == 0.0).all()))
        check("manifest_mobility",
              r1["manifest"]["mobility_status"] == "excluded_no_OD_no_verified_crosswalk")
    print("self-check: ALL PASS" if ok else "self-check: FAILURES")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--panel", default=str(DEFAULT_PANEL))
    p.add_argument("--distance", default=str(DEFAULT_DISTANCE))
    p.add_argument("--outdir", default=str(DEFAULT_OUTDIR))
    p.add_argument("--seed", type=int, default=20260921)
    p.add_argument("--k", type=int, default=5)
    p.add_argument("--k-geo", type=int, default=8)
    p.add_argument("--k-feat", type=int, default=5)
    p.add_argument("--resolution", type=float, default=1.0)
    p.add_argument("--self-check", action="store_true")
    args = p.parse_args(argv)

    if args.self_check:
        return self_check()

    panel_path = Path(args.panel)
    dist_path = Path(args.distance)
    outdir = Path(args.outdir)
    panel = pd.read_parquet(panel_path)
    dist = pd.read_parquet(dist_path)
    res = run_pipeline(panel, dist, outdir, seed=args.seed, k=args.k,
                       k_geo=args.k_geo, k_feat=args.k_feat,
                       resolution=args.resolution)
    man_path = outdir / "graph_manifest.json"
    man = json.loads(man_path.read_text(encoding="utf-8"))
    man["inputs"] = {
        "panel": {"path": str(panel_path), "sha256": sha256_file(panel_path),
                  "rows": int(len(panel))},
        "distance": {"path": str(dist_path), "sha256": sha256_file(dist_path),
                     "rows": int(len(dist))},
    }
    man_path.write_text(json.dumps(man, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                        encoding="utf-8")
    m = res["metrics"]
    print(f"A5 done: mask_n={m['mask']['n']} "
          f"edges={m['graph_audit']['n_undirected_edges']} "
          f"components={m['graph_audit']['components']}")
    for name, mm in m["methods"].items():
        print(f"  {name}: k={mm['n_clusters']} sil={mm['silhouette']:.4f} "
              f"CH={mm['calinski_harabasz']:.1f} DB={mm['davies_bouldin']:.4f} "
              f"mod={mm['modularity_geo']:.4f} sizes={mm['sizes']}")
    print(f"outdir={outdir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
