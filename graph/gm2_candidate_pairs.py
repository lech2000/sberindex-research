"""Propose, but never certify, 2023→2025 municipal OKTMO correspondences.

The December 2024 official snapshot includes codes effective 2025-01-01.
Name matching is a triage aid; laws and dated classification change records
must prove any legal successor edge before GM2 may consume it.
"""

import argparse
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import re


CHANGES = {"65": {"765"}, "66": {"740", "741"}}
GROUP_CODES = {"000", "500", "600", "700"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_section_one(path: Path) -> list[list[str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return [row for row in csv.reader(stream, delimiter=";")
                if len(row) > 12 and row[5] == "1" and row[0] in CHANGES
                and row[2:4] == ["000", "000"] and row[1] not in GROUP_CODES]


def code(row: list[str]) -> str:
    return "".join(row[:4])


def normalized_name(value: str) -> str:
    return re.sub(r"\s+муниципальный\s+(?:район|округ)$", "",
                  value.strip().casefold())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--after", type=Path, required=True)
    parser.add_argument("--smolensk", type=Path, required=True)
    parser.add_argument("--sverdlovsk", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    args = parser.parse_args()
    before, after = read_section_one(args.before), read_section_one(args.after)
    after_codes = {code(row) for row in after}
    disappeared = [row for row in before if code(row) not in after_codes]
    new = [row for row in after if row[9] in CHANGES[row[0]]]
    with args.smolensk.open(newline="") as stream:
        smolensk = {row["oktmo"] for row in csv.DictReader(stream)}
    with args.sverdlovsk.open(newline="") as stream:
        sverdlovsk = {row["oktmo11_padded"] for row in csv.DictReader(stream)}
    if len(smolensk) != 25 or len(sverdlovsk) != 53:
        raise ValueError("regional source code counts changed")
    expected_new = smolensk | sverdlovsk
    if {code(row) for row in new} != expected_new:
        raise ValueError("official 2024 change rows disagree with regional current nodes")
    if len(disappeared) != 78 or len(new) != 78:
        raise ValueError("expected 78 disappeared and 78 new regional codes")
    if any(row[12] != "01.01.2025" for row in new):
        raise ValueError("new municipal codes are not all effective 2025-01-01")
    result = []
    for current in sorted(new, key=code):
        matches = [previous for previous in disappeared
                   if previous[0] == current[0]
                   and normalized_name(previous[6]) == normalized_name(current[6])]
        unique = len(matches) == 1
        previous = matches[0] if unique else None
        result.append({
            "region": "Свердловская область" if current[0] == "65" else "Смоленская область",
            "old_oktmo11": code(previous) if previous else "",
            "new_oktmo11": code(current),
            "old_name": previous[6] if previous else "",
            "new_name": current[6],
            "old_center": previous[7] if previous else "",
            "new_center": current[7],
            "change_number_2024": current[9],
            "effective_from": current[12],
            "status": "unique_name_candidate_not_legal_proof" if unique else "unresolved_name_mismatch",
            "center_comparison": (
                "same" if previous and previous[7].strip() and previous[7].strip() == current[7].strip()
                else "missing_or_different"
            ),
        })
    counts = Counter(row["status"] for row in result)
    if counts != {"unique_name_candidate_not_legal_proof": 76,
                  "unresolved_name_mismatch": 2}:
        raise ValueError(f"unexpected matching distribution: {counts}")
    with args.out.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(result[0]))
        writer.writeheader()
        writer.writerows(result)
    args.audit.write_text(json.dumps({
        "before_sha256": sha256(args.before),
        "after_sha256": sha256(args.after),
        "smolensk_csv_sha256": sha256(args.smolensk),
        "sverdlovsk_csv_sha256": sha256(args.sverdlovsk),
        "new_effective_2025_codes": len(new),
        "disappeared_2023_codes": len(disappeared),
        "status_counts": dict(counts),
        "center_comparison_counts": dict(Counter(row["center_comparison"] for row in result)),
        "unresolved_new_codes": [row["new_oktmo11"] for row in result
                                 if row["status"] == "unresolved_name_mismatch"],
        "scope": "name_match_candidates_only_no_legal_successor_edges",
    }, ensure_ascii=False, indent=2) + "\n")
    print(dict(counts))


if __name__ == "__main__":
    main()
