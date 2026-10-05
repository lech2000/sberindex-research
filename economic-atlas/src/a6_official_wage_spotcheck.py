"""Compare one primary Rosstat municipal wage table with Tochno indicator 8213002.

The PDF must be provided as a local file. Retrieval and TLS verification are
separate provenance steps; the script never downloads with relaxed TLS.
Requires PyMuPDF in addition to the scientific runtime.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pyarrow.compute as pc
import pyarrow.parquet as pq
import pymupdf


SOURCE_URL = "https://28.rosstat.gov.ru/storage/mediabank/8%288%29.pdf"
REGION = "Амурская область"
INDICATOR = "Y48213002"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def municipality_key(name: str) -> str:
    normalized = name.lower().replace("ё", "е").replace("\n", " ").strip()
    if normalized.startswith("г."):
        return "город " + normalized[2:].strip().split()[0]
    if normalized.startswith("город "):
        return "город " + normalized.split()[1]
    if "прогресс" in normalized:
        return "прогресс"
    return normalized.split()[0]


def audit(pdf_path: Path, parquet_path: Path, year: int) -> dict:
    table = pq.read_table(
        parquet_path,
        columns=["region_name", "municipality", "oktmo", "year", "indicator_value"],
    )
    table = table.filter(
        pc.and_(pc.equal(table["region_name"], REGION), pc.equal(table["year"], year))
    )
    rows = table.to_pylist()
    derivative = {municipality_key(row["municipality"]): row for row in rows}
    if len(derivative) != len(rows):
        raise ValueError("ambiguous normalized municipality names in derivative")

    document = pymupdf.open(pdf_path)
    if len(document) != 3:
        raise ValueError("unexpected official PDF page count")
    comparisons = []
    for page_number, page in enumerate(document, 1):
        for detected in page.find_tables().tables:
            extracted = detected.extract()
            if len(extracted) < 2 or extracted[1][2] != str(year):
                raise ValueError("first wage category is not the requested year")
            if "крупных и средних" not in (extracted[0][1] or ""):
                raise ValueError("unexpected wage category")
            for row in extracted[2:]:
                if not row[0] or not row[2]:
                    continue
                key = municipality_key(row[0])
                if key not in derivative:
                    raise ValueError(f"official municipality not mapped uniquely: {row[0]!r}")
                official = float(row[2].replace(" ", "").replace(",", "."))
                record = derivative[key]
                derived = float(record["indicator_value"])
                comparisons.append({
                    "municipality": row[0].replace("\n", " "),
                    "oktmo": record["oktmo"],
                    "official_rub": official,
                    "derivative_rub": derived,
                    "official_minus_derivative_rub": round(official - derived, 1),
                    "pdf_page": page_number,
                })
    if len(comparisons) != len(rows) or len({r["oktmo"] for r in comparisons}) != len(rows):
        raise ValueError("official and derivative municipality sets differ")
    discrepancies = [r for r in comparisons if abs(r["official_minus_derivative_rub"]) >= 0.05]
    return {
        "source_url": SOURCE_URL,
        "source_pdf_sha256": sha256(pdf_path),
        "source_pdf_bytes": pdf_path.stat().st_size,
        "source_transport": "local copy; original download had unverifiable TLS chain, so this is a provisional spot check",
        "derivative_file": str(parquet_path),
        "derivative_sha256": sha256(parquet_path),
        "indicator_code": INDICATOR,
        "region": REGION,
        "year": year,
        "compared_municipalities": len(comparisons),
        "exact_matches": len(comparisons) - len(discrepancies),
        "discrepancies": discrepancies,
        "max_absolute_difference_rub": max(abs(r["official_minus_derivative_rub"]) for r in comparisons),
        "mean_absolute_difference_rub": round(
            sum(abs(r["official_minus_derivative_rub"]) for r in comparisons) / len(comparisons), 3
        ),
        "status": "provisional_spot_check_a6_open",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--official-pdf", type=Path, required=True)
    parser.add_argument("--derivative-parquet", type=Path, required=True)
    parser.add_argument("--year", type=int, default=2024)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.official_pdf, args.derivative_parquet, args.year)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"status": result["status"], "output": str(args.output)}))


if __name__ == "__main__":
    main()
