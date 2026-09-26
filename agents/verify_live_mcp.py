"""Verify the two SberIndex agent MCP surfaces against production data."""
from __future__ import annotations

import asyncio
import json
import math
import os
import secrets
from typing import Any

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from shared.internal_auth import internal_service_headers


ATLAS = "software:sberindex_atlas_researcher@5"
RADAR = "software:sberindex_radar_researcher@5"
WEB_RESEARCH = {
    "jina_search_web",
    "jina_read_url",
    "robots_check",
    "fetch_page",
    "sitemap_scan",
    "handoff_link",
    "recon_mcp_allowlist",
    "recon_mcp_katana",
    "recon_mcp_hakrawler",
    "recon_mcp_linkfinder",
    "recon_mcp_httpie",
    "apify_web_research",
    "apify_web_research_results",
}
EXPECTED = {
    ATLAS: WEB_RESEARCH | {
        "sberindex_atlas_kb_search",
        "sberindex_data_catalog",
        "sberindex_query_data",
        "sberindex_normalize",
        "sberindex_scientific_metric",
        "sberindex_spatial_moran",
        "sberindex_cluster",
    },
    RADAR: WEB_RESEARCH | {
        "sberindex_radar_kb_search",
        "sberindex_data_catalog",
        "sberindex_query_data",
        "sberindex_normalize",
        "sberindex_scientific_metric",
        "sberindex_forecast",
    },
}
CASES = {
    ATLAS: "case_66cae4a89ba6473f",
    RADAR: "case_008f37d03cf541e5",
}
MCP_URL = os.getenv("SBERINDEX_MCP_URL", "http://127.0.0.1:8004/mcp/")


def result_json(result: Any) -> dict[str, Any]:
    texts = [getattr(block, "text", "") for block in result.content]
    payload = json.loads(next(text for text in texts if text))
    if result.isError or not payload.get("success"):
        raise RuntimeError(payload)
    return payload["result"]


async def session_for(agent_id: str):
    headers = {
        **internal_service_headers(),
        "X-AIOS-Agent-ID": agent_id,
        "X-AIOS-Session-ID": "sberindex-analytics-live-verification",
        "X-AIOS-Request-ID": "verify-" + secrets.token_hex(6),
        "X-AIOS-Principal-ID": "prn_fbab9aa00cd46169",
        "X-AIOS-Case-ID": CASES[agent_id],
    }
    client = httpx.AsyncClient(headers=headers, timeout=180)
    streams = streamable_http_client(
        MCP_URL, http_client=client
    )
    return client, streams


async def verify_agent(agent_id: str) -> dict[str, Any]:
    client, streams_ctx = await session_for(agent_id)
    async with client, streams_ctx as streams, ClientSession(
        streams[0], streams[1]
    ) as session:
        await session.initialize()
        listed = await session.list_tools()
        exposed = {tool.name for tool in listed.tools}
        expected = EXPECTED[agent_id]
        if exposed != expected:
            raise RuntimeError(
                f"{agent_id}: exposed={sorted(exposed)}, expected={sorted(expected)}"
            )

        catalog = result_json(await session.call_tool(
            "sberindex_data_catalog", {"dataset": "historical_spending"}
        ))
        if catalog["datasets"][0]["rows"] != 303126:
            raise RuntimeError(f"unexpected historical row count: {catalog}")
        if any(name.startswith("__index_level_")
               for name in catalog["datasets"][0]["columns"]):
            raise RuntimeError(f"synthetic parquet index leaked: {catalog}")

        query = result_json(await session.call_tool("sberindex_query_data", {
            "dataset": "historical_spending",
            "filters": {"territory_id": 1, "category": "Продовольствие"},
            "limit": 3,
        }))
        if query["matched_rows"] != 24:
            raise RuntimeError(f"unexpected filtered row count: {query}")

        metric = result_json(await session.call_tool(
            "sberindex_scientific_metric", {
                "dataset": "historical_spending",
                "metric": "seasonal_naive_mae",
                "value_column": "value",
                "time_column": "date",
                "lag": 12,
                "filters": {
                    "territory_id": 1,
                    "category": "Продовольствие",
                },
            }
        ))
        metric_value = metric["results"][0]["value"]
        if not math.isclose(metric_value, 1153.5):
            raise RuntimeError(f"unexpected seasonal baseline: {metric}")

        summary: dict[str, Any] = {
            "agent": agent_id,
            "tools": sorted(exposed),
            "historical_rows": catalog["datasets"][0]["rows"],
            "filtered_rows": query["matched_rows"],
            "seasonal_naive_mae": metric_value,
        }
        if agent_id == ATLAS:
            moran = result_json(await session.call_tool(
                "sberindex_spatial_moran", {
                    "dataset": "historical_spending",
                    "filters": {
                        "date": "2023-01",
                        "category": "Продовольствие",
                    },
                    "k_neighbors": 4,
                    "permutations": 9,
                }
            ))
            if moran["territories"] < 2000 or not math.isfinite(moran["moran_i"]):
                raise RuntimeError(f"unexpected Moran result: {moran}")
            summary["moran"] = {
                key: moran[key]
                for key in (
                    "territories",
                    "k_neighbors",
                    "moran_i",
                    "two_sided_permutation_p",
                )
            }
        return summary


async def main() -> None:
    results = []
    for agent_id in (ATLAS, RADAR):
        results.append(await verify_agent(agent_id))
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
