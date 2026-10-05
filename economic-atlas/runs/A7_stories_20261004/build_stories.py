"""A7.S2 — истории муниципалитетов: профиль расходов, контекст и проверка вывода на смене метода и порога (04.10.2026).

Что считает:
1. Профиль расходов МО напрямую, без разбиения: доли 5 категорий в «Все категории» (как в A6), сдвиг средних долей 2024 к 2023
   в единицах замороженной стандартизации 2023 и его положение среди 1896 МО; то же относительно медианы МО по месяцу.
2. Помесячные разбиения на сетке из 36 конфигураций (3 нормировки × K ∈ {2, 3, 5} × (k-means 3 зерна + Ward)); выравнивание меток
   венгерским методом; модальная группа за 2023 и за 2024; признак «сменила группу».
3. Поле неоднозначности: запас (d2 − d1)/(d2 + d1) до второго центра; порог τ0 = 10-й процентиль запаса по всем МО-месяцам 2023,
   проверка на множителях 0,75 / 1 / 1,25 (это НАШ показатель на уровне МО, не архивный candidate_margin идентичностей A6).
4. Согласие конфигураций: у скольких конфигураций из 36 сменила группу каждая МО; Жаккар множеств «сменили группу» между конфигурациями.
5. Контекст по шести городам: население 2023–2024, зарплаты по отраслям 2023–2024, миграция 2023 (за 2024 в пакете нет).

Правило отбора заданное ДО расчёта: города фиксированной выборки бюджетного пилота оператора (Орск, Бузулук, Курган, Шадринск, Тюмень, Ишим);
историями становятся те, у кого есть хотя бы одна пара бюджетных наблюдений (Орск, Курган, Ишим, Бузулук, Тюмень); Шадринск без бюджетов — контрольный.

Не считает и не заявляет: причинность, занятость по МО (выгрузка Y48423005 на этом хосте отсутствует), миграцию 2024, бюджетные цифры
(они берутся из документов дел как сообщённые оператором и не пересчитываются здесь).

Запуск: python build_stories.py [--panel ...] [--data-sense-dir ...] [--outdir .]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import linear_sum_assignment

HERE = Path(__file__).resolve().parent
ATLAS = HERE.parents[1]
sys.path.insert(0, str(ATLAS / "src"))
import a6_temporal as a6  # noqa: E402

CITIES = {1673: "Орск", 1668: "Бузулук", 1333: "Курган", 2192: "Ишим", 2190: "Тюмень", 1334: "Шадринск"}
STORY_IDS = [1673, 1333, 2192, 1668, 2190]  # правило отбора: ≥ 1 пара бюджетных наблюдений
KS = (2, 3, 5)
SEEDS = (0, 1, 2)
MARGIN_FACTORS = (0.75, 1.0, 1.25)
NORMS = ("z2023", "zall", "logz2023")
BASE_SEED = 20261004
SECTORS_OF_INTEREST = ["0", "D", "F", "G", "P", "Q", "H", "I"]


# ───────────────────────────── нормировки ─────────────────────────────
def normalise(S: np.ndarray, months: list[str], how: str):
    if how == "z2023":
        return a6.standardize_frozen(S, months)[0]
    if how == "zall":
        pool = S.reshape(-1, S.shape[2])
        mu, sd = pool.mean(0), pool.std(0)
        sd = np.where(sd == 0, 1.0, sd)
        return (S - mu) / sd
    if how == "logz2023":
        if (S <= 0).any():
            raise ValueError("logz: неположительные доли")
        L = np.log(S)
        fit = [i for i, m in enumerate(months) if m.startswith("2023")]
        pool = L[:, fit, :].reshape(-1, L.shape[2])
        mu, sd = pool.mean(0), pool.std(0)
        sd = np.where(sd == 0, 1.0, sd)
        return (L - mu) / sd
    raise ValueError(how)


# ───────────────────────────── разбиения ─────────────────────────────
def fit_month(X: np.ndarray, k: int, family: str, seed: int):
    from sklearn.cluster import AgglomerativeClustering, KMeans

    if family == "kmeans":
        km = KMeans(n_clusters=k, n_init=10, random_state=seed)
        lab = km.fit_predict(X)
        return lab, km.cluster_centers_
    lab = AgglomerativeClustering(n_clusters=k, linkage="ward").fit_predict(X)
    return lab, np.stack([X[lab == c].mean(axis=0) for c in range(k)])


def align_sequence(raw_labels: list[np.ndarray], raw_centres: list[np.ndarray]):
    """Венгерское выравнивание id групп к предыдущим выровненным центрам; месяц 0 — как есть."""
    aligned, cens = [raw_labels[0].copy()], [raw_centres[0].copy()]
    for m in range(1, len(raw_labels)):
        prev = cens[-1]
        cost = ((raw_centres[m][:, None, :] - prev[None, :, :]) ** 2).sum(-1)
        r, c = linear_sum_assignment(cost)
        mapping = np.empty(len(r), int)
        mapping[r] = c
        aligned.append(mapping[raw_labels[m]])
        new_c = np.empty_like(raw_centres[m])
        new_c[mapping] = raw_centres[m]
        cens.append(new_c)
    return np.stack(aligned), cens  # (M, N), список (k, F)


def margins(X: np.ndarray, centres: np.ndarray) -> np.ndarray:
    """(d2 − d1)/(d2 + d1) до двух ближайших центров; 0 — МО на границе групп, 1 — далеко от второго центра."""
    d = np.sqrt(((X[:, None, :] - centres[None, :, :]) ** 2).sum(-1))
    d.sort(axis=1)
    return (d[:, 1] - d[:, 0]) / (d[:, 1] + d[:, 0] + 1e-12)


def modal(labels: np.ndarray, k: int):
    """labels (12, N) за год → (мода (N), признак ничьей (N))."""
    counts = np.stack([(labels == g).sum(axis=0) for g in range(k)], axis=0)  # (k, N)
    top = counts.argmax(axis=0)
    srt = np.sort(counts, axis=0)
    return top, srt[-1] == srt[-2]


def run_config(Z: np.ndarray, k: int, family: str, seed_off: int):
    N, M, _ = Z.shape
    raw_l, raw_c = [], []
    for m in range(M):
        lab, cen = fit_month(Z[:, m, :], k, family, BASE_SEED + 1000 * seed_off + m)
        raw_l.append(lab)
        raw_c.append(cen)
    lab, cens = align_sequence(raw_l, raw_c)
    mar = np.stack([margins(Z[:, m, :], cens[m]) for m in range(M)])  # (M, N)
    return lab, mar


def summarise_config(lab: np.ndarray, mar: np.ndarray, k: int, months: list[str], tau0: float):
    i23 = [i for i, m in enumerate(months) if m.startswith("2023")]
    i24 = [i for i, m in enumerate(months) if m.startswith("2024")]
    g23, t23 = modal(lab[i23], k)
    g24, t24 = modal(lab[i24], k)
    rec = {
        "g23": g23, "g24": g24, "tie": t23 | t24,
        "changed": (g23 != g24) & ~(t23 | t24),
        "switches": (lab[1:] != lab[:-1]).sum(axis=0),
        "mean_margin_24": mar[i24].mean(axis=0),
    }
    for f in MARGIN_FACTORS:
        rec[f"amb_frac_24_x{f}"] = (mar[i24] < tau0 * f).mean(axis=0)
    return rec


# ───────────────────────────── прямой профиль ─────────────────────────────
def pct_rank(x: np.ndarray, v: float) -> float:
    x = x[np.isfinite(x)]
    return float(100.0 * (x < v).mean() + 50.0 * (x == v).mean())


def direct_profile(S, Z, months, tids, panel_all):
    i23 = [i for i, m in enumerate(months) if m.startswith("2023")]
    i24 = [i for i, m in enumerate(months) if m.startswith("2024")]
    d_abs = np.linalg.norm(Z[:, i24].mean(1) - Z[:, i23].mean(1), axis=1)
    rel = Z - np.median(Z, axis=0, keepdims=True)  # относительно медианы МО в тот же месяц
    d_rel = np.linalg.norm(rel[:, i24].mean(1) - rel[:, i23].mean(1), axis=1)
    dshare = (S[:, i24].mean(1) - S[:, i23].mean(1)) * 100.0  # п.п. доли в «Все категории»
    tot = panel_all.pivot_table(index="tid", columns="month", values="value", aggfunc="first").reindex(tids)
    L23, L24 = tot[[months[i] for i in i23]].mean(1).to_numpy(), tot[[months[i] for i in i24]].mean(1).to_numpy()
    yoy = L24 / L23 - 1.0
    return d_abs, d_rel, dshare, L23, L24, yoy, rel


def robust_z(x: np.ndarray, v: float) -> float:
    med = np.nanmedian(x)
    mad = np.nanmedian(np.abs(x - med)) * 1.4826
    return float((v - med) / mad) if mad > 0 else float("nan")


# ───────────────────────────── контекст ─────────────────────────────
def context(ds_dir: Path, tids: np.ndarray):
    pop = pd.read_parquet(ds_dir / "2_bdmo_population.parquet")
    # в таблице рядом лежат одиночные возрасты, агрегаты «65+», «70+», «80+» и «Всего»: суммировать всё нельзя (двойной счёт);
    # берётся строка age = «Всего» по двум полам, как в проверке занятости A6
    tot = pop[pop["age"].astype(str) == "Всего"].groupby(["territory_id", "year"])["value"].sum().unstack("year")
    mig = pd.read_parquet(ds_dir / "3_bdmo_migration.parquet")
    mt = mig[(mig.age == "Всего")].groupby(["territory_id", "year"])["value"].sum(min_count=1).unstack("year")
    sal = pd.read_parquet(ds_dir / "4_bdmo_salary.parquet")
    sal = sal[(sal.period == "январь-декабрь") & (sal.okved_letter.isin(SECTORS_OF_INTEREST))]
    sw = sal.pivot_table(index="territory_id", columns=["okved_letter", "year"], values="value", aggfunc="first")
    return tot, mt, sw


# ───────────────────────────── занятость, архив A6_v2, бюджеты ─────────────────────────────
def employment_block(path: str, dic: pd.DataFrame, story_tids):
    """Среднесписочная численность работников организаций БЕЗ субъектов малого предпринимательства (Tochno/БДМО Y48423005),
    январь–декабрь, МО верхнего уровня. ОКТМО панели → первые 8 цифр без дефисов. Перцентили — среди МО выгрузки с обоими годами."""
    e = pd.read_parquet(path, columns=["okved2", "oktmo", "mun_level", "year", "indicator_value", "indicator_period"])
    d = e[(e["indicator_period"] == "Январь-декабрь") & e["year"].isin([2023, 2024]) & e["mun_level"].str.contains("верхнего", na=False)]
    is_tot = d["okved2"].str.startswith("Всего", na=False)
    tot = d[is_tot].pivot_table(index="oktmo", columns="year", values="indicator_value", aggfunc="first").dropna()
    tot = tot[tot[2023] > 0]
    g = tot[2024] / tot[2023] - 1.0
    out = {}
    for t in story_tids:
        o8 = str(dic.loc[t, "oktmo"]).replace("-", "")[:8]
        if o8 not in g.index:
            out[int(t)] = None
            continue
        reg = g[g.index.str[:2] == o8[:2]]
        sec = d[(d["oktmo"] == o8) & ~is_tot[d.index]].pivot_table(index="okved2", columns="year", values="indicator_value", aggfunc="first")
        sec = sec[sec[2023] >= 800].dropna()
        sec["d"] = sec[2024] - sec[2023]
        top = pd.concat([sec.nsmallest(2, "d"), sec.nlargest(2, "d")]).drop_duplicates()
        out[int(t)] = {
            "oktmo8": o8, "workers_2023": float(tot.loc[o8, 2023]), "workers_2024": float(tot.loc[o8, 2024]), "growth": round(float(g.loc[o8]), 4),
            "growth_pct_national": round(pct_rank(g.to_numpy(), float(g.loc[o8])), 1), "n_national": int(len(g)),
            "growth_pct_region": round(pct_rank(reg.to_numpy(), float(g.loc[o8])), 1), "n_region": int(len(reg)),
            "median_growth_national": round(float(g.median()), 4),
            "largest_section_changes": [{"section": str(i), "d_workers": float(r["d"]), "growth": round(float(r[2024] / r[2023] - 1), 4)} for i, r in top.iterrows()],
            "definition": "организации без субъектов малого предпринимательства, январь–декабрь; не занятость всех жителей",
        }
    return out


def _identity_stats(a: pd.DataFrame):
    a = a.sort_values(["territory_id", "month"]).copy()
    a["ident"] = a["identity_id"].fillna("").astype(str)
    a["yr"] = a["month"].str[:4]
    rows = {}
    for tid, g in a.groupby("territory_id"):
        seq = [x for x in g["ident"] if x]
        sw = int(sum(1 for i in range(1, len(seq)) if seq[i] != seq[i - 1]))
        m = {}
        for yr, gg in g.groupby("yr"):
            vals = [x for x in gg["ident"] if x]
            m[yr] = max(set(vals), key=vals.count) if vals else None
        rows[int(tid)] = {"switches": sw, "ambiguous_months": int((g["ident"] == "").sum()), "mode_2023": m.get("2023"), "mode_2024": m.get("2024"),
                          "changed": bool(m.get("2023") and m.get("2024") and m["2023"] != m["2024"]),
                          "dec_2024_ambiguous": bool(g.loc[g["month"] == "2024-12", "ident"].iloc[0] == ""),
                          "sequence": "".join((x[-1] if x else "-") for x in g["ident"])}
    return rows


def archive_block(a6dir: str, story_tids):
    """Собственный результат метода идентичностей M2 (архив A6_v2): сквозные ID по месяцам, смены, неоднозначные месяцы, 5 зёрен."""
    base = _identity_stats(pd.read_parquet(Path(a6dir) / "assignments.parquet"))
    sw_all = np.array([v["switches"] for v in base.values()], float)
    out = {"population": {"n_mo": len(base), "changed_modal_identity_base": int(sum(v["changed"] for v in base.values())),
                          "switches_median": float(np.median(sw_all)), "switches_p95": float(np.percentile(sw_all, 95))}, "by_mo": {}, "seeds": {}}
    seeds = sorted((Path(a6dir) / "robustness").glob("seed-*/assignments.parquet"))
    seed_stats = {sd.parent.name: _identity_stats(pd.read_parquet(sd)) for sd in seeds}
    out["population"]["changed_modal_identity_by_seed"] = {k: int(sum(v["changed"] for v in st.values())) for k, st in seed_stats.items()}
    for t in story_tids:
        b = base[int(t)]
        out["by_mo"][int(t)] = {**b, "switches_pct_among_mo": round(pct_rank(sw_all, float(b["switches"])), 1),
                                "changed_in_n_seeds": int(sum(st[int(t)]["changed"] for st in seed_stats.values())), "n_seeds": len(seed_stats),
                                "dec_2024_ambiguous_in_n_seeds": int(sum(st[int(t)]["dec_2024_ambiguous"] for st in seed_stats.values()))}
    return out


def budget_block(pilot_path: str, supp_path: str):
    """Первичные наблюдения оператора (Mac): расходы, трансферты, доли функциональных разделов; числа пересчитываются здесь."""
    o = pd.read_parquet(pilot_path)
    res = {}
    for tid, g in o.groupby("territory_id"):
        p = g.pivot_table(index="metric", columns="year", values="executed_kopecks", aggfunc="first") / 100.0
        r = {"expense_rub": {str(y): (None if pd.isna(p.loc["expense", y]) else float(p.loc["expense", y])) for y in p.columns} if "expense" in p.index else None}
        if "expense" in p.index and 2023 in p.columns and 2024 in p.columns and pd.notna(p.loc["expense", 2024]):
            r["expense_change"] = round(float(p.loc["expense", 2024] / p.loc["expense", 2023] - 1), 4)
            for m in ("revenue", "grants", "tax_nontax"):
                if m in p.index and pd.notna(p.loc[m, 2024]):
                    r[f"{m}_change"] = round(float(p.loc[m, 2024] / p.loc[m, 2023] - 1), 4)
            funcs = [m for m in p.index if m.startswith("function_")]
            if funcs:
                r["function_share"] = {m: {"2023": round(float(p.loc[m, 2023] / p.loc["expense", 2023]), 4), "2024": round(float(p.loc[m, 2024] / p.loc["expense", 2024]), 4),
                                           "change": round(float(p.loc[m, 2024] / p.loc[m, 2023] - 1), 4) if p.loc[m, 2023] else None} for m in funcs}
        r["note"] = "2024 отсутствует" if r.get("expense_change") is None else ""
        res[int(tid)] = r
    s = pd.read_parquet(supp_path)
    b = s[(s["territory_id"] == 1668) & (s["measure"] == "executed")].pivot_table(index="metric", columns="year", values="value_kopecks", aggfunc="first") / 100.0
    res[1668] = {"period": "первое полугодие (H1), не год", "expense_rub_h1": {"2023": float(b.loc["expense", 2023]), "2024": float(b.loc["expense", 2024])},
                 "expense_change": round(float(b.loc["expense", 2024] / b.loc["expense", 2023] - 1), 4),
                 "function_share": {m: {"2023": round(float(b.loc[m, 2023] / b.loc["expense", 2023]), 4), "2024": round(float(b.loc[m, 2024] / b.loc["expense", 2024]), 4),
                                        "change": round(float(b.loc[m, 2024] / b.loc[m, 2023] - 1), 4)} for m in b.index if m.startswith("function_")}}
    return res


# ───────────────────────────── основной расчёт ─────────────────────────────
def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--panel", default=str(ATLAS / "data" / "panel_v1.parquet"))
    ap.add_argument("--data-sense-dir", default=os.environ.get("SBERINDEX_DATA_SENSE_DIR"))
    ap.add_argument("--employment", default=os.environ.get("SBERINDEX_TOCHNO_Y48423005"),
                    help="data_Y48423005_112_v20250918.parquet (Tochno/БДМО, занятость организаций без малого бизнеса)")
    ap.add_argument("--a6v2-dir", default=os.environ.get("SBERINDEX_A6V2_DIR"),
                    help="каталог архивного прогона A6_v2 (assignments.parquet и robustness/seed-*/assignments.parquet)")
    ap.add_argument("--budget-pilot", default=str(HERE / "inputs_from_mac" / "budget_pilot_observations.parquet"))
    ap.add_argument("--budget-supplement", default=str(HERE / "inputs_from_mac" / "budget_supplement_observations.parquet"))
    ap.add_argument("--outdir", default=str(HERE))
    a = ap.parse_args(argv)
    out = Path(a.outdir)
    panel = pd.read_parquet(a.panel)
    tids, months, S, audit = a6.build_monthly_shares(panel)
    idx = {int(t): i for i, t in enumerate(tids)}
    missing = [t for t in CITIES if t not in idx]
    if missing:
        raise SystemExit(f"города вне маски панели: {missing}")
    p = panel.copy()
    p["tid"] = p["territory_id"].astype(int)
    p["month"] = pd.to_datetime(p["date"]).dt.strftime("%Y-%m")
    all_cat = p[p["category"] == a6.TOTAL_CAT][["tid", "month", "value"]]

    Zs = {n: normalise(S, months, n) for n in NORMS}
    d_abs, d_rel, dshare, L23, L24, yoy, rel = direct_profile(S, Zs["z2023"], months, tids, all_cat)

    # τ0 — 10-й процентиль запаса по всем МО-месяцам 2023 для K = 5 k-means на z2023 (объявлено заранее; затем множители)
    configs, rows, flags = [], [], {}
    taus = {}
    for norm in NORMS:
        Z = Zs[norm]
        for k in KS:
            for fam, seeds in (("kmeans", SEEDS), ("ward", (0,))):
                for s in seeds:
                    lab, mar = run_config(Z, k, fam, s)
                    key = f"{norm}|{fam}|K{k}|s{s}"
                    i23 = [i for i, m in enumerate(months) if m.startswith("2023")]
                    tau0 = float(np.percentile(mar[i23], 10))
                    taus[key] = tau0
                    rec = summarise_config(lab, mar, k, months, tau0)
                    flags[key] = rec["changed"]
                    for t in CITIES:
                        j = idx[t]
                        rows.append({"config": key, "norm": norm, "family": fam, "K": k, "seed": s, "tid": t, "city": CITIES[t],
                                     "g23": int(rec["g23"][j]), "g24": int(rec["g24"][j]), "tie": bool(rec["tie"][j]),
                                     "changed": bool(rec["changed"][j]), "switches": int(rec["switches"][j]),
                                     "mean_margin_24": round(float(rec["mean_margin_24"][j]), 4),
                                     **{k2: round(float(rec[k2][j]), 4) for k2 in rec if k2.startswith("amb_frac")}})
                    configs.append(key)
    cfg_df = pd.DataFrame(rows)
    cfg_df.to_csv(out / "robustness_by_config.csv", index=False)

    F = np.stack([flags[c] for c in configs], axis=0)  # (C, N)
    n_changed = F.sum(axis=0)
    base_rate = F.mean(axis=1)
    jac = np.zeros((len(configs), len(configs)))
    for i in range(len(configs)):
        for j in range(len(configs)):
            u = (F[i] | F[j]).sum()
            jac[i, j] = (F[i] & F[j]).sum() / u if u else np.nan
    iu = np.triu_indices(len(configs), 1)
    agreement = {
        "n_configs": len(configs),
        "mean_base_rate_changed": round(float(base_rate.mean()), 4),
        "base_rate_min_max": [round(float(base_rate.min()), 4), round(float(base_rate.max()), 4)],
        "pairwise_jaccard_changed_mean": round(float(np.nanmean(jac[iu])), 4),
        "pairwise_jaccard_changed_quartiles": [round(float(q), 4) for q in np.nanpercentile(jac[iu], [25, 50, 75])],
        "mo_flagged_by_all_configs": int((n_changed == len(configs)).sum()),
        "mo_flagged_by_none": int((n_changed == 0).sum()),
        "mo_flagged_by_some_not_all": int(((n_changed > 0) & (n_changed < len(configs))).sum()),
        "n_mo": int(len(tids)),
        "by_K_mean_base_rate": {str(k): round(float(np.mean([base_rate[i] for i, c in enumerate(configs) if f"|K{k}|" in c])), 4) for k in KS},
        "tau0_by_config_range": [round(min(taus.values()), 4), round(max(taus.values()), 4)],
    }

    top = {}
    if a.data_sense_dir:
        dd = pd.read_parquet(Path(a.data_sense_dir) / "municipal_dictionary.parquet").drop_duplicates("territory_id").set_index("territory_id")
        for key, arr in (("abs", d_abs), ("relative_to_monthly_median", d_rel)):
            order = np.argsort(-arr)[:10]
            top[key] = [{"tid": int(tids[i]), "name": str(dd.loc[tids[i], "name_short"]), "region": str(dd.loc[tids[i], "region_name"]),
                         "distance": round(float(arr[i]), 3)} for i in order]
        agreement["top10_profile_change_post_hoc_not_a_selection"] = top
        agreement["profile_distance_quantiles_abs"] = {q: round(float(np.percentile(d_abs, q)), 3) for q in (50, 90, 95, 99)}
        agreement["profile_distance_quantiles_relative"] = {q: round(float(np.percentile(d_rel, q)), 3) for q in (50, 90, 95, 99)}

    # контекст
    ctx = None
    if a.data_sense_dir:
        pop, mig, sal = context(Path(a.data_sense_dir), tids)
        ctx = (pop, mig, sal)

    dic = None
    if a.data_sense_dir:
        dic = pd.read_parquet(Path(a.data_sense_dir) / "municipal_dictionary.parquet").drop_duplicates("territory_id").set_index("territory_id")
    region_of = (dic.loc[tids, "region_code"].to_numpy() if dic is not None else None)

    extra = {"employment": None, "archive": None}
    if a.employment and dic is not None and Path(a.employment).exists():
        extra["employment"] = employment_block(a.employment, dic, list(CITIES))
    if a.a6v2_dir and (Path(a.a6v2_dir) / "assignments.parquet").exists():
        extra["archive"] = archive_block(a.a6v2_dir, list(CITIES))
    budgets = budget_block(a.budget_pilot, a.budget_supplement) if Path(a.budget_pilot).exists() and Path(a.budget_supplement).exists() else None
    if extra["archive"] is not None:
        agreement["archive_A6_v2"] = extra["archive"]["population"]

    stories = {}
    for t, name in CITIES.items():
        j = idx[t]
        c = cfg_df[cfg_df.tid == t]
        s = {
            "tid": t, "name": name, "story": t in STORY_IDS,
            "profile_distance_z2023": {"value": round(float(d_abs[j]), 3), "pct_among_mo": round(pct_rank(d_abs, d_abs[j]), 1)},
            "profile_distance_relative_to_monthly_median": {"value": round(float(d_rel[j]), 3), "pct_among_mo": round(pct_rank(d_rel, d_rel[j]), 1)},
            "share_shift_pp_2024_minus_2023": {cat: {"pp": round(float(dshare[j, i]), 2), "pct_among_mo": round(pct_rank(dshare[:, i], dshare[j, i]), 1),
                                                    "robust_z": round(robust_z(dshare[:, i], dshare[j, i]), 2)} for i, cat in enumerate(a6.SHARE_CATS)},
            "total_consumption": {"mean_2023": round(float(L23[j]), 0), "mean_2024": round(float(L24[j]), 0), "yoy": round(float(yoy[j]), 4),
                                  "yoy_pct_among_mo": round(pct_rank(yoy, yoy[j]), 1), "yoy_median_mo": round(float(np.nanmedian(yoy)), 4)},
            "april_2024_relative_z": {cat: round(float(rel[j, months.index('2024-04'), i]), 2) for i, cat in enumerate(a6.SHARE_CATS)},
            "april_2023_relative_z": {cat: round(float(rel[j, months.index('2023-04'), i]), 2) for i, cat in enumerate(a6.SHARE_CATS)},
            "partition_robustness": {
                "configs": len(configs), "changed_in_n_configs": int(n_changed[j]),
                "changed_share": round(float(n_changed[j]) / len(configs), 3),
                "by_K": {str(k): int(sum(F[i, j] for i, cc in enumerate(configs) if f'|K{k}|' in cc)) for k in KS},
                "of_per_K": {str(k): int(sum(1 for cc in configs if f'|K{k}|' in cc)) for k in KS},
                "by_family": {fam: int(sum(F[i, j] for i, cc in enumerate(configs) if f'|{fam}|' in cc)) for fam in ("kmeans", "ward")},
                "ties": int(c["tie"].sum()),
                "median_switches_24m": float(c["switches"].median()),
                "ambiguous_fraction_2024_median_over_configs": {f: round(float(c[f"amb_frac_24_x{f}"].median()), 3) for f in MARGIN_FACTORS},
                "rank_of_n_changed_among_mo": round(pct_rank(n_changed.astype(float), float(n_changed[j])), 1),
            },
        }
        s["profile_distance_pct_by_normalisation"] = {}
        for nrm, Zn in Zs.items():
            i23_ = [i for i, m in enumerate(months) if m.startswith("2023")]
            i24_ = [i for i, m in enumerate(months) if m.startswith("2024")]
            da = np.linalg.norm(Zn[:, i24_].mean(1) - Zn[:, i23_].mean(1), axis=1)
            rl = Zn - np.median(Zn, axis=0, keepdims=True)
            dr = np.linalg.norm(rl[:, i24_].mean(1) - rl[:, i23_].mean(1), axis=1)
            s["profile_distance_pct_by_normalisation"][nrm] = {"abs": round(pct_rank(da, da[j]), 1), "relative": round(pct_rank(dr, dr[j]), 1)}
        if region_of is not None:
            peers = np.flatnonzero(region_of == region_of[j])
            s["region_peers"] = {
                "region": str(dic.loc[t, "region_name"]), "n_mo_in_region": int(len(peers)),
                "yoy_region_median": round(float(np.nanmedian(yoy[peers])), 4),
                "yoy_pct_within_region": round(pct_rank(yoy[peers], yoy[j]), 1),
                "profile_distance_abs_pct_within_region": round(pct_rank(d_abs[peers], d_abs[j]), 1),
                "profile_distance_rel_pct_within_region": round(pct_rank(d_rel[peers], d_rel[j]), 1),
            }
        if ctx is not None:
            pop, mig, sal = ctx
            pg = (pop[2024] / pop[2023] - 1.0)
            s["population"] = {"2023": float(pop.loc[t, 2023]), "2024": float(pop.loc[t, 2024]), "growth": round(float(pg.loc[t]), 4),
                               "growth_pct_among_mo": round(pct_rank(pg.reindex(tids).to_numpy(), float(pg.loc[t])), 1)}
            mv = mig.loc[t, 2023] if t in mig.index else np.nan
            s["migration_2023_net_total"] = None if not np.isfinite(mv) else {
                "net": float(mv), "per_1000_pop": round(float(mv) / float(pop.loc[t, 2023]) * 1000, 2),
                "per_1000_pct_among_mo": round(pct_rank((mig[2023].reindex(tids) / pop[2023].reindex(tids) * 1000).to_numpy(),
                                                        float(mv) / float(pop.loc[t, 2023]) * 1000), 1)}
            sec = {}
            for letter in SECTORS_OF_INTEREST:
                if (letter, 2023) in sal.columns and (letter, 2024) in sal.columns and t in sal.index:
                    g = (sal[(letter, 2024)] / sal[(letter, 2023)] - 1.0)
                    v = g.loc[t]
                    if np.isfinite(v):
                        sec[letter] = {"2023": float(sal.loc[t, (letter, 2023)]), "2024": float(sal.loc[t, (letter, 2024)]),
                                       "growth": round(float(v), 4), "growth_pct_among_mo": round(pct_rank(g.reindex(tids).to_numpy(), float(v)), 1)}
            s["salary_jan_dec"] = sec
        if extra["employment"] is not None:
            s["employment_organisations_excl_small_business"] = extra["employment"].get(t)
        if extra["archive"] is not None:
            s["a6_v2_archive_identity"] = extra["archive"]["by_mo"].get(t)
        if budgets is not None:
            s["budget_recomputed_from_primary_observations"] = budgets.get(t)
        stories[name] = s

    (out / "story_inputs.json").write_text(json.dumps(stories, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "population_agreement.json").write_text(json.dumps(agreement, ensure_ascii=False, indent=1), encoding="utf-8")
    prov = {
        "run_id": "A7-stories-20261004", "status": "EXPLORATORY_NOT_GATE_PASS",
        "panel_sha256": hashlib.sha256(Path(a.panel).read_bytes()).hexdigest(),
        "code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "a6_temporal_sha256": hashlib.sha256((ATLAS / "src" / "a6_temporal.py").read_bytes()).hexdigest(),
        "n_mo": int(len(tids)), "months": [months[0], months[-1]], "configs": configs,
        "inputs_from_mac": {
            "employment_parquet_sha256": (hashlib.sha256(Path(a.employment).read_bytes()).hexdigest() if a.employment and Path(a.employment).exists() else None),
            "a6_v2_assignments_sha256": (hashlib.sha256((Path(a.a6v2_dir) / "assignments.parquet").read_bytes()).hexdigest() if a.a6v2_dir and (Path(a.a6v2_dir) / "assignments.parquet").exists() else None),
            "budget_pilot_observations_sha256": hashlib.sha256(Path(a.budget_pilot).read_bytes()).hexdigest() if Path(a.budget_pilot).exists() else None,
            "budget_supplement_observations_sha256": hashlib.sha256(Path(a.budget_supplement).read_bytes()).hexdigest() if Path(a.budget_supplement).exists() else None,
            "mac_working_copies": ["/Users/sergey/projects/sberindex-research-bdmo (занятость, A6_v2)", "/Users/sergey/projects/sberindex-research-accelerated-public-20261003 (бюджетные наблюдения)"]},
        "selection_rule": "города фиксированной выборки бюджетного пилота; истории — с ≥ 1 парой бюджетных наблюдений (Орск, Курган, Ишим, Бузулук, Тюмень); Шадринск — контрольный без бюджетов",
        "not_available": ["миграция 2024 (проверенное ядро БДПМО 8112023 — только 2023)", "годовые бюджеты Бузулука/Тюмени 2024 и Шадринска (не получены оператором)"],
        "margin_note": "запас до второго центра — показатель этого прогона, не candidate_margin идентичностей A6",
        "tau0": "10-й процентиль запаса по МО-месяцам 2023 для каждой конфигурации, затем множители 0,75/1/1,25",
    }
    (out / "provenance.json").write_text(json.dumps(prov, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(agreement, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
