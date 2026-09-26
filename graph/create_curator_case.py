"""Create the curator case once using the case-service idempotency contract."""
from __future__ import annotations

import hashlib
import json

import httpx


payload = {
    "owner_id": "prn_fbab9aa00cd46169",
    "title": "СберИндекс 2026 — Куратор исследований",
    "goal": (
        "Принимать staging-доказательства, сверять их с лестницами двух "
        "исследований и выдавать следующий атомарный шаг"
    ),
    "created_from": "api",
    "client_message_id": "sberindex-research-curator-case-v1",
}
payload["client_request_hash"] = hashlib.sha256(
    json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
).hexdigest()
response = httpx.post("http://case-service:8013/cases", json=payload, timeout=30)
response.raise_for_status()
print(json.dumps(response.json(), ensure_ascii=False))
