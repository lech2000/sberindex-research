#!/usr/bin/env python3
"""Attach the searchable literature map and manifest to both FixAR cases."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import urllib.parse
import urllib.request
from pathlib import Path

from shared.internal_auth import internal_service_headers


ROOT = Path(__file__).resolve().parent
OWNER = "prn_fbab9aa00cd46169"
CASE_URL = os.getenv("CASE_URL", "http://localhost:8013")
VAULT_URL = os.getenv("VAULT_SERVICE_URL", "http://vault-service:8019")
CASES = {
    "economic-atlas": "case_66cae4a89ba6473f",
    "shock-radar": "case_008f37d03cf541e5",
}


def request(method: str, url: str, body: dict | None = None, *, binary: bool = False):
    headers = {"content-type": "application/json", **internal_service_headers()}
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode()
    with urllib.request.urlopen(
        urllib.request.Request(url, data=data, method=method, headers=headers), timeout=120
    ) as response:
        raw = response.read()
        return raw if binary else json.loads(raw)


def attach(case_id: str, slug: str, path: Path, title: str, mime: str, part: int) -> dict:
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    text = raw.decode("utf-8")
    document = request(
        "POST",
        f"{VAULT_URL}/vault/documents",
        {
            "owner_id": OWNER,
            "title": title,
            "content_b64": base64.b64encode(raw).decode(),
            "mime": mime,
            "kind": "file",
            "sensitivity": "normal",
            "domain": "software",
            "source_case_id": case_id,
            "in_knowledge": False,
            "text": text,
        },
    )["document"]
    material = request(
        "POST",
        f"{CASE_URL}/cases/{case_id}/materials",
        {
            "kind": "file",
            "mime": mime,
            "title": title,
            "storage_ref": f"vault:{document['id']}",
            "extracted": text,
            "sensitivity": "normal",
            "source_channel": "api",
            "uploaded_by": OWNER,
            "client_message_id": f"sberindex-2026-09-20:{slug}:literature:{part}",
            "client_request_hash": digest,
            "part_index": part,
        },
    )
    query = urllib.parse.urlencode({"principal_id": OWNER})
    content = request(
        "GET",
        f"{CASE_URL}/cases/{case_id}/materials/{material['id']}/content?{query}",
        binary=True,
    )
    if hashlib.sha256(content).hexdigest() != digest:
        raise RuntimeError(f"roundtrip mismatch: {title}")
    return {"id": material["id"], "title": title, "sha256": digest, "verified": True}


def main() -> None:
    receipts = []
    for slug, case_id in CASES.items():
        case = request("GET", f"{CASE_URL}/cases/{case_id}")
        if case.get("owner_id") != OWNER:
            raise RuntimeError(f"unexpected owner for {case_id}")
        files = [
            (
                ROOT / f"{slug}-literature-review.md",
                "Научная литература — приоритет чтения.md",
                "text/markdown",
            ),
            (ROOT / "papers.json", "Научная литература — реестр 30 работ.json", "application/json"),
        ]
        materials = [
            attach(case_id, slug, path, title, mime, 60 + index)
            for index, (path, title, mime) in enumerate(files)
        ]
        receipts.append({"project": slug, "case_id": case_id, "materials": materials})
    output = {"synced_on": "2026-09-20", "cases": receipts}
    (ROOT / "fixar-literature-receipts.json").write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    main()
