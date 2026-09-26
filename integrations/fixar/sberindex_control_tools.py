"""Narrow self-service controls for the SberIndex research loop.

These are intentionally not shell or deployment tools.  A researcher may
enqueue one named n8n run, or ask the platform to reload and verify the agent
catalog.  Code changes, container restarts and deploy-lock operations remain
outside the model's authority.
"""
from __future__ import annotations

import os
from typing import Any

import httpx

from shared.internal_auth import internal_service_headers


N8N_URL = os.getenv("N8N_SERVICE_URL", "http://n8n:5678").rstrip("/")
LANDSCAPE_URL = os.getenv(
    "LANDSCAPE_SERVICE_URL", "http://landscape-service:8016"
).rstrip("/")
WEBHOOK_PATH = "sberindex-graph-steward"
AGENTS = {
    "sberindex_atlas_researcher": (4, "sberindex_atlas_kb_search"),
    "sberindex_radar_researcher": (4, "sberindex_radar_kb_search"),
    "sberindex_graph_steward": (2, "sberindex_graph_kb_search"),
    "sberindex_research_curator": (2, "sberindex_graph_kb_search"),
}


def _trusted(value: dict[str, Any] | None) -> dict[str, str]:
    context = value if isinstance(value, dict) else {}
    principal_id = str(context.get("principal_id") or "").strip()
    case_id = str(context.get("case_id") or "").strip()
    invocation_id = str(context.get("invocation_id") or "").strip()
    if not principal_id or not case_id or not invocation_id:
        raise RuntimeError("нужен доверенный контекст исследователя и дела")
    return {
        "principal_id": principal_id,
        "case_id": case_id,
        "invocation_id": invocation_id,
    }


async def sberindex_research_request_run(
    topic: str,
    _request_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Enqueue one graph-steward pass through the fixed n8n webhook."""
    context = _trusted(_request_context)
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            f"{N8N_URL}/webhook/{WEBHOOK_PATH}",
            json={
                "job": "graph_refresh",
                "topic": topic.strip(),
                "requested_by": context["principal_id"],
                "source_case_id": context["case_id"],
                "run_key": context["invocation_id"],
            },
        )
    if response.status_code >= 400:
        raise RuntimeError(f"n8n webhook отвечает {response.status_code}")
    try:
        payload = response.json()
    except ValueError:
        payload = {"message": response.text[:500]}
    return {"accepted": True, "workflow": WEBHOOK_PATH, "receipt": payload}


async def sberindex_research_repair(
    _request_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Reload the mounted catalog and verify the three fixed agent surfaces."""
    context = _trusted(_request_context)
    headers = internal_service_headers()
    async with httpx.AsyncClient(headers=headers, timeout=30) as client:
        reload_response = await client.post(f"{LANDSCAPE_URL}/packs/reload")
        reload_response.raise_for_status()
        reload_result = reload_response.json()
        checks = []
        for agent_id, (version, required_tool) in AGENTS.items():
            response = await client.get(
                f"{LANDSCAPE_URL}/domains/software/agents/{agent_id}/config",
                params={
                    "assurance": 2,
                    "version": version,
                    "tenant": context["principal_id"],
                    "case": context["case_id"],
                },
            )
            if response.status_code >= 400:
                checks.append({
                    "agent": agent_id,
                    "ok": False,
                    "error": f"catalog HTTP {response.status_code}",
                })
                continue
            config = response.json()
            tools = set(config.get("tools") or [])
            checks.append({
                "agent": agent_id,
                "version": config.get("version"),
                "model": config.get("model"),
                "ok": (
                    config.get("model") == "mimo-v2.5-pro"
                    and required_tool in tools
                ),
                "required_tool": required_tool,
            })
    return {
        "reloaded": not bool(reload_result.get("problems")),
        "catalog": reload_result,
        "checks": checks,
        "healthy": all(item["ok"] for item in checks),
        "repair_scope": "catalog_reload_and_agent_surface_check",
    }


SBERINDEX_CONTROL_TOOL_SPECS = [
    {
        "name": "sberindex_research_request_run",
        "description": (
            "По явной просьбе живого исследователя поставить один атомарный "
            "проход смотрителя муниципального графа в закреплённый n8n workflow"
        ),
        "fn": sberindex_research_request_run,
        "parameters": {
            "type": "object",
            "properties": {
                "topic": {"type": "string", "minLength": 5, "maxLength": 500},
            },
            "required": ["topic"],
            "additionalProperties": False,
        },
        "category": "sberindex-control",
    },
    {
        "name": "sberindex_research_repair",
        "description": (
            "Безопасно перечитать смонтированный каталог агентов и проверить "
            "модель/обязательные инструменты исследовательского контура; не "
            "меняет код, не перезапускает контейнеры и не обходит deploy-lock"
        ),
        "fn": sberindex_research_repair,
        "parameters": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        "category": "sberindex-control",
    },
]
