#!/usr/bin/env python3
"""Compare a saved SberIndex dashboard snapshot with Data Sense spending.

The dashboard does not expose territory_id. Match complete monthly category
series, never municipality names or a single value. A match is accepted only
when every series has a unique counterpart and the multisets are equal. This
proves equivalence of two snapshots; it does not establish an OKTMO crosswalk
or redistribution rights.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq


OFFICIAL_COLUMNS = {
    "indicator_id", "period", "value", "obs_status", "source",
    "category_15", "mo", "freq", "unit_measure", "unit_mult",
}
HISTORICAL_COLUMNS = {"date", "territory_id", "category", "value"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _series(rows: pd.DataFrame, group: list[str], month: str) -> Counter:
    signatures: Counter = Counter()
    for key, part in rows.groupby(group, sort=False, dropna=False):
        category = key[-1]
        points = sorted(zip(part[month].tolist(), part["value"].tolist()))
        signatures[(category, tuple(points))] += 1
    return signatures


def audit(official_path: Path, historical_path: Path) -> dict:
    official = pq.read_table(official_path).to_pandas()
    historical = pq.read_table(historical_path).to_pandas()
    missing = {
        "official": sorted(OFFICIAL_COLUMNS - set(official)),
        "historical": sorted(HISTORICAL_COLUMNS - set(historical)),
    }
    if any(missing.values()):
        raise ValueError(f"Missing required columns: {missing}")

    # SOWA timestamps are UTC; 21:00 UTC becomes midnight in Moscow at the
    # beginning of the reported month.
    local_period = pd.to_datetime(official["period"], utc=True).dt.tz_convert(
        "Europe/Moscow"
    )
    month_boundary_ok = bool(
        ((local_period.dt.day == 1) & (local_period.dt.hour == 0)).all()
    )
    official["month"] = local_period.dt.strftime("%Y-%m")
    official["category"] = official["category_15"]

    for name, table in (("official", official), ("historical", historical)):
        if table["value"].isna().any():
            raise ValueError(f"{name}: null value must not be silently filled")
        number = pd.to_numeric(table["value"], errors="raise")
        if not (number == number.round()).all():
            raise ValueError(f"{name}: fractional values need explicit handling")
        table["value"] = number.astype("int64")

    official_signatures = _series(
        official, ["indicator_id", "category"], "month"
    )
    historical_signatures = _series(
        historical, ["territory_id", "category"], "date"
    )
    official_groups = sum(official_signatures.values())
    historical_groups = sum(historical_signatures.values())
    ambiguous = sum(
        count for count in official_signatures.values() if count > 1
    )
    official_categories_per_id = official.groupby("indicator_id")[
        "category"
    ].nunique()
    metadata = {
        key: sorted(map(str, official[key].dropna().unique().tolist()))
        for key in ("obs_status", "source", "freq", "unit_measure", "unit_mult")
    }
    exact = official_signatures == historical_signatures
    official_duplicate_keys = int(
        official.duplicated(["indicator_id", "category", "month"]).sum()
    )
    historical_duplicate_keys = int(
        historical.duplicated(["territory_id", "category", "date"]).sum()
    )
    month_count = len(official["month"].unique())
    official_coverage = official.groupby(["indicator_id", "category"])[
        "month"
    ].nunique()
    historical_coverage = historical.groupby(["territory_id", "category"])[
        "date"
    ].nunique()
    result = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "method": "unique full category-month-value series; names not joined",
        "official_file_sha256": sha256(official_path),
        "historical_file_sha256": sha256(historical_path),
        "official_rows": int(len(official)),
        "historical_rows": int(len(historical)),
        "official_series": int(official_groups),
        "historical_series": int(historical_groups),
        "official_indicator_ids": int(official["indicator_id"].nunique()),
        "historical_territory_ids": int(historical["territory_id"].nunique()),
        "official_distinct_names": int(official["mo"].nunique()),
        "months": sorted(official["month"].unique().tolist()),
        "categories": sorted(official["category"].unique().tolist()),
        "metadata": metadata,
        "month_boundary_ok": month_boundary_ok,
        "indicator_single_category": bool(
            (official_categories_per_id == 1).all()
        ),
        "ambiguous_series": int(ambiguous),
        "unmatched_official_series": int(
            sum((official_signatures - historical_signatures).values())
        ),
        "unmatched_historical_series": int(
            sum((historical_signatures - official_signatures).values())
        ),
        "exact_series_multiset_match": exact,
        "official_duplicate_series_month_keys": official_duplicate_keys,
        "historical_duplicate_series_month_keys": historical_duplicate_keys,
        "official_complete_series": int((official_coverage == month_count).sum()),
        "historical_complete_series": int((historical_coverage == month_count).sum()),
        "official_missing_series_month_cells": int(
            official_groups * month_count - official_coverage.sum()
        ),
        "historical_missing_series_month_cells": int(
            historical_groups * month_count - historical_coverage.sum()
        ),
        "redistribution_rights": "unverified",
        "oktmo_crosswalk": "not established by this comparison",
    }
    result["pass"] = bool(
        exact
        and not ambiguous
        and month_boundary_ok
        and result["indicator_single_category"]
        and result["official_rows"] == result["historical_rows"]
        and not official_duplicate_keys
        and not historical_duplicate_keys
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--official", type=Path, required=True)
    parser.add_argument("--historical", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = audit(args.official, args.historical)
    encoded = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded)
    else:
        print(encoded, end="")
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
