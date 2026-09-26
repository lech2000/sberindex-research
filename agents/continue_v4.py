"""Recover A1/R0 when MiMo printed an XML tool tag instead of calling MCP."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx

from shared.internal_auth import internal_service_headers


HERE = Path(__file__).resolve().parent
OWNER = "prn_fbab9aa00cd46169"
DIALOG = "http://dialog-service:8021"
PROJECTS = {
    "economic-atlas": {
        "case_id": "case_66cae4a89ba6473f",
        "title": "Экономический атлас муниципалитетов",
        "agent": "sberindex_atlas_researcher",
        "gate": "A1",
        "message": """Продолжи A1. Предыдущий ответ был напечатанным XML
<tool_call>, поэтому инструмент НЕ выполнился и доказательств пока нет. Не
печатай XML или псевдовызовы. Сделай настоящий native function call:
sberindex_atlas_kb_search по муниципальному кроссволку, затем
sberindex_data_catalog для historical_spending; после этого настоящий
jina_search_web по официальному ОКТМО. Дай короткий проверяемый результат A1 с
URL и измеримым планом покрытия либо честный BLOCKED. Заверши GATE_REPORT.""",
    },
    "shock-radar": {
        "case_id": "case_008f37d03cf541e5",
        "title": "Радар потребительских сдвигов",
        "agent": "sberindex_radar_researcher",
        "gate": "R0",
        "message": """Продолжи R0. Предыдущий ответ был напечатанным XML
<tool_call>, поэтому URL НЕ был прочитан и доказательств пока нет. Не печатай
XML или псевдовызовы. Сделай настоящий native function call:
sberindex_radar_kb_search по availability/vintage, затем настоящий
jina_read_url для официальной страницы СберИндекса о муниципальных расходах.
Верни строки availability audit только с подтверждёнными полями; неизвестное
оставь unknown и R0 BLOCKED. Заверши GATE_REPORT.""",
    },
}


async def one(client: httpx.AsyncClient, project: str, cfg: dict) -> dict:
    response = await client.post(f"{DIALOG}/dialog", json={
        "case_id": cfg["case_id"],
        "case_title": cfg["title"],
        "message": cfg["message"],
        "domain": "software",
        "agent": cfg["agent"],
        "agent_version": 5,
        "assurance": 2,
        "principal_id": OWNER,
        "client_message_id": f"sberindex-v4-native-retry-{cfg['gate'].lower()}-20260920",
    })
    if response.is_error:
        raise RuntimeError(f"dialog {response.status_code}: {response.text}")
    reply = str(response.json().get("reply") or "")
    return {
        "project": project,
        "case_id": cfg["case_id"],
        "gate": cfg["gate"],
        "has_gate_report": "GATE_REPORT" in reply,
        "raw_tool_tag": "<tool_call>" in reply,
        "reply_chars": len(reply),
        "reply": reply,
    }


async def main() -> None:
    async with httpx.AsyncClient(headers=internal_service_headers(), timeout=600) as client:
        results = await asyncio.gather(*[
            one(client, project, cfg) for project, cfg in PROJECTS.items()
        ], return_exceptions=True)
    payload = {"continued_at": datetime.now(timezone.utc).isoformat(), "results": []}
    for project, result in zip(PROJECTS, results, strict=True):
        payload["results"].append(
            {"project": project, "error": repr(result)}
            if isinstance(result, Exception) else result
        )
    (HERE / "v4-continue-receipts.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
