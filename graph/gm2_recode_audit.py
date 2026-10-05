#!/usr/bin/env python3
"""Audit dated Rosstat settlement recode snapshots without inferring MO identity."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter
from pathlib import Path


CODE = re.compile(r"[0-9 ]+")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_snapshot(path: Path) -> tuple[set[tuple[str, str, str, str]], int]:
    rows: set[tuple[str, str, str, str]] = set()
    skipped = 0
    with path.open(encoding="cp1251", newline="") as stream:
        reader = csv.reader(stream, delimiter=";")
        next(reader)  # dataset title
        next(reader)  # column labels
        for row in reader:
            if len(row) < 4 or not CODE.fullmatch(row[1].strip()) or not row[3].strip():
                skipped += 1
                continue
            old = row[1].replace(" ", "").strip()
            new = row[2].replace(" ", "").strip()
            if len(old) != 11 or (new and (not new.isdigit() or len(new) != 11)):
                skipped += 1
                continue
            rows.add((row[0].strip(), old, new, row[3].strip()))
    return rows, skipped


def audit(before: Path, after: Path) -> dict:
    early, skipped_early = read_snapshot(before)
    late, skipped_late = read_snapshot(after)
    added = late - early
    region_changes = {}
    for region in ("Смоленская область", "Свердловская область"):
        region_changes[region] = dict(sorted(Counter(
            change for subject, _, _, change in late if subject == region
        ).items()))
    return {
        "scope": "settlement_recode_only_not_municipal_successor_proof",
        "before": {"file": before.name, "sha256": sha256(before),
                   "unique_rows": len(early), "skipped_nondata_rows": skipped_early},
        "after": {"file": after.name, "sha256": sha256(after),
                  "unique_rows": len(late), "skipped_nondata_rows": skipped_late},
        "new_rows": len(added),
        "new_2024_change_rows": sum("/2024" in row[3] for row in added),
        "region_changes_after": region_changes,
        "sample_explicit_pairs": [
            {"region": region, "old": old, "new": new, "change": change}
            for region, old, new, change in sorted(added)
            if (old, new) in {("66603101001", "66503000001"),
                              ("66633101001", "66533000001"),
                              ("65703000001", "65502000001")}
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", required=True, type=Path)
    parser.add_argument("--after", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = audit(args.before, args.after)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(result["new_rows"], result["new_2024_change_rows"])


if __name__ == "__main__":
    main()
