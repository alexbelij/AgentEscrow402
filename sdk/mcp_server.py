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
# Tool definitions — Core Escrow (15 tools)
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
                "service_hash": {"type": "string", "description": "SHA-256 hash of the escrow"},
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
                "reason_hash": {"type": "string", "description": "SHA-256 of the dispute reason"},
            },
            "required": ["sender", "service_hash", "reason_hash"],
        },
    ),
    Tool(
        name="get_escrow",
        description="Fetch the current status and details of an escrow.",
        inputSchema={
            "type": "object",
            "properties": {"service_hash": {"type": "string"}},
            "required": ["service_hash"],
        },
    ),
    Tool(
        name="get_reputation",
        description="Query the on-chain reputation score of an agent.",
        inputSchema={
            "type": "object",
            "properties": {"agent": {"type": "string", "description": "Agent ID to look up"}},
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
                    "description": "Filter by status",
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
            "properties": {"amount": {"type": "integer", "description": "Escrow amount in motes"}},
            "required": ["amount"],
        },
    ),
    Tool(
        name="get_escrow_history",
        description="Get the full state change history of an escrow.",
        inputSchema={
            "type": "object",
            "properties": {"service_hash": {"type": "string"}},
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
            "properties": {"limit": {"type": "integer", "description": "Max events", "default": 20}},
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

    # ------------------------------------------------------------------
    # AI Arbitration tools (3)
    # ------------------------------------------------------------------
    Tool(
        name="submit_dispute_arbitration",
        description=(
            "Submit a disputed escrow to the AI arbitration engine. "
            "Analyzes evidence from both parties and produces a binding resolution."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "service_hash": {"type": "string", "description": "Escrow identifier"},
                "evidence_sender": {"type": "string", "description": "Sender evidence text/hash"},
                "evidence_receiver": {"type": "string", "description": "Receiver evidence text/hash"},
                "category": {
                    "type": "string",
                    "enum": ["non_delivery", "quality", "late_delivery", "fraud"],
                    "description": "Dispute category",
                },
            },
            "required": ["service_hash", "evidence_sender", "evidence_receiver"],
        },
    ),
    Tool(
        name="get_arbitration_result",
        description="Get the AI arbitration verdict and reasoning for a dispute.",
        inputSchema={
            "type": "object",
            "properties": {
                "arbitration_id": {"type": "string", "description": "Arbitration case ID"},
            },
            "required": ["arbitration_id"],
        },
    ),
    Tool(
        name="appeal_arbitration",
        description="Appeal an AI arbitration decision within the allowed window.",
        inputSchema={
            "type": "object",
            "properties": {
                "arbitration_id": {"type": "string"},
                "appellant": {"type": "string", "description": "Agent ID filing appeal"},
                "new_evidence": {"type": "string", "description": "Additional evidence hash"},
            },
            "required": ["arbitration_id", "appellant"],
        },
    ),

    # ------------------------------------------------------------------
    # Risk Scoring tools (3)
    # ------------------------------------------------------------------
    Tool(
        name="calculate_risk_score",
        description=(
            "Calculate a composite risk score for a proposed escrow transaction. "
            "Considers counterparty history, amount, and chain heuristics."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "sender": {"type": "string"},
                "receiver": {"type": "string"},
                "amount": {"type": "integer", "description": "Amount in motes"},
            },
            "required": ["sender", "receiver", "amount"],
        },
    ),
    Tool(
        name="get_risk_report",
        description="Retrieve a detailed risk breakdown for an agent or escrow.",
        inputSchema={
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "Agent ID or service_hash"},
                "report_type": {
                    "type": "string",
                    "enum": ["agent", "escrow"],
                    "default": "agent",
                },
            },
            "required": ["target"],
        },
    ),
    Tool(
        name="set_risk_threshold",
        description="Configure auto-reject threshold for high-risk transactions.",
        inputSchema={
            "type": "object",
            "properties": {
                "threshold": {
                    "type": "number",
                    "description": "Risk score 0.0-1.0 above which transactions are flagged",
                    "minimum": 0.0,
                    "maximum": 1.0,
                },
                "action": {
                    "type": "string",
                    "enum": ["flag", "reject", "require_review"],
                    "default": "flag",
                },
            },
            "required": ["threshold"],
        },
    ),

    # ------------------------------------------------------------------
    # Identity Registry tools (3)
    # ------------------------------------------------------------------
    Tool(
        name="register_identity",
        description="Register a new agent identity with KYC-level credentials on-chain.",
        inputSchema={
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "Unique agent identifier"},
                "public_key": {"type": "string", "description": "Ed25519 public key hex"},
                "metadata": {
                    "type": "object",
                    "description": "Optional metadata (display_name, org, contact)",
                },
            },
            "required": ["agent_id", "public_key"],
        },
    ),
    Tool(
        name="verify_identity",
        description="Verify an agent's identity and credential status.",
        inputSchema={
            "type": "object",
            "properties": {
                "agent_id": {"type": "string"},
            },
            "required": ["agent_id"],
        },
    ),
    Tool(
        name="revoke_identity",
        description="Revoke an agent's identity credentials (admin only).",
        inputSchema={
            "type": "object",
            "properties": {
                "agent_id": {"type": "string"},
                "reason": {"type": "string", "description": "Revocation reason"},
            },
            "required": ["agent_id", "reason"],
        },
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
            {"receiver": args["receiver"], "amount": args["amount"], "service_hash": sh, "ttl": args.get("ttl", 300)},
            params={"sender": args["sender"]},
        )

    elif name == "release_escrow":
        result = await _post(f"{base}/release", {"service_hash": args["service_hash"]}, params={"sender": args["sender"]})

    elif name == "refund_escrow":
        result = await _post(f"{base}/refund", {"service_hash": args["service_hash"]}, params={"sender": args["sender"]})

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
        result = {"header": f"x402;1;{args['amount']};{sh};{ts};{nonce}", "service_hash": sh, "nonce": nonce}

    elif name == "list_escrows":
        params = {}
        if "status" in args:
            params["status"] = args["status"]
        if "limit" in args:
            params["limit"] = str(args["limit"])
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"{base}/escrows" + (f"?{qs}" if qs else "")
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
        result = await _get(f"{base}/events?limit={args.get('limit', 20)}")

    elif name == "compute_hash":
        result = await _post(f"{base}/compute-hash", {"sender": args["sender"], "receiver": args["receiver"], "amount": args["amount"]})

    elif name == "health_check":
        result = await _get(f"{base}/health")

    # --- AI Arbitration ---
    elif name == "submit_dispute_arbitration":
        result = await _post(f"{base}/arbitration/submit", {
            "service_hash": args["service_hash"],
            "evidence_sender": args["evidence_sender"],
            "evidence_receiver": args["evidence_receiver"],
            "category": args.get("category", "non_delivery"),
        })

    elif name == "get_arbitration_result":
        result = await _get(f"{base}/arbitration/{args['arbitration_id']}")

    elif name == "appeal_arbitration":
        result = await _post(f"{base}/arbitration/{args['arbitration_id']}/appeal", {
            "appellant": args["appellant"],
            "new_evidence": args.get("new_evidence", ""),
        })

    # --- Risk Scoring ---
    elif name == "calculate_risk_score":
        result = await _post(f"{base}/risk/score", {
            "sender": args["sender"],
            "receiver": args["receiver"],
            "amount": args["amount"],
        })

    elif name == "get_risk_report":
        result = await _get(f"{base}/risk/report/{args['target']}?type={args.get('report_type', 'agent')}")

    elif name == "set_risk_threshold":
        result = await _post(f"{base}/risk/threshold", {
            "threshold": args["threshold"],
            "action": args.get("action", "flag"),
        })

    # --- Identity Registry ---
    elif name == "register_identity":
        result = await _post(f"{base}/identity/register", {
            "agent_id": args["agent_id"],
            "public_key": args["public_key"],
            "metadata": args.get("metadata", {}),
        })

    elif name == "verify_identity":
        result = await _get(f"{base}/identity/{args['agent_id']}/verify")

    elif name == "revoke_identity":
        result = await _post(f"{base}/identity/{args['agent_id']}/revoke", {"reason": args["reason"]})

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
            print("SSE transport requires: pip install mcp[sse] uvicorn starlette", file=sys.stderr)
            sys.exit(1)


async def _run_stdio(app: "Server") -> None:
    async with stdio_server() as (read, write):
        await app.run(read, write, app.create_initialization_options())


if __name__ == "__main__":
    main()
