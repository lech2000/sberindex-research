"""Attach the reviewed graph contract and pin the existing FixAR graph case."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
from pathlib import Path

import httpx

from shared.internal_auth import internal_service_headers


ROOT = Path(__file__).resolve().parents[1]
OWNER = "prn_fbab9aa00cd46169"
CASE_ID = "case_43de12a8dc2e4abd"
CURATOR_CASE_ID = "case_d058db85c48a487c"
CASE = "http://case-service:8013"
VAULT = "http://vault-service:8019"
LANDSCAPE = "http://landscape-service:8016"
FILES = (
    ("model-lab/ARCHITECTURE.md", "Архитектура доказательного графа муниципалитетов.md", "text/markdown"),
    ("model-lab/loaded-data-audit.json", "Аудит загруженных муниципальных данных.json", "application/json"),
    ("graph/OPERATIONS.md", "Эксплуатационный контракт Graph Steward.md", "text/markdown"),
    ("graph/evidence.schema.json", "Схема staging evidence.json", "application/json"),
    ("graph/curator.schema.json", "Схема решения куратора.json", "application/json"),
)


async def attach(client: httpx.AsyncClient, case_id: str, relative: str,
                 title: str, mime: str, part: int) -> dict:
    raw = (ROOT / relative).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    payload = {
        "owner_id": OWNER,
        "title": title,
        "content_b64": base64.b64encode(raw).decode(),
        "mime": mime,
        "kind": "file",
        "sensitivity": "normal",
        "domain": "software",
        "source_case_id": case_id,
        "in_knowledge": False,
        "text": raw.decode(),
    }
    upload = await client.post(f"{VAULT}/vault/documents", json=payload)
    if upload.status_code >= 500:
        await asyncio.sleep(0.5)
        upload = await client.post(f"{VAULT}/vault/documents", json=payload)
    document = upload.raise_for_status().json()["document"]
    material = (await client.post(f"{CASE}/cases/{case_id}/materials", json={
        "kind": "file",
        "mime": mime,
        "title": title,
        "storage_ref": f"vault:{document['id']}",
        "extracted": raw.decode(),
        "sensitivity": "normal",
        "source_channel": "api",
        "uploaded_by": OWNER,
        "client_message_id": f"sberindex-graph-v1:{case_id}:{part}:{digest[:16]}",
        "client_request_hash": digest,
        "part_index": part,
    })).raise_for_status().json()
    return {"source": relative, "material_id": material["id"], "sha256": digest}


async def main() -> None:
    async with httpx.AsyncClient(
        headers=internal_service_headers(), timeout=120
    ) as client:
        config = (await client.get(
            f"{LANDSCAPE}/domains/software/agents/sberindex_graph_steward/config",
            params={"assurance": 2, "version": 3, "tenant": OWNER, "case": CASE_ID},
        )).raise_for_status().json()
        if config.get("model") != "mimo-v2.5-pro" or \
                "sberindex_graph_kb_search" not in config.get("tools", []):
            raise RuntimeError(f"invalid graph agent config: {config}")
        curator_config = (await client.get(
            f"{LANDSCAPE}/domains/software/agents/sberindex_research_curator/config",
            params={"assurance": 2, "version": 3, "tenant": OWNER,
                    "case": CURATOR_CASE_ID},
        )).raise_for_status().json()
        if curator_config.get("model") != "mimo-v2.5-pro" or \
                "sberindex_graph_kb_search" not in curator_config.get("tools", []):
            raise RuntimeError(f"invalid curator config: {curator_config}")
        attachments = {
            case_id: [
                await attach(client, case_id, relative, title, mime, 90 + index)
                for index, (relative, title, mime) in enumerate(FILES)
            ]
            for case_id in (CASE_ID, CURATOR_CASE_ID)
        }
        old = (await client.get(
            f"{CASE}/cases/{CASE_ID}/routing",
            params={"principal_id": OWNER},
        )).raise_for_status().json()
        route = (await client.put(f"{CASE}/cases/{CASE_ID}/routing", json={
            "principal_id": OWNER,
            "domain": "software",
            "selected_agent_id": "sberindex_graph_steward",
            "selected_agent_version": 3,
            "selected_agent_score": 0,
            "selected_agent_catalog_hash": "",
            "selected_agent_algorithm": "",
            "reason": "Graph Steward v3: hourly n8n staging loop + cluster, verified 21.09.2026",
            "assurance": 2,
            "expect_domain": old.get("domain", ""),
            "expect_selected_agent_id": old.get("selected_agent_id", ""),
        })).raise_for_status().json()
        curator_old = (await client.get(
            f"{CASE}/cases/{CURATOR_CASE_ID}/routing",
            params={"principal_id": OWNER},
        )).raise_for_status().json()
        curator_route = (await client.put(
            f"{CASE}/cases/{CURATOR_CASE_ID}/routing", json={
                "principal_id": OWNER,
                "domain": "software",
                "selected_agent_id": "sberindex_research_curator",
                "selected_agent_version": 3,
                "selected_agent_score": 0,
                "selected_agent_catalog_hash": "",
                "selected_agent_algorithm": "",
                "reason": "Research Curator v3: review every graph staging result",
                "assurance": 2,
                "expect_domain": curator_old.get("domain", ""),
                "expect_selected_agent_id": curator_old.get("selected_agent_id", ""),
            },
        )).raise_for_status().json()
    print(json.dumps({
        "case_id": CASE_ID,
        "agent": "software:sberindex_graph_steward@3",
        "model": config["model"],
        "curator": "software:sberindex_research_curator@3",
        "attachments": attachments,
        "routing": {"graph": route, "curator": curator_route},
    }, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
