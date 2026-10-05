"""A12 descriptive consensus cores and conditional regional-bootstrap passports."""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import cut_tree, linkage
from scipy.optimize import linear_sum_assignment
from scipy.spatial.distance import squareform
from sklearn.metrics import adjusted_rand_score

from atlas_common import (ATLAS, SEED, check_inputs, load_module, load_monthly,
                          markdown_table, provenance, run_dir, write_json)

THRESHOLDS = (.8, .9, .95)
STORIES = {1673: "Орск", 1333: "Курган", 2192: "Ишим", 1668: "Бузулук", 2190: "Тюмень"}


def coassociation(config_labels):
    labels = np.asarray(config_labels)
    if labels.ndim != 2 or len(labels) == 0:
        raise ValueError("Expected configurations x nodes")
    counts = np.zeros((labels.shape[1], labels.shape[1]), dtype=np.uint16)
    for row in labels:
        counts += row[:, None] == row[None, :]
    return counts.astype(float) / len(labels)


def consensus_cores(coassoc, k=5, threshold=.9):
    c = np.asarray(coassoc, float)
    if c.ndim != 2 or c.shape[0] != c.shape[1] or not np.isfinite(c).all() or not np.allclose(c,c.T):
        raise ValueError("Invalid coassociation")
    if (c < 0).any() or (c > 1).any() or not 1 <= k <= len(c):
        raise ValueError("Invalid coassociation/K")
    distance = 1 - c
    np.fill_diagonal(distance, 0)
    labels = cut_tree(linkage(squareform(distance, checks=True), method="average"), n_clusters=k).ravel()
    score = np.full(len(c), np.nan)
    for group in np.unique(labels):
        members = np.flatnonzero(labels == group)
        if len(members) > 1:
            score[members] = (c[np.ix_(members,members)].sum(1) - np.diag(c)[members]) / (len(members) - 1)
    return labels, score, np.isfinite(score) & (score >= threshold)


def population_by_year(frame):
    d = frame[(frame.age.astype(str) == "Всего") & frame.year.isin([2023, 2024])].copy()
    # Identical source rows are repeated for two panel municipalities. Collapse
    # complete duplicates, record their count in main; conflicting keys fail.
    d = d.drop_duplicates()
    if d.duplicated(["territory_id", "year", "gender"]).any():
        raise ValueError("Duplicate population key; no silent double counting")
    if set(d.gender) != {"Женщины", "Мужчины"}:
        raise ValueError("Unexpected gender aggregation; specify convention first")
    counts = d.groupby(["territory_id", "year"]).gender.nunique()
    if (counts != 2).any():
        raise ValueError("Incomplete male/female population totals")
    return d.groupby(["territory_id", "year"]).value.sum(min_count=2).unstack("year")


def regional_bootstrap(values, regions, core, seed=SEED, repeats=1000):
    """Sample all panel regions; fixed memberships, region multiplicities retained."""
    values = np.asarray(values, float)
    if values.ndim == 1:
        values = values[:, None]
    _, inv = np.unique(regions, return_inverse=True)
    nr, nf = int(inv.max()+1), values.shape[1]
    sums, counts = np.zeros((nr,nf)), np.zeros((nr,nf))
    for column in range(nf):
        valid = core & np.isfinite(values[:,column])
        np.add.at(sums[:,column], inv[valid], values[valid,column])
        np.add.at(counts[:,column], inv[valid], 1)
    rng = np.random.default_rng(seed)
    multiplicity = rng.multinomial(nr, np.full(nr, 1/nr), size=repeats)
    den = multiplicity @ counts
    draws = np.divide(multiplicity @ sums, den, out=np.full_like(den,np.nan), where=den>0)
    result = []
    for column in range(nf):
        finite = draws[:,column][np.isfinite(draws[:,column])]
        result.append({"ci95": np.quantile(finite,[.025,.975]).tolist() if len(finite) else None,
                       "valid_resamples": len(finite), "NA_resamples": repeats-len(finite)})
    return result


