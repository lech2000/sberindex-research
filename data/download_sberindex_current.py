#!/usr/bin/env python3
"""Download the public SberIndex dashboard datasets through the site's SOWA API.

Requires pyarrow. For an isolated install:
  uv pip install --target /tmp/sberindex-python-deps pyarrow
  PYTHONPATH=/tmp/sberindex-python-deps python download_sberindex_current.py
"""

from __future__ import annotations

import argparse
import base64
import concurrent.futures
import hashlib
import json
import math
import os
import random
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq


API_URL = "https://sberindex.ru/api/sowa"
DATASETS = {
    "municipal-consumer-spending": {
        "slug": "potrebitelskie-beznalicnye-rashody-na-urovne-munizipalnyh-obrazovanij",
        "referer": "https://sberindex.ru/ru/dashboards/potrebitelskie-beznalicnye-rashody-na-urovne-munizipalnyh-obrazovanij",
    },
    "mobility-index": {
        "slug": "indeks-mobilnosti",
        "referer": "https://sberindex.ru/ru/dashboards/indeks-mobilnosti",
    },
}


def decode_sowa(value, declared_type=None):
    if isinstance(value, list):
        return [decode_sowa(item) for item in value]
    if isinstance(value, dict) and value.get("type") == "object":
        return {
            item["key"]: decode_sowa(item.get("value"), item.get("type"))
            for item in value.get("value", [])
        }
    if not isinstance(value, str):
        return value
    match = re.match(r"^__([a-z0-9]*)__(.*)$", value, flags=re.S)
    if not match:
        return value
    encoded_type, payload = match.groups()
    value_type = declared_type or encoded_type
    if value_type == "null":
        return None
    if value_type == "boolean":
        return payload == "true"
    if value_type == "number":
        number = float(payload)
        return int(number) if number.is_integer() else number
    if value_type == "string":
        return base64.b64decode(payload).decode("utf-8")
    return payload


def request_page(slug: str, referer: str, limit: int, offset: int, attempts: int = 4):
    route = f"/dataset/v1/{slug}?limit={limit}&offset={offset}"
    body = json.dumps(
        {
            "SOWA": {
                "method": "GET",
                "route": base64.b64encode(route.encode()).decode(),
                "data": {"type": "object", "value": []},
            }
        }
    ).encode()
    for attempt in range(1, attempts + 1):
        try:
            completed = subprocess.run(
                [
                    "/usr/bin/curl",
                    "--fail",
                    "--silent",
                    "--show-error",
                    "--retry",
                    "2",
                    API_URL,
                    "-H",
                    "content-type: application/json",
                    "-H",
                    f"RqUID: {random.getrandbits(128):032x}",
                    "-H",
                    "X-Language: ru",
                    "-H",
                    "Origin: https://sberindex.ru",
                    "-H",
                    f"Referer: {referer}",
                    "-H",
                    "User-Agent: aiOS2-SberIndex-research/1.0",
                    "--data-binary",
                    "@-",
                ],
                input=body,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
                timeout=120,
            )
            raw = json.loads(completed.stdout)
            decoded = decode_sowa(raw["SOWA"]["data"])
            if "errors" in decoded:
                raise RuntimeError(decoded.get("message") or str(decoded["errors"]))
            return decoded
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, RuntimeError, json.JSONDecodeError):
            if attempt == attempts:
                raise
            time.sleep(attempt * 2)


def table_from_page(fields, rows):
    columns = {field: [] for field in fields}
    for row in rows:
        for field, value in zip(fields, row):
            columns[field].append(value)
    arrays = {}
    for field, values in columns.items():
        if field == "value":
            arrays[field] = pa.array(values, type=pa.float64())
        else:
            arrays[field] = pa.array(
                [None if value is None else str(value) for value in values],
                type=pa.string(),
            )
    return pa.table(arrays)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def download_dataset(name: str, config: dict, out_dir: Path, workers: int):
    limit = 10_000
    first = request_page(config["slug"], config["referer"], limit, 0)
    total = int(first["pagination"]["total_records"])
    fields = first["fields"]
    offsets = list(range(0, total, limit))
    pages = {0: first}

    def fetch(offset):
        return offset, request_page(config["slug"], config["referer"], limit, offset)

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(fetch, offset) for offset in offsets[1:]]
        for future in concurrent.futures.as_completed(futures):
            offset, page = future.result()
            pages[offset] = page
            print(f"{name}: {min(offset + len(page['data']), total)}/{total}", flush=True)

    destination = out_dir / f"{name}.parquet"
    temporary = destination.with_suffix(".parquet.part")
    writer = None
    row_count = 0
    try:
        for offset in offsets:
            page = pages[offset]
            table = table_from_page(fields, page["data"])
            if writer is None:
                writer = pq.ParquetWriter(temporary, table.schema, compression="zstd")
            writer.write_table(table)
            row_count += table.num_rows
    finally:
        if writer is not None:
            writer.close()
    if row_count != total:
        raise RuntimeError(f"{name}: expected {total} rows, wrote {row_count}")
    os.replace(temporary, destination)

    return {
        "name": name,
        "dashboard_url": config["referer"],
        "api_route": f"/dataset/v1/{config['slug']}",
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "rows": row_count,
        "columns": fields,
        "bytes": destination.stat().st_size,
        "sha256": sha256(destination),
        "file": str(destination),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out",
        default=str(Path(__file__).resolve().parent / "raw" / "sberindex-dashboard-current"),
    )
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "source": "SberIndex public dashboard API",
        "api_url": API_URL,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "datasets": [],
    }
    for name, config in DATASETS.items():
        manifest["datasets"].append(download_dataset(name, config, out_dir, args.workers))

    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(f"Wrote {manifest_path}")


if __name__ == "__main__":
    main()
