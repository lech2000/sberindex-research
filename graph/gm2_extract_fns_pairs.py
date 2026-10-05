"""Read the official Smolensk FNS 2025 XLS code comparison as source evidence."""

import argparse
import csv
import hashlib
import json
from pathlib import Path
import re

import xlrd


SOURCE_PAGE = "https://www.nalog.gov.ru/rn67/news/tax_doc_news/15505089/"
SOURCE_XLS = "https://www.nalog.gov.ru/html/sites/www.rn67.nalog.ru/document_yfns/kodOKTMO.xls"


def oktmo11(value: object) -> str:
    if not isinstance(value, (int, float)) or int(value) != value:
        raise ValueError(f"invalid numeric OKTMO cell: {value!r}")
    code = str(int(value))
    if len(code) != 8:
        raise ValueError(f"expected eight-digit municipal code: {code}")
    return code + "000"


def norm(name: str) -> str:
    return re.sub(r"\s+(?:(?:муниципальный\s+)?(?:район|округ)|городское\s+поселение)$", "",
                  name.removeprefix("Муниципальное образование ").strip().casefold())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--xls", type=Path, required=True)
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    args = parser.parse_args()
    with args.candidates.open(newline="") as stream:
        expected = {row["new_oktmo11"]: row for row in csv.DictReader(stream)
                    if row["region"] == "Смоленская область"}
    sheet = xlrd.open_workbook(str(args.xls)).sheet_by_name("Сопоставление 2025")
    pairs = []
    for idx in range(3, sheet.nrows):
        values = sheet.row_values(idx)
        if values[2] != "Муниципальный район" or values[5] != "Муниципальный округ":
            continue
        old_code, new_code = oktmo11(values[1]), oktmo11(values[4])
        previous = expected.get(new_code)
        if previous is None or previous["old_oktmo11"] != old_code:
            raise ValueError(f"FNS pair differs from official snapshot candidate: {old_code}→{new_code}")
        pairs.append({
            "old_oktmo11": old_code,
            "new_oktmo11": new_code,
            "old_name_fns": str(values[0]).strip(),
            "new_name_fns": str(values[3]).strip(),
            "regional_law_ref_fns": " ".join(str(values[6]).split()),
            "valid_from": "2025-01-01",
            "xls_row": idx + 1,
            "old_name_consistency": ("same_stem" if norm(str(values[0])) == norm(previous["old_name"])
                                     else "mismatch_review"),
            "source_url": SOURCE_XLS,
            "pair_status": "official_fns_code_pair_law_text_unverified",
        })
    if len(pairs) != 25 or len({row["new_oktmo11"] for row in pairs}) != 25:
        raise ValueError("expected 25 unique FNS municipal pairs")
    if {row["new_oktmo11"] for row in pairs} != set(expected):
        raise ValueError("FNS municipal set differs from 25 regional nodes")
    with args.out.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(pairs[0]))
        writer.writeheader()
        writer.writerows(pairs)
    args.audit.write_text(json.dumps({
        "source_page": SOURCE_PAGE,
        "source_xls": SOURCE_XLS,
        "source_sha256": hashlib.sha256(args.xls.read_bytes()).hexdigest(),
        "sheet": sheet.name,
        "sheet_rows": sheet.nrows,
        "official_code_pairs": len(pairs),
        "old_name_mismatches": [row["xls_row"] for row in pairs
                                if row["old_name_consistency"] == "mismatch_review"],
        "law_texts_independently_verified": False,
        "attachment_available_at_verified": False,
        "scope": "official_FNS_code_pairs_not_independent_law_text_verification",
    }, ensure_ascii=False, indent=2) + "\n")
    print(f"official FNS code pairs: {len(pairs)}")


if __name__ == "__main__":
    main()
