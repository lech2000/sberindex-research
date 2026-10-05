"""A11 complete validity table with nulls, graph sensitivity and cross-year check."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
from sklearn.metrics import calinski_harabasz_score, davies_bouldin_score, silhouette_score

import network_icvi as icvi
from atlas_a9 import read_network
from atlas_a10 import METHODS, partition_key, primary_partitions
from atlas_common import (CONFIGS, KS, PRIMARY_CONFIG, SEED, SEEDS, annual_features,
                          config_name, load_features, markdown_table, provenance, run_dir,
                          verify_artifacts, write_json)
from atlas_sdbw import s_dbw


def feature_metrics(x, lab):
    sd = s_dbw(x, lab)
    alternate = s_dbw(x, lab, centre_domain="own_cluster")
    k = len(np.unique(lab))
    valid = 2 <= k < len(lab)
    return {"SW": float(silhouette_score(x, lab)) if valid else None,
            "CH": float(calinski_harabasz_score(x, lab)) if valid else None,
            "DB": float(davies_bouldin_score(x, lab)) if valid else None,
            "S_Dbw": sd["S_Dbw"], "S_Dbw_status": sd["status"],
            "Scat": sd.get("Scat"), "Dens_bw": sd.get("Dens_bw"),
            "S_Dbw_own_cluster": alternate["S_Dbw"],
            "S_Dbw_own_status": alternate["status"],
            "S_Dbw_undefined_pairs": sd.get("undefined_pairs"),
            "S_Dbw_singletons": sd.get("singleton_clusters"),
            "K": k, "largest_group_share": float(np.unique(lab, return_counts=True)[1].max()/len(lab))}


def graph_metrics(a, lab):
    r = icvi.compute_network_indices(a, lab)
    null = icvi.random_partition_null(a, lab, B=300, seed=SEED)
    return {"AVI": r["AVI"], "AVU": r["AVU"], "ANUI": r["ANUI"],
            "Q_newman": r["modularity_newman"], "MQ_status": icvi.MQ_STATUS,
            "clusters_without_edges": r["clusters_without_edges"],
            "AVI_null_mean": null["AVI"]["null_mean"], "AVI_null_sd": null["AVI"]["null_sd"],
            "AVI_z": null["AVI"]["z"], "null_B": 300,
            "AVI_z_status": "COMPUTED" if null["AVI"]["null_sd"] > 0 else "NA_ZERO_NULL_SD"}


def main():
    verify_artifacts(9)
    verify_artifacts(10)
    out = run_dir(11)
    ids, x = load_features()
    parts = primary_partitions()
    features = {key: feature_metrics(x, lab) for key, lab in parts.items()}
    seed_metrics = []
    for method in METHODS:
        for k in KS:
            key = partition_key(method, k)
            frame = pd.read_parquet(run_dir(10) / f"assignments_A5_{key}.parquet")
            for seed in SEEDS:
                values = features[key] if seed == SEED else feature_metrics(x, frame[f"label_seed_{seed}"].to_numpy())
                seed_metrics.append({"partition": key, "seed": seed, **values})
    pd.DataFrame(seed_metrics).to_csv(out / "feature_metrics_all_seeds.csv", index=False)
    table = []
    for k, mode, weight in CONFIGS:
        config = config_name(k, mode, weight)
        a = read_network("A5", config, ids)
        for key, lab in parts.items():
            table.append({"partition": key, "network": config, "window": "A5", **features[key], **graph_metrics(a, lab)})
        print("A11 indices + 300 null permutations", config, flush=True)
    df = pd.DataFrame(table)
    df.to_csv(out / "all_networks_validity.csv", index=False, na_rep="NA")
    primary_df = df[df.network == PRIMARY_CONFIG]
    primary_df.to_csv(out / "validity.csv", index=False, na_rep="NA")
    _, annual, transform = annual_features()
    cross = []
    for label_window, xx in annual.items():
        pp = primary_partitions(label_window)
        for graph_window in annual:
            a = read_network(graph_window, PRIMARY_CONFIG, ids)
            for key, lab in pp.items():
                cross.append({"partition": key, "label_window": label_window,
                              "graph_window": graph_window, **feature_metrics(xx, lab), **graph_metrics(a, lab)})
            print("A11 cross-year", label_window, graph_window, flush=True)
    cd = pd.DataFrame(cross)
    cd.to_csv(out / "cross_year_validity.csv", index=False, na_rep="NA")
    differences = []
    for window in annual:
        other = next(w for w in annual if w != window)
        for key in parts:
            same = cd[(cd.label_window == window) & (cd.graph_window == window) & (cd.partition == key)].iloc[0]
            reverse = cd[(cd.label_window == window) & (cd.graph_window == other) & (cd.partition == key)].iloc[0]
            differences.append({"partition": key, "label_window": window, "same_year_AVI": same.AVI,
                                "cross_year_AVI": reverse.AVI, "same_minus_cross": same.AVI - reverse.AVI})
    pd.DataFrame(differences).to_csv(out / "cross_year_differences.csv", index=False)
    write_json(out / "results.json", {"n_nodes": len(ids), "n_primary_rows": len(primary_df),
        "n_graph_sensitivity_rows": len(df), "n_cross_year_rows": len(cd),
        "primary_network": PRIMARY_CONFIG, "primary_table": primary_df.to_dict("records"),
        "cross_year_differences": differences, "MQ_status": icvi.MQ_STATUS,
        "S_Dbw_status_counts": primary_df.S_Dbw_status.value_counts().to_dict(),
        "null_B": 300, "no_K_selection": True,
        "limits": ["cross-year is not independent economic validation", "null z is not a p-value",
                   "S_Dbw population variance / pair-union convention; undefined densities remain NA",
                   "AVI null ~1/K only for balanced groups; AVU not a universal constant for K<=3"]})
    display = primary_df[["partition", "K", "SW", "CH", "DB", "S_Dbw", "S_Dbw_status", "AVI", "AVU", "ANUI", "Q_newman", "AVI_null_mean", "AVI_z", "largest_group_share"]]
    (out / "README.md").write_text("# A11 — индексы валидности\n\nОсновная заранее заданная сеть: k7 union Gaussian. Все12 сети в all_networks_validity.csv.\n\n" + markdown_table(display) +
        "\n\nMQ: SPEC_UNRESOLVED; Q_newman имеет собственное имя. Каждый NA содержит статус, приближения не подставлялись.\n\n"
        "Как читать: индексы описывают согласованность с признаками/графом, а не истинность экономических типов. "
        "AVI зависит от K и размера групп; эмпирическая нулевая модель сохраняет размеры. AVI/ANUI могут поощрять гигант. "
        "AVU у двух связанных групп=1, для K3 универсальной константы нет. z — не p-value. "
        "S_Dbw не используется для выбора K; монотонность по K не гарантируется.\n\n"
        "S_Dbw: Halkidi/Vazirgiannis (2001), DOI10.1109/ICDM.2001.989517, собственная формульная реализация; "
        "radius=sqrt(sum(norm(var_i)))/K. В тесте 6 точек ручной результат1/97; pair-union и own-cluster показаны отдельно.\n\n"
        "Cross-year в cross_year_validity.csv; разбиения пересчитаны на соответствующем годе. "
        "Это ослабляет same-window замкнутость, но общий источник/нормировка и временная корреляция сохраняются.\n")
    provenance(11, dependencies=[run_dir(9) / "provenance.json", run_dir(10) / "provenance.json"])


if __name__ == "__main__":
    main()
