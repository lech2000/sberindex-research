"""A10 equal-K comparison, seed variability and common subsample stability."""
from __future__ import annotations

import json
import warnings
from itertools import combinations

import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix
from sklearn.cluster import AgglomerativeClustering, Birch, KMeans, SpectralClustering
from sklearn.metrics import adjusted_rand_score, normalized_mutual_info_score
from sklearn.mixture import GaussianMixture

from atlas_a9 import build_network, louvain_labels, read_network
from atlas_common import (KS, PRIMARY_CONFIG, SEED, SEEDS, annual_features,
                          load_features, markdown_table, provenance, run_dir, verify_artifacts, write_json)

METHODS = ("kmeans", "ward", "average", "gmm_diag", "spectral", "birch")


def fit_method(x, method, k, seed=SEED, affinity=None):
    if method == "kmeans":
        model = KMeans(n_clusters=k, n_init=10, max_iter=300, random_state=seed)
    elif method in {"ward", "average"}:
        model = AgglomerativeClustering(n_clusters=k, linkage=method, metric="euclidean")
    elif method == "gmm_diag":
        model = GaussianMixture(n_components=k, covariance_type="diag", n_init=5,
                                reg_covar=1e-6, max_iter=300, random_state=seed)
    elif method == "spectral":
        if affinity is None:
            affinity = build_network(x, min(7, len(x) - 1))[0]
        model = SpectralClustering(n_clusters=k, affinity="precomputed", eigen_solver="arpack",
                                   assign_labels="kmeans", n_init=10, random_state=seed)
        x = csr_matrix(affinity)
    elif method == "birch":
        model = Birch(threshold=.5, branching_factor=50, n_clusters=k)
    else:
        raise ValueError("Unknown method")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        labels = model.fit_predict(x)
    info = {"actual_K": int(len(np.unique(labels))), "requested_K": k,
            "converged": bool(getattr(model, "converged_", True)),
            "warnings": [str(w.message) for w in caught]}
    info["valid_fixed_K"] = info["actual_K"] == k and info["converged"]
    return np.asarray(labels, int), info


def partition_key(method, k):
    return method + "_K" + str(k)


def primary_partitions(window="A5"):
    out = run_dir(10)
    result = {}
    for method in METHODS:
        for k in KS:
            key = partition_key(method, k)
            result[key] = pd.read_parquet(out / f"assignments_{window}_{key}.parquet")["label"].to_numpy(int)
    result["louvain_natural"] = pd.read_parquet(out / f"assignments_{window}_louvain_natural.parquet")["label"].to_numpy(int)
    return result


