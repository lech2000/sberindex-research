#!/usr/bin/env python3
"""Execute the five GM1 contract queries on a disposable local PostgreSQL DB."""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from pathlib import Path


HERE = Path(__file__).resolve().parent
SCHEMA = HERE / "GM1_SCHEMA_2026-10-01.md"
FIXTURE = """
CREATE TABLE administrative_identity (
 identity_id text, municipality_id text, system text, code text,
 valid_from date, valid_to date, evidence_status text);
CREATE TABLE dataset_release (release_id text, publisher text);
CREATE TABLE observation (
 observation_id text, municipality_id text, indicator_id text,
 period_start date, period_end date, canonical_dimension_key text,
 release_id text, vintage text, obs_status text, value numeric,
 provenance_class text, available_at timestamptz);
CREATE TABLE experiment_input (
 run_id text, observation_id text, role text, origin_at timestamptz);
INSERT INTO administrative_identity VALUES
 ('a','m1','OKTMO','001','2023-01-01',NULL,'verified'),
 ('b','m2','OKTMO','001','2024-01-01',NULL,'verified');
INSERT INTO dataset_release VALUES ('r1','СберИндекс');
INSERT INTO observation VALUES
 ('o1','m1','spend','2024-01-01','2024-02-01','food','r1','v1','A',10,
  'observed','2025-01-01'),
 ('o2','m2','spend','2024-01-01','2024-02-01','food','r1','v1','A',11,
  'synthetic_assumption','2024-01-01'),
 ('o3','m1','spend','2024-02-01','2024-03-01','food','r1','v1','A',12,
  'observed','2024-03-01'),
 ('o4','m1','spend','2024-02-01','2024-03-01','food','r1','v1','A',12,
  'observed','2024-03-01');
INSERT INTO experiment_input VALUES
 ('run','o1','train_feature','2024-06-01'),
 ('run','o2','measured_evaluation','2024-06-01');
"""


def run(*args: str) -> str:
    result = subprocess.run(
        args, text=True, capture_output=True, env={**os.environ, "LC_ALL": "C", "LANG": "C"}
    )
    if result.returncode:
        raise RuntimeError(f"{args[0]} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def queries() -> list[str]:
    body = SCHEMA.read_text()
    found = re.findall(r"(?m)^Q[1-5]\. .*?\n\n((?:    [^\n]*\n)+)", body)
    if len(found) != 5:
        raise ValueError(f"expected five SQL blocks, got {len(found)}")
    return ["\n".join(line[4:] for line in block.splitlines()).rstrip(";")
            for block in found]


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="gm1-pg-") as directory:
        root = Path(directory)
        data = root / "data"
        run("initdb", "-D", str(data), "-A", "trust", "-U", "gm1")
        options = f"-c listen_addresses='' -k {root} -p 55449"
        run("pg_ctl", "-D", str(data), "-l", str(root / "postgres.log"),
            "-o", options, "-w", "start")
        try:
            base = ("psql", "-h", str(root), "-p", "55449", "-U", "gm1",
                    "-d", "postgres", "-v", "ON_ERROR_STOP=1", "-At")
            run(*base, "-c", FIXTURE)
            counts = [int(run(*base, "-c", f"SELECT COUNT(*) FROM ({query}) q"))
                      for query in queries()]
            assert counts == [1, 1, 1, 2, 1], counts
            print(json.dumps({"query_counts": counts, "pass": True}))
        finally:
            run("pg_ctl", "-D", str(data), "-m", "immediate", "-w", "stop")


if __name__ == "__main__":
    main()
