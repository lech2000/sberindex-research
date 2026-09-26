"""Idempotently seed the municipality-graph staging corpus with reviewed inputs."""
from __future__ import annotations

import json
import os
from pathlib import Path

import httpx


ROOT = Path(__file__).resolve().parents[1]
KB = os.getenv("KB_FORGE_URL", "http://127.0.0.1:8300").rstrip("/")
CASE_ID = "case_43de12a8dc2e4abd"
DOCS = (
    ("model-lab/ARCHITECTURE.md", "Архитектура доказательного графа муниципалитетов", "architecture"),
    ("model-lab/loaded-data-audit.json", "Аудит загруженных муниципальных данных", "loaded_data_audit"),
    ("graph/OPERATIONS.md", "Эксплуатационный контракт Graph Steward", "operations"),
    ("graph/evidence.schema.json", "Схема staging evidence муниципального графа", "evidence_schema"),
    ("graph/curator.schema.json", "Схема решения куратора исследований", "curator_schema"),
)


def main() -> None:
    receipts = []
    with httpx.Client(timeout=120) as client:
        for relative, title, kind in DOCS:
            path = ROOT / relative
            response = client.post(f"{KB}/api/corpora/77/documents/integrate", json={
                "title": title,
                "url": f"https://agrigate.pro/v2/#case/{CASE_ID}",
                "text": path.read_text(encoding="utf-8"),
                "meta": {
                    "project": "sberindex-2026",
                    "case_id": CASE_ID,
                    "kind": kind,
                    "verified_on": "2026-09-20",
                    "verified_at": "local bridge 127.0.0.1:8300",
                    "source_path": relative,
                },
            })
            response.raise_for_status()
            receipts.append({"source": relative, "receipt": response.json()})
    print(json.dumps({"corpus_id": 77, "documents": receipts}, ensure_ascii=False))


if __name__ == "__main__":
    main()
