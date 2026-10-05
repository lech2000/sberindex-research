"""A8 — внешняя проверка замороженного разбиения Атласа на зарплатах и занятости 2025 года (05.10.2026). Протокол: PROTOCOL.md.

Запуск (один раз; правки после просмотра результатов — только исправление ошибок с повтором всего прогона):
  python run_a8.py --data-sense-dir <sberindex-data-sense-2025> --wages <data_Y48423007_112_v20260928.parquet> \
                   --employment <data_Y48423005_112_v20260928.parquet> --a6v2 <A6_v2/assignments.parquet> [--outdir .]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ATLAS = HERE.parents[1]
sys.path.insert(0, str(ATLAS / "src"))

B_BOOT, B_PERM = 1000, 2000
SEED = 20261005
CV_SEEDS = tuple(range(20261005, 20261010))
INDICATORS = {"wage": "Y48423007", "emp": "Y48423005"}
MAIN_TESTS = (("wage", "S1"), ("wage", "S3"), ("emp", "S1"), ("emp", "S3"))


# ───────────────────────────── статистика ─────────────────────────────
def onehot(codes: np.ndarray) -> np.ndarray:
    u, inv = np.unique(codes, return_inverse=True)
    M = np.zeros((len(codes), len(u)))
    M[np.arange(len(codes)), inv] = 1.0
    return M


def lstsq(X: np.ndarray, y: np.ndarray) -> np.ndarray:
    return np.linalg.lstsq(X, y, rcond=None)[0]


def adj_r2(y: np.ndarray, X: np.ndarray) -> float:
    n = len(y)
    b = lstsq(X, y)
    rss = float(((y - X @ b) ** 2).sum())
    tss = float(((y - y.mean()) ** 2).sum())
    rank = int(np.linalg.matrix_rank(X))
    return 1.0 - (rss / (n - rank)) / (tss / (n - 1))


def coef_g(y: np.ndarray, X0: np.ndarray, g: np.ndarray) -> float:
    return float(lstsq(np.column_stack([X0, g]), y)[-1])


def column_basis(X: np.ndarray) -> np.ndarray:
    u, s, _ = np.linalg.svd(X, full_matrices=False)
    return u[:, s > s.max() * 1e-10]


def perm_pvalue(y: np.ndarray, X0: np.ndarray, g: np.ndarray, regions: np.ndarray, B: int, seed: int) -> tuple[float, float]:
    """Перестановка G внутри региона. Коэффициент при G через проекцию на дополнение к столбцам X0 (теорема Фриша–Во)."""
    U = column_basis(X0)
    y_t = y - U @ (U.T @ y)

    def beta(gv):
        g_t = gv - U @ (U.T @ gv)
        den = float(g_t @ g_t)
        return float(g_t @ y_t) / den if den > 0 else 0.0

    obs = beta(g)
    rng = np.random.default_rng(seed)
    idx = [np.flatnonzero(regions == r) for r in np.unique(regions)]
    ge = 0
    for _ in range(B):
        gp = g.copy()
        for ix in idx:
            if len(ix) > 1:
                gp[ix] = g[rng.permutation(ix)]
        if abs(beta(gp)) >= abs(obs) - 1e-12:
            ge += 1
    return obs, (1 + ge) / (B + 1)


def cluster_bootstrap_ci(y: np.ndarray, Xc: np.ndarray, g: np.ndarray, regions: np.ndarray, B: int, seed: int) -> tuple[float, float]:
    """Бутстрэп по регионам: регионы с возвращением, повторы одного региона получают отдельные фиксированные эффекты."""
    rng = np.random.default_rng(seed)
    uniq = np.unique(regions)
    rows = {r: np.flatnonzero(regions == r) for r in uniq}
    out = []
    for _ in range(B):
        pick = rng.choice(uniq, size=len(uniq), replace=True)
        ix = np.concatenate([rows[r] for r in pick])
        rid = np.concatenate([np.full(len(rows[r]), k) for k, r in enumerate(pick)])
        X = np.column_stack([onehot(rid), Xc[ix], g[ix]])
        out.append(float(lstsq(X, y[ix])[-1]))
    lo, hi = np.percentile(out, [2.5, 97.5])
    return float(lo), float(hi)


def cv_mse_reduction(y: np.ndarray, X0: np.ndarray, g: np.ndarray, folds: int = 10, seeds=CV_SEEDS) -> dict:
    """Снижение MSE (1 − MSE_с_G / MSE_без_G) при случайной k-кратной проверке, повторённой по зёрнам."""
    X1 = np.column_stack([X0, g])
    reds = []
    for s in seeds:
        rng = np.random.default_rng(s)
        order = rng.permutation(len(y))
        parts = np.array_split(order, folds)
        e0 = e1 = 0.0
        for k in range(folds):
            te = parts[k]
            tr = np.concatenate([parts[j] for j in range(folds) if j != k])
            e0 += float(((y[te] - X0[te] @ lstsq(X0[tr], y[tr])) ** 2).sum())
            e1 += float(((y[te] - X1[te] @ lstsq(X1[tr], y[tr])) ** 2).sum())
        reds.append(1.0 - e1 / e0)
    return {"mean": float(np.mean(reds)), "min": float(np.min(reds)), "max": float(np.max(reds))}


def holm(pvals: dict[str, float]) -> dict[str, float]:
    items = sorted(pvals.items(), key=lambda kv: kv[1])
    m = len(items)
    adj, run = {}, 0.0
    for rank, (k, p) in enumerate(items):
        run = max(run, min(1.0, (m - rank) * p))
        adj[k] = run
    return adj


def analyse(y: np.ndarray, Xcont: np.ndarray, regions: np.ndarray, g: np.ndarray, seed: int = SEED, b_boot: int = B_BOOT, b_perm: int = B_PERM) -> dict:
    """Одна спецификация: коэффициент при G, интервал по регионам, перестановочное p, ΔR² и снижение MSE в перекрёстной проверке."""
    FE = onehot(regions)
    X0 = np.column_stack([FE, Xcont])
    beta, p_perm = perm_pvalue(y, X0, g, regions, b_perm, seed)
    lo, hi = cluster_bootstrap_ci(y, Xcont, g, regions, b_boot, seed)
    return {"n": int(len(y)), "n_group1": int(g.sum()), "n_regions": int(len(np.unique(regions))), "coef_G": beta, "ci95_region_bootstrap": [lo, hi],
            "p_permutation_within_region": p_perm, "delta_adj_r2": adj_r2(y, np.column_stack([X0, g])) - adj_r2(y, X0),
            "cv_mse_reduction": cv_mse_reduction(y, X0, g)}


# ───────────────────────────── данные ─────────────────────────────
def tochno_table(path: str) -> tuple[pd.DataFrame, pd.Series]:
    e = pd.read_parquet(path, columns=["okved2", "oktmo", "oktmo_history", "mun_level", "year", "indicator_value", "indicator_period"])
    e["oktmo"] = e["oktmo"].astype(str)
    d = e[e["okved2"].str.startswith("Всего", na=False) & (e["indicator_period"] == "Январь-декабрь") & e["mun_level"].str.contains("верхнего", na=False)]
    t = d.pivot_table(index="oktmo", columns="year", values="indicator_value", aggfunc="first")
    hist = d[d["year"] == 2025].drop_duplicates("oktmo").set_index("oktmo")["oktmo_history"].astype(str)
    return t, hist


def own_partition_dec2024(panel_path: str) -> pd.Series:
    """Вторичное разбиение (протокол): z2023, k-means K = 2, декабрь 2024, зерно 20261004. Возвращает метку 0/1 по territory_id (ориентацию задаёт вызывающий)."""
    import a6_temporal as a6
    from sklearn.cluster import KMeans

    tids, months, S, _ = a6.build_monthly_shares(pd.read_parquet(panel_path))
    Z, _ = a6.standardize_frozen(S, months)
    lab = KMeans(n_clusters=2, n_init=10, random_state=20261004).fit_predict(Z[:, months.index("2024-12"), :])
    return pd.Series(lab, index=tids)


def build_sample(ds_dir: Path, wages: str, employment: str, a6v2: str, panel_path: str, own_label: pd.Series | None = None):
    dic = pd.read_parquet(ds_dir / "municipal_dictionary.parquet").drop_duplicates("territory_id").set_index("territory_id")
    tids = np.array(sorted(pd.read_parquet(panel_path, columns=["territory_id"])["territory_id"].unique()))
    base = dic.loc[tids, ["region_code", "lat", "lon", "type", "oktmo", "year_to"]].copy()
    base["o8"] = base["oktmo"].astype(str).str.replace("-", "").str[:8]
    pop = pd.read_parquet(ds_dir / "2_bdmo_population.parquet")
    pop = pop[(pop["age"].astype(str) == "Всего") & (pop["year"] == 2024)].groupby("territory_id")["value"].sum()
    ma = pd.read_parquet(ds_dir / "1_market_access.parquet").drop_duplicates("territory_id").set_index("territory_id")["market_access"]
    base["lnpop"] = np.log(pop.reindex(base.index))
    base["lnma"] = np.log(ma.reindex(base.index))
    a = pd.read_parquet(a6v2)
    dec = a[a["month"] == "2024-12"].drop_duplicates("territory_id").set_index("territory_id")["label"]
    base["G"] = (dec.reindex(base.index) == 1).astype(float)
    base["G_known"] = dec.reindex(base.index).notna()
    if own_label is not None:
        lab = own_label.reindex(base.index)
        big = lab[base["lnpop"] >= base["lnpop"].median()].mean() > lab[base["lnpop"] < base["lnpop"].median()].mean()  # G=1 — группа с большим числом жителей
        base["G_own"] = (lab == (1 if big else 0)).astype(float)
    out = {"base": base, "exclusions": {}}
    for name, path in (("wage", wages), ("emp", employment)):
        t, hist = tochno_table(path)
        d = base.copy()
        for y in (2023, 2024, 2025):
            d[f"v{y}"] = d["o8"].map(t[y]) if y in t.columns else np.nan
        d["hist"] = d["o8"].map(hist)
        ex = {"year_to_not_current": int((d["year_to"] != 9999).sum())}
        keep = (d["year_to"] == 9999)
        ex["missing_or_nonpositive_values_2023_2025"] = int((keep & ~((d[["v2023", "v2024", "v2025"]] > 0).all(axis=1))).sum())
        keep &= (d[["v2023", "v2024", "v2025"]] > 0).all(axis=1)
        merged = d["hist"].fillna("").str.contains("Объединение|Присоединение")
        ex["boundary_change_merge_or_join"] = int((keep & merged).sum())
        keep &= ~merged
        ex["no_population_or_market_access_or_label"] = int((keep & ~(d["lnpop"].notna() & d["lnma"].notna() & d["G_known"])).sum())
        keep &= d["lnpop"].notna() & d["lnma"].notna() & d["G_known"]
        dup = d.loc[keep, "o8"].duplicated(keep=False)
        ex["duplicate_oktmo_key"] = int(dup.sum())
        keep &= ~d["o8"].duplicated(keep=False)
        out[name] = d[keep].copy()
        out["exclusions"][name] = {**ex, "n_final": int(keep.sum())}
    return out


def controls(d: pd.DataFrame) -> np.ndarray:
    lat, lon = d["lat"].to_numpy(float), d["lon"].to_numpy(float)
    lat, lon = (lat - lat.mean()) / lat.std(), (lon - lon.mean()) / lon.std()
    types = pd.get_dummies(d["type"].astype(str), drop_first=True).to_numpy(float)
    return np.column_stack([np.ones(len(d)), lat, lon, lat ** 2, lon ** 2, lat * lon, d["lnpop"].to_numpy(float), d["lnma"].to_numpy(float), types])


def specs(d: pd.DataFrame, year: int) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """(y, Xcont) для S1/S2/S3 для исходов года `year` (2025 — основной, 2024 — контроль метода)."""
    cur, lag = np.log(d[f"v{year}"].to_numpy(float)), np.log(d[f"v{year - 1}"].to_numpy(float))
    Xc = controls(d)
    return {"S1": (cur, Xc), "S2": (cur, np.column_stack([Xc, lag])), "S3": (cur - lag, Xc)}


def run(ds_dir, wages, employment, a6v2, panel_path, outdir):
    sample = build_sample(Path(ds_dir), wages, employment, a6v2, panel_path, own_label=own_partition_dec2024(panel_path))
    res = {"sample_exclusions": sample["exclusions"], "primary": {}, "diagnostic_S2": {}, "replication_2024": {}, "secondary_partition_own_kmeans_dec2024": {}, "descriptive": {}}
    for name in ("wage", "emp"):
        d = sample[name]
        g, reg = d["G"].to_numpy(float), d["region_code"].astype(str).to_numpy()
        res["descriptive"][name] = {
            "n": int(len(d)), "n_group1": int(g.sum()), "mean_ln_pop_by_group": {"0": float(d.loc[g == 0, "lnpop"].mean()), "1": float(d.loc[g == 1, "lnpop"].mean())},
            "share_urban_okrug_by_group": {"0": float((d.loc[g == 0, "type"] == "городской округ").mean()), "1": float((d.loc[g == 1, "type"] == "городской округ").mean())},
            "mean_ln_value_2025_by_group": {"0": float(np.log(d.loc[g == 0, "v2025"]).mean()), "1": float(np.log(d.loc[g == 1, "v2025"]).mean())},
            "mean_growth_2025_by_group": {"0": float(np.log(d.loc[g == 0, "v2025"] / d.loc[g == 0, "v2024"]).mean()), "1": float(np.log(d.loc[g == 1, "v2025"] / d.loc[g == 1, "v2024"]).mean())}}
        g_own = d["G_own"].to_numpy(float)
        res["descriptive"][name]["secondary_partition_n_group1"] = int(g_own.sum())
        res["descriptive"][name]["agreement_primary_vs_secondary_partition"] = float((g == g_own).mean())
        for sp, (y, Xc) in specs(d, 2025).items():
            res["secondary_partition_own_kmeans_dec2024"].setdefault(name, {})[sp] = analyse(y, Xc, reg, g_own)
        for year, key in ((2025, "main"), (2024, "replication")):
            for sp, (y, Xc) in specs(d, year).items():
                r = analyse(y, Xc, reg, g)
                if key == "main":
                    (res["diagnostic_S2"] if sp == "S2" else res["primary"]).setdefault(name, {})[sp] = r
                else:
                    res["replication_2024"].setdefault(name, {})[sp] = r
    raw_p = {f"{n}_{s}": res["primary"][n][s]["p_permutation_within_region"] for n, s in MAIN_TESTS}
    adj = holm(raw_p)
    for n, s in MAIN_TESTS:
        r = res["primary"][n][s]
        r["p_holm_4_tests"] = adj[f"{n}_{s}"]
        lo, hi = r["ci95_region_bootstrap"]
        r["criteria"] = {"ci_excludes_zero": bool(lo > 0 or hi < 0), "holm_p_below_0_05": bool(adj[f"{n}_{s}"] < 0.05), "cv_mse_reduction_positive": bool(r["cv_mse_reduction"]["mean"] > 0)}
        r["positive_result"] = all(r["criteria"].values())
    Path(outdir, "results.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return res


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-sense-dir", required=True)
    ap.add_argument("--wages", required=True)
    ap.add_argument("--employment", required=True)
    ap.add_argument("--a6v2", required=True)
    ap.add_argument("--panel", default=str(ATLAS / "data" / "panel_v1.parquet"))
    ap.add_argument("--outdir", default=str(HERE))
    a = ap.parse_args(argv)
    prov = {"run_id": "A8-wages2025-validation-20261005", "status": "EXPLORATORY_NOT_GATE_PASS", "protocol_sha256": hashlib.sha256((HERE / "PROTOCOL.md").read_bytes()).hexdigest(),
            "code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "inputs_sha256": {k: hashlib.sha256(Path(v).read_bytes()).hexdigest() for k, v in (("wages", a.wages), ("employment", a.employment), ("a6v2_assignments", a.a6v2), ("panel_v1", a.panel))},
            "tochno_release": "v20260928 (паспорт: data/tochno-bdmo-v20260928-intake.json)", "seeds": {"main": SEED, "cv": list(CV_SEEDS)}, "B_bootstrap": B_BOOT, "B_permutation": B_PERM}
    Path(a.outdir, "provenance.json").write_text(json.dumps(prov, ensure_ascii=False, indent=1), encoding="utf-8")
    res = run(a.data_sense_dir, a.wages, a.employment, a.a6v2, a.panel, a.outdir)
    print(json.dumps({"sample": res["sample_exclusions"], "primary_positive": {f"{n}_{s}": res["primary"][n][s]["positive_result"] for n, s in MAIN_TESTS}}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
