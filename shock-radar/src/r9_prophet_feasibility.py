#!/usr/bin/env python3
"""Deterministic R9 Prophet feasibility pilot on the exact paired baseline mask.

This is a diagnostic subset, never a scientific pass or an independent holdout.
The target months, origin rule and missing-value exclusions match
``r9_paired_baselines.py``. Prophet sees only months <= the forecast origin.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path

import pandas as pd

from r8_prophet_batch import prophet_fit_predict
from r9_paired_baselines import evaluate as baseline_evaluate, sha256


HORIZONS = (1, 3, 6, 12)
MIN_TRAIN = 6


def _month_before(target: str, months: int) -> str:
    return str(pd.Period(target, freq="M") - months)


def select_series(wide: pd.DataFrame, per_category: int) -> list[tuple[str, str]]:
    """Take a stable, category-stratified diagnostic subset before seeing errors."""
    if per_category < 1:
        raise ValueError("per_category must be positive")
    by_category: dict[str, list[tuple[str, str]]] = {}
    for tid, cat in wide.index:
        by_category.setdefault(str(cat), []).append((str(tid), str(cat)))
    chosen = []
    for cat in sorted(by_category):
        ranked = sorted(by_category[cat], key=lambda key: (
            hashlib.sha256((key[0] + "\0" + key[1]).encode()).hexdigest(), key))
        chosen.extend(ranked[:per_category])
    return chosen


def paired_tasks(wide: pd.DataFrame, selected: list[tuple[str, str]]) -> list[dict]:
    """Apply the same calendar and missingness mask as R9 baselines."""
    months = sorted(wide.columns)
    targets = months[-6:]
    tasks = []
    for tid, cat in selected:
        series = wide.loc[(tid, cat)]
        for horizon in HORIZONS:
            for target in targets:
                origin = _month_before(target, horizon)
                seasonal_month = _month_before(target, 12)
                if origin not in months or seasonal_month not in months:
                    continue
                if seasonal_month > origin:
                    continue
                actual, last, seasonal = (series.get(m) for m in
                                          (target, origin, seasonal_month))
                history = series[[m for m in months if m <= origin]].dropna()
                if (pd.isna(actual) or pd.isna(last) or pd.isna(seasonal)
                        or len(history) < 2):
                    continue
                tasks.append({
                    "territory_id": tid, "category": cat,
                    "horizon": horizon, "origin": origin, "target": target,
                    "actual": float(actual), "pred_last": float(last),
                    "pred_seasonal": float(seasonal),
                    "pred_mean": float(history.mean()),
                })
    return tasks


def run(raw: Path, output_dir: Path, per_category: int) -> dict:
    baseline = baseline_evaluate(raw)
    if [r["horizon"] for r in baseline["results"]] != list(HORIZONS):
        raise ValueError("baseline horizons changed")
    panel = pd.read_parquet(raw)
    panel["territory_id"] = panel["territory_id"].astype(str)
    panel["month"] = pd.to_datetime(panel["date"]).dt.to_period("M").astype(str)
    wide = panel.pivot(index=["territory_id", "category"], columns="month",
                       values="value")
    selected = select_series(wide, per_category)
    tasks = paired_tasks(wide, selected)
    if not tasks:
        raise ValueError("no paired pilot tasks")

    logging.getLogger("cmdstanpy").setLevel(logging.ERROR)
    predictions = []
    failures = []
    grouped: dict[tuple[str, str, str], list[dict]] = {}
    for task in tasks:
        key = (task["territory_id"], task["category"], task["origin"])
        grouped.setdefault(key, []).append(task)
    for (tid, cat, origin), group in sorted(grouped.items()):
        series = wide.loc[(tid, cat)]
        train = [(pd.Timestamp(month + "-01"), float(value))
                 for month, value in series.items()
                 if month <= origin and pd.notna(value)]
        if len(train) < MIN_TRAIN:
            failures.append({"territory_id": tid, "category": cat,
                             "origin": origin, "reason": "insufficient_train"})
            continue
        target_dates = [pd.Timestamp(task["target"] + "-01") for task in group]
        try:
            yhat = prophet_fit_predict(train, target_dates, seed=20261001)
        except Exception as exc:
            failures.append({"territory_id": tid, "category": cat,
                             "origin": origin, "reason": type(exc).__name__})
            continue
        for task, value in zip(group, yhat, strict=True):
            predictions.append({**task, "pred_prophet": float(value)})

    frame = pd.DataFrame(predictions)
    if frame.empty:
        raise ValueError("all Prophet pilot fits failed")
    results = []
    for horizon in HORIZONS:
        subset = frame[frame.horizon == horizon]
        if subset.empty:
            results.append({"horizon": horizon, "n_common": 0})
            continue
        results.append({
            "horizon": horizon, "n_common": len(subset),
            "n_territories": int(subset.territory_id.nunique()),
            "mae": {name: float((subset.actual - subset[column]).abs().mean())
                    for name, column in (("prophet", "pred_prophet"),
                                         ("last_value", "pred_last"),
                                         ("seasonal_naive", "pred_seasonal"),
                                         ("train_mean", "pred_mean"))},
        })
    report = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "status": "feasibility_pilot_only", "r9_scientific_pass": False,
        "raw_sha256": sha256(raw),
        "sample_method": "SHA256-ranked territory/category, fixed count per category",
        "n_selected_series": len(selected), "n_candidate_rows": len(tasks),
        "n_fits": len(grouped), "n_fit_failures": len(failures),
        "n_predicted_rows": len(frame), "failures": failures,
        "results": results,
        "constraints": ["same R9 calendar/missingness mask within each horizon",
                        "Prophet trained only through each origin",
                        "sample is diagnostic and not an independent holdout",
                        "value unit and historical available_at unverified"],
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(output_dir / "predictions.parquet", index=False)
    (output_dir / "metrics.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--per-category", type=int, default=5)
    args = parser.parse_args()
    report = run(args.raw, args.output_dir, args.per_category)
    print(json.dumps({k: report[k] for k in
                      ("status", "n_selected_series", "n_fits",
                       "n_fit_failures", "n_predicted_rows")}, indent=2))


if __name__ == "__main__":
    main()