def main():
    verify_artifacts(9)
    out = run_dir(10)
    ids, x = load_features()
    affinity = read_network(config=PRIMARY_CONFIG, ids=ids)
    primary, models, seed_rows = {}, [], []
    for method in METHODS:
        for k in KS:
            key = partition_key(method, k)
            frame = pd.DataFrame({"territory_id": ids})
            seed_labs = []
            for seed in SEEDS:
                lab, info = fit_method(x, method, k, seed, affinity)
                frame[f"label_seed_{seed}"] = lab
                seed_labs.append(lab)
                models.append({"window": "A5", "method": method, "K": k, "seed": seed, **info})
            frame["label"] = seed_labs[0]
            primary[key] = seed_labs[0]
            frame.to_parquet(out / f"assignments_A5_{key}.parquet", index=False)
            for i, j in combinations(range(5), 2):
                seed_rows.append({"partition": key, "seed_a": SEEDS[i], "seed_b": SEEDS[j],
                                  "ari": adjusted_rand_score(seed_labs[i], seed_labs[j])})
            print("A10 full", key, flush=True)
    frame = pd.DataFrame({"territory_id": ids})
    seed_labs = [louvain_labels(affinity, seed) for seed in SEEDS]
    for seed, lab in zip(SEEDS, seed_labs):
        frame[f"label_seed_{seed}"] = lab
        models.append({"window": "A5", "method": "louvain", "K": None, "seed": seed,
                       "actual_K": len(np.unique(lab)), "valid_fixed_K": False, "converged": True})
    frame["label"] = seed_labs[0]
    primary["louvain_natural"] = seed_labs[0]
    frame.to_parquet(out / "assignments_A5_louvain_natural.parquet", index=False)
    for i, j in combinations(range(5), 2):
        seed_rows.append({"partition": "louvain_natural", "seed_a": SEEDS[i], "seed_b": SEEDS[j],
                          "ari": adjusted_rand_score(seed_labs[i], seed_labs[j])})
    names = list(primary)
    ari, nmi, same_k = [], [], []
    for a in names:
        ari.append([adjusted_rand_score(primary[a], primary[b]) for b in names])
        nmi.append([normalized_mutual_info_score(primary[a], primary[b], average_method="arithmetic") for b in names])
    for k in KS:
        for ma, mb in combinations(METHODS, 2):
            a, b = partition_key(ma, k), partition_key(mb, k)
            same_k.append({"K": k, "method_a": ma, "method_b": mb,
                           "ari": adjusted_rand_score(primary[a], primary[b]),
                           "nmi": normalized_mutual_info_score(primary[a], primary[b], average_method="arithmetic")})
    pd.DataFrame(ari, index=names, columns=names).to_csv(out / "agreement_ari.csv")
    pd.DataFrame(nmi, index=names, columns=names).to_csv(out / "agreement_nmi.csv")
    pd.DataFrame(same_k).to_csv(out / "same_k_agreement.csv", index=False)
    pd.DataFrame(seed_rows).to_csv(out / "seed_consistency.csv", index=False)
    stable = []
    n_sub = int(.8 * len(ids))
    for repeat in range(20):
        sub = np.sort(np.random.default_rng(SEED + 100 + repeat).choice(len(ids), n_sub, replace=False))
        sub_aff = build_network(x[sub], 7, ids=ids[sub])[0]
        for method in METHODS:
            for k in KS:
                key = partition_key(method, k)
                lab, info = fit_method(x[sub], method, k, SEED, sub_aff)
                stable.append({"partition": key, "repeat": repeat, "subset_seed": SEED + 100 + repeat,
                               "n": n_sub, "ari": adjusted_rand_score(primary[key][sub], lab), **info})
        lab = louvain_labels(sub_aff)
        stable.append({"partition": "louvain_natural", "repeat": repeat, "subset_seed": SEED + 100 + repeat,
                       "n": n_sub, "ari": adjusted_rand_score(primary["louvain_natural"][sub], lab),
                       "actual_K": len(np.unique(lab)), "requested_K": None, "converged": True,
                       "valid_fixed_K": False, "warnings": []})
        print("A10 subsample", repeat + 1, "/20", flush=True)
    stable_df = pd.DataFrame(stable)
    stable_df.drop(columns="warnings").to_csv(out / "stability.csv", index=False)
    summary = stable_df.groupby("partition").ari.agg(["mean", "median", "min", "max", "std"])
    summary.to_csv(out / "stability_summary.csv")
    _, annual, transform = annual_features()
    for window, xx in annual.items():
        aa = read_network(window, PRIMARY_CONFIG, ids)
        for method in METHODS:
            for k in KS:
                lab, info = fit_method(xx, method, k, SEED, aa)
                pd.DataFrame({"territory_id": ids, "label": lab}).to_parquet(out / f"assignments_{window}_{partition_key(method,k)}.parquet", index=False)
                models.append({"window": window, "method": method, "K": k, "seed": SEED, **info})
        lab = louvain_labels(aa)
        pd.DataFrame({"territory_id": ids, "label": lab}).to_parquet(out / f"assignments_{window}_louvain_natural.parquet", index=False)
        print("A10 cross-year fits", window, flush=True)
    failed = [r for r in models if r["method"] != "louvain" and not r["valid_fixed_K"]]
    results = {"n_nodes": len(ids), "methods_fixed_K": list(METHODS), "K_grid": KS,
               "seeds": SEEDS, "n_subsamples": 20, "n_stability_rows": len(stable),
               "models": models, "invalid_fixed_K": failed, "same_K_agreement": same_k,
               "stability_summary": summary.reset_index().to_dict("records"),
               "deviations": ["Birch added as sixth fixed-K method; Louvain natural K separately"],
               "no_best_method_selected": True}
    write_json(out / "results.json", results)
    weakest = sorted(same_k, key=lambda r: r["ari"])[:5]
    lines = ["# A10 — сравнение методов", "", f"6 методов при K=3,5,8; 5 seeds; 20 общих подвыборок по {n_sub} МО.",
             "Louvain отдельно с естественным K; Birch добавлен до расчёта. Детерминированные повторы не независимы.", "",
             f"Некорректных full fixed-K fits: {len(failed)}. Полные предупреждения в results.json.", "", "Наиболее сильные расхождения (описательные):"]
    lines.extend(f"- K={r['K']} {r['method_a']} / {r['method_b']}: ARI={r['ari']:.4f}, NMI={r['nmi']:.4f}" for r in weakest)
    lines += ["", "Устойчивость к подвыборке:", "", markdown_table(summary.reset_index()), "",
              "ARI сравнивается на общих ID, граф перестраивается. Это не out-of-sample качество. Выбор лучшего метода/K не проводился."]
    (out / "README.md").write_text("\n".join(lines) + "\n")
    provenance(10, dependencies=[run_dir(9) / "results.json", run_dir(9) / "provenance.json"])


if __name__ == "__main__":
    main()
