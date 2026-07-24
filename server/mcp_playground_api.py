"""Hosted MCP playground endpoints.

Serves the MCP tool catalogue (26 tools shipped in `docs/mcp_tools_schema.json`
and implemented by `sdk/mcp_server.py`) to the frontend so a visitor can
browse, inspect, and *safely dry-run* the tools without installing an MCP
client — see docs/MCP_PLAYGROUND.md.

Two endpoints only:

- ``GET  /mcp/tools``        — the tool catalogue: name, description,
                              input JSON schema. Read-only.
- ``POST /mcp/tools/{name}/call``
                              — invoke a single tool. Under the hood this
                              maps 1:1 to an existing hosted API endpoint
                              — no separate implementation path — so the
                              same auth, rate-limits, and Observer/Driver
                              policy fence apply. The mapping is
                              deliberately declarative + read-mostly:
                              write tools stay behind the same x402
                              payment header and role fence as their
                              underlying REST endpoint.

Return shape mirrors an MCP tool response (`content` list of
`{type, text}`) so the frontend renderer can be reused verbatim if we
ever ship a real hosted MCP server.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mcp", tags=["mcp"])

# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------

_SCHEMA_PATH = Path(__file__).resolve().parent.parent / "docs" / "mcp_tools_schema.json"


def _load_schema() -> dict[str, Any]:
    """Load the shipped tool catalogue. Cached at import time."""
    try:
        return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        logger.warning("mcp_tools_schema.json not found at %s", _SCHEMA_PATH)
        return {"name": "AgentEscrow402 MCP Server", "version": "unknown", "tools": []}
    except json.JSONDecodeError as exc:
        logger.error("mcp_tools_schema.json is not valid JSON: %s", exc)
        return {"name": "AgentEscrow402 MCP Server", "version": "unknown", "tools": []}


_CATALOGUE = _load_schema()
_TOOLS_BY_NAME: dict[str, dict[str, Any]] = {t["name"]: t for t in _CATALOGUE.get("tools", [])}


@router.get("/tools")
async def list_tools() -> dict[str, Any]:
    """Return the shipped MCP tool catalogue (name, description, input schema).

    Read-only. Safe to call from any role. Response matches the shape of
    `docs/mcp_tools_schema.json` verbatim.
    """
    return _CATALOGUE


# ---------------------------------------------------------------------------
# Tool → REST dispatch
# ---------------------------------------------------------------------------


class ToolCallRequest(BaseModel):
    arguments: dict[str, Any] = Field(default_factory=dict)


def _content(text: str, is_error: bool = False) -> dict[str, Any]:
    """Wrap a text payload in the MCP `content` envelope."""
    return {
        "content": [{"type": "text", "text": text}],
        "isError": is_error,
    }


async def _forward_json(
    request: Request,
    method: str,
    path: str,
    *,
    json_body: dict[str, Any] | None = None,
    query_params: dict[str, Any] | None = None,
) -> Any:
    """Invoke a hosted endpoint in-process via ASGI so the request keeps
    the same auth / middleware / role fence as a direct HTTP call.

    Uses httpx.AsyncClient(transport=ASGITransport(app=...)) instead of
    calling the route function directly — this way the x402 payment
    middleware, rate limits, Observer-mode fence, and every other layer
    are exercised exactly like a real client call.
    """
    import httpx  # local import so a stripped-down deploy still imports the module

    transport = httpx.ASGITransport(app=request.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://mcp-playground") as client:
        # Preserve x402 / observer / bearer headers from the caller so the
        # inner request behaves the same as a direct call.
        forwarded_headers = {
            k: v
            for k, v in request.headers.items()
            if k.lower()
            in {
                "x-payment",
                "authorization",
                "x-observer-role",
                "x-ae402-demo-identity",
                "content-type",
            }
        }
        forwarded_headers.setdefault("content-type", "application/json")
        response = await client.request(
            method,
            path,
            params=query_params,
            json=json_body,
            headers=forwarded_headers,
        )
        try:
            return response.status_code, response.json()
        except ValueError:
            return response.status_code, {"raw": response.text}


# Declarative tool -> REST endpoint mapping. Each entry:
#   (method, path_template, body_or_query, kind)
# path_template can reference {arg} placeholders from `arguments`.
# `body_or_query`:
#   - "body"  → arguments (minus path placeholders) become the JSON body
#   - "query" → arguments (minus path placeholders) become query params
#   - "none"  → nothing forwarded
# `kind`:
#   - "read"  → allowed in observer mode
#   - "write" → x402 required; blocked in observer role at the fetcher
#              layer *if it were called from the browser*; on the server
#              side we still trust the x402 header enforcement.
_TOOL_ROUTES: dict[str, tuple[str, str, str, str]] = {
    # Escrow lifecycle
    "create_escrow": ("POST", "/escrow", "body", "write"),
    "release_escrow": ("POST", "/release", "body", "write"),
    "refund_escrow": ("POST", "/refund", "body", "write"),
    "dispute_escrow": ("POST", "/dispute", "body", "write"),
    # Reads
    "get_escrow": ("GET", "/escrow/{escrow_id}", "none", "read"),
    "get_reputation": ("GET", "/reputation/{account}", "none", "read"),
    "list_escrows": ("GET", "/escrows", "query", "read"),
    "get_stats": ("GET", "/stats", "none", "read"),
    "estimate_fee": ("GET", "/estimate", "query", "read"),
    "get_escrow_history": ("GET", "/escrow/{escrow_id}/history", "none", "read"),
    "list_agents": ("GET", "/agents", "none", "read"),
    "health_check": ("GET", "/health", "none", "read"),
    # Compute / helpers (idempotent POST)
    "compute_hash": ("POST", "/compute-hash", "query", "read"),
    "build_x402_header": ("POST", "/x402/build-header", "body", "read"),
    # Risk
    "calculate_risk_score": ("POST", "/risk/score", "body", "read"),
    "get_risk_dashboard": ("GET", "/risk/dashboard", "none", "read"),
    # Identity registry
    "register_identity": ("POST", "/registry/register", "body", "write"),
    "get_identity": ("GET", "/registry/identity/{did}", "none", "read"),
    # Arbitration
    "submit_dispute_arbitration": ("POST", "/arbitration/analyze", "body", "write"),
    "get_arbitration_result": ("GET", "/arbitration/result/{dispute_id}", "none", "read"),
    "appeal_arbitration": ("POST", "/arbitration/appeal", "body", "write"),
    "elect_arbiter": ("POST", "/arbiter/elect-vrf", "body", "read"),
    # Batch
    "batch_release": ("POST", "/escrows/batch-release", "body", "write"),
    "batch_cancel": ("POST", "/escrows/batch-cancel", "body", "write"),
    # Streaming
    "claim_stream": ("POST", "/escrow/{escrow_id}/stream-claim", "none", "write"),
}


@router.post("/tools/{tool_name}/call")
async def call_tool(tool_name: str, request: Request, payload: ToolCallRequest) -> Any:
    """Invoke a single MCP tool by name.

    Response mirrors the MCP `CallToolResult` shape:
        { "content": [{ "type": "text", "text": "<json-encoded body>" }],
          "isError": false | true,
          "status": <int http status of the underlying endpoint>,
          "tool": "<tool name>" }

    Errors from the underlying REST endpoint are surfaced as
    `isError: true` with the response body serialized in the content
    block, so the playground can render a red error card without a
    separate error-response schema.
    """
    if tool_name not in _TOOLS_BY_NAME:
        raise HTTPException(status_code=404, detail=f"unknown tool: {tool_name}")

    if tool_name not in _TOOL_ROUTES:
        # Documented in the schema but not yet dispatchable — respond with
        # a structured "not routed" placeholder instead of a 500.
        return JSONResponse(
            status_code=501,
            content={
                **_content(
                    f"Tool '{tool_name}' is declared in the MCP schema but has no REST dispatch route yet. "
                    "It is available via the stdio/SSE MCP server (`python -m sdk.mcp_server`).",
                    is_error=True,
                ),
                "tool": tool_name,
                "status": 501,
            },
        )

    method, path_template, kind, _ = _TOOL_ROUTES[tool_name]
    args = dict(payload.arguments or {})

    # Fill path placeholders from arguments.
    try:
        path = path_template.format(**args)
    except KeyError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"missing required path argument for '{tool_name}': {exc.args[0]}",
        ) from exc

    # Remove placeholders from remaining args.
    used_path_args = {name.strip("{}") for name in _extract_placeholders(path_template)}
    forward_args = {k: v for k, v in args.items() if k not in used_path_args}

    body: dict[str, Any] | None
    query: dict[str, Any] | None
    if kind == "body":
        body, query = forward_args, None
    elif kind == "query":
        body, query = None, forward_args
    else:
        body, query = None, None

    try:
        status, data = await _forward_json(
            request,
            method,
            path,
            json_body=body,
            query_params=query,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("mcp playground dispatch failed for %s", tool_name)
        return JSONResponse(
            status_code=500,
            content={
                **_content(f"Dispatch failed: {exc}", is_error=True),
                "tool": tool_name,
                "status": 500,
            },
        )

    text = json.dumps(data, ensure_ascii=False, indent=2)
    return {
        **_content(text, is_error=status >= 400),
        "tool": tool_name,
        "status": status,
    }


def _extract_placeholders(template: str) -> list[str]:
    """Return the raw '{name}' segments in a path template."""
    out: list[str] = []
    start = 0
    while True:
        i = template.find("{", start)
        if i == -1:
            break
        j = template.find("}", i)
        if j == -1:
            break
        out.append(template[i : j + 1])
        start = j + 1
    return out
