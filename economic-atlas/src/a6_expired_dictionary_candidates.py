"""Produce unverified leads for 2024 panel IDs with expired dictionary rows.

This is candidate discovery, not a legal/official municipality successor map.
No expiry cause or successor is inferred from a name or reused OKTMO alone.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path

import pyarrow.compute as pc
import pyarrow.parquet as pq


TOTAL_OKVED = "Всего по обследуемым видам экономической деятельности"
ANNUAL_PERIOD = "Январь-декабрь"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def code(value: str) -> str:
    digits = "".join(char for char in value if char.isdigit())
    if len(digits) != 11 or not digits.endswith("000"):
        raise ValueError(f"unexpected dictionary OKTMO: {value!r}")
    return digits[:8]


def audit(panel_path: Path, dictionary_path: Path, employment_path: Path, year: int) -> dict:
    p = pq.read_table(panel_path, columns=["territory_id", "date"]).to_pydict()
    panel_ids = {
        int(territory_id) for territory_id, date in zip(p["territory_id"], p["date"])
        if str(date).startswith(str(year))
    }
    dictionary = pq.read_table(
        dictionary_path,
        columns=["territory_id", "oktmo", "year_from", "year_to", "region_name", "name_short", "name"],
    ).to_pylist()
    by_id: dict[int, list[dict]] = defaultdict(list)
    active_by_name: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in dictionary:
        territory_id = int(row["territory_id"])
        by_id[territory_id].append(row)
        if row["year_from"] <= year <= row["year_to"]:
            key = (row["region_name"], row["name_short"].strip().casefold())
            active_by_name[key].append(row)

    table = pq.read_table(
        employment_path,
        columns=["oktmo", "oktmo_stable", "year", "indicator_value", "okved2", "indicator_period"],
    )
    table = table.filter(pc.equal(table["year"], year)).to_pydict()
    any_codes = {
        oktmo for oktmo, value in zip(table["oktmo"], table["indicator_value"])
        if value is not None
    }
    stable_codes = {
        oktmo for oktmo, value in zip(table["oktmo_stable"], table["indicator_value"])
        if value is not None
    }
    annual_codes = {
        oktmo for oktmo, value, okved, period in zip(
            table["oktmo"], table["indicator_value"], table["okved2"], table["indicator_period"]
        ) if value is not None and okved == TOTAL_OKVED and period == ANNUAL_PERIOD
    }

    records = []
    for territory_id in sorted(panel_ids):
        rows = by_id.get(territory_id, [])
        if any(row["year_from"] <= year <= row["year_to"] for row in rows):
            continue
        if not rows or not all(row["year_to"] < year for row in rows):
            continue
        latest = max(rows, key=lambda row: (row["year_to"], row["year_from"]))
        oktmo = code(latest["oktmo"])
        name_key = (latest["region_name"], latest["name_short"].strip().casefold())
        same_name = sorted({
            int(row["territory_id"]) for row in active_by_name[name_key]
            if int(row["territory_id"]) != territory_id
        })
        records.append({
            "territory_id": territory_id,
            "region_name": latest["region_name"],
            "name": latest["name"],
            "last_dictionary_year_to": latest["year_to"],
            "last_dictionary_oktmo_8": oktmo,
            "same_oktmo_in_2024_annual_total": oktmo in annual_codes,
            "same_oktmo_in_any_2024_value": oktmo in any_codes,
            "same_oktmo_in_2024_stable_code": oktmo in stable_codes,
            "active_same_region_short_name_ids_unverified": same_name,
            "expiry_reason": "unknown",
            "successor_id": None,
        })
    summary = Counter()
    for record in records:
        summary["same_oktmo_in_2024_annual_total"] += record["same_oktmo_in_2024_annual_total"]
        summary["same_oktmo_in_any_2024_value"] += record["same_oktmo_in_any_2024_value"]
        summary["same_oktmo_in_2024_stable_code"] += record["same_oktmo_in_2024_stable_code"]
        summary["active_same_region_short_name"] += bool(record["active_same_region_short_name_ids_unverified"])
        summary["any_candidate_signal"] += any((
            record["same_oktmo_in_any_2024_value"],
            record["same_oktmo_in_2024_stable_code"],
            record["active_same_region_short_name_ids_unverified"],
        ))
    return {
        "year": year,
        "status": "candidate_signals_only_no_verified_successors",
        "panel_sha256": digest(panel_path),
        "dictionary_sha256": digest(dictionary_path),
        "employment_sha256": digest(employment_path),
        "expired_panel_ids": len(records),
        "summary": dict(summary),
        "records": records,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel", type=Path, required=True)
    parser.add_argument("--dictionary", type=Path, required=True)
    parser.add_argument("--employment", type=Path, required=True)
    parser.add_argument("--year", type=int, default=2024)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.panel, args.dictionary, args.employment, args.year)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"status": result["status"], "expired_panel_ids": result["expired_panel_ids"]}))


if __name__ == "__main__":
    main()
