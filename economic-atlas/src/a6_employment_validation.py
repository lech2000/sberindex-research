"""Descriptive external A6 check against annual municipal employment."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
from pathlib import Path

import numpy as np
import pandas as pd

TOTAL_SECTOR = "Всего по обследуемым видам экономической деятельности"
ANNUAL = "Январь-декабрь"
GENDERS = {"Женщины", "Мужчины"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def oktmo8(value: str) -> str:
    digits = "".join(c for c in str(value) if c.isdigit())
    if len(digits) != 11 or not digits.endswith("000"):
        raise ValueError(f"unexpected dictionary OKTMO {value!r}")
    return digits[:8]


def unique_values(df: pd.DataFrame, keys: list[str], value: str) -> pd.DataFrame:
    """Reject conflicting non-null records; collapse exact or null duplicates."""
    counts = df.groupby(keys, dropna=False)[value].nunique(dropna=True)
    if (counts > 1).any():
        raise ValueError(f"conflicting {value} for {int((counts > 1).sum())} keys")
    return df.dropna(subset=[value]).drop_duplicates(keys)


def dictionary_map(path: Path, tids: set[int]) -> pd.DataFrame:
    df = pd.read_parquet(path, columns=[
        "territory_id", "oktmo", "year_from", "year_to", "region_name",
    ])
    df = df[df.territory_id.isin(tids) & (df.year_from <= 2023)
            & (df.year_to >= 2024)].copy()
    df["oktmo"] = df.oktmo.map(oktmo8)
    df = df[["territory_id", "oktmo", "region_name"]].drop_duplicates()
    if df.territory_id.duplicated().any() or df.oktmo.duplicated().any():
        raise ValueError("non-unique active territory_id ↔ OKTMO mapping")
    return df


def employment(path: Path) -> pd.DataFrame:
    df = pd.read_parquet(path, columns=[
        "oktmo", "year", "okved2", "indicator_period", "indicator_value",
    ])
    df = df[(df.year.isin([2023, 2024])) & (df.okved2 == TOTAL_SECTOR)
            & (df.indicator_period == ANNUAL)].copy()
    if df.duplicated(["oktmo", "year"]).any():
        raise ValueError("duplicate annual total-sector employment key")
    df = df.pivot(index="oktmo", columns="year", values="indicator_value")
    df = df.rename(columns={2023: "e23", 2024: "e24"}).reset_index()
    for col in ("e23", "e24"):
        df.loc[~np.isfinite(df[col]) | (df[col] <= 0), col] = np.nan
    return df


def population(path: Path) -> pd.DataFrame:
    df = pd.read_parquet(path, columns=[
        "territory_id", "year", "period", "age", "gender", "value",
    ])
    df = df[(df.year == 2024) & (df.period == "год")
            & (df.age == "Всего") & (df.gender.isin(GENDERS))].copy()
    df = unique_values(df, ["territory_id", "gender"], "value")
    df.loc[~np.isfinite(df.value) | (df.value <= 0), "value"] = np.nan
    df = df.dropna(subset=["value"])
    sizes = df.groupby("territory_id").gender.nunique()
    complete = set(sizes[sizes == 2].index)
    df = df[df.territory_id.isin(complete)]
    df = df.groupby("territory_id", as_index=False).value.sum()
    return df.rename(columns={"value": "p24"})


def region_crossproducts(df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    grams, rhs = [], []
    for _, block in df.groupby("region_name", sort=True):
        x = np.column_stack([
            block.label.to_numpy(dtype=float),
            np.log(block.e23.to_numpy(dtype=float)),
            np.log(block.p24.to_numpy(dtype=float)),
        ])
        y = np.log(block.e24.to_numpy(dtype=float))
        x -= x.mean(axis=0)
        y -= y.mean()
        grams.append(x.T @ x)
        rhs.append(x.T @ y)
    return np.stack(grams), np.stack(rhs)


def fe_estimate(grams: np.ndarray, rhs: np.ndarray,
                weights: np.ndarray) -> float:
    gram = np.einsum("r,rij->ij", weights, grams)
    vector = np.einsum("r,ri->i", weights, rhs)
    if np.linalg.matrix_rank(gram) != 3:
        raise ValueError("fixed-effect design rank deficient")
    return float(np.linalg.solve(gram, vector)[0])


def estimate(df: pd.DataFrame, n_boot: int, seed: int) -> dict:
    grams, rhs = region_crossproducts(df)
    n_regions = len(grams)
    beta = fe_estimate(grams, rhs, np.ones(n_regions))
    rng = np.random.default_rng(seed)
    draws = np.empty(n_boot)
    for i in range(n_boot):
        counts = np.bincount(rng.integers(n_regions, size=n_regions),
                             minlength=n_regions)
        draws[i] = fe_estimate(grams, rhs, counts)
    lo, hi = np.percentile(draws, [2.5, 97.5])
    return {
        "specification": "log(E24) ~ label + log(E23) + log(P24) + region FE",
        "n": len(df), "regions": n_regions,
        "beta_label": beta, "relative_difference": float(np.expm1(beta)),
        "bootstrap": {
            "unit": "region", "repetitions": n_boot, "seed": seed,
            "beta_95pct": [float(lo), float(hi)],
            "relative_difference_95pct": [float(np.expm1(lo)),
                                          float(np.expm1(hi))],
        },
    }


def run(assignments_path: Path, dictionary_path: Path, employment_path: Path,
        population_path: Path, n_boot: int, seed: int) -> tuple[dict, pd.DataFrame]:
    a = pd.read_parquet(assignments_path)
    a = a[a.month == "2024-12"].copy()
    if a.territory_id.duplicated().any() or set(a.label) != {0, 1}:
        raise ValueError("unexpected December 2024 assignment keys or labels")
    cohort = a.merge(dictionary_map(dictionary_path, set(a.territory_id)),
                     on="territory_id", how="left", validate="one_to_one")
    cohort = cohort.merge(employment(employment_path), on="oktmo", how="left",
                          validate="many_to_one")
    cohort = cohort.merge(population(population_path), on="territory_id",
                          how="left", validate="one_to_one")
    cohort["eligible"] = (cohort.oktmo.notna() & cohort.e23.notna()
                           & cohort.e24.notna() & cohort.p24.notna())
    coverage = []
    for label, block in cohort.groupby("label", sort=True):
        yes = block[block.eligible]
        stable = yes[(yes.status != "ambiguous") & yes.identity_id.notna()]
        coverage.append({
            "label": int(label), "assignments": len(block),
            "active_dictionary": int(block.oktmo.notna().sum()),
            "both_employment_years": int((block.e23.notna()
                                           & block.e24.notna()).sum()),
            "population_2024": int(block.p24.notna().sum()),
            "analysis_eligible": len(yes),
            "eligible_stable_identity": len(stable),
            "stable_identity_ids": int(stable.identity_id.nunique()),
            "median_employment_2024": (float(yes.e24.median()) if len(yes)
                                        else None),
            "median_employment_ratio_24_23": (
                float((yes.e24 / yes.e23).median()) if len(yes) else None),
        })
    valid = cohort[cohort.eligible].copy()
    if set(valid.label) != {0, 1}:
        raise ValueError("one monthly label has no eligible employment")
    metrics = {
        "gate": "A6", "status": "EXPLORATORY_EXTERNAL_CHECK_A6_OPEN",
        "month": "2024-12", "panel_assignments": len(cohort),
        "analysis_eligible": len(valid),
        "exclusions": {
            "no_active_2023_2024_dictionary": int(cohort.oktmo.isna().sum()),
            "no_both_employment_years_after_dictionary": int(
                (cohort.oktmo.notna() & (cohort.e23.isna()
                 | cohort.e24.isna())).sum()),
            "no_population_after_other_checks": int((cohort.oktmo.notna()
                & cohort.e23.notna() & cohort.e24.notna()
                & cohort.p24.isna()).sum()),
        },
        "coverage_by_label": coverage,
        "identity_contrast": "NA" if any(row["stable_identity_ids"] == 0
                                       for row in coverage) else "estimable",
        "monthly_label_association": estimate(valid, n_boot, seed),
        "limitations": [
            "Monthly A6 labels are not confirmed longitudinal identities.",
            "Employment excludes small enterprises and is not total employment.",
            "The derivative source has no independently verified historical availability timestamp.",
            "Labels and hypothesis were inspected before this protocol; inference is exploratory.",
        ],
        "gate_pass": False,
    }
    return metrics, pd.DataFrame(coverage)


def self_check() -> None:
    rows = []
    for region in range(4):
        for j in range(12):
            label = j % 2
            e23 = 100 + 5 * j + region
            p24 = 500 + 7 * j + 10 * region
            e24 = np.exp(1.4 + 0.18 * label + 0.7 * np.log(e23)
                         + 0.1 * np.log(p24) + region / 8)
            rows.append((f"r{region}", label, e23, e24, p24))
    df = pd.DataFrame(rows, columns=["region_name", "label", "e23",
                                     "e24", "p24"])
    result = estimate(df, 20, 1)
    assert abs(result["beta_label"] - 0.18) < 1e-8
    try:
        unique_values(pd.DataFrame({"id": [1, 1], "value": [2, 3]}),
                      ["id"], "value")
    except ValueError:
        pass
    else:
        raise AssertionError("conflicting duplicate not rejected")
    assert oktmo8("79-701-000-000") == "79701000"
    print("A6 employment self-check: PASS")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assignments", type=Path)
    parser.add_argument("--dictionary", type=Path)
    parser.add_argument("--employment", type=Path)
    parser.add_argument("--population", type=Path)
    parser.add_argument("--outdir", type=Path)
    parser.add_argument("--n-bootstrap", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=20260930)
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args()
    if args.self_check:
        self_check()
        return
    paths = [args.assignments, args.dictionary, args.employment,
             args.population]
    if args.outdir is None or any(path is None for path in paths):
        parser.error("all input paths and --outdir are required")
    if args.n_bootstrap < 1:
        parser.error("--n-bootstrap must be positive")
    metrics, coverage = run(*paths, args.n_bootstrap, args.seed)
    args.outdir.mkdir(parents=True, exist_ok=True)
    (args.outdir / "metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2) + "\n")
    coverage.to_csv(args.outdir / "coverage_by_label.csv", index=False)
    manifest = {
        "code_sha256": sha256(Path(__file__)),
        "input_sha256": {label: sha256(path) for label, path in zip(
            ["assignments", "dictionary", "employment", "population"], paths)},
        "python": platform.python_version(),
        "pandas": pd.__version__, "numpy": np.__version__,
        "n_bootstrap": args.n_bootstrap, "seed": args.seed,
    }
    (args.outdir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"status": metrics["status"],
                      "eligible": metrics["analysis_eligible"],
                      "identity_contrast": metrics["identity_contrast"]}))


if __name__ == "__main__":
    main()
