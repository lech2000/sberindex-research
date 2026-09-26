#!/usr/bin/env python3
"""Attach research-agent policy, source queue and per-case ladders to FixAR."""

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
CASES = {
    "economic-atlas": "case_66cae4a89ba6473f",
    "shock-radar": "case_008f37d03cf541e5",
}


def request(method: str, url: str, body: dict | None = None, *, binary: bool = False):
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


def attach(case_id: str, slug: str, path: Path, title: str, mime: str, part: int) -> dict:
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    text = raw.decode("utf-8")
    document = request("POST", f"{VAULT_URL}/vault/documents", {
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
    })["document"]
    material = request("POST", f"{CASE_URL}/cases/{case_id}/materials", {
        "kind": "file",
        "mime": mime,
        "title": title,
        "storage_ref": f"vault:{document['id']}",
        "extracted": text,
        "sensitivity": "normal",
        "source_channel": "api",
        "uploaded_by": OWNER,
        "client_message_id": f"sberindex-2026-09-20:{slug}:research-agent:{part}",
        "client_request_hash": digest,
        "part_index": part,
    })
    query = urllib.parse.urlencode({"principal_id": OWNER})
    content = request(
        "GET", f"{CASE_URL}/cases/{case_id}/materials/{material['id']}/content?{query}",
        binary=True,
    )
    if hashlib.sha256(content).hexdigest() != digest:
        raise RuntimeError(f"roundtrip mismatch: {title}")
    return {"id": material["id"], "title": title, "sha256": digest, "verified": True}


def main() -> None:
    receipts = []
    shared = [
        (ROOT / "agents" / "README.md", "Исследовательские агенты и лестница источников.md", "text/markdown"),
        (ROOT / "agents" / "source-queue.json", "Очередь загрузок и пробелов данных.json", "application/json"),
        (ROOT / "data" / "apify-sberindex-source-discovery-2026-09-20.json", "Apify — обнаружение официальных источников 20.09.2026.json", "application/json"),
        (ROOT / "IMPLEMENTATION_PROPOSAL.md", "Предложение реализации исследовательского контура.md", "text/markdown"),
    ]
    for slug, case_id in CASES.items():
        case = request("GET", f"{CASE_URL}/cases/{case_id}")
        if case.get("owner_id") != OWNER:
            raise RuntimeError(f"unexpected owner for {case_id}")
        ladder = (
            ROOT / "economic-atlas" / "research-ladder.md"
            if slug == "economic-atlas"
            else ROOT / "shock-radar" / "research-ladder.md"
        )
        files = shared + [(ladder, "Подробная лестница исследования.md", "text/markdown")]
        materials = [
            attach(case_id, slug, path, title, mime, 40 + index)
            for index, (path, title, mime) in enumerate(files)
        ]
        receipts.append({"slug": slug, "case_id": case_id, "materials": materials})
    output = {"synced_on": "2026-09-20", "cases": receipts}
    (ROOT / "data" / "fixar-research-agent-receipts.json").write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    main()
