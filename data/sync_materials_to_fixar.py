#!/usr/bin/env python3
"""Attach the audited data passports to the two existing FixAR cases."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


from shared.internal_auth import internal_service_headers


ROOT = Path(__file__).resolve().parents[1]
OWNER = "prn_fbab9aa00cd46169"
CASE_URL = "http://localhost:8013"
VAULT_URL = os.getenv("VAULT_SERVICE_URL", "http://vault-service:8019")
PROJECTS = {
    "economic-atlas": "case_66cae4a89ba6473f",
    "shock-radar": "case_008f37d03cf541e5",
}


def request(method: str, url: str, body: dict | None = None, *, binary=False):
    headers = {"content-type": "application/json", **internal_service_headers()}
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode()
    try:
        with urllib.request.urlopen(
            urllib.request.Request(url, data=data, method=method, headers=headers), timeout=120
        ) as response:
            raw = response.read()
            return raw if binary else json.loads(raw)
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"{error.code} {url}: {error.read().decode()[:1200]}") from None


def attach(case_id: str, slug: str, path: Path, title: str, mime: str, index: int):
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    decoded = raw.decode() if mime in {"text/markdown", "application/json", "text/csv"} else ""
    upload = {
        "owner_id": OWNER,
        "title": title,
        "content_b64": base64.b64encode(raw).decode(),
        "mime": mime,
        "kind": "file",
        "sensitivity": "normal",
        "domain": "software",
        "source_case_id": case_id,
        "in_knowledge": False,
    }
    if decoded:
        upload["text"] = decoded
    vault_document = request("POST", f"{VAULT_URL}/vault/documents", upload)["document"]
    material = request(
        "POST",
        f"{CASE_URL}/cases/{case_id}/materials",
        {
            "kind": "file",
            "mime": mime,
            "title": title,
            "storage_ref": f"vault:{vault_document['id']}",
            "extracted": decoded,
            "sensitivity": "normal",
            "source_channel": "api",
            "uploaded_by": OWNER,
            "client_message_id": f"sberindex-2026-09-20:{slug}:data:{index}",
            "client_request_hash": digest,
            "part_index": index,
        },
    )
    query = urllib.parse.urlencode({"principal_id": OWNER})
    downloaded = request(
        "GET", f"{CASE_URL}/cases/{case_id}/materials/{material['id']}/content?{query}", binary=True
    )
    if hashlib.sha256(downloaded).hexdigest() != digest:
        raise RuntimeError(f"FixAR material roundtrip mismatch for {title}")
    return {"id": material["id"], "title": title, "sha256": digest, "verified": True}


def main() -> None:
    receipts = []
    common = [
        (ROOT / "data" / "DATA_CATALOG.md", "Каталог данных, покрытие и ограничения — 20.09.2026.md", "text/markdown"),
        (ROOT / "data" / "schema-report.json", "Схемы, пропуски и SHA-256 загруженных данных.json", "application/json"),
    ]
    for slug, case_id in PROJECTS.items():
        case = request("GET", f"{CASE_URL}/cases/{case_id}")
        if case.get("owner_id") != OWNER:
            raise RuntimeError(f"Unexpected owner for {case_id}")
        files = common + [
            (ROOT / slug / "data-manifest.json", "Манифест данных проекта.json", "application/json"),
            (
                ROOT / slug / "research-plan.md",
                "План исследований и разработки — обновлено после загрузки данных.md",
                "text/markdown",
            ),
            (
                ROOT / f"{slug}-scaffold.zip",
                "Каркас проекта — обновлён после загрузки данных.zip",
                "application/zip",
            ),
            (
                ROOT / "data" / "SEMANTIC_CORPORA.md",
                "Семантические корпуса и будущие аналитические инструменты.md",
                "text/markdown",
            ),
        ]
        materials = [
            attach(case_id, slug, path, title, mime, index + 20)
            for index, (path, title, mime) in enumerate(files)
        ]
        receipt = {"slug": slug, "case_id": case_id, "materials": materials}
        receipts.append(receipt)
        print(json.dumps(receipt, ensure_ascii=False), flush=True)
    (ROOT / "data" / "fixar-data-receipts.json").write_text(
        json.dumps({"synced_on": "2026-09-20", "cases": receipts}, ensure_ascii=False, indent=2) + "\n"
    )


if __name__ == "__main__":
    main()
