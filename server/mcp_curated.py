"""
Curated MCP tool whitelist (G).

`list_tools()` in `server/mcp_playground_api.py` filters through this
whitelist so a random operator can't accidentally expose an internal
admin route as an LLM-callable tool. Adding a new tool is a one-line
change here plus a schema entry in the playground module; removing
one is a one-line change here.

The order of `CURATED_TOOLS` is also the order the tools show up in
`GET /mcp/tools`, so it doubles as the documentation surface.

Status classification
---------------------

  "stable"   — v1 contract, safe to depend on
  "beta"     — behaviour stable but the response shape may still evolve
  "internal" — for tests only; NEVER returned to a public LLM host
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CuratedTool:
    name: str
    status: str  # stable | beta | internal
    mutates: bool
    requires_x402: bool
    summary: str


CURATED_TOOLS: list[CuratedTool] = [
    CuratedTool(
        "create_escrow",
        "stable",
        True,
        True,
        "Register a new escrow with buyer, seller, amount, and service hash.",
    ),
    CuratedTool(
        "settle_escrow",
        "stable",
        True,
        True,
        "Release funds on a satisfied escrow.",
    ),
    CuratedTool(
        "dispute_escrow",
        "stable",
        True,
        True,
        "Open a formal dispute with attached evidence hashes.",
    ),
    CuratedTool(
        "get_escrow_status",
        "stable",
        False,
        False,
        "Read the current on-chain state of one escrow.",
    ),
    CuratedTool(
        "list_agents",
        "stable",
        False,
        False,
        "Discover verified agents in the /agents registry.",
    ),
    CuratedTool(
        "get_agent_reputation",
        "stable",
        False,
        False,
        "Fetch a reputation score for one agent.",
    ),
    CuratedTool(
        "quote_insurance_premium",
        "stable",
        False,
        False,
        "Ask what the premium would be for a proposed escrow.",
    ),
    CuratedTool(
        "check_risk_regime",
        "beta",
        False,
        False,
        "Run the CUSUM regime-shift detector on a sample stream.",
    ),
    CuratedTool(
        "preview_dispute_rubric",
        "beta",
        False,
        False,
        "Ask what the deterministic dispute rubric would score.",
    ),
]

CURATED_TOOL_NAMES: frozenset[str] = frozenset(t.name for t in CURATED_TOOLS)


def is_curated(tool_name: str) -> bool:
    """Cheap membership check for the MCP whitelist."""
    return tool_name in CURATED_TOOL_NAMES


def get_curated(tool_name: str) -> CuratedTool | None:
    for t in CURATED_TOOLS:
        if t.name == tool_name:
            return t
    return None
