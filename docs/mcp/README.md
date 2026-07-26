# AE402 MCP surface

**Status:** stable (v1)
**Endpoint:** `GET /mcp/tools` · `POST /mcp/tools/{tool_name}/call`

AE402 speaks Model Context Protocol so any MCP-aware LLM host —
Claude Desktop, Cursor, OpenClaw, the OpenAI Assistants SDK — can call
into the escrow surface as first-class tools. This document is the
contract; the tool descriptions inside `/mcp/tools` are the machine-
readable version of the same thing.

## What's exposed

The curated tool set (see `server/mcp_curated.py`) is intentionally
small — nine tools that together cover the full escrow lifecycle
plus a peek at the risk surface:

| Tool | What it does |
|------|-------------|
| `create_escrow`         | Register a new escrow (buyer, seller, amount, service hash). |
| `settle_escrow`         | Release funds on a satisfied escrow. |
| `dispute_escrow`        | Open a formal dispute, attaches evidence hashes. |
| `get_escrow_status`     | Read the current on-chain state of one escrow. |
| `list_agents`           | Discover verified agents in the /agents registry. |
| `get_agent_reputation`  | Fetch a reputation score for one agent. |
| `quote_insurance_premium` | Ask what the premium would be for a proposed escrow. |
| `check_risk_regime`     | Run the CUSUM regime-shift detector on a sample stream. |
| `preview_dispute_rubric`| Ask what the deterministic rubric would score. |

Every tool returns structured JSON with a stable schema. Unknown fields
are ignored; new fields are additive.

## Why the surface is small

Two reasons:

1. **Safety** — every tool that mutates state (create/settle/dispute)
   is 402-authenticated. The MCP layer forwards the client's X402
   header untouched. Unauthenticated clients only get the read-only
   inspection tools.
2. **Debuggability** — 9 tools with strict schemas are easier to test
   end-to-end than 40 half-documented ones. New tools land here only
   after they clear the same test bar as `create_escrow` (unit +
   integration + MCP sanity).

## Safety controls

- **Prompt-injection filter.** Any string an MCP tool returns to the
  LLM host is first filtered through `server/agentic_safety.py` (same
  filter used by the dispute-AI narrator).
- **Rate limit.** Per-caller: 60 calls/min soft, 200 calls/min hard.
- **No LLM-in-the-loop for money moves.** The `settle_escrow` and
  `dispute_escrow` tools require the caller to have already produced a
  valid X402 payment; the MCP layer never signs on the LLM's behalf.
- **Structured error surface.** Every failure returns
  `{"error": {"code": ..., "message": ..., "details": {...}}}` — the
  LLM never has to parse a stack trace.

## Roadmap

- **v1.1** — add `attest_hop` for multi-hop A2A choreography (already
  live under `/intent-chain/*` but not yet exposed as an MCP tool).
- **v2** — MCP tool for the bridge (`initiate_swap`, `lock_leg`,
  `claim_leg`, `refund_leg`). Gated on I.4 landing.

## Related

- `server/mcp_playground_api.py` — endpoint implementation
- `server/mcp_curated.py` — the whitelist that gates `list_tools`
- `docs/AGENTIC_SAFETY.md` — the broader safety story
- `tests/test_mcp_sanity_and_security.py` — 101 sanity + security tests
