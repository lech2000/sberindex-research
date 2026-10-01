#!/usr/bin/env python3
"""Check dictionary OKTMO codes against dated official Rosstat section-1 CSVs."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def audit(dictionary_path: Path, structure_path: Path,
          snapshots: list[tuple[int, Path]]) -> dict:
    dictionary = pd.read_parquet(dictionary_path).copy()
    dictionary["code"] = dictionary.oktmo.str.replace("-", "", regex=False)
    structure = pd.read_csv(structure_path, sep=";", dtype=str)
    columns = structure["field name"].tolist()
    if columns != ["TER", "KOD1", "KOD2", "KOD3", "KC", "RAZDEL", "NAME1",
                   "Centrum", "NomDescr", "NomAkt", "Status", "DateUtv", "DateVved"]:
        raise ValueError("unexpected Rosstat structure schema")
    results = []
    for year, path in snapshots:
        official = pd.read_csv(path, sep=";", header=None, names=columns,
                               dtype=str, low_memory=False)
        official["code"] = (official.TER + official.KOD1 + official.KOD2 +
                            official.KOD3)
        section1 = official[official.RAZDEL == "1"]
        codes = set(section1.code)
        if section1.duplicated("code").any():
            raise ValueError(f"duplicate official section-1 code in {path}")
        alternatives = {}
        for label, inclusive in (("half_open", False), ("inclusive_end", True)):
            active = dictionary[(dictionary.year_from <= year) &
                                ((dictionary.year_to >= year) if inclusive
                                 else (dictionary.year_to > year))]
            found = active.code.isin(codes)
            alternatives[label] = {
                "dictionary_active_rows": len(active),
                "codes_present_in_official_section_1": int(found.sum()),
                "codes_absent_from_official_section_1": int((~found).sum()),
                "absent_examples": active.loc[~found,
                    ["territory_id", "oktmo", "name_short"]].head(10).to_dict("records"),
            }
        results.append({"snapshot_year": year,
                        "official_file": path.name,
                        "official_sha256": sha256_file(path),
                        "official_rows": len(official),
                        "official_section_1_unique_codes": len(codes),
                        "alternatives": alternatives})
    return {"status": "official_code_existence_audit_not_identity_proof",
            "dictionary_sha256": sha256_file(dictionary_path),
            "structure_sha256": sha256_file(structure_path),
            "snapshots": results,
            "caveat": "code presence does not prove territory_id identity, legal succession or year_to semantics"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dictionary", required=True, type=Path)
    parser.add_argument("--structure", required=True, type=Path)
    parser.add_argument("--snapshot", action="append", required=True,
                        help="YEAR:PATH, can be repeated")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    snapshots = []
    for item in args.snapshot:
        year, path = item.split(":", 1)
        snapshots.append((int(year), Path(path)))
    result = audit(args.dictionary, args.structure, snapshots)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    for row in result["snapshots"]:
        print(row["snapshot_year"], row["official_section_1_unique_codes"],
              row["alternatives"]["half_open"]["codes_absent_from_official_section_1"])


if __name__ == "__main__":
    main()
