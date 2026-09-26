#!/usr/bin/env python3
"""Normalize small public supplementary datasets for the SberIndex projects.

The script is deterministic and performs no network calls. Raw responses stay in
``raw/``; derived, analysis-ready tables are written to ``curated/``.
"""

from __future__ import annotations

import csv
import json
from datetime import date, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parent
RAW = ROOT / "raw"
CURATED = ROOT / "curated"


def prepare_cbr() -> dict:
    sources = [
        ("cbr-m2-2022-2026.json", "money_supply"),
        ("cbr-fx-2022-2026.json", "fx_rate"),
    ]
    output = CURATED / "cbr-macro-monthly.csv"
    rows: list[dict] = []
    for filename, dataset in sources:
        payload = json.loads((RAW / "cbr" / filename).read_text())
        indicators = {item["id"]: item["elname"] for item in payload["headerData"]}
        units = {item["id"]: item["val"] for item in payload["units"]}
        publication = payload["SType"][0]
        for item in payload["RawData"]:
            rows.append(
                {
                    "dataset": dataset,
                    "publication": publication["PublName"],
                    "series_id": item["element_id"],
                    "series_name": indicators[item["element_id"]],
                    "period_label": item["dt"].strip(),
                    "period_end_exclusive": item["date"][:10],
                    "periodicity": item["periodicity"],
                    "value": "" if item["obs_val"] is None else item["obs_val"],
                    "unit": units[item["unit_id"]],
                    "decimals": item["digits"],
                }
            )
    rows.sort(key=lambda r: (r["period_end_exclusive"], r["dataset"], r["series_id"]))
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    values = [row for row in rows if row["value"] != ""]
    return {
        "file": str(output.relative_to(ROOT)),
        "rows": len(rows),
        "non_null_values": len(values),
        "series": len({(row["dataset"], row["series_id"]) for row in rows}),
        "period_min": min(row["period_end_exclusive"] for row in rows),
        "period_max": max(row["period_end_exclusive"] for row in rows),
    }


STATUS = {
    "0": ("working_day", False, False, False),
    "1": ("non_working_day", True, False, False),
    "2": ("shortened_working_day", False, True, False),
    "4": ("special_working_day", False, False, False),
    "8": ("public_holiday", True, False, True),
}


def prepare_calendar() -> dict:
    output = CURATED / "russia-production-calendar.csv"
    rows: list[dict] = []
    for source in sorted((RAW / "isdayoff").glob("isdayoff-*.txt")):
        year = int(source.stem.rsplit("-", 1)[1])
        codes = source.read_text().strip()
        cursor = date(year, 1, 1)
        for code in codes:
            if code not in STATUS:
                raise ValueError(f"Unknown isDayOff status {code!r} in {source}")
            name, non_working, shortened, holiday = STATUS[code]
            rows.append(
                {
                    "date": cursor.isoformat(),
                    "status_code": code,
                    "status_name": name,
                    "is_non_working": str(non_working).lower(),
                    "is_shortened": str(shortened).lower(),
                    "is_public_holiday": str(holiday).lower(),
                }
            )
            cursor += timedelta(days=1)
        expected = (date(year + 1, 1, 1) - date(year, 1, 1)).days
        if len(codes) != expected:
            raise ValueError(f"{source}: expected {expected} day codes, got {len(codes)}")
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return {
        "file": str(output.relative_to(ROOT)),
        "rows": len(rows),
        "period_min": rows[0]["date"],
        "period_max": rows[-1]["date"],
        "status_counts": {
            code: sum(row["status_code"] == code for row in rows) for code in STATUS
        },
    }


def main() -> None:
    CURATED.mkdir(parents=True, exist_ok=True)
    report = {
        "cbr_macro": prepare_cbr(),
        "production_calendar": prepare_calendar(),
    }
    (CURATED / "preparation-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
