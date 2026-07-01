"""AgentEscrow402 MCP Server.

Exposes escrow functionality via the Model Context Protocol (MCP),
letting any MCP-compatible LLM manage on-chain payments natively.

Start:
    python -m sdk.mcp_server                        # stdio (default)
    python -m sdk.mcp_server --transport sse         # SSE on port 8402

Requires: ``pip install mcp``
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import time
import uuid
from typing import Any

try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import TextContent, Tool

    HAS_MCP = True
except ImportError:
    HAS_MCP = False

import httpx

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_API_URL = "http://localhost:8000"


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


async def _post(url: str, body: dict[str, Any], params: dict[str, str] | None = None) -> dict:
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(url, json=body, params=params)
        r.raise_for_status()
        return r.json()


async def _get(url: str) -> dict:
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(url)
        r.raise_for_status()
        return r.json()


def _hash(sender: str, receiver: str, amount: int, nonce: str) -> str:
    return hashlib.sha256(f"{sender}:{receiver}:{amount}:{nonce}".encode()).hexdigest()


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

TOOLS = [
    Tool(
        name="create_escrow",
        description=(
            "Lock funds in a new escrow between sender and receiver. "
            "Returns the created escrow record with service_hash."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "sender": {"type": "string", "description": "Payer agent ID"},
                "receiver": {"type": "string", "description": "Service provider ID"},
                "amount": {"type": "integer", "description": "Amount in motes"},
                "ttl": {
                    "type": "integer",
                    "description": "Time-to-live in seconds (60-86400)",
                    "default": 300,
                },
            },
            "required": ["sender", "receiver", "amount"],
        },
    ),
    Tool(
        name="release_escrow",
        description="Release escrowed funds to the receiver after service delivery.",
        inputSchema={
            "type": "object",
            "properties": {
                "sender": {"type": "string"},
                "service_hash": {
                    "type": "string",
                    "description": "SHA-256 hash of the escrow",
                },
            },
            "required": ["sender", "service_hash"],
        },
    ),
    Tool(
        name="refund_escrow",
        description="Refund escrowed funds back to the sender.",
        inputSchema={
            "type": "object",
            "properties": {
                "sender": {"type": "string"},
                "service_hash": {"type": "string"},
            },
            "required": ["sender", "service_hash"],
        },
    ),
    Tool(
        name="dispute_escrow",
        description="Open a dispute on an active escrow.",
        inputSchema={
            "type": "object",
            "properties": {
                "sender": {"type": "string"},
                "service_hash": {"type": "string"},
                "reason_hash": {
                    "type": "string",
                    "description": "SHA-256 of the dispute reason",
                },
            },
            "required": ["sender", "service_hash", "reason_hash"],
        },
    ),
    Tool(
        name="get_escrow",
        description="Fetch the current status and details of an escrow.",
        inputSchema={
            "type": "object",
            "properties": {
                "service_hash": {"type": "string"},
            },
            "required": ["service_hash"],
        },
    ),
    Tool(
        name="get_reputation",
        description="Query the on-chain reputation score of an agent.",
        inputSchema={
            "type": "object",
            "properties": {
                "agent": {"type": "string", "description": "Agent ID to look up"},
            },
            "required": ["agent"],
        },
    ),
    Tool(
        name="build_x402_header",
        description="Build an x402 payment header for HTTP requests.",
        inputSchema={
            "type": "object",
            "properties": {
                "sender": {"type": "string"},
                "receiver": {"type": "string"},
                "amount": {"type": "integer"},
            },
            "required": ["sender", "receiver", "amount"],
        },
    ),
    Tool(
        name="list_escrows",
        description="List all escrows with optional status filter.",
        inputSchema={
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "Filter by status (active, completed, disputed, expired)",
                },
                "limit": {"type": "integer", "description": "Max results", "default": 50},
            },
        },
    ),
    Tool(
        name="get_stats",
        description="Get aggregate escrow statistics: total count, volume, success rate.",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="estimate_fee",
        description="Estimate fees and insurance cost for a given escrow amount.",
        inputSchema={
            "type": "object",
            "properties": {
                "amount": {"type": "integer", "description": "Escrow amount in motes"},
            },
            "required": ["amount"],
        },
    ),
    Tool(
        name="get_escrow_history",
        description="Get the full state change history of an escrow.",
        inputSchema={
            "type": "object",
            "properties": {
                "service_hash": {"type": "string"},
            },
            "required": ["service_hash"],
        },
    ),
    Tool(
        name="list_agents",
        description="List all known agents with their reputation scores.",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="get_events",
        description="Get recent escrow events (creates, releases, disputes).",
        inputSchema={
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Max events", "default": 20},
            },
        },
    ),
    Tool(
        name="compute_hash",
        description="Compute the service hash for a sender-receiver-amount tuple.",
        inputSchema={
            "type": "object",
            "properties": {
                "sender": {"type": "string"},
                "receiver": {"type": "string"},
                "amount": {"type": "integer"},
            },
            "required": ["sender", "receiver", "amount"],
        },
    ),
    Tool(
        name="health_check",
        description="Check API and blockchain connection health status.",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="list_escrows",
        description="List all escrows with optional status filter.",
        inputSchema={
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "Filter by status (active, completed, disputed, expired)",
                    "enum": ["active", "completed", "disputed", "expired"],
                },
                "limit": {"type": "integer", "description": "Max results (default 50)", "default": 50},
            },
        },
    ),
    Tool(
        name="get_stats",
        description="Get aggregate escrow statistics: total count, volume, success rate.",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="estimate_fee",
        description="Estimate fees and insurance cost for a given escrow amount.",
        inputSchema={
            "type": "object",
            "properties": {
                "amount": {"type": "integer", "description": "Escrow amount in motes"},
            },
            "required": ["amount"],
        },
    ),
    Tool(
        name="get_escrow_history",
        description="Get the full state change history of an escrow.",
        inputSchema={
            "type": "object",
            "properties": {
                "service_hash": {"type": "string"},
            },
            "required": ["service_hash"],
        },
    ),
    Tool(
        name="list_agents",
        description="List all known agents with their reputation scores.",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="get_events",
        description="Get recent escrow events (creates, releases, disputes).",
        inputSchema={
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Max events to return", "default": 20},
            },
        },
    ),
    Tool(
        name="compute_hash",
        description="Compute the service hash for a sender-receiver-amount tuple.",
        inputSchema={
            "type": "object",
            "properties": {
                "sender": {"type": "string"},
                "receiver": {"type": "string"},
                "amount": {"type": "integer"},
            },
            "required": ["sender", "receiver", "amount"],
        },
    ),
    Tool(
        name="health_check",
        description="Check API and blockchain connection health status.",
        inputSchema={"type": "object", "properties": {}},
    ),
]

# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------


async def handle_tool(name: str, args: dict[str, Any], api_url: str) -> str:
    """Route a tool call to the API and return JSON."""
    base = api_url.rstrip("/")

    if name == "create_escrow":
        nonce = uuid.uuid4().hex
        sh = _hash(args["sender"], args["receiver"], args["amount"], nonce)
        result = await _post(
            f"{base}/escrow",
            {
                "receiver": args["receiver"],
                "amount": args["amount"],
                "service_hash": sh,
                "ttl": args.get("ttl", 300),
            },
            params={"sender": args["sender"]},
        )

    elif name == "release_escrow":
        result = await _post(
            f"{base}/release",
            {"service_hash": args["service_hash"]},
            params={"sender": args["sender"]},
        )

    elif name == "refund_escrow":
        result = await _post(
            f"{base}/refund",
            {"service_hash": args["service_hash"]},
            params={"sender": args["sender"]},
        )

    elif name == "dispute_escrow":
        result = await _post(
            f"{base}/dispute",
            {"service_hash": args["service_hash"], "reason_hash": args["reason_hash"]},
            params={"sender": args["sender"]},
        )

    elif name == "get_escrow":
        result = await _get(f"{base}/escrow/{args['service_hash']}")

    elif name == "get_reputation":
        result = await _get(f"{base}/reputation/{args['agent']}")

    elif name == "build_x402_header":
        nonce = uuid.uuid4().hex
        sh = _hash(args["sender"], args["receiver"], args["amount"], nonce)
        ts = int(time.time())
        result = {
            "header": f"x402;1;{args['amount']};{sh};{ts};{nonce}",
            "service_hash": sh,
            "nonce": nonce,
        }

    elif name == "list_escrows":
        params = []
        if "status" in args:
            params.append(f"status={args['status']}")
        if "limit" in args:
            params.append(f"limit={args['limit']}")
        qs = f"?{'&'.join(params)}" if params else ""
        result = await _get(f"{base}/escrows{qs}")

    elif name == "get_stats":
        result = await _get(f"{base}/stats")

    elif name == "estimate_fee":
        result = await _get(f"{base}/estimate?amount={args['amount']}")

    elif name == "get_escrow_history":
        result = await _get(f"{base}/escrow/{args['service_hash']}/history")

    elif name == "list_agents":
        result = await _get(f"{base}/agents")

    elif name == "get_events":
        limit = args.get("limit", 20)
        result = await _get(f"{base}/events?limit={limit}")

    elif name == "compute_hash":
        result = await _post(f"{base}/compute-hash", {
            "sender": args["sender"],
            "receiver": args["receiver"],
            "amount": args["amount"],
        })

    elif name == "health_check":
        result = await _get(f"{base}/health")


    elif name == "list_escrows":
        params = {}
        if "status" in args:
            params["status"] = args["status"]
        if "limit" in args:
            params["limit"] = str(args["limit"])
        url = f"{base}/escrows"
        if params:
            qs = "&".join(f"{k}={v}" for k, v in params.items())
            url += f"?{qs}"
        result = await _get(url)

    elif name == "get_stats":
        result = await _get(f"{base}/stats")

    elif name == "estimate_fee":
        result = await _get(f"{base}/estimate?amount={args['amount']}")

    elif name == "get_escrow_history":
        result = await _get(f"{base}/escrow/{args['service_hash']}/history")

    elif name == "list_agents":
        result = await _get(f"{base}/agents")

    elif name == "get_events":
        limit = args.get("limit", 20)
        result = await _get(f"{base}/events?limit={limit}")

    elif name == "compute_hash":
        result = await _post(f"{base}/compute-hash", {
            "sender": args["sender"],
            "receiver": args["receiver"],
            "amount": args["amount"],
        })

    elif name == "health_check":
        result = await _get(f"{base}/health")

    else:
        result = {"error": f"Unknown tool: {name}"}

    return json.dumps(result, indent=2)


# ---------------------------------------------------------------------------
# MCP server setup
# ---------------------------------------------------------------------------


def build_server(api_url: str = DEFAULT_API_URL) -> "Server":
    """Create the MCP server with registered tools."""
    if not HAS_MCP:
        raise ImportError("Install the `mcp` package: pip install mcp")

    app = Server("agentescrow402")

    @app.list_tools()
    async def list_tools() -> list[Tool]:
        return TOOLS

    @app.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        text = await handle_tool(name, arguments, api_url)
        return [TextContent(type="text", text=text)]

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="AgentEscrow402 MCP Server")
    parser.add_argument("--api-url", default=DEFAULT_API_URL)
    parser.add_argument("--transport", choices=["stdio", "sse"], default="stdio")
    parser.add_argument("--port", type=int, default=8402)
    args = parser.parse_args()

    app = build_server(api_url=args.api_url)

    if args.transport == "stdio":
        asyncio.run(_run_stdio(app))
    else:
        try:
            import uvicorn
            from mcp.server.sse import SseServerTransport
            from starlette.applications import Starlette
            from starlette.routing import Route

            sse = SseServerTransport("/messages")
            starlette = Starlette(
                routes=[
                    Route("/sse", endpoint=sse.handle_sse_request),
                    Route("/messages", endpoint=sse.handle_post_message, methods=["POST"]),
                ]
            )
            uvicorn.run(starlette, host="0.0.0.0", port=args.port)
        except ImportError:
            print(
                "SSE transport requires: pip install mcp[sse] uvicorn starlette",
                file=sys.stderr,
            )
            sys.exit(1)


async def _run_stdio(app: "Server") -> None:
    async with stdio_server() as (read, write):
        await app.run(read, write, app.create_initialization_options())


if __name__ == "__main__":
    main()
