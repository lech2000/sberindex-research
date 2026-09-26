"""Retry the two first gates after a bounded model turn or transient attach race."""
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


ATLAS_RETRY = (
    "Повтори только A0 и уложись в один короткий ответ. Вызови "
    "sberindex_atlas_kb_search с query='критерии эксперимента A0' и limit=2, "
    "затем sberindex_data_catalog для historical_spending и "
    "sberindex_query_data для territory_id=1, category='Продовольствие', "
    "limit=3. На основании именно этих ответов дай готовое содержание "
    "protocol/question.md (до 700 слов) и "
    "формальный GATE_REPORT. Не делай дополнительный веб-поиск. Учитывай "
    "1 896 кандидатов полной панели, смысл показателя расходов и то, что "
    "мобильность не является OD-матрицей."
)

RADAR_RETRY = (
    "Выполни только R0 и уложись в один короткий ответ. Вызови "
    "sberindex_radar_kb_search с query='forecast contract R0' и limit=2, "
    "затем sberindex_data_catalog для historical_spending и "
    "sberindex_scientific_metric: dataset=historical_spending, "
    "metric=seasonal_naive_mae, time_column=date, lag=12, filters "
    "territory_id=1 и category='Продовольствие'. Затем дай готовое содержание "
    "protocol/forecast_contract.yaml (до 120 "
    "строк) и формальный GATE_REPORT. Не делай дополнительный веб-поиск. "
    "Зафиксируй target, горизонты, origins, observed/published/available "
    "timestamps, событие, бюджет ложных тревог и временной split; учти 24 "
    "месячные точки и отсутствие второго среза мобильности."
)


async def main() -> None:
    async with httpx.AsyncClient(
        headers=internal_service_headers(), timeout=300) as client:
        atlas_response = (await client.post(f"{KICKOFF.DIALOG}/dialog", json={
            "case_id": KICKOFF.PROJECTS["economic-atlas"]["case_id"],
            "case_title": KICKOFF.PROJECTS["economic-atlas"]["title"],
            "message": ATLAS_RETRY, "domain": "software",
            "agent": "sberindex_atlas_researcher", "agent_version": 2,
            "assurance": 2, "principal_id": KICKOFF.OWNER,
            "client_message_id": "sberindex-ladder-v2-a0-dialogtools-20260920",
        })).raise_for_status().json()

        radar_response = (await client.post(f"{KICKOFF.DIALOG}/dialog", json={
            "case_id": KICKOFF.PROJECTS["shock-radar"]["case_id"],
            "case_title": KICKOFF.PROJECTS["shock-radar"]["title"],
            "message": RADAR_RETRY, "domain": "software",
            "agent": "sberindex_radar_researcher", "agent_version": 2,
            "assurance": 2, "principal_id": KICKOFF.OWNER,
            "client_message_id": "sberindex-ladder-v2-r0-dialogtools-20260920",
        })).raise_for_status().json()

    atlas_reply = str(atlas_response.get("reply") or "")
    radar_reply = str(radar_response.get("reply") or "")
    payload = {
        "retried_at": datetime.now(timezone.utc).isoformat(),
        "results": [
            {"project": "economic-atlas", "gate": "A0",
             "reply_chars": len(atlas_reply),
             "has_gate_report": "GATE_REPORT" in atlas_reply,
             "reply": atlas_reply},
            {"project": "shock-radar", "gate": "R0",
             "reply_chars": len(radar_reply),
             "has_gate_report": "GATE_REPORT" in radar_reply,
             "reply": radar_reply},
        ],
    }
    (HERE / "retry-receipts.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
