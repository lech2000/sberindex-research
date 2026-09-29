"""Audit last-observation baseline at assumed release lags 1, 2 and 3.

This does not refit Prophet or Chronos. It checks the existing lag-2
prediction against the raw panel, then evaluates all three lag assumptions
on their common, observed-only key mask.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path

import pyarrow.parquet as pq


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def shift_month(ym: str, offset: int) -> str:
    year, month = map(int, ym.split("-"))
    value = year * 12 + month - 1 + offset
    return f"{value // 12:04d}-{value % 12 + 1:02d}"


def run(raw_path: Path, paired_path: Path) -> dict:
    raw_rows = pq.read_table(raw_path, columns=["territory_id", "category", "date", "value"]).to_pylist()
    raw = {}
    for row in raw_rows:
        key = (str(row["territory_id"]), row["category"], row["date"][:7])
        if key in raw:
            raise ValueError(f"duplicate raw key {key}")
        if row["value"] is not None:
            raw[key] = float(row["value"])

    predictions = pq.read_table(
        paired_path,
        columns=["territory_id", "category", "origin", "target", "horizon", "actual", "pred_lastavailable", "paired"],
    ).to_pylist()
    seen = set()
    common = defaultdict(list)
    individual = defaultdict(list)
    per_horizon = defaultdict(lambda: defaultdict(list))
    for row in predictions:
        key = (str(row["territory_id"]), row["category"], row["origin"], row["target"], row["horizon"])
        if key in seen:
            raise ValueError(f"duplicate paired key {key}")
        seen.add(key)
        if row["paired"] is not True:
            raise ValueError(f"unpaired row {key}")
        if shift_month(row["origin"], int(row["horizon"])) != row["target"]:
            raise ValueError(f"target horizon mismatch {key}")
        target_key = (key[0], key[1], row["target"])
        actual = raw.get(target_key)
        if actual is None or actual != float(row["actual"]):
            raise ValueError(f"target differs from raw panel {key}")
        values = {
            lag: raw.get((key[0], key[1], shift_month(row["origin"], -lag)))
            for lag in (1, 2, 3)
        }
        if values[2] is None or values[2] != float(row["pred_lastavailable"]):
            raise ValueError(f"archived lag-2 baseline differs from raw panel {key}")
        for lag, value in values.items():
            if value is not None:
                individual[lag].append(abs(actual - value))
        if all(value is not None for value in values.values()):
            for lag, value in values.items():
                error = abs(actual - value)
                common[lag].append(error)
                per_horizon[int(row["horizon"])][lag].append(error)

    if len(predictions) != 171150:
        raise ValueError(f"expected full R8 mask, got {len(predictions)}")
    if len(individual[2]) != len(predictions):
        raise ValueError("lag-2 coverage is incomplete")

    mean = lambda errors: sum(errors) / len(errors) if errors else None
    return {
        "status": "DIAGNOSTIC_BASELINE_ONLY_NOT_MODEL_LAG_SENSITIVITY",
        "release_lags_months": [1, 2, 3],
        "definition": "exact raw observation at origin minus lag; no imputation",
        "input_sha256": {"raw_panel": sha256(raw_path), "paired_predictions": sha256(paired_path)},
        "paired_rows": len(predictions),
        "archived_lag2_exact_match_rows": len(individual[2]),
        "individual_mask": {str(lag): {"n": len(individual[lag]), "mae": mean(individual[lag])} for lag in (1, 2, 3)},
        "common_mask": {
            "n": len(common[1]),
            "mae": {str(lag): mean(common[lag]) for lag in (1, 2, 3)},
            "per_horizon": {
                str(h): {"n": len(per_horizon[h][1]), "mae": {str(lag): mean(per_horizon[h][lag]) for lag in (1, 2, 3)}}
                for h in (1, 2, 3)
            },
        },
        "interpretation_limit": "Only last-observation baseline changes with lag; Prophet, Chronos and boosting were not refit at lag 1 or 3. These retrospective data have no verified historical available_at.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--paired", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.raw, args.paired)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"status": result["status"], "common_n": result["common_mask"]["n"]}))


if __name__ == "__main__":
    main()