def passports(ids, shares, z, labels, scores, regions, names, pop):
    core = np.isfinite(scores) & (scores >= .9)
    items = []
    logpop = np.where(pop > 0, np.log(np.where(pop>0,pop,np.nan)), np.nan)
    for label in np.unique(labels):
        members = np.flatnonzero(core & (labels==label))
        if not len(members):
            continue
        mask = core & (labels==label)
        vals = np.column_stack((shares,logpop))
        intervals = regional_bootstrap(vals, regions, mask, seed=SEED+int(label))
        profile = shares[members].mean(0)
        centre = z[members].mean(0)
        dist = np.linalg.norm(z[members]-centre,axis=1)
        typical = members[np.lexsort((ids[members],dist))[:5]]
        reg, counts = np.unique(regions[members], return_counts=True)
        goodpop = logpop[members][np.isfinite(logpop[members])]
        items.append({"cluster":int(label),"n_core":len(members),"fraction_all_MO":len(members)/len(ids),
            "share_profile_mean":profile.tolist(),"mean_ln_population":float(goodpop.mean()) if len(goodpop) else None,
            "population_n_observed":len(goodpop),"population_n_missing":len(members)-len(goodpop),
            "region_composition":{str(r):int(n) for r,n in zip(reg,counts)},
            "typical_MO":[{"territory_id":int(ids[i]),"name":str(names[i]),"distance_frozen_z":float(np.linalg.norm(z[i]-centre))} for i in typical],
            "conditional_ci95":intervals,"bootstrap_repeats":1000,
            "ci_limit":"fixed memberships; descriptive conditional regional bootstrap"})
    return items


