#!/usr/bin/env python3
"""A16: pre-registered exploratory checks against municipal FNS proxies.

Read runs/A16_indirect_metrics_20261008/PROTOCOL.md before changing masks,
outcomes, or thresholds. Raw downloaded Parquet files remain under output/.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.dataset as ds
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import Ridge
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from a15_sector_construct_validity import NUMERIC, ROOT, digest, load_base


RUN = ROOT / "economic-atlas/runs/A16_indirect_metrics_20261008"
FIVE_CODES = {
    "По коду вычета 320": "education_320",
    "По коду вычета 321": "education_321",
    "По коду вычета 330 (пп. 4 п. 1 ст. 219)": "npf_330",
}
SEVEN_CODES = {"Y777000006": "income_rub", "Y777000020": "income_records"}


def normalize_oktmo(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    frame["oktmo8"] = frame.object_oktmo.astype(str).str.replace(r"\D", "", regex=True).str[:8]
    frame = frame[frame.oktmo8.str.fullmatch(r"\d{8}")].copy()
    bad_history = frame.oktmo_history.fillna("").str.contains(
        "Объединение|Присоединение", case=False, regex=True)
    return frame.loc[~bad_history].copy()


def discard_ambiguous(frame: pd.DataFrame, key: list[str]) -> tuple[pd.DataFrame, int]:
    ambiguous = frame.duplicated(key, keep=False)
    return frame.loc[~ambiguous].copy(), int(ambiguous.sum())


def load_five(path: Path) -> tuple[pd.DataFrame, dict]:
    dataset = ds.dataset(path, format="parquet")
    filt = ((ds.field("year") == 2024)
            & (ds.field("object_level") == "Муниципальное образование верхнего уровня")
            & (ds.field("indicator_code") == "Y777000033")
            & (ds.field("deduction").isin(list(FIVE_CODES))))
    cols = ["object_oktmo", "oktmo_history", "deduction", "indicator_value",
            "null_value_reason", "report_date"]
    raw = dataset.to_table(filter=filt, columns=cols).to_pandas()
    raw = raw[raw.report_date.astype(str) == "2025-06-01"].copy()
    raw = normalize_oktmo(raw)
    raw["metric"] = raw.deduction.map(FIVE_CODES)
    raw, duplicate_rows = discard_ambiguous(raw, ["oktmo8", "metric"])
    raw["indicator_value"] = pd.to_numeric(raw.indicator_value, errors="coerce")
    hidden = raw.indicator_value.isna() | raw.null_value_reason.ne("NN")
    raw.loc[hidden, "indicator_value"] = np.nan
    if raw.indicator_value.dropna().lt(0).any():
        raise ValueError("negative deduction amount")
    wide = raw.pivot(index="oktmo8", columns="metric", values="indicator_value").reset_index()
    for col in FIVE_CODES.values():
        if col not in wide:
            wide[col] = np.nan
    audit = {"candidate_rows_after_history_filter": len(raw) + duplicate_rows,
             "ambiguous_rows_excluded": duplicate_rows,
             "hidden_rows_after_deduplication": int(hidden.sum()),
             "municipalities_with_any_row": len(wide)}
    return wide, audit


def load_seven(path: Path) -> tuple[pd.DataFrame, dict]:
    dataset = ds.dataset(path, format="parquet")
    filt = ((ds.field("year") == 2024)
            & (ds.field("object_level") == "Муниципальное образование верхнего уровня")
            & (ds.field("indicator_code").isin(list(SEVEN_CODES)))
            & (ds.field("indicator_period") == "Значение показателя за год")
            & (ds.field("tax_rate") == "Всего"))
    cols = ["object_oktmo", "oktmo_history", "indicator_code", "indicator_value",
            "null_value_reason", "report_date"]
    raw = dataset.to_table(filter=filt, columns=cols).to_pandas()
    raw = raw[raw.report_date.astype(str) == "2025-01-01"].copy()
    raw = normalize_oktmo(raw)
    raw["metric"] = raw.indicator_code.map(SEVEN_CODES)
    raw, duplicate_rows = discard_ambiguous(raw, ["oktmo8", "metric"])
    raw["indicator_value"] = pd.to_numeric(raw.indicator_value, errors="coerce")
    hidden = raw.indicator_value.isna() | raw.null_value_reason.ne("NN")
    raw.loc[hidden, "indicator_value"] = np.nan
    if raw.indicator_value.dropna().lt(0).any():
        raise ValueError("negative income amount or record count")
    wide = raw.pivot(index="oktmo8", columns="metric", values="indicator_value").reset_index()
    for col in SEVEN_CODES.values():
        if col not in wide:
            wide[col] = np.nan
    audit = {"candidate_rows_after_history_filter": len(raw) + duplicate_rows,
             "ambiguous_rows_excluded": duplicate_rows,
             "hidden_rows_after_deduplication": int(hidden.sum()),
             "municipalities_with_any_row": len(wide)}
    return wide, audit


def coverage(base: pd.DataFrame, selected: pd.DataFrame) -> dict:
    all_groups = base.groupby("label").size()
    observed = selected.groupby("label").size().reindex(all_groups.index, fill_value=0)
    return {str(group): {"n": int(observed[group]), "of": int(all_groups[group]),
                         "fraction": float(observed[group] / all_groups[group])}
            for group in all_groups.index}


def cv_association(frame: pd.DataFrame, outcome: np.ndarray,
                   numeric: list[str] | None = None) -> dict:
    numeric = list(NUMERIC if numeric is None else numeric)
    if len(frame) != len(outcome) or frame.region.nunique() < 5:
        raise ValueError("invalid region CV sample")
    x = frame[numeric + ["type", "label"]].reset_index(drop=True)
    region = frame.region.reset_index(drop=True)
    y = np.asarray(outcome, dtype=float)
    if not np.isfinite(y).all() or not np.isfinite(x[numeric].to_numpy(dtype=float)).all():
        raise ValueError("non-finite CV input")
    pred_base, pred_group = np.full(len(y), np.nan), np.full(len(y), np.nan)
    folds = []
    for fold, (train, test) in enumerate(GroupKFold(n_splits=5).split(x, y, groups=region)):
        predictions = []
        for include_label in (False, True):
            categorical = ["type", "label"] if include_label else ["type"]
            model = Pipeline([
                ("features", ColumnTransformer([
                    ("numeric", StandardScaler(), numeric),
                    ("categorical", OneHotEncoder(handle_unknown="ignore", sparse_output=False), categorical),
                ])),
                ("ridge", Ridge(alpha=10)),
            ])
            model.fit(x.iloc[train], y[train])
            predictions.append(model.predict(x.iloc[test]))
        pred_base[test], pred_group[test] = predictions
        base_mse = float(np.mean((y[test] - pred_base[test])**2))
        group_mse = float(np.mean((y[test] - pred_group[test])**2))
        folds.append({"fold": fold, "n": len(test), "regions": int(region.iloc[test].nunique()),
                      "base_mse": base_mse, "group_mse": group_mse,
                      "mse_reduction": 1 - group_mse / base_mse})
    if np.isnan(pred_base).any() or np.isnan(pred_group).any():
        raise AssertionError("missing out-of-fold prediction")
    losses = pd.DataFrame({"region": region, "base_sq": (y - pred_base)**2,
                           "group_sq": (y - pred_group)**2})
    region_losses = losses.groupby("region", as_index=False)[["base_sq", "group_sq"]].sum()
    rng = np.random.default_rng(20261008)
    idx = rng.integers(0, len(region_losses), size=(2000, len(region_losses)))
    base_sum = region_losses.base_sq.to_numpy()[idx].sum(axis=1)
    group_sum = region_losses.group_sq.to_numpy()[idx].sum(axis=1)
    bootstrap = 1 - group_sum / base_sum
    reduction = 1 - float(losses.group_sq.sum() / losses.base_sq.sum())
    ci = np.quantile(bootstrap, [0.025, 0.975]).tolist()
    return {"n": len(frame), "regions": int(region.nunique()),
            "base_mse": float(losses.base_sq.mean()),
            "group_mse": float(losses.group_sq.mean()),
            "mse_reduction": reduction, "ci95_region_bootstrap": ci,
            "positive_folds": sum(f["mse_reduction"] > 0 for f in folds), "folds": folds}


def evaluate(base: pd.DataFrame, selected: pd.DataFrame, y: np.ndarray,
             numeric: list[str] | None = None) -> dict:
    group_coverage = coverage(base, selected)
    metrics = cv_association(selected, y, numeric)
    metrics["coverage_by_group"] = group_coverage
    metrics["regions_with_multiple_groups"] = int((selected.groupby("region").label.nunique() > 1).sum())
    metrics["noticeable_signal"] = bool(
        metrics["mse_reduction"] >= .02
        and metrics["ci95_region_bootstrap"][0] > 0
        and metrics["positive_folds"] >= 4
        and metrics["regions"] >= 50
        and min(v["fraction"] for v in group_coverage.values()) >= .70)
    return metrics


def analysis(base: pd.DataFrame, five: pd.DataFrame, seven: pd.DataFrame) -> dict:
    joined = base.merge(five, on="oktmo8", how="left", validate="one_to_one")
    joined = joined.merge(seven, on="oktmo8", how="left", validate="one_to_one")
    income_per_record = joined.income_rub / joined.income_records
    income_mask = joined.income_rub.gt(0) & joined.income_records.gt(0) & income_per_record.gt(0)
    npf_mask = joined.npf_330.notna() & joined.npf_330.ge(0)
    edu_mask = joined.education_320.notna() & joined.education_321.notna()
    edu_sum = joined.education_320 + joined.education_321
    edu_selected = joined.loc[edu_mask]
    edu_coverage = coverage(base, edu_selected)
    edu_positive_fraction = float((edu_sum[edu_mask] > 0).mean()) if edu_mask.any() else 0.0
    education_ready = bool(edu_positive_fraction >= .30
                           and min(v["fraction"] for v in edu_coverage.values()) >= .70)

    npf = joined.loc[npf_mask].copy()
    income = joined.loc[income_mask].copy()
    result = {
        "status": "retrospective_exploratory_not_typology_confirmation",
        "base_eligible": len(base),
        "education_deduction_feasibility": {
            "both_codes_observed_n": len(edu_selected),
            "positive_n": int((edu_sum[edu_mask] > 0).sum()),
            "positive_fraction": edu_positive_fraction,
            "coverage_by_group": edu_coverage,
            "passes_predefined_gate": education_ready,
            "regression_run": False,
        },
        "npf_deduction": evaluate(base, npf, np.log1p(npf.npf_330.to_numpy(dtype=float)
                                                       / npf.pop2023.to_numpy(dtype=float) * 1000)),
        "income_per_record": evaluate(base, income, np.log(income.income_rub.to_numpy(dtype=float)
                                                            / income.income_records.to_numpy(dtype=float))),
        "exclusion_counts": {
            "npf_missing_or_hidden": int((~npf_mask).sum()),
            "income_missing_or_nonpositive": int((~income_mask).sum()),
            "education_either_code_missing_or_hidden": int((~edu_mask).sum()),
        },
    }
    if education_ready:
        edu = joined.loc[edu_mask].copy()
        result["education_deduction_feasibility"]["regression_run"] = True
        result["education_deduction_feasibility"]["association"] = evaluate(
            base, edu, np.log1p(edu_sum[edu_mask].to_numpy(dtype=float)
                                / edu.pop2023.to_numpy(dtype=float) * 1000))
    overlap_mask = npf_mask & income_mask
    overlap = joined.loc[overlap_mask].copy()
    overlap["log_income_per_record"] = np.log(income_per_record[overlap_mask].to_numpy(dtype=float))
    overlap_coverage = coverage(base, overlap)
    if min(v["fraction"] for v in overlap_coverage.values()) >= .70:
        result["npf_income_adjusted"] = evaluate(
            base, overlap, np.log1p(overlap.npf_330.to_numpy(dtype=float)
                                     / overlap.pop2023.to_numpy(dtype=float) * 1000),
            NUMERIC + ["log_income_per_record"])
    else:
        result["npf_income_adjusted"] = {
            "not_run": "less_than_70_percent_overlap_in_at_least_one_group",
            "coverage_by_group": overlap_coverage}
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dictionary", type=Path, required=True)
    parser.add_argument("--population", type=Path, required=True)
    parser.add_argument("--five-ndfl", type=Path, required=True)
    parser.add_argument("--seven-ndfl", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    if not out.is_relative_to(ROOT / "output"):
        parser.error("raw working output must stay under ignored output/")
    out.mkdir(parents=True, exist_ok=True)
    inputs = {"assignments": ROOT / "economic-atlas/runs/A10_method_comparison_20261005/assignments_annual2023_kmeans_K5.parquet",
              "dictionary": args.dictionary, "population": args.population,
              "five_ndfl": args.five_ndfl, "seven_ndfl": args.seven_ndfl,
              "protocol": RUN / "PROTOCOL.md", "code": Path(__file__)}
    base, base_audit = load_base(args.dictionary, args.population)
    five, five_audit = load_five(args.five_ndfl)
    seven, seven_audit = load_seven(args.seven_ndfl)
    result = analysis(base, five, seven)
    result["base_audit"] = base_audit
    result["source_audit"] = {"five_ndfl": five_audit, "seven_ndfl": seven_audit}
    result["input_sha256"] = {name: digest(path) for name, path in inputs.items()}
    (out / "metrics.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"result": str(out / "metrics.json")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
