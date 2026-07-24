# Hosted MCP Playground

A visitor-facing surface on the AE402 console that lets you browse,
inspect, and dry-run every tool that the shipped MCP server
(`sdk/mcp_server.py`) exposes — without installing an MCP client.

- **URL**: `/console/mcp-playground`
- **Catalogue**: `GET /mcp/tools`
- **Call**: `POST /mcp/tools/{tool_name}/call`

## What it is

A **builder tool**. The point is to see what a tool does, what it takes,
what it returns, exactly — so an integrator can go from "does AE402 do
X?" to a working call in under a minute, without wiring up an MCP host.

## How it works

The playground page renders three panels:

1. **Catalogue** on the left, grouped by purpose (Escrow lifecycle,
   Identity & reputation, Arbitration, Risk, x402 helpers, Read-only,
   Other). The category is a best-effort classifier over the tool
   name — never authoritative — for orientation only.
2. **Tool detail** on the right: name, description, required
   arguments, and the full JSON Schema for `inputSchema`.
3. **Runner**: a JSON-object arguments editor (auto-populated from the
   schema with typed defaults), a Call button, and a response viewer.
   The response block is the raw REST response body wrapped in an MCP
   `content` envelope.

## Dispatch fidelity

`POST /mcp/tools/{name}/call` maps 1:1 to the same REST endpoint the
underlying MCP tool would call. The dispatcher (`_forward_json` in
`server/mcp_playground_api.py`) uses `httpx.AsyncClient` over an
`ASGITransport(app=...)` so the inner call goes through the exact same
FastAPI middleware chain as an external HTTP request — including:

- x402 payment header enforcement
- Observer/Driver policy fence (see `docs/OBSERVER_DRIVER_UX.md`)
- Rate limiting
- Every other middleware in the chain

There is no separate implementation path, and no bypass. If a tool
requires an x402 payment header today, calling it from the playground
requires the same header today.

## Response shape

```
{
  "content": [{ "type": "text", "text": "<json-encoded response body>" }],
  "isError": true | false,
  "status": <HTTP status of the underlying REST endpoint>,
  "tool": "<tool name>"
}
```

Mirrors an MCP `CallToolResult` so the playground renderer would work
verbatim against a real stdio/SSE MCP server if we ever want to point
at one.

## Not routed

A tool that is declared in `docs/mcp_tools_schema.json` but has no REST
dispatch entry in `_TOOL_ROUTES` returns HTTP 501 with a structured
message directing the caller to run the MCP server directly:

```
python -m sdk.mcp_server                # stdio (default)
python -m sdk.mcp_server --transport sse # SSE
```

## Observer / Driver interplay

- All tool calls go through `POST /mcp/tools/*/call`, which itself
  goes through the same fetcher-layer Observer fence that every other
  browser-side write does. So Observer mode allows browsing and read
  tools, but the Call button is disabled with an Observer tooltip and
  the underlying dispatcher would refuse a non-GET call from the
  browser anyway.
- Driver mode unlocks everything, subject to the same auth/x402
  fences that already apply to the REST endpoint.

## Adding a tool

1. Add it to `sdk/mcp_server.py`.
2. Regenerate `docs/mcp_tools_schema.json` (via
   `scripts/gen_mcp_tools_schema.py`).
3. Add a mapping in `_TOOL_ROUTES` in
   `server/mcp_playground_api.py` — no schema duplication, the
   playground picks up the new tool automatically once the
   catalogue file is regenerated.

If the underlying REST endpoint is idempotent / compute-only, kind
should be `"read"`.

## Not in scope

- **Hosted stdio/SSE MCP server** — the playground does not run
  `sdk/mcp_server.py` as a persistent process. It exposes the same
  functionality over plain REST, so any MCP-compatible client can
  bring its own transport. Running a shared hosted stdio process is
  an anti-pattern (per-client sessions, not a multi-tenant surface).
- **Auth beyond x402** — the playground reuses whatever the caller's
  session already has. It does not mint API keys or session tokens.
