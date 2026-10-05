"""Extract dated current MO nodes from Sverdlovskstat's OKTMO section 1.

The landing page dates the territorial composition; the PDF provides codes.
This does not establish old-to-new successor edges.
"""

import argparse
import csv
import hashlib
import json
import re
from pathlib import Path


PAGE_URL = "https://66.rosstat.gov.ru/folder/80245"
PDF_URL = "https://66.rosstat.gov.ru/storage/mediabank/%D0%9E%D0%9A%D0%A2%D0%9C%D0%9E(1).pdf"
PATTERN = re.compile(r"^65\s+(5\d\d)\s+000\s+\d\s+-\s+(.+)$", re.MULTILINE)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--page", type=Path, required=True)
    parser.add_argument("--pdf-text", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--checked-at", required=True)
    args = parser.parse_args()
    page_raw, pdf_raw = args.page.read_bytes(), args.pdf_text.read_bytes()
    page, pdf = page_raw.decode(), pdf_raw.decode()
    if (f"URL Source: {PAGE_URL}" not in page
            or "С 1 января 2025 года" not in page
            or "53 муниципальных округа" not in page
            or f"URL Source: {PDF_URL}" not in pdf):
        raise ValueError("source identity or date not confirmed")
    try:
        section = pdf.split("65 500 000  9 Муниципальные округа Свердловской области/", 1)[1]
        section = section.split("65 600 000  1 Муниципальные районы Свердловской области", 1)[0]
    except IndexError as exc:
        raise ValueError("expected OKTMO section 1 boundaries absent") from exc
    rows = []
    for middle, tail in PATTERN.findall(section):
        name = tail.strip().split("  ", 1)[0].strip()
        oktmo8 = f"65{middle}000"
        rows.append({"oktmo8": oktmo8, "oktmo11_padded": oktmo8 + "000",
                     "name_in_classifier": name, "valid_from": "2025-01-01",
                     "source_url": PDF_URL})
    if len(rows) != 53 or len({row["oktmo8"] for row in rows}) != 53:
        raise ValueError(f"expected 53 unique current municipal codes, got {len(rows)}")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    args.audit.write_text(json.dumps({
        "landing_url": PAGE_URL,
        "pdf_url": PDF_URL,
        "transport": "Jina Reader proxy of official Sverdlovskstat HTML/PDF",
        "landing_capture_sha256": hashlib.sha256(page_raw).hexdigest(),
        "pdf_capture_sha256": hashlib.sha256(pdf_raw).hexdigest(),
        "checked_at": args.checked_at,
        "valid_from": "2025-01-01",
        "municipal_districts": len(rows),
        "scope": "dated_current_nodes_only_no_successor_edges",
        "oktmo11_note": "3-zero padding of section-1 eight-digit code for comparison only",
    }, ensure_ascii=False, indent=2) + "\n")
    print(f"extracted {len(rows)} dated current nodes")


if __name__ == "__main__":
    main()
