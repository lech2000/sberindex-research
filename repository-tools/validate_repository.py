"""Stdlib-only repository validator for the sberindex-2026 repository.

Run from the repository root (which IS deliverables/sberindex-2026)::

    python3 repository-tools/validate_repository.py
    python3 repository-tools/validate_repository.py --check-hashes

What it checks (and only that):
- every tracked ``*.py`` parses with ``ast`` (except archived/external
  directories and ``__pycache__``);
- known JSON files parse;
- manifest ``sha256`` fields are non-empty strings (recomputing file
  hashes is opt-in via ``--check-hashes`` and only for files present
  in this checkout);
- ``actions.json`` entries have the expected shape
  (``what``/``due``/``depends_on``/``done``/``status`` with sane types);
  entries 05 (economic-atlas) and 07 (shock-radar) are reported as
  closed when their ``done`` flag is true;
- ``agents/progress.json`` mentions the A6 (atlas) and R8 (radar) gates;
- project ``config.json`` files carry a ``seed``;
- evidence paths referenced below exist (raw downloads such as
  ``5_connection.parquet`` / ``8_consumption.parquet`` are gitignored
  and reported as missing-optional, never as failures).

Deliberately NOT asserted: experiment run counts, number of actions,
or any particular ``status`` enum value.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

EXCLUDE_DIRS = {"archived", "external", "vendor", "__pycache__", ".git",
                ".venv", "venv", "env", "output", ".pytest_cache"}

JSON_FILES = [
    "economic-atlas/config.json",
    "economic-atlas/actions.json",
    "economic-atlas/data-manifest.json",
    "economic-atlas/experiments.json",
    "shock-radar/config.json",
    "shock-radar/actions.json",
    "shock-radar/data-manifest.json",
    "shock-radar/experiments.json",
    "data/manifest.json",
    "agents/progress.json",
    "economic-atlas/runs/A5/graph_manifest.json",
    "economic-atlas/runs/A6/manifest.json",
    "economic-atlas/runs/A6/temporal_manifest.json",
    "shock-radar/runs/R7/manifest.json",
    "shock-radar/runs/R7_v2/manifest.json",
    "shock-radar/runs/R7_v2/signal/manifest.json",
    "shock-radar/runs/R7_v2/operator_run_manifest.json",
    "shock-radar/runs/R8/metrics.json",
    "shock-radar/runs/R8/news_audit.json",
    "economic-atlas/runs/A4/kmeans.json",
    "economic-atlas/runs/A4/agglomerative.json",
    "shock-radar/events/registry_rules.json",
]

EVIDENCE_REQUIRED = [
    "economic-atlas/data/panel_v1.parquet",
    "economic-atlas/data/panel_passport.json",
    "economic-atlas/runs/A4/kmeans.json",
    "economic-atlas/runs/A4/agglomerative.json",
    "economic-atlas/runs/A5/graph_manifest.json",
    "economic-atlas/runs/A6/manifest.json",
    "shock-radar/events/registry.parquet",
    "shock-radar/events/news_events.json",
    "shock-radar/events/news_features.parquet",
    "shock-radar/runs/R7_v2/signal/signal.parquet",
    "shock-radar/runs/R7_v2/signal/manifest.json",
    "shock-radar/runs/R7_v2/registry_eligible.parquet",
    "shock-radar/runs/R7_v2/manifest.json",
    "shock-radar/runs/R8/metrics.json",
    "repository-tools/reproduce.py",
    "repository-tools/validate_repository.py",
    "repository-tools/requirements-science.txt",
    "repository-tools/requirements-tsfm.txt",
]

EVIDENCE_OPTIONAL = [
    "data/raw/sberindex-data-sense-2025/5_connection.parquet",
    "data/raw/sberindex-data-sense-2025/8_consumption.parquet",
]

ACTION_KEYS = {
    "what": str,
    "due": (str, type(None)),
    "depends_on": list,
    "done": bool,
    "status": str,
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def iter_python_files():
    for path in sorted(REPO_ROOT.rglob("*.py")):
        if any(part in EXCLUDE_DIRS for part in path.relative_to(REPO_ROOT).parts):
            continue
        yield path


def check_ast(report: dict) -> None:
    files = list(iter_python_files())
    report["python_files_checked"] = len(files)
    bad = []
    for path in files:
        try:
            ast.parse(path.read_text(encoding="utf-8"),
                      filename=str(path.relative_to(REPO_ROOT)))
        except (SyntaxError, UnicodeDecodeError) as exc:
            bad.append(f"{path.relative_to(REPO_ROOT)}: {exc}")
    report["python_ast_errors"] = bad


def check_json(report: dict) -> None:
    loaded: dict[str, object] = {}
    bad: list[str] = []
    missing: list[str] = []
    for rel in JSON_FILES:
        path = REPO_ROOT / rel
        if not path.exists():
            missing.append(rel)
            continue
        try:
            loaded[rel] = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            bad.append(f"{rel}: {exc}")
    report["json_bad"] = bad
    report["json_missing"] = missing
    report["json_loaded"] = sorted(loaded)
    check_actions(report, loaded)
    check_progress(report, loaded)
    check_configs(report, loaded)
    check_manifest_shas(report, loaded)


def check_actions(report: dict, loaded: dict[str, object]) -> None:
    shapes: list[str] = []
    closed: dict[str, bool | None] = {}
    for rel in ("economic-atlas/actions.json", "shock-radar/actions.json"):
        actions = loaded.get(rel)
        if not isinstance(actions, list):
            shapes.append(f"{rel}: top level is not a list")
            continue
        for i, entry in enumerate(actions):
            if not isinstance(entry, dict):
                shapes.append(f"{rel}[{i}]: not an object")
                continue
            for key, want in ACTION_KEYS.items():
                if key not in entry:
                    shapes.append(f"{rel}[{i}]: missing key {key!r}")
                elif not isinstance(entry[key], want):
                    shapes.append(
                        f"{rel}[{i}]: key {key!r} has type "
                        f"{type(entry[key]).__name__}, want {want}")
        marker = "05." if "economic-atlas" in rel else "07."
        for entry in actions:
            if isinstance(entry, dict) and str(entry.get("what", "")).startswith(marker):
                closed[rel] = bool(entry.get("done")) if "done" in entry else None
    report["actions_shape_errors"] = shapes
    report["closed_source"] = closed


def check_progress(report: dict, loaded: dict[str, object]) -> None:
    progress = loaded.get("agents/progress.json")
    text = json.dumps(progress, ensure_ascii=False) if progress is not None else ""
    report["progress_mentions_A6"] = "A6" in text
    report["progress_mentions_R8"] = "R8" in text


def check_configs(report: dict, loaded: dict[str, object]) -> None:
    seeds: dict[str, object] = {}
    problems: list[str] = []
    for rel in ("economic-atlas/config.json", "shock-radar/config.json"):
        cfg = loaded.get(rel)
        if not isinstance(cfg, dict):
            problems.append(f"{rel}: not an object")
            continue
        seed = cfg.get("seed")
        seeds[rel] = seed
        if not isinstance(seed, int):
            problems.append(f"{rel}: seed is not int: {seed!r}")
    report["config_seeds"] = seeds
    report["config_problems"] = problems


def iter_sha_entries(obj: object, path: str = "$"):
    if isinstance(obj, dict):
        for key, value in obj.items():
            here = f"{path}.{key}"
            if key == "sha256" and isinstance(value, str):
                yield here, value
            else:
                yield from iter_sha_entries(value, here)
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            yield from iter_sha_entries(value, f"{path}[{i}]")


def check_manifest_shas(report: dict, loaded: dict[str, object]) -> None:
    empty: list[str] = []
    count = 0
    for rel, obj in loaded.items():
        for where, value in iter_sha_entries(obj):
            count += 1
            if not value.strip():
                empty.append(f"{rel}:{where}")
    report["sha256_fields"] = count
    report["sha256_empty"] = empty


def check_evidence(report: dict) -> None:
    missing = [rel for rel in EVIDENCE_REQUIRED if not (REPO_ROOT / rel).exists()]
    absent_optional = [rel for rel in EVIDENCE_OPTIONAL if not (REPO_ROOT / rel).exists()]
    report["evidence_missing"] = missing
    report["evidence_optional_absent"] = absent_optional


def check_hashes(report: dict) -> None:
    checked: dict[str, str] = {}
    errors: list[str] = []
    for rel in EVIDENCE_REQUIRED:
        path = REPO_ROOT / rel
        if path.is_file():
            try:
                checked[rel] = sha256_file(path)
            except OSError as exc:
                errors.append(f"{rel}: {exc}")
    report["hashes_recomputed"] = checked
    report["hash_errors"] = errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Stdlib-only validator for the sberindex-2026 repository.")
    parser.add_argument("--check-hashes", action="store_true",
                        help="recompute SHA256 of present evidence files "
                             "(slow on large parquets, opt-in)")
    parser.add_argument("--report", default=None,
                        help="write JSON report to this path (repo-relative or absolute)")
    args = parser.parse_args(argv)

    report: dict[str, object] = {"repo_root": str(REPO_ROOT)}
    check_ast(report)
    check_json(report)
    check_evidence(report)
    if args.check_hashes:
        check_hashes(report)

    failures = (
        report["python_ast_errors"]
        + report["json_bad"]
        + report["json_missing"]
        + report["actions_shape_errors"]
        + report["config_problems"]
        + report["evidence_missing"]
        + report["sha256_empty"]
    )
    report["failures"] = failures
    report["ok"] = not failures

    print(f"python files AST-checked: {report['python_files_checked']}, "
          f"errors: {len(report['python_ast_errors'])}")
    for item in report["python_ast_errors"]:
        print(f"  AST-FAIL {item}")
    print(f"json loaded: {len(report['json_loaded'])}, bad: {len(report['json_bad'])}, "
          f"missing: {len(report['json_missing'])}")
    for item in report["json_bad"] + report["json_missing"]:
        print(f"  JSON-FAIL {item}")
    print(f"actions shape errors: {len(report['actions_shape_errors'])}")
    for item in report["actions_shape_errors"]:
        print(f"  ACTIONS-FAIL {item}")
    print(f"closed-source flags: {report['closed_source']}")
    print(f"progress mentions A6/R8: {report['progress_mentions_A6']}/"
          f"{report['progress_mentions_R8']}")
    print(f"config seeds: {report['config_seeds']}")
    for item in report["config_problems"]:
        print(f"  CONFIG-FAIL {item}")
    print(f"sha256 fields: {report['sha256_fields']}, empty: {len(report['sha256_empty'])}")
    print(f"evidence missing: {len(report['evidence_missing'])}; "
          f"optional absent: {report['evidence_optional_absent']}")
    for item in report["evidence_missing"]:
        print(f"  EVIDENCE-FAIL {item}")
    if args.report:
        out = Path(args.report)
        out = out if out.is_absolute() else REPO_ROOT / out
        out.write_text(json.dumps(report, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        print(f"report written to {out}")
    print("VALIDATE: " + ("OK" if report["ok"] else "FAILURES"))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
