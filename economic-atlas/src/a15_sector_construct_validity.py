#!/usr/bin/env python3
"""A15: frozen region-held-out sector check, plus internal IndustryMap context.

Read PROTOCOL.md before changing any outcome, mask, feature, or criterion.
IndustryMap-derived output must stay under the ignored output/ directory.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import Ridge
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler


ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / "economic-atlas/runs/A15_sector_construct_validity_20261008"
ASSIGNMENTS = ROOT / "economic-atlas/runs/A10_method_comparison_20261005/assignments_annual2023_kmeans_K5.parquet"
EMPLOYMENT = ROOT / "data/external/tochno_bdmo_20250918/data_Y48423005_112_v20250918.parquet"
NUMERIC = ["log_pop", "log_pop_sq", "lat", "lon", "lat_sq", "lon_sq", "lat_lon"]
BAD_INDUSTRY_CITY_IDS = {5: "Адыгейск", 10: "Алабазино", 1337: "рп Екатериновка", 1368: "рп Солнечный"}


def digest(path: Path) -> str:
    h = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def unique(frame: pd.DataFrame, columns: list[str], source: str) -> None:
    if frame.duplicated(columns).any():
        raise ValueError(f"duplicate {columns} in {source}")


def load_base(dictionary: Path, population: Path) -> tuple[pd.DataFrame, dict]:
    assignments = pd.read_parquet(ASSIGNMENTS, columns=["territory_id", "label"])
    unique(assignments, ["territory_id"], "assignments")
    if len(assignments) != 1896 or assignments.label.nunique() != 5:
        raise ValueError("frozen K5 assignments unexpectedly changed")

    d = pd.read_parquet(dictionary)
    d = d[pd.to_numeric(d.year_to, errors="coerce") == 9999].copy()
    d["oktmo8"] = d.oktmo.astype(str).str.replace(r"\D", "", regex=True).str[:8]
    d = d[d.oktmo8.str.fullmatch(r"\d{8}")].copy()
    duplicate_oktmo = set(d.loc[d.duplicated("oktmo8", keep=False), "oktmo8"])
    d = d[~d.oktmo8.isin(duplicate_oktmo)].copy()
    unique(d, ["territory_id"], "dictionary")

    p = pd.read_parquet(population, columns=["territory_id", "year", "period", "age", "gender", "value"])
    p = p[(p.year == 2023) & (p.period == "год") & (p.age == "Всего")
          & (p.gender.isin(["Мужчины", "Женщины"]))].copy()
    exact_population_duplicates = int(p.duplicated().sum())
    p = p.drop_duplicates().copy()
    unique(p, ["territory_id", "gender"], "population")
    p.value = pd.to_numeric(p.value, errors="coerce")
    p = p.pivot(index="territory_id", columns="gender", values="value")
    p["pop2023"] = p[["Мужчины", "Женщины"]].sum(axis=1, min_count=2)
    p = p[["pop2023"]].reset_index()

    base = assignments.merge(d[["territory_id", "oktmo8", "region_code", "type", "lat", "lon"]],
                             on="territory_id", how="left", validate="one_to_one")
    base = base.merge(p, on="territory_id", how="left", validate="one_to_one")
    mask = (base.oktmo8.notna() & base.region_code.notna() & base.type.notna()
            & np.isfinite(pd.to_numeric(base.lat, errors="coerce"))
            & np.isfinite(pd.to_numeric(base.lon, errors="coerce"))
            & np.isfinite(pd.to_numeric(base.pop2023, errors="coerce"))
            & (base.pop2023 > 0))
    counts = {"frozen_assignments": len(assignments), "base_eligible": int(mask.sum()),
              "base_excluded": int((~mask).sum()), "ambiguous_dictionary_oktmo8": len(duplicate_oktmo),
              "population_exact_duplicate_rows_removed": exact_population_duplicates}
    base = base[mask].copy()
    base["region"] = base.region_code.astype(str)
    base["label"] = base.label.astype(str)
    base["log_pop"] = np.log(base.pop2023.astype(float))
    base["log_pop_sq"] = base.log_pop**2
    base["lat_sq"] = base.lat.astype(float)**2
    base["lon_sq"] = base.lon.astype(float)**2
    base["lat_lon"] = base.lat.astype(float) * base.lon.astype(float)
    unique(base, ["oktmo8"], "base")
    return base, counts


def load_employment() -> pd.DataFrame:
    cols = ["oktmo", "year", "indicator_period", "mun_level", "okved2", "indicator_value", "oktmo_history"]
    e = pd.read_parquet(EMPLOYMENT, columns=cols)
    e = e[(e.year == 2024) & (e.indicator_period == "Январь-декабрь")
          & (e.mun_level == "Муниципальное образование верхнего уровня")].copy()
    bad_history = e.oktmo_history.fillna("").str.contains("Объединение|Присоединение", case=False, regex=True)
    e = e[~bad_history].copy()
    okved = e.okved2.fillna("")
    e["sector"] = np.select([okved.str.startswith("Всего по обследуемым"),
                              okved.str.startswith("Раздел G "),
                              okved.str.startswith("Раздел C ")],
                             ["total", "trade_G", "manufacturing_C"], default="")
    e = e[e.sector != ""].copy()
    e["oktmo8"] = e.oktmo.astype(str).str.replace(r"\D", "", regex=True).str[:8]
    unique(e, ["oktmo8", "sector"], "BDMO annual sectors")
    e.indicator_value = pd.to_numeric(e.indicator_value, errors="coerce")
    return e.pivot(index="oktmo8", columns="sector", values="indicator_value").reset_index()


def model(include_label: bool) -> Pipeline:
    categories = ["type", "label"] if include_label else ["type"]
    return Pipeline([
        ("features", ColumnTransformer([
            ("numeric", StandardScaler(), NUMERIC),
            ("categorical", OneHotEncoder(handle_unknown="ignore", sparse_output=False), categories),
        ])),
        ("ridge", Ridge(alpha=10)),
    ])


def region_cv(frame: pd.DataFrame, y: np.ndarray) -> tuple[dict, pd.DataFrame]:
    if len(frame) != len(y) or frame.region.nunique() < 5:
        raise ValueError("invalid region-held-out sample")
    X = frame[NUMERIC + ["type", "label"]].reset_index(drop=True)
    region = frame.region.reset_index(drop=True)
    y = np.asarray(y, dtype=float)
    if not np.isfinite(y).all():
        raise ValueError("non-finite outcome")
    base_pred = np.full(len(frame), np.nan)
    group_pred = np.full(len(frame), np.nan)
    folds = []
    for fold, (train, test) in enumerate(GroupKFold(n_splits=5).split(X, y, groups=region)):
        first, second = model(False), model(True)
        first.fit(X.iloc[train], y[train]); second.fit(X.iloc[train], y[train])
        base_pred[test] = first.predict(X.iloc[test])
        group_pred[test] = second.predict(X.iloc[test])
        base_mse = float(np.mean((y[test] - base_pred[test])**2))
        group_mse = float(np.mean((y[test] - group_pred[test])**2))
        folds.append({"fold": fold, "n": len(test), "regions": int(region.iloc[test].nunique()),
                      "base_mse": base_mse, "group_mse": group_mse,
                      "mse_reduction": 1 - group_mse / base_mse})
    if np.isnan(base_pred).any() or np.isnan(group_pred).any():
        raise AssertionError("missing OOF prediction")
    losses = pd.DataFrame({"region": region, "base_sq": (y - base_pred)**2,
                           "group_sq": (y - group_pred)**2})
    region_losses = losses.groupby("region", as_index=False)[["base_sq", "group_sq"]].sum()
    rng = np.random.default_rng(20261008)
    idx = rng.integers(0, len(region_losses), size=(2000, len(region_losses)))
    base_sum = region_losses.base_sq.to_numpy()[idx].sum(axis=1)
    group_sum = region_losses.group_sq.to_numpy()[idx].sum(axis=1)
    bootstrap = 1 - group_sum / base_sum
    reduction = 1 - float(losses.group_sq.sum() / losses.base_sq.sum())
    ci = np.quantile(bootstrap, [0.025, 0.975]).tolist()
    result = {"n": len(frame), "regions": int(region.nunique()),
              "base_mse": float(losses.base_sq.mean()), "group_mse": float(losses.group_sq.mean()),
              "mse_reduction": reduction, "ci95_region_bootstrap": ci,
              "positive_folds": sum(f["mse_reduction"] > 0 for f in folds), "folds": folds,
              "strong_signal": bool(reduction >= .02 and ci[0] > 0
                                    and sum(f["mse_reduction"] > 0 for f in folds) >= 4)}
    return result, losses


def employment_check(base: pd.DataFrame, annual: pd.DataFrame) -> dict:
    joined = base.merge(annual, on="oktmo8", how="left", validate="one_to_one")
    results = {}
    for sector in ("trade_G", "manufacturing_C"):
        ratio = joined[sector] / joined.total
        valid = joined.total.gt(0) & joined[sector].gt(0) & ratio.gt(0) & ratio.le(1)
        selected = joined.loc[valid].copy()
        y = np.arcsin(np.sqrt(ratio[valid].to_numpy(dtype=float)))
        metrics, _ = region_cv(selected, y)
        denominator = base.groupby("label").size()
        coverage = selected.groupby("label").size().reindex(denominator.index, fill_value=0)
        metrics["coverage_by_group"] = {
            key: {"n": int(coverage[key]), "of": int(denominator[key]),
                  "fraction": float(coverage[key] / denominator[key])} for key in denominator.index}
        metrics["regions_with_multiple_groups"] = int((selected.groupby("region").label.nunique() > 1).sum())
        no_total = joined.total.isna()
        bad_total = joined.total.notna() & ~joined.total.gt(0)
        no_sector = joined[sector].isna()
        bad_sector = joined[sector].notna() & ~joined[sector].gt(0)
        bad_ratio = ratio.notna() & ~ratio.between(0, 1)
        metrics["exclusions_from_base"] = {
            "missing_total": int(no_total.sum()),
            "nonpositive_total": int(bad_total.sum()),
            "missing_sector": int(no_sector.sum()),
            "nonpositive_sector": int(bad_sector.sum()),
            "invalid_ratio": int(bad_ratio.sum()),
            "unique_excluded": int((~valid).sum()),
        }
        metrics["invalid_ratio_nonmissing"] = int((ratio.notna() & ~ratio.between(0, 1)).sum())
        results[sector] = metrics
    return results


def industry_check(base: pd.DataFrame, annual: pd.DataFrame, cities_path: Path,
                   polygons_path: Path) -> dict:
    import geopandas as gpd

    cities = pd.read_parquet(cities_path)
    if len(cities) != 1889 or cities.snapshot_id.nunique() != 1 or cities.snapshot_id.iloc[0] != "26676ba153b6e4db":
        raise ValueError("unexpected IndustryMap snapshot")
    unique(cities, ["source_city_index"], "IndustryMap cities")
    for city_id, name in BAD_INDUSTRY_CITY_IDS.items():
        match = cities.loc[cities.source_city_index == city_id, "city"]
        if len(match) != 1 or match.iloc[0] != name:
            raise ValueError(f"IndustryMap conflict index {city_id} changed")
    points = gpd.GeoDataFrame(cities, geometry=gpd.points_from_xy(cities.lon, cities.lat), crs="EPSG:4326")
    polygons = gpd.read_file(polygons_path)
    polygons = polygons[(pd.to_numeric(polygons.year_from, errors="coerce") <= 2024)
                        & (pd.to_numeric(polygons.year_to, errors="coerce") > 2024)]
    if polygons.crs != points.crs:
        points = points.to_crs(polygons.crs)
    joined = gpd.sjoin(points, polygons[["territory_id", "geometry"]], how="left", predicate="within")
    n_matches = joined.groupby("source_city_index").territory_id.count()
    one_match = set(n_matches[n_matches == 1].index)
    joined = joined[joined.source_city_index.isin(one_match)
                    & ~joined.source_city_index.isin(BAD_INDUSTRY_CITY_IDS)].copy()
    joined["territory_id"] = pd.to_numeric(joined.territory_id, errors="coerce")
    joined = joined[joined.territory_id.notna()].copy()
    worker = joined.groupby("territory_id", as_index=False).agg(
        industrial_workers=("industrial_workers_reported", "sum"),
        enterprises=("enterprise_count_reported", "sum"),
        city_points=("source_city_index", "size"))
    selected = base.merge(worker, on="territory_id", how="inner", validate="one_to_one")
    if (selected.industrial_workers < 0).any():
        raise ValueError("negative IndustryMap worker count")
    metrics, _ = region_cv(selected, np.log1p(selected.industrial_workers.to_numpy(dtype=float)))
    manufacturing = base.merge(annual[["oktmo8", "manufacturing_C"]], on="oktmo8", how="left")
    overlap = selected[["territory_id", "industrial_workers"]].merge(
        manufacturing[["territory_id", "manufacturing_C"]], on="territory_id")
    overlap = overlap[overlap.manufacturing_C.gt(0)]
    rho = spearmanr(np.log1p(overlap.industrial_workers), np.log1p(overlap.manufacturing_C))
    metrics["industrymap_snapshot"] = "26676ba153b6e4db"
    metrics["city_points_total"] = len(cities)
    metrics["city_points_one_polygon"] = len(one_match)
    metrics["city_points_kept_after_conflicts"] = len(joined)
    metrics["covered_municipalities"] = len(selected)
    metrics["official_manufacturing_overlap"] = len(overlap)
    metrics["official_manufacturing_spearman"] = float(rho.statistic) if len(overlap) >= 3 else None
    metrics["coverage_by_group"] = {
        label: {"n": int((selected.label == label).sum()), "of": int((base.label == label).sum())}
        for label in sorted(base.label.unique())}
    metrics["regions_with_multiple_groups"] = int((selected.groupby("region").label.nunique() > 1).sum())
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dictionary", type=Path, required=True)
    parser.add_argument("--population", type=Path, required=True)
    parser.add_argument("--industry-cities", type=Path)
    parser.add_argument("--industry-polygons", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if (args.industry_cities is None) != (args.industry_polygons is None):
        parser.error("both IndustryMap inputs must be provided together")
    out = args.out.resolve()
    if not out.is_relative_to(ROOT / "output"):
        parser.error("output must be inside the repository's ignored output/ directory")
    out.mkdir(parents=True, exist_ok=True)
    inputs = {"assignments": ASSIGNMENTS, "employment": EMPLOYMENT,
              "dictionary": args.dictionary, "population": args.population,
              "protocol": RUN / "PROTOCOL.md", "code": Path(__file__)}
    if args.industry_cities:
        inputs.update(industry_cities=args.industry_cities, industry_polygons=args.industry_polygons)
    base, base_counts = load_base(args.dictionary, args.population)
    annual = load_employment()
    public = {"status": "retrospective_exploratory", "base": base_counts,
              "input_sha256": {name: digest(path) for name, path in inputs.items() if not name.startswith("industry_")},
              "bdmo_sector_results": employment_check(base, annual)}
    (out / "bdmo-sector-results.json").write_text(json.dumps(public, ensure_ascii=False, indent=2) + "\n")
    if args.industry_cities:
        internal = {"status": "internal_only_not_for_publication",
                    "input_sha256": {name: digest(path) for name, path in inputs.items()},
                    "industrymap_result": industry_check(base, annual, args.industry_cities, args.industry_polygons)}
        (out / "industrymap-internal.json").write_text(json.dumps(internal, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"public_result": str(out / "bdmo-sector-results.json"),
                      "industry_internal": bool(args.industry_cities)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
