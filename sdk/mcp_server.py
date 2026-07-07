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
import re
import urllib.parse

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_API_URL = "http://localhost:8000"
MAX_AMOUNT = 10**18  # max 1 quintillion motes
MAX_TTL = 86400
MIN_TTL = 60
MAX_LIMIT = 500
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
ID_RE = re.compile(r"^[a-zA-Z0-9_\-.:]{1,128}$")

# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _validate_amount(v: Any) -> int:
    """Validate numeric amount is positive and bounded."""
    val = int(v)
    if val <= 0:
        raise ValueError("amount must be positive")
    if val > MAX_AMOUNT:
        raise ValueError(f"amount exceeds maximum ({MAX_AMOUNT})")
    return val


def _validate_limit(v: Any, default: int = 20) -> int:
    val = int(v) if v is not None else default
    return max(1, min(val, MAX_LIMIT))


def _validate_id(v: str, name: str = "id") -> str:
    s = str(v).strip()
    if not ID_RE.match(s):
        raise ValueError(f"invalid {name}: must be 1-128 alphanumeric chars")
    return s


def _validate_hash(v: str, name: str = "hash") -> str:
    s = str(v).strip().lower()
    if not SHA256_RE.match(s):
        raise ValueError(f"invalid {name}: must be 64 hex chars")
    return s


def _safe_path(segment: str) -> str:
    """URL-encode a path segment to prevent injection."""
    return urllib.parse.quote(str(segment), safe="")


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


async def _post(url: str, body: dict[str, Any], params: dict[str, str] | None = None) -> dict:
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(url, json=body, params=params)
        r.raise_for_status()
        return r.json()


async def _get(url: str, params: dict[str, Any] | None = None) -> dict:
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(url, params=params)
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
        description=(
            "Get recent escrow activity. Note: the backend also exposes a "
            "real-time SSE stream at GET /events for live subscriptions."
        ),
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
            "Get the IsolationForest anomaly-detection risk score for an agent. "
            "Trained on real escrow data; returns score, anomaly flag, and explanation."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "agent": {"type": "string", "description": "Agent ID or account hash"},
            },
            "required": ["agent"],
        },
    ),
    Tool(
        name="get_risk_dashboard",
        description="Get aggregated risk scores for all known agents.",
        inputSchema={"type": "object", "properties": {}},
    ),

    # ------------------------------------------------------------------
    # Identity Registry tools (3)
    # ------------------------------------------------------------------
    Tool(
        name="register_identity",
        description="Register a new agent identity with public key and capabilities.",
        inputSchema={
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "Unique agent identifier"},
                "public_key": {"type": "string", "description": "Ed25519 public key hex"},
                "capabilities": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of capability strings (e.g. 'compute', 'storage')",
                },
            },
            "required": ["agent_id", "public_key"],
        },
    ),
    Tool(
        name="get_identity",
        description="Look up an agent's registered identity, reputation and capabilities.",
        inputSchema={
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "Agent ID to look up"},
            },
            "required": ["agent_id"],
        },
    ),

    # ------------------------------------------------------------------
    # VRF Arbiter Election (1)
    # ------------------------------------------------------------------
    Tool(
        name="elect_arbiter",
        description="Run a VRF-based on-chain random arbiter election for a dispute.",
        inputSchema={
            "type": "object",
            "properties": {
                "dispute_id": {"type": "string", "description": "Dispute identifier"},
                "sender": {"type": "string", "description": "Dispute sender agent ID"},
                "receiver": {"type": "string", "description": "Dispute receiver agent ID"},
                "seed_hash": {"type": "string", "description": "64-hex randomness seed"},
            },
            "required": ["dispute_id", "sender", "receiver", "seed_hash"],
        },
    ),

    # ------------------------------------------------------------------
    # Batch Escrow (2)
    # ------------------------------------------------------------------
    Tool(
        name="batch_release",
        description="Release multiple escrows atomically with cap/quorum guard.",
        inputSchema={
            "type": "object",
            "properties": {
                "sender": {"type": "string"},
                "service_hashes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of escrow service hashes to release",
                },
            },
            "required": ["sender", "service_hashes"],
        },
    ),
    Tool(
        name="batch_cancel",
        description="Cancel (refund) multiple pending escrows atomically.",
        inputSchema={
            "type": "object",
            "properties": {
                "sender": {"type": "string"},
                "service_hashes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of pending escrow service hashes to cancel",
                },
            },
            "required": ["sender", "service_hashes"],
        },
    ),

    # ------------------------------------------------------------------
    # Streaming Escrow (1)
    # ------------------------------------------------------------------
    Tool(
        name="claim_stream",
        description="Claim a fully-vested streaming escrow (triggers on-chain release).",
        inputSchema={
            "type": "object",
            "properties": {
                "service_hash": {"type": "string", "description": "Streaming escrow hash"},
            },
            "required": ["service_hash"],
        },
    ),
]


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------


