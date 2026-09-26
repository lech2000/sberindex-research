"""Pin the two FixAR cases to researcher v5 and execute one current gate.

The Atlas agent works only on A1. The Radar agent stays on R0 until it finds
authoritative publication/vintage evidence or returns a precise blocker.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx

from shared.internal_auth import internal_service_headers


HERE = Path(__file__).resolve().parent
OWNER = "prn_fbab9aa00cd46169"
CASE = "http://case-service:8013"
LANDSCAPE = "http://landscape-service:8016"
DIALOG = "http://dialog-service:8021"
PROJECTS = {
    "economic-atlas": {
        "case_id": "case_66cae4a89ba6473f",
        "title": "Экономический атлас муниципалитетов",
        "agent": "sberindex_atlas_researcher",
        "gate": "A1",
        "required_tools": {
            "sberindex_atlas_kb_search", "sberindex_data_catalog",
            "sberindex_query_data", "sberindex_cluster", "jina_search_web",
            "robots_check", "recon_mcp_allowlist", "apify_web_research",
        },
        "message": """Выполни только ворота A1 после уже принятого A0. Сначала
прочитай корпуса 74/75 и каталог загруженных таблиц. Затем найди официальный,
воспроизводимый кроссволк муниципальных идентификаторов к ОКТМО/региону и
проверь, можно ли им закрыть 2 143 территории historical_spending и 1 896
строк population/migration. Используй встроенный поиск MiMo Pro для разведки,
официальный файл/API либо Jina/robots-aware чтение для доказательства.
Recon применяй только пассивно после allowlist. Apify применяй лишь если
публичный JS-сайт не читается двумя предыдущими путями. Верни содержание
protocol/municipality_crosswalk.md: ключи, кардинальность, покрытие,
неоднозначности, неприсоединившиеся записи, источник и checksum/дату загрузки.
Не выдумывай соответствия и не ставь PASS без скачиваемого авторитетного
источника и измеренного покрытия. Заверши формальным GATE_REPORT A1.""",
    },
    "shock-radar": {
        "case_id": "case_008f37d03cf541e5",
        "title": "Радар потребительских сдвигов",
        "agent": "sberindex_radar_researcher",
        "gate": "R0",
        "required_tools": {
            "sberindex_radar_kb_search", "sberindex_data_catalog",
            "sberindex_query_data", "sberindex_forecast", "jina_search_web",
            "robots_check", "recon_mcp_allowlist", "apify_web_research",
        },
        "message": """Продолжи только заблокированные ворота R0. Найди
авторитетные сведения о дате публикации, доступности и vintages муниципального
датасета потребительских безналичных расходов СберИндекса. Сначала проверь
корпуса 74/76 и реестр загруженных файлов. Для внешнего веба используй
встроенный поиск MiMo Pro, затем официальный файл/API или Jina/robots-aware
чтение. Recon — только пассивно после allowlist; Apify — лишь для сложного
публичного JS-сайта, если два предыдущих пути не закрыли пробел. Верни строки
для data/availability_audit.csv с source, observed_at, published_at,
available_at, vintage, evidence_url, checked_at и confidence. Не подставляй
дату скачивания вместо даты доступности и не выдумывай неизвестные поля. Если
источник не публикует эти метаданные, оставь R0 BLOCKED и назови точный запрос
владельцу данных. Заверши формальным GATE_REPORT R0.""",
    },
}


async def start_one(client: httpx.AsyncClient, project: str, cfg: dict) -> dict:
    live = (await client.get(
        f"{LANDSCAPE}/domains/software/agents/{cfg['agent']}/config",
        params={"assurance": 2, "version": 5, "tenant": OWNER,
                "case": cfg["case_id"]},
    )).raise_for_status().json()
    exposed = set(live.get("tools", []))
    if live.get("model") != "mimo-v2.5-pro" or not cfg["required_tools"] <= exposed:
        raise RuntimeError(f"{project}: invalid v4 config: {live}")

    old = (await client.get(
        f"{CASE}/cases/{cfg['case_id']}/routing",
        params={"principal_id": OWNER},
    )).raise_for_status().json()
    route_response = await client.put(f"{CASE}/cases/{cfg['case_id']}/routing", json={
        "principal_id": OWNER,
        "domain": "software",
        "selected_agent_id": cfg["agent"],
        "selected_agent_version": 5,
        "selected_agent_score": 0,
        "selected_agent_catalog_hash": "",
        "selected_agent_algorithm": "",
        "reason": f"Исследовательский проход {cfg['gate']} v5: кластер/прогноз + официальный веб, Recon/Apify по лестнице",
        "assurance": 2,
        "expect_domain": old.get("domain", ""),
        "expect_selected_agent_id": old.get("selected_agent_id", ""),
    })
    if route_response.is_error:
        raise RuntimeError(
            f"routing {route_response.status_code}: {route_response.text}; old={old}"
        )
    route = route_response.json()

    response = (await client.post(f"{DIALOG}/dialog", json={
        "case_id": cfg["case_id"],
        "case_title": cfg["title"],
        "message": cfg["message"],
        "domain": "software",
        "agent": cfg["agent"],
        "agent_version": 5,
        "assurance": 2,
        "principal_id": OWNER,
        "client_message_id": f"sberindex-v4-{cfg['gate'].lower()}-{project}-20260920",
    })).raise_for_status().json()
    reply = str(response.get("reply") or "")
    return {
        "project": project,
        "case_id": cfg["case_id"],
        "gate": cfg["gate"],
        "agent": f"software:{cfg['agent']}@5",
        "model": live["model"],
        "tools": sorted(exposed),
        "routing_version": route["selected_agent_version"],
        "has_gate_report": "GATE_REPORT" in reply,
        "reply_chars": len(reply),
        "reply": reply,
    }


async def main() -> None:
    async with httpx.AsyncClient(
        headers=internal_service_headers(), timeout=600
    ) as client:
        results = await asyncio.gather(*[
            start_one(client, project, cfg)
            for project, cfg in PROJECTS.items()
        ], return_exceptions=True)
    payload = {"started_at": datetime.now(timezone.utc).isoformat(), "results": []}
    for project, result in zip(PROJECTS, results, strict=True):
        if isinstance(result, Exception):
            payload["results"].append({"project": project, "error": repr(result)})
        else:
            payload["results"].append(result)
    (HERE / "v4-start-receipts.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
