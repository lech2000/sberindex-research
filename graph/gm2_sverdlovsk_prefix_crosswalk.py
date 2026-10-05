"""Project official settlement recodes to candidate municipal prefixes.

The resulting 8/11-digit pairs are corroborated by *settlement* rows, not
printed as municipal-level successor pairs in the source DOC. Keep that
distinction in the graph and do not use this output to rewrite SberIndex IDs.
"""

import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import json
from pathlib import Path
import re

from gm2_candidate_pairs import code, read_section_one


RECODE_URL = "https://rosstat.gov.ru/storage/mediabank/765_24_OKTMO.doc"
LAW_URL = "https://www.pravo.gov66.ru/media/pravo/24-%D0%9E%D0%97_879vsft.pdf"
SETTLEMENT_CODE = re.compile(r"65\s+\d{3}\s+\d{3}\s+\d{3}")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--recode-text", type=Path, required=True)
    ap.add_argument("--before", type=Path, required=True)
    ap.add_argument("--current", type=Path, required=True)
    ap.add_argument("--candidates", type=Path, required=True)
    ap.add_argument("--law-pdf", type=Path, required=True)
    ap.add_argument("--law-ocr-dir", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--audit", type=Path, required=True)
    a = ap.parse_args()

    codes = [re.sub(r"\s+", "", line.strip())
             for line in a.recode_text.read_text().splitlines()
             if SETTLEMENT_CODE.fullmatch(line.strip())]
    if len(codes) != 3054:
        raise ValueError(f"expected 1,527 old/new settlement pairs, got {len(codes)} codes")
    settlement_pairs = list(zip(codes[::2], codes[1::2]))
    if any(old == new for old, new in settlement_pairs):
        raise ValueError("unchanged code in recoding table")
    old_by_new = defaultdict(set)
    new_by_old = defaultdict(set)
    counts = Counter()
    for old, new in settlement_pairs:
        old8, new8 = old[:8], new[:8]
        old_by_new[new8].add(old8)
        new_by_old[old8].add(new8)
        counts[(old8, new8)] += 1
    if len(old_by_new) != 53 or len(new_by_old) != 53:
        raise ValueError("expected 53 distinct old and new municipal prefixes")
    if any(len(values) != 1 for values in (*old_by_new.values(), *new_by_old.values())):
        raise ValueError("ambiguous municipality prefix projection")

    with a.current.open(newline="") as f:
        current = {row["oktmo8"]: row for row in csv.DictReader(f)}
    with a.candidates.open(newline="") as f:
        candidates = {row["new_oktmo11"]: row for row in csv.DictReader(f)
                      if row["region"] == "Свердловская область"}
    before = {code(row): row for row in read_section_one(a.before)}
    if set(old_by_new) != set(current) or len(candidates) != 53:
        raise ValueError("prefix projection differs from official current municipalities")

    ocr = "\n".join(p.read_text() for p in sorted(a.law_ocr_dir.glob("page-*.txt")))
    articles = {int(number) for number in re.findall(r"Статья\s+(\d+)\.", ocr)}
    if articles != set(range(1, 55)):
        raise ValueError(f"law OCR does not cover articles 1–54: {sorted(articles)}")
    if "Ирбитского муниципального" not in ocr or "Махнёвского муниципального" not in ocr:
        raise ValueError("law OCR missing two naming-exception articles")

    rows = []
    for new8 in sorted(old_by_new):
        old8 = next(iter(old_by_new[new8]))
        old11, new11 = old8 + "000", new8 + "000"
        prior = candidates[new11]
        if old11 not in before:
            raise ValueError(f"old prefix missing in national 2023 snapshot: {old11}")
        if prior["old_oktmo11"] and prior["old_oktmo11"] != old11:
            raise ValueError(f"name candidate disagrees with settlement recode: {new11}")
        rows.append({
            "old_oktmo11": old11,
            "new_oktmo11": new11,
            "old_name_classifier": before[old11][6],
            "new_name_classifier": current[new8]["name_in_classifier"],
            "n_settlement_code_pairs": counts[(old8, new8)],
            "prior_name_match_status": prior["status"],
            "valid_from": "2025-01-01",
            "source_recode_url": RECODE_URL,
            "source_status_law_url": LAW_URL,
            "pair_status": "parent_prefix_inferred_from_official_settlement_recode",
        })
    if sum(row["n_settlement_code_pairs"] for row in rows) != 1527:
        raise ValueError("not all settlement rows accounted for")
    exceptions = [row for row in rows if row["prior_name_match_status"] == "unresolved_name_mismatch"]
    if {row["new_oktmo11"] for row in exceptions} != {"65530000000", "65536000000"}:
        raise ValueError("unexpected unresolved name exceptions")

    with a.out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    a.audit.write_text(json.dumps({
        "checked_at": "2026-10-02",
        "recode_url": RECODE_URL,
        "recode_doc_sha256": "48d839c6eb3e9d9232ab89c9cadaed17ef6f343b2fc2c17a81142bb6c81150d2",
        "recode_text_sha256": sha(a.recode_text),
        "law_url": LAW_URL,
        "law_pdf_sha256": sha(a.law_pdf),
        "before_sha256": sha(a.before),
        "current_csv_sha256": sha(a.current),
        "settlement_code_pairs": len(settlement_pairs),
        "unique_parent_prefix_pairs": len(rows),
        "name_match_candidates_corrob": len(rows) - len(exceptions),
        "name_exceptions_prefix_resolved": [
            {"old": row["old_oktmo11"], "new": row["new_oktmo11"]}
            for row in exceptions],
        "law_articles_detected": len(articles),
        "source_level": "settlement_recode_projected_to_parent_prefix",
        "explicit_municipal_successor_pairs_in_source": False,
        "sberindex_territory_id_joined": False,
    }, ensure_ascii=False, indent=2) + "\n")
    print(f"{len(settlement_pairs)} settlement pairs → {len(rows)} unique parent prefix pairs")


if __name__ == "__main__":
    main()
