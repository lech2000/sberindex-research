#!/usr/bin/env python3
"""Create and seed the three semantic corpora for SberIndex 2026 research."""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
KB = "http://10.189.141.165:8300"
OWNER = "prn_fbab9aa00cd46169"
DEFAULTS = {
    "embed_provider": "local",
    "embed_model": "text-embedding-bge-m3",
    "embed_dim": 1024,
    "chat_provider": "mimo",
    "chat_model": "mimo-v2.5-pro",
}
SPECS = {
    "shared": {
        "name": f"research:sberindex-2026:shared:{OWNER}",
        "description": "Общая база исследований СберИндекс 2026: условия, данные, справочники, лицензии и общая методология. Создана 20.09.2026 для дел Атласа и Радара.",
        "documents": [
            ("СберИндекс 2026 — общий каталог данных", "data/DATA_CATALOG.md", "data_catalog", "source"),
            ("СберИндекс 2026 — схема и качество данных", "data/schema-report.json", "schema_report", "observation"),
            ("СберИндекс 2026 — полный манифест источников", "data/manifest.json", "source_manifest", "observation"),
            ("СберИндекс 2026 — правила семантических корпусов", "data/SEMANTIC_CORPORA.md", "corpus_policy", "decision"),
            ("СберИндекс 2026 — исследовательские агенты", "agents/README.md", "agent_policy", "decision"),
            ("СберИндекс 2026 — очередь источников", "agents/source-queue.json", "source_queue", "observation"),
            ("СберИндекс 2026 — Apify: обнаружение официальных источников 20.09.2026", "data/apify-sberindex-source-discovery-2026-09-20.json", "source_discovery", "observation"),
            ("СберИндекс 2026 — предложение реализации", "IMPLEMENTATION_PROPOSAL.md", "implementation", "plan"),
        ],
    },
    "economic-atlas": {
        "name": f"research:sberindex-2026:economic-atlas:{OWNER}",
        "description": "Рабочая память дела «Экономический атлас муниципалитетов»: план, графы, кластеризация, ICVI, эксперименты и проверенные выводы. Создана 20.09.2026.",
        "case_id": "case_66cae4a89ba6473f",
        "documents": [
            ("Экономический атлас — план исследований", "economic-atlas/research-plan.md", "research_plan", "plan"),
            ("Экономический атлас — манифест данных", "economic-atlas/data-manifest.json", "data_manifest", "observation"),
            ("Экономический атлас — лестница A0–A10", "economic-atlas/research-ladder.md", "research_ladder", "plan"),
        ],
    },
    "shock-radar": {
        "name": f"research:sberindex-2026:shock-radar:{OWNER}",
        "description": "Рабочая память дела «Радар потребительских сдвигов»: прогнозы, change points, новости, backtest, эксперименты и проверенные выводы. Создана 20.09.2026.",
        "case_id": "case_008f37d03cf541e5",
        "documents": [
            ("Радар потребительских сдвигов — план исследований", "shock-radar/research-plan.md", "research_plan", "plan"),
            ("Радар потребительских сдвигов — манифест данных", "shock-radar/data-manifest.json", "data_manifest", "observation"),
            ("Радар потребительских сдвигов — лестница R0–R10", "shock-radar/research-ladder.md", "research_ladder", "plan"),
        ],
    },
}


def request(method: str, url: str, body: dict | None = None):
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode()
    headers = {"content-type": "application/json"} if body is not None else {}
    with urllib.request.urlopen(
        urllib.request.Request(url, data=data, headers=headers, method=method), timeout=240
    ) as response:
        return json.loads(response.read())


def ensure_corpus(spec: dict) -> dict:
    existing = next((c for c in request("GET", f"{KB}/api/corpora") if c.get("name") == spec["name"]), None)
    if existing:
        return existing
    return request(
        "POST",
        f"{KB}/api/corpora",
        {"name": spec["name"], "description": spec["description"], **DEFAULTS},
    )


def main() -> None:
    receipt = {"created_or_verified_on": "2026-09-20", "corpora": {}}
    for project, spec in SPECS.items():
        corpus = ensure_corpus(spec)
        corpus_id = int(corpus["id"])
        documents = []
        for title, relative, kind, evidence in spec["documents"]:
            meta = {
                "project": project,
                "kind": kind,
                "stage": "research_setup",
                "evidence_level": evidence,
                "verified_on": "2026-09-20",
            }
            if spec.get("case_id"):
                meta["case_id"] = spec["case_id"]
            result = request(
                "POST",
                f"{KB}/api/corpora/{corpus_id}/documents/integrate",
                {
                    "title": title,
                    "text": (ROOT / relative).read_text(),
                    "url": "https://sber.ru/sberindex/konkurs_sberindex",
                    "meta": meta,
                },
            )
            documents.append({"title": title, "file": relative, "result": result})
            print(json.dumps({"corpus_id": corpus_id, "title": title, "result": result}, ensure_ascii=False), flush=True)
        receipt["corpora"][project] = {
            "id": corpus_id,
            "name": spec["name"],
            "documents": documents,
        }
    (ROOT / "data" / "semantic-corpora-receipts.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n"
    )


if __name__ == "__main__":
    main()
