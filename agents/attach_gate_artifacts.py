"""Attach reviewed A0/R0 artifacts to their existing FixAR cases."""
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
CASE = "http://case-service:8013"
VAULT = "http://vault-service:8019"
ARTIFACTS = (
    {
        "project": "economic-atlas",
        "case_id": "case_66cae4a89ba6473f",
        "path": ROOT / "economic-atlas/protocol/question.md",
        "title": "Atlas A0 — проверяемый исследовательский вопрос.md",
        "mime": "text/markdown",
    },
    {
        "project": "shock-radar",
        "case_id": "case_008f37d03cf541e5",
        "path": ROOT / "shock-radar/protocol/forecast_contract.yaml",
        "title": "Radar R0 — forecast contract, BLOCKED по availability.yaml",
        "mime": "application/yaml",
    },
)


async def attach(client: httpx.AsyncClient, item: dict) -> dict:
    raw = item["path"].read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    upload_payload = {
        "owner_id": OWNER,
        "title": item["title"],
        "content_b64": base64.b64encode(raw).decode(),
        "mime": item["mime"],
        "kind": "file",
        "sensitivity": "normal",
        "domain": "software",
        "source_case_id": item["case_id"],
        "in_knowledge": False,
        "text": raw.decode(),
    }
    upload = await client.post(f"{VAULT}/vault/documents", json=upload_payload)
    if upload.status_code >= 500:
        await asyncio.sleep(0.5)
        upload = await client.post(f"{VAULT}/vault/documents", json=upload_payload)
    doc = upload.raise_for_status().json()["document"]
    material = (await client.post(
        f"{CASE}/cases/{item['case_id']}/materials",
        json={
            "kind": "file",
            "mime": item["mime"],
            "title": item["title"],
            "storage_ref": f"vault:{doc['id']}",
            "extracted": raw.decode(),
            "sensitivity": "normal",
            "source_channel": "api",
            "uploaded_by": OWNER,
            "client_message_id": f"sberindex-gate-artifact:{item['project']}:{digest[:16]}",
            "client_request_hash": digest,
            "part_index": 90,
        },
    )).raise_for_status().json()
    return {
        "project": item["project"],
        "case_id": item["case_id"],
        "file": str(item["path"].relative_to(ROOT)),
        "sha256": digest,
        "vault_document_id": doc["id"],
        "material_id": material["id"],
    }


async def main() -> None:
    async with httpx.AsyncClient(
        headers=internal_service_headers(), timeout=180
    ) as client:
        receipts = [await attach(client, item) for item in ARTIFACTS]
    payload = {
        "attached_at": datetime.now(timezone.utc).isoformat(),
        "receipts": receipts,
    }
    (ROOT / "agents/gate-artifact-receipts.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
