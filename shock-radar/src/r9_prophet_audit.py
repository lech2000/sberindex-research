#!/usr/bin/env python3
"""Reconcile a completed R9 checkpoint run against the frozen paired mask.

This is a mechanical audit of coverage and MAE, not an independent holdout or
permission to mark the scientific gate passed.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path

import pandas as pd

from r9_paired_baselines import evaluate as baseline_evaluate, sha256
from r9_prophet_feasibility import HORIZONS, paired_tasks


KEY = ("territory_id", "category", "origin", "horizon", "target")
PREDICTIONS = {
    "prophet": "pred_prophet",
    "last_value": "pred_last",
    "seasonal_naive": "pred_seasonal",
    "train_mean": "pred_mean",
}


def audit(raw: Path, run_dir: Path) -> dict:
    progress = json.loads((run_dir / "progress.json").read_text())
    metrics = json.loads((run_dir / "metrics.json").read_text())
    fingerprint = json.loads((run_dir / "fingerprint.json").read_text())
    complete = (progress.get("status") in {"computed", "incomplete_mask"}
                and progress["completed_series"] == progress["total_series"] == 12468
                and len(list((run_dir / "checkpoints").glob("*.json"))) == 12468)
    if not complete:
        raise ValueError("run has not completed all series")
    baseline = baseline_evaluate(raw)
    panel = pd.read_parquet(raw)
    panel["territory_id"] = panel.territory_id.astype(str)
    panel["month"] = pd.to_datetime(panel.date).dt.to_period("M").astype(str)
    wide = panel.pivot(index=["territory_id", "category"], columns="month", values="value")
    expected = pd.DataFrame(paired_tasks(
        wide, [(str(tid), str(cat)) for tid, cat in wide.index]
    ))
    predicted = pd.read_parquet(run_dir / "predictions.parquet")
    if len(predicted) != metrics["n_predictions"] or len(predicted) != progress["n_predictions"]:
        raise ValueError("prediction file and metrics count disagree")
    for frame, label in ((expected, "expected"), (predicted, "predicted")):
        if frame.duplicated(list(KEY)).any():
            raise ValueError(f"duplicate {label} keys")
    if fingerprint["raw_sha256"] != sha256(raw) or baseline["source_sha256"] != sha256(raw):
        raise ValueError("raw file changed since run")
    if len(expected) != sum(item["n_observations"] for item in baseline["results"]):
        raise ValueError("baseline and paired task counts disagree")
    joined = expected.merge(predicted, on=list(KEY), how="outer", indicator=True,
                            suffixes=("_expected", "_predicted"), validate="one_to_one")
    counts = Counter(joined["_merge"].astype(str))
    if counts["right_only"]:
        raise ValueError(f"{counts['right_only']} predictions outside frozen mask")
    common = joined[joined["_merge"] == "both"]
    for column in ("actual", "pred_last", "pred_seasonal", "pred_mean"):
        if not (common[f"{column}_expected"] - common[f"{column}_predicted"]).abs().lt(1e-7).all():
            raise ValueError(f"stored prediction changed {column} source/baseline value")
    by_horizon = []
    for horizon in HORIZONS:
        part = common[common.horizon == horizon]
        mae = {
            name: float((part.actual_expected - part[
                "pred_prophet" if name == "prophet" else f"{column}_predicted"
            ]).abs().mean())
            for name, column in PREDICTIONS.items()
        }
        stored = next(item for item in metrics["results"] if item["horizon"] == horizon)
        if len(part) != stored["n_common"]:
            raise ValueError(f"horizon {horizon}: stored common count mismatch")
        if any(abs(mae[name] - stored["mae"][name]) > 1e-7 for name in mae):
            raise ValueError(f"horizon {horizon}: stored MAE mismatch")
        by_horizon.append({"horizon": horizon, "n_common": len(part),
                           "n_baseline_mask": int((expected.horizon == horizon).sum()),
                           "mae_common": mae})
    reasons = Counter(item["reason"] for item in metrics["failures"])
    failed_rows = sum(int(item["n_rows"]) for item in metrics["failures"])
    if failed_rows != counts["left_only"]:
        raise ValueError("failed-row count does not explain missing predictions")
    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "source_sha256": fingerprint["raw_sha256"],
        "technical_run_complete": True,
        "expected_paired_rows": len(expected),
        "predicted_rows": len(predicted),
        "missing_rows": counts["left_only"],
        "failure_reasons": dict(reasons),
        "unexpected_fit_failure": bool(set(reasons) - {"insufficient_train"}),
        "by_horizon": by_horizon,
        "independent_new_holdout": False,
        "historical_asof_verified": False,
        "r9_scientific_pass": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    report = audit(args.raw, args.run_dir)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({key: report[key] for key in
                      ("technical_run_complete", "predicted_rows", "missing_rows",
                       "unexpected_fit_failure")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
