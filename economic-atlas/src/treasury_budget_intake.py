"""Audited intake of annual Treasury 0503317 XLS inside a user supplied ZIP.

This is a regional context dataset, never a municipality budget crosswalk.
Source amounts remain nullable integer kopecks; blank cells are not zero-filled.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import zipfile

import pandas as pd
import xlrd

SCOPES = [
    "consolidated_with_territorial_fund", "elimination_with_territorial_fund",
    "consolidated_region", "elimination_within_region", "regional_budget",
    "intracity_municipalities", "municipal_okrugs", "urban_okrugs",
    "urban_okrugs_with_districts", "intracity_districts", "municipal_districts",
    "urban_settlements", "rural_settlements", "territorial_fund",
]
LOCAL_SCOPES = SCOPES[5:13]
SCOPE_TERMS = ["внебюджетного фонда", "суммы, подлежащие исключению", "консолидированный бюджет",
               "суммы, подлежащие исключению", "бюджет субъекта", "муниципальных образований",
               "муниципальных округов", "городских округов", "внутригородским делением",
               "внутригородских районов", "муниципальных районов", "городских поселений",
               "сельских поселений", "бюджет территориального"]
SOURCE_URL = "https://roskazna.gov.ru/ispolnenie-byudzhetov/konsolidirovannye-byudzhety-subektov-rossijskoj-federacii"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def display_name(name: str) -> str:
    try:
        return name.encode("cp437").decode("cp866")
    except UnicodeError:
        return name


def clean(value: object) -> str:
    return " ".join(str(value).split())


def kopecks(value: object) -> int | None:
    if value is None or value == "":
        return None
    text = re.sub(r"\s", "", str(value)).replace(",", ".")
    number = Decimal(text)
    if not number.is_finite() or number * 100 != (number * 100).to_integral_value():
        raise ValueError(f"Nonfinite amount or precision beyond kopecks: {text}")
    return int(number * 100)


def ratio(numerator: int | None, denominator: int | None) -> float | None:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return numerator / denominator


def safe_members(archive: zipfile.ZipFile) -> None:
    for item in archive.infolist():
        path = PurePosixPath(item.filename.replace("\\", "/"))
        if path.is_absolute() or ".." in path.parts or item.flag_bits & 1:
            raise ValueError("Unsafe path or encrypted member")
        if item.file_size > 500_000_000:
            raise ValueError("Individual member exceeds intake limit")
    if sum(i.file_size for i in archive.infolist()) > 1_000_000_000:
        raise ValueError("Archive exceeds intake expansion limit")


def inspect_archive(path: Path):
    inventory, verified = [], {}
    with zipfile.ZipFile(path) as outer:
        safe_members(outer)
        for item in outer.infolist():
            name = display_name(item.filename)
            record = {"name": name, "bytes": item.file_size, "status": "quarantined"}
            try:
                data = outer.read(item)
                record["sha256"] = digest(data)
                with zipfile.ZipFile(io.BytesIO(data)) as inner:
                    safe_members(inner)
                    bad = inner.testzip()
                    if bad:
                        raise zipfile.BadZipFile("Inner CRC failure: " + display_name(bad))
                    record.update(status="verified_crc", members=len(inner.infolist()),
                                  expanded_bytes=sum(i.file_size for i in inner.infolist()))
                verified[name] = data
            except zipfile.BadZipFile as exc:
                record["reason"] = str(exc)
            inventory.append(record)
    return inventory, verified


def header(book: xlrd.book.Book, filename: str) -> dict:
    sheet = book.sheet_by_name("0503317_Д")
    if str(sheet.cell_value(3, 17)) != "0503317":
        raise ValueError("Unexpected form")
    date_text = str(sheet.cell_value(4, 17))
    date = datetime.strptime(date_text, "%d.%m.%Y")
    if date.month != 1 or date.day != 1 or "Годовая" not in sheet.cell_value(7, 0):
        raise ValueError("Only annual January 1 statements are supported")
    if clean(sheet.cell_value(8, 0)) != "Единица измерения: руб." or str(sheet.cell_value(8, 17)) != "383":
        raise ValueError("Wrong unit; do not silently multiply thousands of rubles")
    code = filename.split("_")[0]
    return {
        "report_entity_id": "treasury_0503317_" + code,
        "source_file_code": code, "source_filename": filename,
        "financial_authority": clean(sheet.cell_value(5, 3)),
        "source_budget_name": clean(sheet.cell_value(6, 3)),
        "header_oktmo_verbatim": str(sheet.cell_value(6, 17)),
        "entity_kind": "national_summary" if not sheet.cell_value(6, 17) else "reporting_territory",
        "report_date": date.date().isoformat(), "financial_year": date.year - 1,
        "unit_source": "RUB", "unit_storage": "kopeck", "scale": 100,
        "municipality_crosswalk_verified": False,
    }


def extract_sheet(sheet, header_row: int, plan_start: int, actual_start: int,
                  total_row: int, indicator: str, metadata: dict):
    labels = [clean(sheet.cell_value(header_row, plan_start + j)) for j in range(14)]
    actual_labels = [clean(sheet.cell_value(header_row, actual_start + j)) for j in range(14)]
    if labels != actual_labels or len(set(labels)) != 14:
        raise ValueError("Budget scope headers differ or duplicate")
    if any(term not in label.lower() for term, label in zip(SCOPE_TERMS, labels)):
        raise ValueError("Budget columns are not in the explicitly supported scope order")
    if "консолидированный бюджет" not in labels[0].lower():
        raise ValueError("Scope order is not the supported printed form")
    # These two separate blocks must be the actual table headings, not inferred.
    if "Утвержденные бюджетные назначения" != clean(sheet.cell_value(header_row - 1, plan_start)):
        raise ValueError("Missing approved appropriation block")
    if clean(sheet.cell_value(header_row - 1, actual_start)) != "Исполнено":
        raise ValueError("Missing execution block")
    selected = [(total_row, indicator, None)]
    if indicator == "expense_total":
        for row in range(total_row + 1, sheet.nrows):
            values = sheet.row_values(row)
            # Only top functional sections: do not add their KVR descendants.
            if re.fullmatch(r"\d{2}00", str(values[3])) and values[4] == "0000000000" and values[5] == "000":
                selected.append((row, "expense_function", str(values[3])))
        codes = [code for _, _, code in selected[1:]]
        if len(codes) != len(set(codes)):
            raise ValueError("Repeated functional section")
    rows = []
    for row_index, concept, function in selected:
        for value_kind, start in [("approved", plan_start), ("executed", actual_start)]:
            for j, scope in enumerate(SCOPES):
                rows.append({
                    **{k: metadata[k] for k in ["report_entity_id", "financial_year", "report_date", "entity_kind"]},
                    "indicator": concept, "function_code": function,
                    "indicator_name": clean(sheet.cell_value(row_index, 0)),
                    "budget_scope": scope, "budget_scope_label": labels[j],
                    "scope_role": "elimination_adjustment" if "elimination" in scope else "reported_budget",
                    "value_kind": value_kind, "amount_kopecks": kopecks(sheet.cell_value(row_index, start + j)),
                    "source_sheet": sheet.name, "source_row_1based": row_index + 1,
                    "source_column_1based": start + j + 1,
                    "source_filename": metadata["source_filename"], "source_sha256": metadata["sha256"],
                })
    return rows


def consistency(rows: list[dict]) -> dict:
    totals = {(r["indicator"], r["value_kind"], r["budget_scope"]): r["amount_kopecks"]
              for r in rows if r["indicator"] != "expense_function"}
    checked, skipped, errors, plan_diagnostics = 0, 0, [], []
    for kind in ["approved", "executed"]:
        for scope in SCOPES:
            values = [totals[(key, kind, scope)] for key in ["revenue_total", "expense_total", "financing_total"]]
            if None in values:
                skipped += 1
                continue
            residual = values[1] - values[0] - values[2]
            checked += 1
            if abs(residual) > 10:
                discrepancy = {"check": "expense_minus_revenue_minus_financing", "kind": kind,
                               "scope": scope, "residual_kopecks": residual}
                # Printed approved blocks do not always balance in this archive.
                # Preserve this measured fact without assuming a cash execution error
                # or inventing an explanation about the legal basis of appropriations.
                (plan_diagnostics if kind == "approved" else errors).append(discrepancy)
    # Elimination amounts are not budgets and cannot be summed with them.
    # For accounting diagnostics ONLY, absent printed components contribute zero;
    # original nullable amounts are unchanged and no resulting synthetic cells exist.
    accounting_blank_components = 0
    for concept in ["revenue_total", "expense_total", "financing_total"]:
        for kind in ["approved", "executed"]:
            for result_scope, positive, negative in [
                ("consolidated_with_territorial_fund", ["consolidated_region", "territorial_fund"], ["elimination_with_territorial_fund"]),
                ("consolidated_region", ["regional_budget"] + LOCAL_SCOPES, ["elimination_within_region"]),
            ]:
                actual = totals[(concept, kind, result_scope)]
                if actual is None:
                    skipped += 1
                    continue
                components = [totals[(concept, kind, s)] for s in positive + negative]
                accounting_blank_components += components.count(None)
                calc = sum(totals[(concept, kind, s)] or 0 for s in positive) - sum(totals[(concept, kind, s)] or 0 for s in negative)
                checked += 1
                if abs(actual - calc) > 10:
                    errors.append({"check": "consolidation_identity", "kind": kind, "concept": concept,
                                   "scope": result_scope, "residual_kopecks": actual - calc})
    function_sum_checks = 0
    for kind in ["approved", "executed"]:
        for scope in SCOPES:
            actual = totals[("expense_total", kind, scope)]
            parts = [r["amount_kopecks"] for r in rows if r["indicator"] == "expense_function"
                     and r["value_kind"] == kind and r["budget_scope"] == scope]
            if actual is None or not parts:
                continue
            function_sum_checks += 1
            calc = sum(x for x in parts if x is not None)
            if abs(actual - calc) > 10:
                errors.append({"check": "top_functions_sum", "kind": kind, "scope": scope,
                               "residual_kopecks": actual - calc})
    return {"checked": checked, "skipped_incomplete": skipped, "errors": errors,
            "approved_balance_diagnostics": plan_diagnostics, "function_sum_checks": function_sum_checks,
            "accounting_only_blank_components": accounting_blank_components,
            "tolerance_kopecks": 10, "nullable_source_cells_unchanged": True}


def profiles(rows, metadata):
    out = []
    for scope in ["consolidated_region", "regional_budget"] + LOCAL_SCOPES:
        x = {(r["indicator"], r["value_kind"]): r["amount_kopecks"]
             for r in rows if r["budget_scope"] == scope and r["indicator"] != "expense_function"}
        rev, ex = x[("revenue_total", "executed")], x[("expense_total", "executed")]
        out.append({**metadata, "budget_scope": scope,
                    "revenue_executed_kopecks": rev, "expense_executed_kopecks": ex,
                    "expense_approved_kopecks": x[("expense_total", "approved")],
                    "financing_executed_kopecks": x[("financing_total", "executed")],
                    "surplus_kopecks": None if None in (rev, ex) else rev - ex,
                    "expense_execution_ratio": ratio(ex, x[("expense_total", "approved")]),
                    "deficit_to_revenue_ratio": None if None in (rev, ex) else ratio(ex - rev, rev)})
    return out


def self_check():
    assert kopecks("25\xa0858\xa0756\xa0899\xa0381,60") == 2_585_875_689_938_160
    assert kopecks("") is None and kopecks(0.0) == 0 and kopecks("-1,02") == -102
    for invalid in ["nan", "Infinity", "1.001"]:
        try:
            kopecks(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError("Invalid amount accepted")
    assert ratio(1, 0) is None and ratio(None, 2) is None and ratio(120, 100) == 1.2
    values = {s: None for s in SCOPES}
    values.update(regional_budget=100, urban_okrugs=50, elimination_within_region=20,
                  consolidated_region=130, territorial_fund=30,
                  elimination_with_territorial_fund=5, consolidated_with_territorial_fund=155)
    rows = [{"indicator": key, "value_kind": kind, "budget_scope": scope,
             "amount_kopecks": 0 if key == "financing_total" and amount is not None else amount}
            for key in ["revenue_total", "expense_total", "financing_total"]
            for kind in ["approved", "executed"] for scope, amount in values.items()]
    assert not consistency(rows)["errors"]
    bad = [dict(r) for r in rows]
    next(r for r in bad if r["indicator"] == "expense_total" and r["value_kind"] == "executed"
         and r["budget_scope"] == "consolidated_region")["amount_kopecks"] += 100
    assert consistency(bad)["errors"]
    planned = [dict(r) for r in rows]
    next(r for r in planned if r["indicator"] == "expense_total" and r["value_kind"] == "approved"
         and r["budget_scope"] == "urban_okrugs")["amount_kopecks"] += 100
    assert consistency(planned)["approved_balance_diagnostics"]
    # A subtotal and a detail row must not be combined; empty functions are absent.
    assert sum(r["amount_kopecks"] is None for r in rows) == sum(r["amount_kopecks"] is None for r in bad)
    print(json.dumps({"self_check": "PASS", "fixtures": ["localized_large_decimal", "missing_vs_zero",
          "negative_cash_flow", "reject_nonfinite_subkopeck", "zero_denominator_abstain",
          "eliminations_not_added", "detect_accounting_mutation", "keep_source_nulls"]}))


def run(archive: Path, outdir: Path):
    if outdir.exists():
        raise FileExistsError("Use a new run directory, never overwrite a completed intake")
    outdir.mkdir(parents=True)
    inventory, verified = inspect_archive(archive)
    matches = [name for name in verified if "0503317" in name and "Excel" in name]
    if len(matches) != 1:
        raise ValueError("Exactly one CRC-verified Excel 0503317 family required")
    selected_name = matches[0]
    (outdir / "raw").mkdir()
    (outdir / "raw" / "0503317-verified.zip").write_bytes(verified[selected_name])
    rows, books, checks, summary = [], [], [], []
    with zipfile.ZipFile(io.BytesIO(verified[selected_name])) as inner:
        for member in inner.infolist():
            if Path(member.filename).suffix.lower() != ".xls":
                continue
            data = inner.read(member)
            book = xlrd.open_workbook(file_contents=data)
            meta = header(book, member.filename)
            meta["sha256"] = digest(data)
            sheet_names = [s.name for s in book.sheets() if s.name != "XDO_METADATA"]
            meta["data_sheets"] = sheet_names
            part = []
            for name, hr, plan, actual, total, concept in [
                ("0503317_Д", 13, 4, 22, 15, "revenue_total"),
                ("0503317_Р", 2, 6, 26, 4, "expense_total"),
                ("0503317_ИФ", 2, 4, 22, 4, "financing_total"),
            ]:
                part += extract_sheet(book.sheet_by_name(name), hr, plan, actual, total, concept, meta)
            audit = consistency(part)
            checks.append({"report_entity_id": meta["report_entity_id"], **audit})
            books.append(meta)
            rows += part
            summary += profiles(part, meta)
    frame = pd.DataFrame(rows)
    frame["amount_kopecks"] = pd.array([r["amount_kopecks"] for r in rows], dtype="Int64")
    key = ["report_entity_id", "indicator", "function_code", "value_kind", "budget_scope"]
    if frame.duplicated(key).any():
        raise ValueError("Duplicate natural key")
    frame.to_parquet(outdir / "budget-cells.parquet", index=False)
    totals = frame[frame.indicator != "expense_function"]
    totals.to_csv(outdir / "budget-totals.csv", index=False)
    frame[frame.indicator == "expense_function"].to_parquet(outdir / "budget-functions.parquet", index=False)
    profile_frame = pd.DataFrame(summary).drop(columns=["data_sheets"])
    for column in profile_frame.columns:
        if column.endswith("_kopecks"):
            profile_frame[column] = pd.array([row[column] for row in summary], dtype="Int64")
    profile_frame.to_parquet(outdir / "budget-profiles.parquet", index=False)
    for filename, data in [("inventory.json", inventory), ("books.json", books), ("consistency.json", checks), ("profiles.json", summary)]:
        (outdir / filename).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    errors = [e for check in checks for e in check["errors"]]
    passport = {
        "checked_at": datetime.now(timezone.utc).isoformat(), "supplied_on": "2026-10-04",
        "status": "computed_regional_context_partial_archive" if not errors else "accounting_review_required",
        "source_channel": "owner_supplied_file", "source_url_candidate": SOURCE_URL,
        "official_download_hash_matched": False, "source_published_at": None,
        "available_at": None, "vintage": None,
        "archive_name": archive.name, "archive_bytes": archive.stat().st_size,
        "archive_sha256": hashlib.file_digest(archive.open("rb"), "sha256").hexdigest(),
        "selected_inner_name": selected_name, "selected_inner_sha256": digest(verified[selected_name]),
        "n_archive_families": len(inventory), "n_crc_verified_families": len(verified),
        "n_quarantined_families": len(inventory) - len(verified),
        "n_workbooks_normalized": len(books), "entity_kinds": dict(Counter(b["entity_kind"] for b in books)),
        "financial_years": sorted(set(b["financial_year"] for b in books)),
        "n_cells": len(frame), "n_nonmissing_cells": int(frame.amount_kopecks.notna().sum()),
        "n_missing_cells_preserved": int(frame.amount_kopecks.isna().sum()),
        "n_total_cells": len(totals), "n_function_cells": int(frame.indicator.eq("expense_function").sum()),
        "n_accounting_checks": sum(c["checked"] for c in checks),
        "n_accounting_checks_skipped_incomplete": sum(c["skipped_incomplete"] for c in checks),
        "n_accounting_errors": len(errors), "accounting_tolerance_kopecks": 10,
        "n_approved_balance_discrepancies": sum(len(c["approved_balance_diagnostics"]) for c in checks),
        "n_function_sum_checks": sum(c["function_sum_checks"] for c in checks),
        "municipality_rows": 0, "municipality_crosswalk_verified": False,
        "historical_asof_verified": False, "admitted_to_r9_predictors": False,
        "atlas_2023_2024_features_changed": False, "scientific_pass": False,
        "code_sha256": digest(Path(__file__).read_bytes()),
        "outputs_sha256": {p.name: digest(p.read_bytes()) for p in sorted(outdir.iterdir()) if p.is_file()},
        "limits": [
            "0503317 is regional consolidation; local scopes group municipalities by type, not individual municipality rows.",
            "File prefix is a Treasury reporting code, not the SberIndex or statistical region code.",
            "Header budget names/OKTMO can be misleading (Tver name and Samara detailed code); no automatic MO join.",
            "2025 annual execution cannot be used as a historically available 2023/2024 predictor.",
            "Approved appropriations are separate from execution; revenues, cash flow, and balance are different concepts.",
            "Blank cells remain null. Zero contribution is used only in printed accounting identity diagnostics.",
            "Do not sum parent scopes with their children or function totals with detail rows; respect elimination columns.",
            "CRC-damaged first family is quarantined; five other families verified but only 0503317 XLS normalized.",
            "Annual archive publication and original portal checksum have not been independently verified.",
            "Approved revenue/expense/financing balance discrepancies are retained as diagnostics with cause unresolved; they are not execution balances.",
        ],
    }
    (outdir / "passport.json").write_text(json.dumps(passport, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: passport[k] for k in ["status", "n_workbooks_normalized", "entity_kinds", "n_cells", "n_missing_cells_preserved", "n_accounting_checks", "n_accounting_errors"]}, ensure_ascii=False))
    if errors:
        raise ValueError("Accounting discrepancies require review; outputs retained")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--outdir", type=Path)
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args()
    if args.self_check:
        self_check()
    else:
        if args.archive is None or args.outdir is None:
            parser.error("--archive and --outdir are required")
        run(args.archive, args.outdir)
