"""Shared contracts for prospectively specified A9--A13 runs."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import platform
import sys
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

import numpy as np
import pandas as pd

ATLAS = Path(__file__).resolve().parents[1]
SRC = ATLAS / "src"
RUN_NAMES = {9: "A9_economic_network_20261005", 10: "A10_method_comparison_20261005",
             11: "A11_icvi_table_20261005", 12: "A12_stable_cores_20261005",
             13: "A13_reproduction_20261005"}
SEED = 20261005
KS = (3, 5, 8)
SEEDS = tuple(range(SEED, SEED + 5))
CONFIGS = tuple((k, mode, weight) for k in (5, 7, 10)
                for mode in ("union", "mutual") for weight in ("gaussian", "binary"))
PRIMARY_CONFIG = "k7_union_gaussian"


def run_dir(number):
    return ATLAS / "runs" / RUN_NAMES[number]


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for part in iter(lambda: stream.read(1 << 20), b""):
            h.update(part)
    return h.hexdigest()


def clean(value):
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, np.ndarray):
        return clean(value.tolist())
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, np.bool_):
        return bool(value)
    return value


def write_json(path, value):
    Path(path).write_text(json.dumps(clean(value), ensure_ascii=False, indent=2,
                                   allow_nan=False) + "\n", encoding="utf-8")


def markdown_table(frame):
    def cell(value):
        return str(value).replace("|", "\\|").replace("\n", " ")
    columns = list(frame.columns)
    lines = ["| " + " | ".join(map(cell, columns)) + " |",
             "| " + " | ".join("---" for _ in columns) + " |"]
    lines.extend("| " + " | ".join(map(cell, row)) + " |" for row in frame.itertuples(index=False, name=None))
    return "\n".join(lines)


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def input_paths(external=False):
    paths = {"features": ATLAS / "runs/A5/features.parquet",
             "assignments": ATLAS / "runs/A5/assignments.parquet",
             "geo_edges": ATLAS / "runs/A5/edges.parquet",
             "panel": ATLAS / "data/panel_v1.parquet",
             "spec": ATLAS / "features/spec.yaml"}
    if external:
        for key in ("SBERINDEX_DATA_SENSE_DIR", "SBERINDEX_MUNICIPAL_DICTIONARY"):
            if not os.environ.get(key):
                raise ValueError(f"Required external input variable: {key}")
        paths["population"] = Path(os.environ["SBERINDEX_DATA_SENSE_DIR"]) / "2_bdmo_population.parquet"
        paths["dictionary"] = Path(os.environ["SBERINDEX_MUNICIPAL_DICTIONARY"])
    return paths


def check_inputs(external=False):
    expected = json.loads((ATLAS / "frozen_inputs.json").read_text())
    paths = input_paths(external)
    for key, path in paths.items():
        if not path.is_file() or sha(path) != expected[key]["sha256"]:
            raise ValueError(f"Frozen input hash mismatch/missing: {key}")
    freeze = json.loads((run_dir(13) / "protocol-freeze.json").read_text())
    for name, digest in freeze["protocol_sha256"].items():
        if sha(ATLAS / "runs" / name / "PROTOCOL.md") != digest:
            raise ValueError(f"Protocol changed after freeze: {name}")
    return paths


def load_features():
    paths = check_inputs()
    features = pd.read_parquet(paths["features"]).sort_values("territory_id").reset_index(drop=True)
    assignments = pd.read_parquet(paths["assignments"])
    if not features.territory_id.is_unique or not assignments.territory_id.is_unique:
        raise ValueError("Duplicate A5 territory keys")
    if len(features) != 1896 or set(features.territory_id) != set(assignments.territory_id):
        raise ValueError("A5 mask differs from frozen 1896 nodes")
    cols = [c for c in features if c.startswith("z_")]
    x = features[cols].to_numpy(float)
    if x.shape != (1896, 5) or not np.isfinite(x).all():
        raise ValueError("Invalid A5 features")
    return features.territory_id.to_numpy(int), x


def load_monthly():
    import a6_temporal as a6
    paths = check_inputs()
    panel = pd.read_parquet(paths["panel"])
    tids, months, shares, audit = a6.build_monthly_shares(panel)
    ids, _ = load_features()
    if not np.array_equal(tids, ids) or len(months) != 24:
        raise ValueError("Monthly mask is not identical to A5; no silent intersection")
    z, transform = a6.standardize_frozen(shares, months)
    return tids, months, shares, z, transform


def annual_features():
    tids, months, shares, z, transform = load_monthly()
    return tids, {"annual" + str(y): z[:, [i for i, m in enumerate(months) if m.startswith(str(y))]].mean(1)
                  for y in (2023, 2024)}, transform


def config_name(k, mode, weight):
    return f"k{k}_{mode}_{weight}"


def provenance(number, external=False, dependencies=()):
    directory = run_dir(number)
    inputs = check_inputs(external)
    files = list(SRC.glob("atlas_*.py")) + [SRC / "a6_temporal.py", SRC / "network_icvi.py",
            ATLAS / "runs/A7_stories_20261004/build_stories.py"]
    outputs = [p for p in directory.rglob("*") if p.is_file()
               and p.name not in {"PROTOCOL.md", "provenance.json"} and "__pycache__" not in p.parts]
    deps = {str(p.relative_to(ATLAS)): sha(p) for p in dependencies}
    write_json(directory / "provenance.json", {
        "run_id": RUN_NAMES[number], "status": "COMPUTED_DESCRIPTIVE",
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "verification_location": "isolated macOS checkout; local Python process",
        "base_commit": "d67f80960895d77515cdc3ea7f9f197be97c2cd2",
        "protocol_sha256": sha(directory / "PROTOCOL.md"),
        "input_sha256": {key: sha(p) for key, p in inputs.items()},
        "code_sha256": {str(p.relative_to(ATLAS)): sha(p) for p in files},
        "dependency_sha256": deps,
        "output_sha256": {str(p.relative_to(directory)): sha(p) for p in outputs},
        "seed": SEED, "python": platform.python_version(),
        "versions": {n: version(n) for n in ["numpy", "pandas", "pyarrow", "scipy", "scikit-learn", "networkx"]},
        "limits": ["descriptive; no new independent 2025 test", "local protocol timestamp, not externally witnessed"]})


def verify_artifacts(number):
    d = run_dir(number)
    p = json.loads((d / "provenance.json").read_text())
    if p["protocol_sha256"] != sha(d / "PROTOCOL.md"):
        raise ValueError("Upstream protocol changed")
    for name, digest in p["output_sha256"].items():
        if sha(d / name) != digest:
            raise ValueError(f"Upstream output changed: {number}/{name}")
    for name, digest in p["code_sha256"].items():
        if sha(ATLAS / name) != digest:
            raise ValueError(f"Upstream code changed: {name}")