def main():
    paths = check_inputs(external=True)
    out = run_dir(12)
    ids, months, shares, z, transform = load_monthly()
    stories = load_module("atlas_a7_stories",ATLAS/"runs/A7_stories_20261004/build_stories.py")
    dictionary = pd.read_parquet(paths["dictionary"])
    if not dictionary.territory_id.is_unique:
        raise ValueError("Duplicate dictionary territory keys")
    dic = dictionary.set_index("territory_id").reindex(ids)
    if dic.region_code.isna().any():
        raise ValueError("Missing region for frozen mask")
    regions = dic.region_code.to_numpy(int)
    names = dic.name_short.to_numpy()
    raw_population = pd.read_parquet(paths["population"])
    panel_population = raw_population[raw_population.territory_id.isin(ids)]
    pop_totals = panel_population[(panel_population.age.astype(str)=="Всего") & panel_population.year.isin([2023,2024])]
    duplicate_rows = int(pop_totals.duplicated().sum())
    duplicate_tids = sorted(int(t) for t in pop_totals.loc[pop_totals.duplicated(keep=False),"territory_id"].unique())
    population = population_by_year(panel_population).reindex(ids)
    outputs, parts, cards = {}, {}, []
    normalized = {norm:stories.normalise(shares,months,norm) for norm in stories.NORMS}
    for year in (2023,2024):
        month = f"{year}-12"
        index = months.index(month)
        configs, config_names = [], []
        for norm in stories.NORMS:
            xx = normalized[norm][:,index,:]
            for k in stories.KS:
                for family, seed_off in [("kmeans",off) for off in stories.SEEDS]+[("ward",0)]:
                    lab,_ = stories.fit_month(xx,k,family,stories.BASE_SEED+1000*seed_off+index)
                    configs.append(lab)
                    config_names.append(f"{norm}|{family}|K{k}|s{seed_off}")
        c = coassociation(configs)
        np.save(out/f"coassociation_{month}.npy",c)
        config_frame = pd.DataFrame(np.asarray(configs).T,columns=config_names)
        config_frame.insert(0,"territory_id",ids)
        config_frame.to_parquet(out/f"configurations_{month}.parquet",index=False)
        labels,scores,core = consensus_cores(c)
        frame = pd.DataFrame({"territory_id":ids,"cluster":labels,"mean_coassociation":scores,
                              **{f"core_{t:.2f}":np.isfinite(scores)&(scores>=t) for t in THRESHOLDS}})
        frame.to_parquet(out/f"cores_{month}.parquet",index=False)
        pop = population[year].to_numpy(float)
        passports_out = passports(ids,shares[:,index,:],z[:,index,:],labels,scores,regions,names,pop)
        write_json(out/f"passports_{month}.json",{"share_categories":stories.a6.SHARE_CATS,"cores":passports_out})
        sensitivity = [{"threshold":t,"n_core":int(np.count_nonzero(np.isfinite(scores)&(scores>=t))),
                        "fraction":float(np.mean(np.isfinite(scores)&(scores>=t)))} for t in THRESHOLDS]
        outputs[month] = {"n_configs":len(configs),"consensus_K":len(np.unique(labels)),
                          "thresholds":sensitivity,"n_passports":len(passports_out),
                          "n_ambiguous_primary":int((~core).sum()),"population_missing_total":int((~np.isfinite(pop)|(pop<=0)).sum())}
        for tid,name in STORIES.items():
            i = int(np.flatnonzero(ids==tid)[0])
            cards.append({"month":month,"territory_id":tid,"name":name,"cluster":int(labels[i]),
                          "mean_coassociation":float(scores[i]),"status":"core" if core[i] else "ambiguous",
                          **{f"core_{t:.2f}":bool(np.isfinite(scores[i]) and scores[i]>=t) for t in THRESHOLDS}})
        parts[year] = (labels,scores,core)
        print("A12",month,"36 configurations",int(core.sum()),"core nodes",flush=True)
    l23,s23,c23 = parts[2023]
    l24,s24,c24 = parts[2024]
    overlap = np.array([[np.count_nonzero((l23==i)&(l24==j)) for j in range(5)] for i in range(5)])
    rows,cols = linear_sum_assignment(-overlap)
    matches = []
    for i,j in zip(rows,cols):
        a,b = (l23==i)&c23,(l24==j)&c24
        union = np.count_nonzero(a|b)
        matches.append({"cluster2023":int(i),"cluster2024":int(j),"core2023_n":int(a.sum()),
                        "core2024_n":int(b.sum()),"core_intersection_n":int((a&b).sum()),
                        "core_jaccard":float((a&b).sum()/union) if union else None})
    write_json(out/"results.json",{"n_nodes":len(ids),"months":outputs,"stories":cards,
        "consensus_ARI_2023_2024":adjusted_rand_score(l23,l24),"aligned_core_jaccard":matches,
        "primary_threshold":.9,"consensus_K_fixed":5,"bootstrap_repeats":1000,
        "population_exact_duplicate_rows_removed":duplicate_rows,"population_duplicate_tids":duplicate_tids,
        "limits":["coassociation depends on K grid; not probability","27/36 KMeans configs; dependent grid",
                  "score to full consensus group, excludes self; no pruning","conditional bootstrap does not refit memberships"]})
    pd.DataFrame(cards).to_csv(out/"five_stories.csv",index=False)
    lines=["# A12 — ядра консенсусных групп","","K=5 задан до расчёта; 36 конфигураций на каждом декабре.",""]
    for month,rec in outputs.items():
        lines.append(f"{month}: core fractions "+", ".join(f"tau={r['threshold']}: {r['n_core']}/1896 ({r['fraction']:.2%})" for r in rec["thresholds"])+f"; паспортов {rec['n_passports']}.")
    lines += ["",f"ARI консенсусов между годами={adjusted_rand_score(l23,l24):.4f}. Матчинг/Жаккар ядер в results.json.","",markdown_table(pd.DataFrame(cards)),"",
              "Паспорта только primary cores. Неоднозначные не получают паспорт. Пустое ядро — допустимый отрицательный результат.",
              "Совстречаемость не является вероятностью; зависит от набора K и доли k-means. Интервалы условны на фиксированных ядрах, не оценивают неопределённость членства."]
    (out/"README.md").write_text("\n".join(lines)+"\n")
    provenance(12,external=True)


if __name__=="__main__":
    main()
