#!/usr/bin/env python3
"""Build auditable manifests and per-project data plans from downloaded files."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pyarrow.compute as pc
import pyarrow.parquet as pq


ROOT = Path(__file__).resolve().parent


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parquet_profile(relative: str, key_columns: list[str]) -> dict:
    path = ROOT / relative
    table = pq.read_table(path)
    nulls = {name: table[name].null_count for name in table.column_names}
    distinct = {}
    for name in key_columns:
        values = table[name].combine_chunks()
        distinct[name] = len(pc.unique(values))
    return {
        "file": relative,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "rows": table.num_rows,
        "columns": [
            {"name": field.name, "type": str(field.type), "nulls": nulls[field.name]}
            for field in table.schema
        ],
        "distinct": distinct,
    }


def file_record(relative: str, **extra) -> dict:
    path = ROOT / relative
    return {
        "file": relative,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        **extra,
    }


def main() -> None:
    dashboard = "raw/sberindex-dashboard-current"
    historical = "raw/sberindex-data-sense-2025"
    profiles = [
        parquet_profile(f"{dashboard}/municipal-consumer-spending.parquet", ["indicator_id", "period", "category_15", "mo"]),
        parquet_profile(f"{dashboard}/mobility-index.parquet", ["indicator_id", "period", "ref_area"]),
        parquet_profile(f"{historical}/1_market_access.parquet", ["territory_id"]),
        parquet_profile(f"{historical}/2_bdmo_population.parquet", ["territory_id", "year", "age"]),
        parquet_profile(f"{historical}/3_bdmo_migration.parquet", ["territory_id", "year", "age"]),
        parquet_profile(f"{historical}/4_bdmo_salary.parquet", ["territory_id", "year", "period", "okved_letter"]),
        parquet_profile(f"{historical}/5_connection.parquet", ["territory_id_x", "territory_id_y"]),
        parquet_profile(f"{historical}/8_consumption.parquet", ["territory_id", "date", "category"]),
    ]
    extra_files = [
        file_record("curated/cbr-macro-monthly.csv", rows=448, coverage="2022-02-01..2026-09-01"),
        file_record("curated/russia-production-calendar.csv", rows=1826, coverage="2022-01-01..2026-12-31"),
        file_record(
            "raw/hse-population-grid/GHS-POP_2021_corrected_for_Russia_HSE.zip",
            coverage="Russia, corrected GHS-POP 2021, 100 m and 1 km GeoTIFF",
        ),
        file_record(f"{historical}/basket_emiss_pars_hackathon.xlsx", role="regional monthly indicator; metric and units not yet verified"),
        file_record(f"{historical}/Описание_данных_для_Хакатона_2025_6_6.docx", role="historical pack documentation"),
    ]
    schema_report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "parquet": profiles,
        "other_files": extra_files,
    }
    (ROOT / "schema-report.json").write_text(
        json.dumps(schema_report, ensure_ascii=False, indent=2) + "\n"
    )

    master = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "retrieved_on": "2026-09-20",
        "storage_policy": "Raw/curated files stay in the workspace; kb-forge stores passports, provenance and analytical findings.",
        "datasets": [
            {
                "id": "sberindex_consumer_spending_current",
                "status": "downloaded_verified",
                "source": "https://sberindex.ru/ru/dashboards/potrebitelskie-beznalicnye-rashody-na-urovne-munizipalnyh-obrazovanij",
                "file": f"{dashboard}/municipal-consumer-spending.parquet",
                "rows": 303126,
                "coverage": "2,190 municipality series × 6 categories, monthly 2023-01..2024-12",
                "license": "Check contest terms before external redistribution",
                "mandatory_sberindex": True,
                "projects": ["economic-atlas", "shock-radar"],
            },
            {
                "id": "sberindex_mobility_current",
                "status": "downloaded_verified_limited_coverage",
                "source": "https://sberindex.ru/ru/dashboards/indeks-mobilnosti",
                "file": f"{dashboard}/mobility-index.parquet",
                "rows": 594,
                "coverage": "297 municipalities in Northwestern Federal District; two observations (2024-12-31 and 2025-11-01 Moscow dates)",
                "license": "Check contest terms before external redistribution",
                "mandatory_sberindex": True,
                "projects": ["economic-atlas", "shock-radar"],
            },
            {
                "id": "sberindex_data_sense_2025_pack",
                "status": "downloaded_verified_historical_pack",
                "source": "https://disk.yandex.ru/d/WH8yJOogD4UrOg",
                "files": [p["file"] for p in profiles if historical in p["file"]]
                + [extra_files[3]["file"], extra_files[4]["file"]],
                "coverage": "SberIndex/Rosstat municipal data, mainly 2023-2024; downloaded from the organiser's 2025 public pack",
                "license": "See supplied documentation and upstream sources",
                "projects": ["economic-atlas", "shock-radar"],
            },
            {
                "id": "rosstat_municipal_employment_by_industry",
                "status": "source_confirmed_download_blocked",
                "source": "https://rosstat.gov.ru/storage/mediabank/Munst.htm",
                "indicator": "8423005 — Среднесписочная численность работников организаций (без субъектов малого предпринимательства)",
                "coverage": "Municipal districts/city districts/intracity territories × economic activity; quarterly cumulative",
                "blocking_reason": "Official BDMO bulk export was not exposed as a stable downloadable URL; Rosstat HTTPS chain failed local verification on 2026-09-20. TLS verification was not bypassed.",
                "projects": ["economic-atlas", "shock-radar"],
            },
            {
                "id": "rosstat_employment_structure_2025_national",
                "status": "identified_download_blocked_wrong_geography_for_primary_use",
                "source": "https://rosstat.gov.ru/opendata/7708234640-employees2025",
                "coverage": "Russia, annual 2017-2025, enlarged economic activities; not a municipal panel",
                "blocking_reason": "Official CSV URL identified, but Rosstat HTTPS chain failed local verification on 2026-09-20. TLS verification was not bypassed.",
                "projects": ["shock-radar"],
            },
            {
                "id": "cbr_macro",
                "status": "downloaded_verified",
                "source": "https://www.cbr.ru/statistics/data-service/APIdocumentation/",
                "file": "curated/cbr-macro-monthly.csv",
                "coverage": "M2 components and end-of-month USD/EUR/CNY rates, 2022-2026",
                "license": "Bank of Russia public statistical data; keep attribution",
                "projects": ["shock-radar"],
            },
            {
                "id": "production_calendar",
                "status": "downloaded_verified",
                "source": "https://www.isdayoff.ru/docs/",
                "file": "curated/russia-production-calendar.csv",
                "coverage": "Daily 2022-2026",
                "license": "Public API; keep source attribution",
                "projects": ["shock-radar"],
            },
            {
                "id": "hse_population_grid_2021",
                "status": "downloaded_verified",
                "source": "https://geoportal.hse.ru/portal/home/item.html?id=9ee9d4ad2b124f82949f9f061e0b42c9",
                "file": extra_files[2]["file"],
                "coverage": "Russia, 2021, 100 m and 1 km corrected population rasters",
                "license": "CC BY 4.0",
                "projects": ["economic-atlas"],
            },
            {
                "id": "sberindex_municipal_dictionary",
                "status": "identified_download_blocked",
                "source": "https://sberindex.ru/ru/research/dataset-borders-and-changes-of-municipalities",
                "download": "https://www.sberbank.com/common/files/t_dict_municipal.rar",
                "blocking_reason": "Download host presented an untrusted certificate chain on 2026-09-20. TLS verification was not bypassed.",
                "license": "CC BY-SA 4.0",
                "projects": ["economic-atlas", "shock-radar"],
            },
            {
                "id": "rosstat_oktmo_2026_09_01",
                "status": "identified_download_blocked",
                "source": "https://rosstat.gov.ru/opendata/7708234640-oktmo",
                "blocking_reason": "Official URL identified, but Rosstat HTTPS chain failed local verification on 2026-09-20. TLS verification was not bypassed.",
                "projects": ["economic-atlas", "shock-radar"],
            },
            {
                "id": "open_meteo_archive",
                "status": "planned_after_coordinates",
                "source": "https://open-meteo.com/en/docs/historical-weather-api",
                "coverage": "Daily weather at selected municipal centroids; request only after a trusted territory crosswalk is available",
                "license": "CC BY 4.0 with attribution",
                "projects": ["shock-radar"],
            },
            {
                "id": "news_events",
                "status": "planned_taxonomy_first",
                "coverage": "Dated, cited public news events with publication-time fields",
                "reason": "Define event taxonomy and as-of rules before collection to prevent temporal leakage",
                "projects": ["shock-radar"],
            },
        ],
    }
    (ROOT / "manifest.json").write_text(json.dumps(master, ensure_ascii=False, indent=2) + "\n")

    common = ["sberindex_consumer_spending_current", "sberindex_mobility_current", "sberindex_data_sense_2025_pack", "rosstat_municipal_employment_by_industry"]
    plans = {
        "economic-atlas": {
            "case_id": "case_66cae4a89ba6473f",
            "common_datasets": common,
            "project_specific": ["hse_population_grid_2021", "sberindex_municipal_dictionary", "rosstat_oktmo_2026_09_01"],
            "target_table": "one row per stable municipality × month with spending shares, population/migration, salary/employment structure, accessibility and mobility where observed",
            "priority_gap": "stable municipality crosswalk and a nationwide municipal employment-by-industry export",
        },
        "shock-radar": {
            "case_id": "case_008f37d03cf541e5",
            "common_datasets": common,
            "project_specific": ["cbr_macro", "production_calendar", "open_meteo_archive", "news_events", "rosstat_employment_structure_2025_national"],
            "target_table": "one row per municipality × category × month with lags, calendar, macro, weather and strictly as-of event features",
            "priority_gap": "longer spending history and stable municipality coordinates/crosswalk before weather collection",
        },
    }
    for slug, plan in plans.items():
        path = ROOT.parent / slug / "data-manifest.json"
        path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n")

    print(f"Wrote {ROOT / 'schema-report.json'}")
    print(f"Wrote {ROOT / 'manifest.json'}")


if __name__ == "__main__":
    main()