async def handle_tool(name: str, args: dict[str, Any], api_url: str) -> str:
    """Route a tool call to the API and return JSON."""
    base = api_url.rstrip("/")

    try:
        if name == "create_escrow":
            sender = _validate_id(args["sender"], "sender")
            receiver = _validate_id(args["receiver"], "receiver")
            amount = _validate_amount(args["amount"])
            ttl_raw = args.get("ttl", 300)
            ttl = max(MIN_TTL, min(int(ttl_raw), MAX_TTL))
            nonce = uuid.uuid4().hex
            sh = _hash(sender, receiver, amount, nonce)
            result = await _post(
                f"{base}/escrow",
                {"receiver": receiver, "amount": amount, "service_hash": sh, "ttl": ttl},
                params={"sender": sender},
            )

        elif name == "release_escrow":
            result = await _post(f"{base}/release", {"service_hash": _validate_hash(args["service_hash"], "service_hash")}, params={"sender": _validate_id(args["sender"], "sender")})

        elif name == "refund_escrow":
            result = await _post(f"{base}/refund", {"service_hash": _validate_hash(args["service_hash"], "service_hash")}, params={"sender": _validate_id(args["sender"], "sender")})

        elif name == "dispute_escrow":
            result = await _post(
                f"{base}/dispute",
                {"service_hash": _validate_hash(args["service_hash"], "service_hash"), "reason_hash": _validate_hash(args["reason_hash"], "reason_hash")},
                params={"sender": _validate_id(args["sender"], "sender")},
            )

        elif name == "get_escrow":
            result = await _get(f"{base}/escrow/{_safe_path(_validate_hash(args['service_hash'], 'service_hash'))}")

        elif name == "get_reputation":
            result = await _get(f"{base}/reputation/{_safe_path(_validate_id(args['agent'], 'agent'))}")

        elif name == "build_x402_header":
            sender = _validate_id(args["sender"], "sender")
            receiver = _validate_id(args["receiver"], "receiver")
            amount = _validate_amount(args["amount"])
            nonce = uuid.uuid4().hex
            sh = _hash(sender, receiver, amount, nonce)
            ts = int(time.time())
            result = {"header": f"x402;1;{amount};{sh};{ts};{nonce}", "service_hash": sh, "nonce": nonce}

        elif name == "list_escrows":
            params: dict[str, str] = {}
            if "status" in args:
                params["status"] = str(args["status"])
            params["limit"] = str(_validate_limit(args.get("limit"), 50))
            result = await _get(f"{base}/escrows", params=params)

        elif name == "get_stats":
            result = await _get(f"{base}/stats")

        elif name == "estimate_fee":
            amount = _validate_amount(args["amount"])
            result = await _get(f"{base}/estimate", params={"amount": str(amount)})

        elif name == "get_escrow_history":
            result = await _get(f"{base}/escrow/{_safe_path(_validate_hash(args['service_hash'], 'service_hash'))}/history")

        elif name == "list_agents":
            result = await _get(f"{base}/agents")

        elif name == "get_events":
            limit = _validate_limit(args.get("limit"), 20)
            result = await _get(f"{base}/escrows", params={"limit": str(limit)})

        elif name == "compute_hash":
            result = await _post(f"{base}/compute-hash", {"sender": _validate_id(args["sender"], "sender"), "receiver": _validate_id(args["receiver"], "receiver"), "amount": _validate_amount(args["amount"])})

        elif name == "health_check":
            result = await _get(f"{base}/health")

        # --- AI Arbitration ---
        elif name == "submit_dispute_arbitration":
            result = await _post(f"{base}/arbitration/analyze", {
                "service_hash": _validate_hash(args["service_hash"], "service_hash"),
                "evidence_sender": str(args["evidence_sender"])[:10000],
                "evidence_receiver": str(args["evidence_receiver"])[:10000],
                "category": args.get("category", "non_delivery"),
            })

        elif name == "get_arbitration_result":
            result = await _get(f"{base}/arbitration/{_safe_path(_validate_id(args['arbitration_id'], 'arbitration_id'))}")

        elif name == "appeal_arbitration":
            result = await _post(f"{base}/arbitration/{_safe_path(_validate_id(args['arbitration_id'], 'arbitration_id'))}/appeal", {
                "appellant": _validate_id(args["appellant"], "appellant"),
                "new_evidence": str(args.get("new_evidence", ""))[:10000],
            })

        # --- Risk Scoring ---
        elif name == "calculate_risk_score":
            agent = _validate_id(args["agent"], "agent")
            result = await _get(f"{base}/risk/score/{_safe_path(agent)}")

        elif name == "get_risk_dashboard":
            result = await _get(f"{base}/risk/dashboard")

        # --- Identity Registry ---
        elif name == "register_identity":
            result = await _post(f"{base}/identity/register", {
                "agent_id": _validate_id(args["agent_id"], "agent_id"),
                "public_key": str(args["public_key"])[:256],
                "capabilities": args.get("capabilities", []),
            })

        elif name == "get_identity":
            result = await _get(f"{base}/identity/{_safe_path(_validate_id(args['agent_id'], 'agent_id'))}")

        # --- VRF Election ---
        elif name == "elect_arbiter":
            result = await _post(f"{base}/vrf/elect", {
                "dispute_id": _validate_id(args["dispute_id"], "dispute_id"),
                "sender": _validate_id(args["sender"], "sender"),
                "receiver": _validate_id(args["receiver"], "receiver"),
                "seed_hash": _validate_hash(args["seed_hash"], "seed_hash"),
            })

        # --- Batch Lifecycle ---
        elif name == "batch_release":
            hashes = [_validate_hash(h, "service_hash") for h in args["service_hashes"]]
            result = await _post(
                f"{base}/escrows/batch-release",
                {"service_hashes": hashes},
                params={"sender": _validate_id(args["sender"], "sender")},
            )

        elif name == "batch_cancel":
            hashes = [_validate_hash(h, "service_hash") for h in args["service_hashes"]]
            result = await _post(
                f"{base}/escrows/batch-cancel",
                {"service_hashes": hashes},
                params={"sender": _validate_id(args["sender"], "sender")},
            )

        # --- Streaming ---
        elif name == "claim_stream":
            sh = _validate_hash(args["service_hash"], "service_hash")
            result = await _post(f"{base}/escrow/{_safe_path(sh)}/stream-claim", {})

        else:
            result = {"error": f"Unknown tool: {name}"}

    except (ValueError, TypeError, KeyError) as exc:
        result = {"error": f"Validation error: {exc}"}
    except httpx.HTTPStatusError:
        result = {"error": "API request failed"}
    except httpx.RequestError:
        result = {"error": "API connection error"}

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
