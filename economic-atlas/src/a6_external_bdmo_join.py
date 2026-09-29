"""Audit a 2024 SberIndex territory_id → OKTMO → Tochno BDMO join.

The indicator tables are a derivative Rosstat publication. This script only
measures join coverage; it does not establish economic validity of clusters.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path

import pyarrow.compute as pc
import pyarrow.parquet as pq


INDICATORS = {
    "Y48423005": "data_Y48423005_112_v20250918.parquet",
    "Y48423007": "data_Y48423007_112_v20250918.parquet",
    "Y48213002": "data_Y48213002_112_v20250918.parquet",
}
TOTAL_OKVED = "Всего по обследуемым видам экономической деятельности"
ANNUAL_PERIOD = "Январь-декабрь"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalize_dictionary_oktmo(value: str) -> str:
    digits = "".join(char for char in value if char.isdigit())
    if len(digits) != 11 or not digits.endswith("000"):
        raise ValueError(f"unexpected SberIndex OKTMO: {value!r}")
    return digits[:8]


def audit(panel_path: Path, dictionary_path: Path, external_dir: Path, year: int) -> dict:
    panel = pq.read_table(panel_path, columns=["territory_id", "date"]).to_pydict()
    panel_ids = {
        int(territory_id)
        for territory_id, date in zip(panel["territory_id"], panel["date"])
        if str(date).startswith(str(year))
    }
    dictionary = pq.read_table(
        dictionary_path,
        columns=["territory_id", "oktmo", "year_from", "year_to", "region_name"],
    ).to_pylist()
    by_id: dict[int, set[str]] = defaultdict(set)
    by_oktmo: dict[str, set[int]] = defaultdict(set)
    all_rows_by_id: dict[int, list[dict]] = defaultdict(list)
    active_region: dict[int, str] = {}
    for row in dictionary:
        territory_id = int(row["territory_id"])
        if territory_id not in panel_ids:
            continue
        all_rows_by_id[territory_id].append(row)
        if not (row["year_from"] <= year <= row["year_to"]):
            continue
        oktmo = normalize_dictionary_oktmo(row["oktmo"])
        by_id[territory_id].add(oktmo)
        by_oktmo[oktmo].add(territory_id)
        active_region[territory_id] = row["region_name"]

    no_active = panel_ids - set(by_id)
    inactive_reasons = Counter()
    inactive_regions = Counter()
    for territory_id in no_active:
        rows = all_rows_by_id[territory_id]
        if not rows:
            reason = "no_dictionary_row"
        elif all(row["year_to"] < year for row in rows):
            reason = "all_rows_expired_before_year"
        elif all(row["year_from"] > year for row in rows):
            reason = "all_rows_start_after_year"
        else:
            reason = "validity_gap_or_conflict"
        inactive_reasons[reason] += 1
        if rows:
            inactive_regions[rows[-1]["region_name"]] += 1

    result = {
        "year": year,
        "status": "join_coverage_only_a6_open",
        "panel_sha256": sha256(panel_path),
        "dictionary_sha256": sha256(dictionary_path),
        "panel_territories": len(panel_ids),
        "active_dictionary_territories": len(by_id),
        "panel_without_active_dictionary": len(no_active),
        "panel_without_active_dictionary_reasons": dict(sorted(inactive_reasons.items())),
        "panel_without_active_dictionary_top_regions": inactive_regions.most_common(10),
        "dictionary_ids_with_multiple_oktmo": sum(len(codes) > 1 for codes in by_id.values()),
        "oktmo_with_multiple_dictionary_ids": sum(len(ids) > 1 for ids in by_oktmo.values()),
        "indicators": {},
    }
    for code, name in INDICATORS.items():
        path = external_dir / name
        columns = ["oktmo", "year", "indicator_value"]
        if code != "Y48213002":
            columns += ["okved2", "indicator_period"]
        table = pq.read_table(path, columns=columns)
        table = table.filter(pc.equal(table["year"], year))
        any_values = table.select(["oktmo", "indicator_value"]).to_pydict()
        any_value_oktmo = {
            oktmo for oktmo, value in zip(any_values["oktmo"], any_values["indicator_value"])
            if value is not None
        }
        if code != "Y48213002":
            table = table.filter(
                pc.and_(
                    pc.equal(table["okved2"], TOTAL_OKVED),
                    pc.equal(table["indicator_period"], ANNUAL_PERIOD),
                )
            )
        values = table.select(["oktmo", "indicator_value"]).to_pydict()
        valid_oktmo = {
            oktmo for oktmo, value in zip(values["oktmo"], values["indicator_value"])
            if value is not None
        }
        matched = {
            territory_id for territory_id, codes in by_id.items()
            if codes & valid_oktmo
        }
        no_selected = set(by_id) - matched
        other_2024 = {
            territory_id for territory_id in no_selected
            if by_id[territory_id] & any_value_oktmo
        }
        no_2024 = no_selected - other_2024
        result["indicators"][code] = {
            "file": str(path),
            "sha256": sha256(path),
            "year_rows_selected": table.num_rows,
            "year_oktmo_with_value": len(valid_oktmo),
            "panel_territories_matched": len(matched),
            "panel_coverage": len(matched) / len(panel_ids) if panel_ids else None,
            "active_dictionary_without_indicator": len(no_selected),
            "active_dictionary_other_2024_value_only": len(other_2024),
            "active_dictionary_no_2024_value": len(no_2024),
            "active_dictionary_unmatched_top_regions": Counter(
                active_region[territory_id] for territory_id in no_selected
            ).most_common(10),
            "matched_with_ambiguous_dictionary_code": sum(
                any(len(by_oktmo[oktmo]) > 1 for oktmo in by_id[territory_id] & valid_oktmo)
                for territory_id in matched
            ),
            "unmatched_panel_id_sample": sorted(panel_ids - matched)[:20],
        }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel", type=Path, required=True)
    parser.add_argument("--dictionary", type=Path, required=True)
    parser.add_argument("--external-dir", type=Path, required=True)
    parser.add_argument("--year", type=int, default=2024)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.panel, args.dictionary, args.external_dir, args.year)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"status": result["status"], "output": str(args.output)}))


if __name__ == "__main__":
    main()
