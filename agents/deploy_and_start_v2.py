"""Attach v2 ladder protocol, pin both cases, and start A0/R0 once.

Run in case-service with the deliverables directory copied to /tmp. Every
mutation has a stable idempotency key. The script does not advance a second
gate: the first report must be inspected before continuation.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx

from shared.internal_auth import internal_service_headers

ROOT = Path(__file__).resolve().parents[1]
OWNER = "prn_fbab9aa00cd46169"
CASE = "http://localhost:8013"
VAULT = "http://vault-service:8019"
LANDSCAPE = "http://landscape-service:8016"
DIALOG = "http://dialog-service:8021"
PROJECTS = {
    "economic-atlas": {
        "case_id": "case_66cae4a89ba6473f",
        "title": "Экономический атлас муниципалитетов",
        "agent": "sberindex_atlas_researcher",
        "kb_tool": "sberindex_atlas_kb_search",
        "ladder": ROOT / "economic-atlas/research-ladder.md",
        "gate": "A0",
        "message": (
            "Приступай к воротам A0. Сначала используй sberindex_atlas_kb_search, "
            "чтобы сверить корпуса 74/75, затем учти приложенные архитектуру, аудит "
            "загруженных файлов и лестницу. Подготовь содержание protocol/question.md: "
            "один проверяемый вопрос, единица анализа, период, практический сценарий, "
            "матрица критерий конкурса→доказательство, неподдерживаемые причинные "
            "утверждения. Учитывай, что 1 896 МО лишь кандидаты полной панели, расходы "
            "— средние безналичные расходы жителей, а мобильность не OD-матрица. "
            "Работай только над A0 и заверши формальным GATE_REPORT."
        ),
    },
    "shock-radar": {
        "case_id": "case_008f37d03cf541e5",
        "title": "Радар потребительских сдвигов",
        "agent": "sberindex_radar_researcher",
        "kb_tool": "sberindex_radar_kb_search",
        "ladder": ROOT / "shock-radar/research-ladder.md",
        "gate": "R0",
        "message": (
            "Приступай к воротам R0. Сначала используй sberindex_radar_kb_search, "
            "чтобы сверить корпуса 74/76, затем учти приложенные архитектуру, аудит "
            "загруженных файлов и лестницу. Подготовь содержание "
            "protocol/forecast_contract.yaml: target, допустимые горизонты, forecast "
            "origins, observed/published/available timestamps, событие, бюджет ложных "
            "тревог, train/validation/закрытый test. Учитывай только 24 месячных точки, "
            "средние расходы жителей и недоступность второго среза мобильности для "
            "ретропрогноза 2023–2024. Работай только над R0 и заверши GATE_REPORT."
        ),
    },
}


async def attach(client: httpx.AsyncClient, project: str, case_id: str,
                 path: Path, title: str, part: int) -> dict:
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    upload_payload = {
        "owner_id": OWNER, "title": title,
        "content_b64": base64.b64encode(raw).decode(), "mime": "text/markdown",
        "kind": "file", "sensitivity": "normal", "domain": "software",
        "source_case_id": case_id, "in_knowledge": False, "text": raw.decode(),
    }
    upload = await client.post(f"{VAULT}/vault/documents", json=upload_payload)
    # Two cases may attach the same protocol concurrently. Vault deduplicates
    # by owner+sha, but a simultaneous insert can lose the unique-key race.
    # Once the winner commits, a single retry follows the normal dedupe path.
    if upload.status_code >= 500:
        await asyncio.sleep(0.5)
        upload = await client.post(f"{VAULT}/vault/documents", json=upload_payload)
    doc = upload.raise_for_status().json()["document"]
    material = (await client.post(f"{CASE}/cases/{case_id}/materials", json={
        "kind": "file", "mime": "text/markdown", "title": title,
        "storage_ref": f"vault:{doc['id']}", "extracted": raw.decode(),
        "sensitivity": "normal", "source_channel": "api", "uploaded_by": OWNER,
        "client_message_id": f"sberindex-ladder-v2:{project}:{part}:{digest[:12]}",
        "client_request_hash": digest, "part_index": part,
    })).raise_for_status().json()
    return {"material_id": material["id"], "sha256": digest}


async def start_one(client: httpx.AsyncClient, project: str, cfg: dict) -> dict:
    case_id = cfg["case_id"]
    live = (await client.get(
        f"{LANDSCAPE}/domains/software/agents/{cfg['agent']}/config",
        params={"assurance": 2, "version": 2, "tenant": OWNER, "case": case_id},
    )).raise_for_status().json()
    if live.get("model") != "mimo-v2.5-pro" or cfg["kb_tool"] not in live.get("tools", []):
        raise RuntimeError(f"{project}: v2 config/model/tool mismatch")

    attachments = [
        await attach(client, project, case_id, ROOT / "agents/README.md",
                     "Исследовательские агенты — протокол ворот v2.md", 80),
        await attach(client, project, case_id, cfg["ladder"],
                     f"Подробная лестница {cfg['gate'][0]}0–{cfg['gate'][0]}10 v2.md", 81),
    ]
    old = (await client.get(f"{CASE}/cases/{case_id}/routing",
                            params={"principal_id": OWNER})).raise_for_status().json()
    route = (await client.put(f"{CASE}/cases/{case_id}/routing", json={
        "principal_id": OWNER, "domain": "software",
        "selected_agent_id": cfg["agent"], "selected_agent_version": 2,
        "selected_agent_score": 0, "selected_agent_catalog_hash": "",
        "selected_agent_algorithm": "",
        "reason": "Владелец запустил пошаговое исследование по воротам v2 20.09.2026",
        "assurance": 2, "expect_domain": old.get("domain", ""),
        "expect_selected_agent_id": old.get("selected_agent_id", ""),
    })).raise_for_status().json()
    response = (await client.post(f"{DIALOG}/dialog", json={
        "case_id": case_id, "case_title": cfg["title"], "message": cfg["message"],
        "domain": "software", "agent": cfg["agent"], "agent_version": 2,
        "assurance": 2, "principal_id": OWNER,
        "client_message_id": f"sberindex-ladder-v2-kickoff-{project}-20260920",
    })).raise_for_status().json()
    reply = str(response.get("reply") or "")
    return {
        "project": project, "case_id": case_id, "gate": cfg["gate"],
        "agent": f"software:{cfg['agent']}@2", "model": live["model"],
        "kb_tool": cfg["kb_tool"], "routing_version": route["selected_agent_version"],
        "attachments": attachments, "reply_chars": len(reply),
        "has_gate_report": "GATE_REPORT" in reply, "reply": reply,
    }


async def main() -> None:
    async with httpx.AsyncClient(headers=internal_service_headers(), timeout=300) as client:
        results = await asyncio.gather(*[
            start_one(client, project, cfg) for project, cfg in PROJECTS.items()
        ], return_exceptions=True)
    payload = {"started_at": datetime.now(timezone.utc).isoformat(), "results": []}
    for project, result in zip(PROJECTS, results, strict=True):
        if isinstance(result, Exception):
            payload["results"].append({"project": project, "error": repr(result)})
        else:
            payload["results"].append(result)
    (ROOT / "agents/kickoff-receipts.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
