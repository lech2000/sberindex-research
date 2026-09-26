"""Ask the Radar agent to reconcile its R0 report with the ladder gate."""
from __future__ import annotations

import asyncio
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx

from shared.internal_auth import internal_service_headers


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "sberindex_kickoff_v2", HERE / "deploy_and_start_v2.py")
assert SPEC and SPEC.loader
KICKOFF = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(KICKOFF)

PROMPT = """Методологическая проверка R0. В предыдущем ответе ты получил
seasonal-naive MAE=1153.5 и создал валидный draft forecast_contract.yaml, но
пометил R0 как PASS при published_at=unknown и available_at=unknown. Лестница
R0 требует, чтобы каждое поле имело observed/published/available timestamp.
Кроме того, единый список origins должен учитывать, что для h=2 и h=3 нужны
полные будущие окна; sample MAE одной территории и категории не является
метрикой всей панели. Дай короткий исправленный GATE_REPORT без повторения
YAML: честный status, что уже проверено, точный blocker, одно следующее
действие для закрытия availability/vintage, и next_gate. Не вызывай новые
инструменты и не объявляй R1, пока R0 не прошёл."""


async def main() -> None:
    async with httpx.AsyncClient(
        headers=internal_service_headers(), timeout=300
    ) as client:
        response = (await client.post(f"{KICKOFF.DIALOG}/dialog", json={
            "case_id": KICKOFF.PROJECTS["shock-radar"]["case_id"],
            "case_title": KICKOFF.PROJECTS["shock-radar"]["title"],
            "message": PROMPT,
            "domain": "software",
            "agent": "sberindex_radar_researcher",
            "agent_version": 2,
            "assurance": 2,
            "principal_id": KICKOFF.OWNER,
            "client_message_id": "sberindex-r0-methodology-review-20260920",
        })).raise_for_status().json()
    reply = str(response.get("reply") or "")
    payload = {
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "has_gate_report": "GATE_REPORT" in reply,
        "reply": reply,
    }
    (HERE / "r0-methodology-review.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
