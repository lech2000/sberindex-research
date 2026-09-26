"""Standalone reproduction driver for the sberindex-2026 repository.

Assumes the repository root IS deliverables/sberindex-2026
(economic-atlas/, shock-radar/, data/, ... directly under it).

Only invokes the existing CLI modules via checked subprocess calls;
no hidden platform calls, no downloads, no network, no LLM, no credentials.

Self-checks (no input data needed, no downloads, no LLM)::

    python3 reproduce.py --self-check
    python3 reproduce.py --self-check --stage a5

Actual runs (explicit paths, read-only archived runs,
outputs always under --output-root, default output/reproduced)::

    python3 reproduce.py --stage all --output-root output/reproduced
    python3 reproduce.py --stage a5 --panel economic-atlas/data/panel_v1.parquet \\
        --distance data/raw/sberindex-data-sense-2025/5_connection.parquet
    python3 reproduce.py --stage r7 --panel-raw8 <8_consumption.parquet> \\
        --registry shock-radar/events/registry.parquet

Verified snapshot facts (2026-09-26, do not invent others):
- frozen panel: economic-atlas/data/panel_v1.parquet (runs/A3/ does NOT
  exist in this snapshot, so there is no runs/A3/panel_frozen.parquet;
  --panel defaults to panel_v1.parquet).
- distance table: data/raw/sberindex-data-sense-2025/5_connection.parquet
  (path from a5_graph.py DEFAULT_DISTANCE; file is a gitignored download
  and is absent from this snapshot -> A5 actual run needs it placed there).
- R7 raw8 panel: data/raw/sberindex-data-sense-2025/8_consumption.parquet
  (path from r7_causal_signal.py PANEL_DEFAULT; likewise a gitignored
  download, absent here -> R7 actual run needs it placed there).
- R7 registry: shock-radar/events/registry.parquet (present).
- R8 inputs: shock-radar/events/news_events.json +
  shock-radar/events/news_features.parquet, cutoff 2024-12-31 (present).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

ATLAS_SRC = REPO_ROOT / "economic-atlas" / "src"
RADAR_SRC = REPO_ROOT / "shock-radar" / "src"

A4_SCRIPT = ATLAS_SRC / "a4_metrics.py"
A5_SCRIPT = ATLAS_SRC / "a5_graph.py"
A6_SCRIPT = ATLAS_SRC / "a6_temporal.py"
R7_SIGNAL_SCRIPT = RADAR_SRC / "r7_causal_signal.py"
R7_DETECTORS_SCRIPT = RADAR_SRC / "d02_d03_detectors.py"
R8_SCRIPT = RADAR_SRC / "r8_news_audit.py"

SELF_CHECK_SCRIPTS = (
    ("a4_metrics", A4_SCRIPT),
    ("a5_graph", A5_SCRIPT),
    ("a6_temporal", A6_SCRIPT),
    ("r7_causal_signal", R7_SIGNAL_SCRIPT),
    ("d02_d03_detectors", R7_DETECTORS_SCRIPT),
    ("r8_news_audit", R8_SCRIPT),
)

STAGE_OF_SCRIPT = {
    "a4_metrics": "a4",
    "a5_graph": "a5",
    "a6_temporal": "a6",
    "r7_causal_signal": "r7",
    "d02_d03_detectors": "r7",
    "r8_news_audit": "r8",
}

DEFAULT_PANEL = Path("economic-atlas/data/panel_v1.parquet")
DEFAULT_DISTANCE = Path("data/raw/sberindex-data-sense-2025/5_connection.parquet")
DEFAULT_PANEL_RAW8 = Path("data/raw/sberindex-data-sense-2025/8_consumption.parquet")
DEFAULT_REGISTRY = Path("shock-radar/events/registry.parquet")
DEFAULT_NEWS_EVENTS = Path("shock-radar/events/news_events.json")
DEFAULT_NEWS_FEATURES = Path("shock-radar/events/news_features.parquet")
DEFAULT_A4_KMEANS = Path("economic-atlas/runs/A4/kmeans.json")
DEFAULT_A4_AGGLOMERATIVE = Path("economic-atlas/runs/A4/agglomerative.json")
DEFAULT_OUTPUT_ROOT = Path("output/reproduced")

A5_SEED = 20260921
A6_SEED = 20260921
R7_BUDGET_MODE = "monthly_causal"
R7_BUDGET = 24
R7_COOLDOWN = 3
R8_CUTOFF = "2024-12-31"

ARCHIVED_RUN_DIRS = (
    REPO_ROOT / "economic-atlas" / "runs",
    REPO_ROOT / "shock-radar" / "runs",
)


def repo_path(value: str | Path) -> Path:
    p = Path(value)
    return p if p.is_absolute() else REPO_ROOT / p


def run_checked(cmd: list[str]) -> None:
    print("+ " + " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)


def ensure_readonly_archived(output_root: Path) -> None:
    out = output_root.resolve()
    for archived in ARCHIVED_RUN_DIRS:
        a = archived.resolve()
        if out == a or a in out.parents:
            raise ValueError(
                f"--output-root {output_root} is inside archived runs {archived}; "
                "archived runs are read-only, pick an independent directory"
            )


def require_files(paths: list[Path], what: str) -> None:
    missing = [str(p) for p in paths if not p.exists()]
    if missing:
        raise FileNotFoundError(
            f"{what} needs missing input file(s) (no downloads are performed):\n"
            + "\n".join(f"  - {m}" for m in missing)
        )


def self_check(stage: str) -> int:
    names = [
        name
        for name, _ in SELF_CHECK_SCRIPTS
        if stage == "all" or STAGE_OF_SCRIPT[name] == stage
    ]
    if stage != "all" and not names:
        raise ValueError(f"nothing self-checkable for stage {stage!r}")
    for name, script in SELF_CHECK_SCRIPTS:
        if name not in names:
            continue
        require_files([script], f"self-check {name}")
        run_checked([sys.executable, str(script), "--self-check"])
        print(f"self-check {name}: PASS", flush=True)
    return 0


def run_a4(args: argparse.Namespace, outdir: Path) -> dict:
    kmeans = repo_path(args.kmeans)
    agglomerative = repo_path(args.agglomerative)
    require_files([A4_SCRIPT, kmeans, agglomerative], "stage a4")
    outdir.mkdir(parents=True, exist_ok=True)
    out = outdir / "metrics.json"
    cmd = [sys.executable, str(A4_SCRIPT), "--kmeans", str(kmeans),
           "--agglomerative", str(agglomerative), "--out", str(out)]
    run_checked(cmd)
    return {"cmd": cmd, "out": str(out)}


def run_a5(args: argparse.Namespace, outdir: Path) -> dict:
    panel = repo_path(args.panel)
    distance = repo_path(args.distance)
    require_files([A5_SCRIPT, panel, distance], "stage a5")
    outdir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(A5_SCRIPT), "--panel", str(panel),
           "--distance", str(distance), "--outdir", str(outdir),
           "--seed", str(A5_SEED), "--k", "5"]
    run_checked(cmd)
    return {"cmd": cmd, "outdir": str(outdir)}


def run_a6(args: argparse.Namespace, outdir: Path) -> dict:
    panel = repo_path(args.panel)
    require_files([A6_SCRIPT, panel], "stage a6 (frozen panel from this repo)")
    outdir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(A6_SCRIPT), "--panel", str(panel),
           "--outdir", str(outdir), "--seed", str(A6_SEED)]
    run_checked(cmd)
    return {"cmd": cmd, "outdir": str(outdir)}


def build_eligible_registry(signal_manifest: Path, registry: Path, out: Path) -> int:
    try:
        import pandas as pd
    except ImportError as exc:
        raise RuntimeError(
            "stage r7 needs pandas to build registry_eligible.parquet; "
            "install requirements-science.txt or run --self-check only"
        ) from exc
    manifest = json.loads(signal_manifest.read_text(encoding="utf-8"))
    try:
        eligible = set(map(str, manifest["registry"]["eligible_ids"]))
    except KeyError as exc:
        raise ValueError(
            f"{signal_manifest} has no registry.eligible_ids; "
            "signal step output is unusable"
        ) from exc
    reg = pd.read_parquet(registry)
    filt = reg[reg["event_id"].astype(str).isin(eligible)].reset_index(drop=True)
    filt.to_parquet(out, index=False)
    return int(len(filt))


def run_r7(args: argparse.Namespace, outdir: Path) -> dict:
    panel_raw8 = repo_path(args.panel_raw8)
    registry = repo_path(args.registry)
    require_files([R7_SIGNAL_SCRIPT, R7_DETECTORS_SCRIPT, panel_raw8, registry],
                  "stage r7")
    signal_dir = outdir / "signal"
    signal_dir.mkdir(parents=True, exist_ok=True)
    signal_cmd = [sys.executable, str(R7_SIGNAL_SCRIPT), "--panel", str(panel_raw8),
                  "--registry", str(registry), "--outdir", str(signal_dir)]
    run_checked(signal_cmd)
    signal_parquet = signal_dir / "signal.parquet"
    signal_manifest = signal_dir / "manifest.json"
    require_files([signal_parquet, signal_manifest], "stage r7 signal output")
    eligible_path = outdir / "registry_eligible.parquet"
    n_eligible = build_eligible_registry(signal_manifest, registry, eligible_path)
    print(f"r7 eligible registry: {n_eligible} events -> {eligible_path}", flush=True)
    detectors_dir = outdir / "detectors"
    detectors_dir.mkdir(parents=True, exist_ok=True)
    detectors_cmd = [sys.executable, str(R7_DETECTORS_SCRIPT),
                     "--cus", str(signal_parquet), "--registry", str(eligible_path),
                     "--outdir", str(detectors_dir),
                     "--budget-mode", R7_BUDGET_MODE,
                     "--budget", str(R7_BUDGET), "--cooldown", str(R7_COOLDOWN)]
    run_checked(detectors_cmd)
    return {"signal_cmd": signal_cmd, "detectors_cmd": detectors_cmd,
            "signal": str(signal_parquet),
            "registry_eligible": str(eligible_path),
            "n_eligible": n_eligible, "outdir": str(detectors_dir)}


def run_r8(args: argparse.Namespace, outdir: Path) -> dict:
    events = repo_path(args.news_events)
    features = repo_path(args.news_features)
    require_files([R8_SCRIPT, events, features], "stage r8")
    outdir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(R8_SCRIPT), "--news-events", str(events),
           "--news-features", str(features), "--cutoff", args.cutoff,
           "--outdir", str(outdir)]
    run_checked(cmd)
    return {"cmd": cmd, "outdir": str(outdir)}


STAGES = ("a4", "a5", "a6", "r7", "r8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Reproduce sberindex-2026 stages a4/a5/a6/r7/r8 "
                    "via the existing CLI modules (checked subprocess calls only).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--self-check", action="store_true",
                   help="run each module with --self-check (no data, no downloads, "
                        "no LLM) and exit")
    p.add_argument("--stage", default="all", choices=(*STAGES, "all"),
                   help="which stage to reproduce (default: all)")
    p.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT),
                   help="independent output root, never inside archived runs "
                        f"(default: {DEFAULT_OUTPUT_ROOT})")
    p.add_argument("--panel", default=str(DEFAULT_PANEL),
                   help=f"frozen panel for a5/a6 (default: {DEFAULT_PANEL})")
    p.add_argument("--distance", default=str(DEFAULT_DISTANCE),
                   help=f"distance table for a5 (default: {DEFAULT_DISTANCE})")
    p.add_argument("--panel-raw8", default=str(DEFAULT_PANEL_RAW8),
                   help=f"raw8 consumption panel for r7 signal (default: {DEFAULT_PANEL_RAW8})")
    p.add_argument("--registry", default=str(DEFAULT_REGISTRY),
                   help=f"synthetic event registry for r7 (default: {DEFAULT_REGISTRY})")
    p.add_argument("--news-events", default=str(DEFAULT_NEWS_EVENTS),
                   help=f"news events JSON for r8 (default: {DEFAULT_NEWS_EVENTS})")
    p.add_argument("--news-features", default=str(DEFAULT_NEWS_FEATURES),
                   help=f"news features parquet for r8 (default: {DEFAULT_NEWS_FEATURES})")
    p.add_argument("--cutoff", default=R8_CUTOFF,
                   help=f"as-of cutoff for r8 (default: {R8_CUTOFF})")
    p.add_argument("--kmeans", default=str(DEFAULT_A4_KMEANS),
                   help=f"kmeans result JSON for a4 (default: {DEFAULT_A4_KMEANS})")
    p.add_argument("--agglomerative", default=str(DEFAULT_A4_AGGLOMERATIVE),
                   help=f"agglomerative result JSON for a4 (default: {DEFAULT_A4_AGGLOMERATIVE})")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.self_check:
        return self_check(args.stage)
    output_root = repo_path(args.output_root)
    ensure_readonly_archived(output_root)
    stages = list(STAGES) if args.stage == "all" else [args.stage]
    results: dict[str, dict] = {}
    runners = {"a4": run_a4, "a5": run_a5, "a6": run_a6,
               "r7": run_r7, "r8": run_r8}
    for stage in stages:
        results[stage] = runners[stage](args, output_root / stage)
        print(f"stage {stage}: DONE -> {results[stage]}", flush=True)
    manifest = {
        "run_utc": datetime.now(timezone.utc).isoformat(),
        "repo_root": str(REPO_ROOT),
        "output_root": str(output_root),
        "stages": results,
    }
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "reproduce_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
