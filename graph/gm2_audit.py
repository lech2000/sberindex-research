#!/usr/bin/env python3
"""Audit a dated SberIndex territory_id→OKTMO dictionary without guessing successors."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

import pandas as pd


REQUIRED = {"territory_id", "oktmo", "year_from", "year_to"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def audit(dictionary_path: Path, spending_path: Path) -> dict:
    dictionary = pd.read_parquet(dictionary_path)
    spending = pd.read_parquet(spending_path)
    if REQUIRED - set(dictionary):
        raise ValueError(f"dictionary missing {sorted(REQUIRED-set(dictionary))}")
    if {"territory_id", "date"} - set(spending):
        raise ValueError("spending missing territory_id/date")
    if dictionary[list(REQUIRED)].isna().any().any():
        raise ValueError("null identity/interval field")
    if dictionary.duplicated("territory_id").any():
        raise ValueError("duplicate territory_id in dictionary")
    if (dictionary.year_to <= dictionary.year_from).any():
        raise ValueError("non-positive year interval")
    if not dictionary.oktmo.astype(str).map(
            lambda code: bool(re.fullmatch(r"\d{2}-\d{3}-\d{3}-\d{3}", code))).all():
        raise ValueError("invalid OKTMO display format")

    spending = spending.copy()
    spending["year"] = pd.to_datetime(spending.date).dt.year
    years = sorted(spending.year.unique())
    yearly = []
    for year in years:
        source = spending[spending.year == year]
        ids = set(source.territory_id.unique())
        variants = {}
        for name, inclusive in (("half_open", False), ("inclusive_end", True)):
            active = dictionary[(dictionary.year_from <= year) &
                                ((dictionary.year_to >= year) if inclusive
                                 else (dictionary.year_to > year))]
            active_ids = set(active.territory_id.unique())
            collisions = active.groupby("oktmo").territory_id.nunique()
            variants[name] = {
                "dictionary_active_rows": len(active),
                "spending_ids": len(ids),
                "matched_spending_ids": len(ids & active_ids),
                "unmatched_spending_ids": len(ids - active_ids),
                "matched_spending_rows": int(source.territory_id.isin(active_ids).sum()),
                "unmatched_spending_rows": int((~source.territory_id.isin(active_ids)).sum()),
                "code_collision_count": int((collisions > 1).sum()),
                "code_collision_examples": sorted(collisions[collisions > 1].index.tolist())[:10],
            }
        yearly.append({"year": int(year), "alternatives": variants})

    transitions = []
    overlapping_half_open = []
    for code, group in dictionary.groupby("oktmo"):
        ordered = group.sort_values(["year_from", "year_to", "territory_id"])
        rows = list(ordered.itertuples(index=False))
        for old, new in zip(rows, rows[1:]):
            if old.year_to > new.year_from:
                overlapping_half_open.append({"oktmo": code,
                                              "older_territory_id": int(old.territory_id),
                                              "newer_territory_id": int(new.territory_id)})
            if old.year_to == new.year_from:
                transitions.append({"oktmo": code,
                                    "older_territory_id": int(old.territory_id),
                                    "newer_territory_id": int(new.territory_id),
                                    "transition_year": int(new.year_from),
                                    "status": "successor_candidate_not_officially_verified"})
    finite = dictionary[dictionary.year_to < 9999]
    transitions_from = {row["older_territory_id"] for row in transitions}
    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "dictionary_sha256": sha256_file(dictionary_path),
        "spending_sha256": sha256_file(spending_path),
        "source_class": "SberIndex dictionary snapshot; official Rosstat acts unverified",
        "interval_semantics": "unknown; both half-open and inclusive-end audited",
        "dictionary_rows": len(dictionary),
        "dictionary_unique_territory_ids": int(dictionary.territory_id.nunique()),
        "dictionary_unique_oktmo": int(dictionary.oktmo.nunique()),
        "finite_year_to_rows": len(finite),
        "expired_without_same_code_contiguous_candidate": int(
            (~finite.territory_id.isin(transitions_from)).sum()),
        "global_spending_ids_in_dictionary": len(
            set(spending.territory_id.unique()) & set(dictionary.territory_id.unique())),
        "yearly": yearly,
        "same_code_contiguous_successor_candidates": transitions,
        "half_open_overlapping_code_pairs": overlapping_half_open,
        "status": "candidate_crosswalk_only",
        "prohibitions": ["do not join by name", "do not treat code reuse as proof of legal successor",
                         "do not claim official OKTMO validity without source acts"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dictionary", required=True, type=Path)
    parser.add_argument("--spending", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = audit(args.dictionary, args.spending)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({key: result[key] for key in
                      ("dictionary_rows", "finite_year_to_rows", "status")}, indent=2))


if __name__ == "__main__":
    main()
