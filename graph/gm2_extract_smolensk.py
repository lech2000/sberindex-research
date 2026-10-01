"""Extract the 2025 municipal district list from Smolenskstat's rendered page.

Input is a Jina Reader capture of https://67.rosstat.gov.ru/mosml. This
creates dated nodes only; it makes no old-to-new OKTMO succession claim.
"""

import argparse
import csv
import hashlib
import json
import re
from pathlib import Path


SOURCE_URL = "https://67.rosstat.gov.ru/mosml"
PATTERN = re.compile(
    r"^\s*(66\s+\d{3}\s+000\s+000)-\s*(.+?)\s+муниципальный округ\b",
    re.MULTILINE,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--checked-at", required=True)
    args = parser.parse_args()
    raw = args.input.read_bytes()
    text = raw.decode("utf-8")
    if f"URL Source: {SOURCE_URL}" not in text or "с 01.01.2025" not in text:
        raise ValueError("capture does not identify the expected dated source")
    rows = [
        {
            "oktmo": "".join(code.split()),
            "name": f"{name.strip()} муниципальный округ",
            "valid_from": "2025-01-01",
            "source_url": SOURCE_URL,
        }
        for code, name in PATTERN.findall(text)
    ]
    if len(rows) != 25 or len({row["oktmo"] for row in rows}) != 25:
        raise ValueError(f"expected 25 unique municipal codes, got {len(rows)}")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    args.audit.write_text(
        json.dumps(
            {
                "source_url": SOURCE_URL,
                "transport": "Jina Reader proxy of official Smolenskstat HTML",
                "source_capture_sha256": hashlib.sha256(raw).hexdigest(),
                "checked_at": args.checked_at,
                "valid_from": "2025-01-01",
                "municipal_districts": len(rows),
                "scope": "dated_current_nodes_only_no_successor_edges",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"extracted {len(rows)} dated current nodes")


if __name__ == "__main__":
    main()
