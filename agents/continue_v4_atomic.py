"""Run one bounded evidence call per SberIndex researcher, sequentially."""
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
STEPS = (
    {
        "project": "economic-atlas",
        "case_id": "case_66cae4a89ba6473f",
        "title": "Экономический атлас муниципалитетов",
        "agent": "sberindex_atlas_researcher",
        "gate": "A1",
        "message": """Атомарный шаг A1. Вызови РОВНО ОДИН инструмент:
sberindex_atlas_kb_search(query='муниципальный кроссволк ОКТМО territory_id
источник', limit=2). Другие инструменты сейчас не вызывай. По его фактическому
ответу зафиксируй, что известно и чего не хватает для измеренного покрытия.
Не ставь PASS. Заверши коротким GATE_REPORT A1 со status BLOCKED и одним
следующим действием.""",
    },
    {
        "project": "shock-radar",
        "case_id": "case_008f37d03cf541e5",
        "title": "Радар потребительских сдвигов",
        "agent": "sberindex_radar_researcher",
        "gate": "R0",
        "message": """Атомарный шаг R0. Вызови РОВНО ОДИН инструмент:
jina_read_url(url='https://sberindex.ru/ru/dashboards/potrebitelskie-beznalicnye-rashody-na-urovne-munizipalnyh-obrazovanij').
Другие инструменты сейчас не вызывай. Из фактического ответа выпиши только
свидетельства о published_at/available_at/vintage; отсутствующее оставь
unknown. Не ставь PASS. Заверши коротким GATE_REPORT R0 со status BLOCKED и
одним следующим действием.""",
    },
)


async def main() -> None:
    results: list[dict] = []
    async with httpx.AsyncClient(headers=internal_service_headers(), timeout=420) as client:
        for step in STEPS:
            response = await client.post(f"{DIALOG}/dialog", json={
                "case_id": step["case_id"],
                "case_title": step["title"],
                "message": step["message"],
                "domain": "software",
                "agent": step["agent"],
                "agent_version": 5,
                "assurance": 2,
                "principal_id": OWNER,
                "client_message_id": f"sberindex-v4-atomic-{step['gate'].lower()}-20260920",
            })
            if response.is_error:
                results.append({
                    "project": step["project"],
                    "error": f"dialog {response.status_code}: {response.text}",
                })
                continue
            reply = str(response.json().get("reply") or "")
            results.append({
                "project": step["project"],
                "case_id": step["case_id"],
                "gate": step["gate"],
                "has_gate_report": "GATE_REPORT" in reply,
                "raw_tool_tag": "<tool_call>" in reply,
                "reply_chars": len(reply),
                "reply": reply,
            })
    payload = {"continued_at": datetime.now(timezone.utc).isoformat(), "results": results}
    (HERE / "v4-atomic-receipts.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
