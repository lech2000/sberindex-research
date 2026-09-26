#!/usr/bin/env python3
"""Index SberIndex research passports in the developer's kb-forge corpus.

Run inside the aiOS2 container, where kb-forge is reachable. Binary datasets
remain in workspace storage and are referenced by hashes in the indexed text.
"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
KB = "http://10.189.141.165:8300"
CORPUS_ID = 61
EXPECTED_CORPUS_NAME = "practice:software:developer:prn_fbab9aa00cd46169"


def request(method: str, url: str, body: dict | None = None):
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode()
    headers = {"content-type": "application/json"} if body is not None else {}
    with urllib.request.urlopen(
        urllib.request.Request(url, data=data, headers=headers, method=method), timeout=240
    ) as response:
        return json.loads(response.read())


def main() -> None:
    corpora = request("GET", f"{KB}/api/corpora")
    corpus = next((item for item in corpora if item.get("id") == CORPUS_ID), None)
    if not corpus or corpus.get("name") != EXPECTED_CORPUS_NAME:
        raise RuntimeError("Developer kb-forge corpus 61 is missing or has changed identity")

    documents = [
        {
            "title": "СберИндекс 2026 — общий каталог данных",
            "path": ROOT / "data" / "DATA_CATALOG.md",
            "url": "https://sber.ru/sberindex/konkurs_sberindex",
            "meta": {"project": "both", "kind": "data_catalog", "verified_on": "2026-09-20"},
        },
        {
            "title": "СберИндекс 2026 — схема и качество загруженных данных",
            "path": ROOT / "data" / "schema-report.json",
            "url": "https://sber.ru/sberindex/konkurs_sberindex",
            "meta": {"project": "both", "kind": "schema_report", "verified_on": "2026-09-20"},
        },
        {
            "title": "СберИндекс 2026 — исследовательские агенты и лестница источников",
            "path": ROOT / "agents" / "README.md",
            "url": "https://sber.ru/sberindex/konkurs_sberindex",
            "meta": {"project": "both", "kind": "agent_policy", "verified_on": "2026-09-20"},
        },
        {
            "title": "СберИндекс 2026 — предложение реализации",
            "path": ROOT / "IMPLEMENTATION_PROPOSAL.md",
            "url": "https://sber.ru/sberindex/konkurs_sberindex",
            "meta": {"project": "both", "kind": "implementation", "verified_on": "2026-09-20"},
        },
        {
            "title": "СберИндекс 2026 — Apify: обнаружение официальных источников 20.09.2026",
            "path": ROOT / "data" / "apify-sberindex-source-discovery-2026-09-20.json",
            "url": "https://rosstat.gov.ru/opendata/7708234640-oktmo",
            "meta": {"project": "both", "kind": "source_discovery", "verified_on": "2026-09-20", "acceptance": "candidate_urls_only"},
        },
        {
            "title": "СберИндекс 2026 — Экономический атлас — план исследований",
            "path": ROOT / "economic-atlas" / "research-plan.md",
            "url": "https://agrigate.pro/v2/#case/case_66cae4a89ba6473f",
            "meta": {"project": "economic-atlas", "case_id": "case_66cae4a89ba6473f", "kind": "research_plan", "verified_on": "2026-09-20"},
        },
        {
            "title": "СберИндекс 2026 — Экономический атлас — манифест данных",
            "path": ROOT / "economic-atlas" / "data-manifest.json",
            "url": "https://agrigate.pro/v2/#case/case_66cae4a89ba6473f",
            "meta": {"project": "economic-atlas", "case_id": "case_66cae4a89ba6473f", "kind": "data_manifest", "verified_on": "2026-09-20"},
        },
        {
            "title": "СберИндекс 2026 — Экономический атлас — лестница A0–A10",
            "path": ROOT / "economic-atlas" / "research-ladder.md",
            "url": "https://agrigate.pro/v2/#case/case_66cae4a89ba6473f",
            "meta": {"project": "economic-atlas", "case_id": "case_66cae4a89ba6473f", "kind": "research_ladder", "verified_on": "2026-09-20"},
        },
        {
            "title": "СберИндекс 2026 — Радар — план исследований",
            "path": ROOT / "shock-radar" / "research-plan.md",
            "url": "https://agrigate.pro/v2/#case/case_008f37d03cf541e5",
            "meta": {"project": "shock-radar", "case_id": "case_008f37d03cf541e5", "kind": "research_plan", "verified_on": "2026-09-20"},
        },
        {
            "title": "СберИндекс 2026 — Радар — манифест данных",
            "path": ROOT / "shock-radar" / "data-manifest.json",
            "url": "https://agrigate.pro/v2/#case/case_008f37d03cf541e5",
            "meta": {"project": "shock-radar", "case_id": "case_008f37d03cf541e5", "kind": "data_manifest", "verified_on": "2026-09-20"},
        },
        {
            "title": "СберИндекс 2026 — Радар — лестница R0–R10",
            "path": ROOT / "shock-radar" / "research-ladder.md",
            "url": "https://agrigate.pro/v2/#case/case_008f37d03cf541e5",
            "meta": {"project": "shock-radar", "case_id": "case_008f37d03cf541e5", "kind": "research_ladder", "verified_on": "2026-09-20"},
        },
    ]
    results = []
    for document in documents:
        text = document["path"].read_text()
        payload = {
            "title": document["title"],
            "text": text,
            "url": document["url"],
            "meta": document["meta"],
        }
        result = request(
            "POST", f"{KB}/api/corpora/{CORPUS_ID}/documents/integrate", payload
        )
        results.append(
            {
                "title": document["title"],
                "file": str(document["path"].relative_to(ROOT)),
                "result": result,
            }
        )
        print(json.dumps(results[-1], ensure_ascii=False), flush=True)

    receipt = {
        "corpus_id": CORPUS_ID,
        "corpus_name": EXPECTED_CORPUS_NAME,
        "integrated_on": "2026-09-20",
        "documents": results,
    }
    (ROOT / "data" / "kb-receipts.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n"
    )


if __name__ == "__main__":
    main()
