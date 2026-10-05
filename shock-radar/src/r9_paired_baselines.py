#!/usr/bin/env python3
"""Independent, calendar-aware R9 baseline audit on the saved spending panel."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import pandas as pd


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def evaluate(path: Path) -> dict:
    panel = pd.read_parquet(path)
    required = {"territory_id", "category", "date", "value"}
    if required - set(panel):
        raise ValueError(f"missing columns: {sorted(required - set(panel))}")
    if panel[list(required)].isna().any().any():
        raise ValueError("null source key/value; never silently fill")
    panel["month"] = pd.to_datetime(panel["date"]).dt.to_period("M").astype(str)
    if panel.duplicated(["territory_id", "category", "month"]).any():
        raise ValueError("duplicate series-month key")
    wide = panel.pivot(index=["territory_id", "category"], columns="month",
                       values="value")
    months = sorted(wide.columns)
    targets = months[-6:]
    results = []
    for horizon in (1, 3, 6, 12):
        errors: dict[str, list[pd.Series]] = {
            "last_value": [], "seasonal_naive": [], "train_mean": []}
        missing_origin = missing_seasonal = 0
        origins: list[str] = []
        for target in targets:
            origin = str(pd.Period(target, freq="M") - horizon)
            seasonal_month = str(pd.Period(target, freq="M") - 12)
            if origin not in wide.columns:
                continue
            actual, previous = wide[target], wide[origin]
            history = wide[[m for m in months if m <= origin]]
            if seasonal_month in wide.columns and seasonal_month <= origin:
                seasonal = wide[seasonal_month]
            else:
                seasonal = pd.Series(float("nan"), index=wide.index)
            has_target = actual.notna()
            missing_origin += int((has_target & previous.isna()).sum())
            eligible = has_target & previous.notna() & history.count(axis=1).ge(2)
            missing_seasonal += int((eligible & seasonal.isna()).sum())
            paired = eligible & seasonal.notna()
            if not paired.any():
                continue
            predictions = {"last_value": previous,
                           "seasonal_naive": seasonal,
                           "train_mean": history.mean(axis=1)}
            for name, prediction in predictions.items():
                errors[name].append((actual[paired] - prediction[paired]).abs())
            origins.append(origin)
        if not errors["last_value"]:
            raise ValueError(f"no paired observations for horizon {horizon}")
        joined = {name: pd.concat(parts) for name, parts in errors.items()}
        macro = joined["last_value"].groupby(level=0).mean()
        results.append({
            "horizon": horizon,
            "origins": origins,
            "test_targets": targets,
            "n_observations": len(joined["last_value"]),
            "n_territories": len(macro),
            "n_missing_origin": missing_origin,
            "n_seasonal_skipped": missing_seasonal,
            "denominators": {name: len(values) for name, values in joined.items()},
            "mae_micro": {name: float(values.mean())
                          for name, values in joined.items()},
            "mae_macro_last_value": float(macro.mean()),
        })
    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "source_sha256": sha256(path),
        "method": "paired calendar origins; target last six months; no filling",
        "historical_asof_verified": False,
        "independent_new_holdout": False,
        "r9_scientific_pass": False,
        "results": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = evaluate(args.raw)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
