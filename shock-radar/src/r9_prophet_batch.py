#!/usr/bin/env python3
"""Checkpointed full-panel R9 Prophet computation on the paired baseline mask.

Each series is an atomic checkpoint. Resume refuses changed input/code/config.
This computation cannot itself turn R9 into a scientific pass.
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
from r9_prophet_feasibility import HORIZONS, MIN_TRAIN, paired_tasks


def write_json_atomic(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    tmp.replace(path)


def run(raw: Path, outdir: Path, max_series: int) -> dict:
    if max_series < 0:
        raise ValueError("max_series must be nonnegative (0 means all)")
    import prophet
    fingerprint = {
        "raw_sha256": sha256(raw),
        "code_sha256": sha256(Path(__file__)),
        "pilot_code_sha256": sha256(Path(__file__).with_name("r9_prophet_feasibility.py")),
        "horizons": list(HORIZONS), "seed": 20261001,
        "model": "Prophet linear, no seasonality, 3 changepoints, no uncertainty samples",
        "prophet_version": prophet.__version__,
    }
    fp_path = outdir / "fingerprint.json"
    if fp_path.exists():
        if json.loads(fp_path.read_text()) != fingerprint:
            raise ValueError("fingerprint mismatch: refuse unsafe resume")
    else:
        write_json_atomic(fp_path, fingerprint)

    baseline = baseline_evaluate(raw)
    if baseline["source_sha256"] != fingerprint["raw_sha256"]:
        raise ValueError("baseline input disagrees with batch fingerprint")
    panel = pd.read_parquet(raw)
    panel["territory_id"] = panel.territory_id.astype(str)
    panel["month"] = pd.to_datetime(panel.date).dt.to_period("M").astype(str)
    wide = panel.pivot(index=["territory_id", "category"], columns="month",
                       values="value")
    selected = [(str(tid), str(cat)) for tid, cat in wide.index]
    tasks = paired_tasks(wide, selected)
    expected_rows = sum(item["n_observations"] for item in baseline["results"])
    if len(tasks) != expected_rows:
        raise ValueError(f"R9 paired mask mismatch: {len(tasks)} vs {expected_rows}")
    by_series: dict[tuple[str, str], list[dict]] = {}
    for task in tasks:
        by_series.setdefault((task["territory_id"], task["category"]), []).append(task)
    logging.getLogger("cmdstanpy").setLevel(logging.ERROR)

    completed = 0
    new = 0
    for (tid, cat), series_tasks in sorted(by_series.items()):
        key = hashlib.sha256((tid + "\0" + cat).encode()).hexdigest()
        ckpt = outdir / "checkpoints" / (key + ".json")
        if ckpt.exists():
            saved = json.loads(ckpt.read_text())
            if saved["territory_id"] != tid or saved["category"] != cat:
                raise ValueError("checkpoint key collision or corruption")
        else:
            if max_series and new >= max_series:
                continue
            series = wide.loc[(tid, cat)]
            origins: dict[str, list[dict]] = {}
            for task in series_tasks:
                origins.setdefault(task["origin"], []).append(task)
            predictions = []
            failures = []
            for origin, group in sorted(origins.items()):
                train = [(pd.Timestamp(month + "-01"), float(value))
                         for month, value in series.items()
                         if month <= origin and pd.notna(value)]
                if len(train) < MIN_TRAIN:
                    failures.append({"origin": origin, "reason": "insufficient_train",
                                     "n_rows": len(group)})
                    continue
                target_dates = [pd.Timestamp(task["target"] + "-01") for task in group]
                try:
                    yhat = prophet_fit_predict(train, target_dates, seed=20261001)
                except Exception as exc:
                    failures.append({"origin": origin, "reason": type(exc).__name__,
                                     "n_rows": len(group)})
                    continue
                predictions.extend({**task, "pred_prophet": float(value)}
                                   for task, value in zip(group, yhat, strict=True))
            write_json_atomic(ckpt, {"territory_id": tid, "category": cat,
                                     "n_expected": len(series_tasks),
                                     "predictions": predictions, "failures": failures})
            new += 1
        completed += 1
        if completed % 25 == 0 or completed == len(by_series):
            write_json_atomic(outdir / "progress.json", {
                "checked_at": datetime.now(timezone.utc).isoformat(),
                "status": "running", "completed_series": completed,
                "total_series": len(by_series), "new_series_this_invocation": new,
                "expected_paired_rows": expected_rows,
                "r9_scientific_pass": False,
            })

    progress = {"checked_at": datetime.now(timezone.utc).isoformat(),
                "completed_series": completed, "total_series": len(by_series),
                "new_series_this_invocation": new,
                "expected_paired_rows": expected_rows,
                "r9_scientific_pass": False}
    if completed != len(by_series):
        progress["status"] = "partial"
        write_json_atomic(outdir / "progress.json", progress)
        return progress

    rows = []
    failures = []
    for ckpt in sorted((outdir / "checkpoints").glob("*.json")):
        saved = json.loads(ckpt.read_text())
        rows.extend(saved["predictions"])
        failures.extend({"territory_id": saved["territory_id"],
                         "category": saved["category"], **failure}
                        for failure in saved["failures"])
    frame = pd.DataFrame(rows)
    if frame.empty:
        raise ValueError("no completed forecasts")
    if frame.duplicated(["territory_id", "category", "origin", "horizon", "target"]).any():
        raise ValueError("duplicate prediction keys")
    results = []
    for horizon in HORIZONS:
        subset = frame[frame.horizon == horizon]
        results.append({
            "horizon": horizon, "n_common": len(subset),
            "n_baseline_mask": next(r["n_observations"] for r in baseline["results"]
                                    if r["horizon"] == horizon),
            "mae": {name: float((subset.actual - subset[column]).abs().mean())
                    for name, column in (("prophet", "pred_prophet"),
                                         ("last_value", "pred_last"),
                                         ("seasonal_naive", "pred_seasonal"),
                                         ("train_mean", "pred_mean"))},
        })
    progress.update({"status": "computed" if not failures and len(frame) == expected_rows
                     else "incomplete_mask", "n_predictions": len(frame),
                     "n_failed_fits": len(failures), "failures": failures,
                     "results": results})
    frame.to_parquet(outdir / "predictions.parquet", index=False)
    write_json_atomic(outdir / "metrics.json", progress)
    write_json_atomic(outdir / "progress.json", progress)
    return progress


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", required=True, type=Path)
    parser.add_argument("--outdir", required=True, type=Path)
    parser.add_argument("--max-series", type=int, default=0,
                        help="new series this invocation; 0 means all")
    args = parser.parse_args()
    result = run(args.raw, args.outdir, args.max_series)
    print(json.dumps({key: result[key] for key in
                      ("status", "completed_series", "total_series")}, indent=2))


if __name__ == "__main__":
    main()
