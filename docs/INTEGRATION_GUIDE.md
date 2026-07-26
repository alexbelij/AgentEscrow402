# Integration Guide

> **Audience.** An engineer who wants to put an escrow into a live
> agent-to-agent flow within their own stack (LangGraph, CrewAI,
> LlamaIndex, MCP-native, or a hand-rolled Python service).
>
> **Reading time.** 15 minutes. All examples in this guide are
> executable — the code exists in `examples/` and `demo/`. No
> pseudocode.

---

## 1. Prerequisites

- Python 3.11+.
- Access to an AE402 backend URL — either your own instance (see
  `docs/deployment/`) or the public sandbox (see the AE402 README for
  the current URL).
- Two agent identities. For sandbox mode any 64-hex string works.
  For live mode you need a Casper key pair (see `docs/KEYS.md`).

Install the client SDK:

```bash
pip install -e ./sdk         # from repo
# or
pip install agent-escrow-402 # once published (Phase 4)
```

---

## 2. The three-step contract

Every AE402 integration reduces to the same three steps regardless of
your agent framework:

1. **Buyer creates an escrow** — commits amount, receiver, deadline.
2. **Seller delivers** — off-chain work, out of AE402's scope.
3. **Buyer releases** (or **refunds** on timeout, or **disputes**
   with quorum arbitration).

That's the whole loop. Everything else — MCP, x402, risk score,
insurance pool — extends this without changing it.

---

## 3. Minimal Python integration

```python
from sdk.client import EscrowClient

buyer  = "aa" * 32          # 64-hex; use a real Casper key in prod
seller = "bb" * 32
amount = 1_000_000          # motes (1 CSPR = 1e9 motes)

c = EscrowClient(base_url="http://localhost:8000", sandbox=True)

# 1. Create.
service_hash = EscrowClient.compute_hash(buyer, seller, amount, nonce="job-42")
c.create_escrow(sender=buyer, receiver=seller, amount=amount,
                service_hash=service_hash, ttl=300)

# 2. Seller does work (out-of-band).

# 3. Release.
c.release(sender=buyer, service_hash=service_hash)

# Verify.
final = c.get_escrow(service_hash)
assert final["status"] == "released"
```

Under 30 lines, no MCP host, no LangGraph, no CrewAI. This is the
irreducible loop.

---

## 4. MCP integration

If your agent host is MCP-native (Claude Desktop, an MCP client SDK,
Anthropic's MCP tooling), point it at `/mcp/tools` and it discovers
every AE402 tool automatically.

Wire example:

```jsonc
// mcp.json (a slice of it)
{
  "mcpServers": {
    "ae402": {
      "url": "http://localhost:8000/mcp",
      "transport": "http"
    }
  }
}
```

The tools exposed are documented in the live catalogue at
`/mcp/tools`. Each tool declares its JSON-Schema `inputSchema` so an
LLM can generate valid calls automatically. See
`docs/MCP_SPEC.md` for the full contract.

Live catalogue snapshot (may drift — the source of truth is
`/mcp/tools`):

- `create_escrow`, `release_escrow`, `refund_escrow`, `dispute_escrow`
- `get_escrow`, `get_escrow_history`, `list_escrows`, `stats`
- `compute_service_hash` (client-side determinism check)
- `risk_score` (agent-reputation hint, see §6)
- `health_check`

---

## 5. LangGraph integration

AE402 acts as a `Tool` in a LangGraph agent. Skeleton:

```python
from langgraph.prebuilt import ToolNode
from langchain_core.tools import tool
from sdk.client import EscrowClient

client = EscrowClient(base_url="…", sandbox=False)

@tool
def create_ae402_escrow(receiver: str, amount: int, nonce: str) -> str:
    "Lock `amount` motes to `receiver` until released or timed out."
    sender = MY_AGENT_KEY  # from your agent's identity module
    h = EscrowClient.compute_hash(sender, receiver, amount, nonce)
    client.create_escrow(sender=sender, receiver=receiver, amount=amount,
                         service_hash=h, ttl=300)
    return h

@tool
def release_ae402_escrow(service_hash: str) -> str:
    client.release(sender=MY_AGENT_KEY, service_hash=service_hash)
    return "released"

tools = ToolNode([create_ae402_escrow, release_ae402_escrow, …])
```

The pattern is identical for CrewAI (`@tool`), LlamaIndex
(`FunctionTool`), Autogen (`register_for_tool`).

---

## 6. Reading the risk hint

Every escrow read returns a `risk_hint` field (see
`server/risk_scoring.py`). It's a `0–100` score with structured
reason codes. The backend does **not** block on risk; that's your
agent's decision.

```python
escrow = c.get_escrow(service_hash)
if escrow["risk_hint"]["score"] >= 70:
    # E.g. dispute proactively, or route to a human reviewer.
    ...
```

Reason codes are documented in `docs/RISK_SCORING.md`. Do not
special-case codes you don't recognise — the vocabulary is versioned
and may grow.

---

## 7. Observability from your side

Every request to the backend echoes an `X-Request-ID` header. If
your integration is instrumented (OpenTelemetry, structured logs,
whatever), include it as a span attribute so a single trace pins down
one AE402 request across your stack + ours.

Details: `docs/OBSERVABILITY.md`.

---

## 8. Error handling: what you actually need to catch

| Status | Meaning | Suggested action |
|---|---|---|
| `400` | Bad input (bad hash, bad address, bad amount) | Fix the input; don't retry |
| `401` | Signature invalid / missing (live mode) | Sign correctly; don't retry blind |
| `403` | Escrow FSM refuses this transition | Re-read state; the escrow moved under you |
| `404` | Escrow not found | Recompute `service_hash`; you may be using the wrong one |
| `409` | State conflict (double-release, etc.) | Read /history to see who moved it |
| `429` | Rate-limited | Back off exponentially, then retry |
| `5xx` | Backend error | Retry with jitter; alert if persistent |

The SDK maps these to typed exceptions (`EscrowNotFound`,
`InvalidSignature`, `StateConflict`, `RateLimited`, `BackendError`).
Import them from `sdk.errors`.

---

## 9. Testing locally

```bash
# Boot the backend in sandbox mode.
make judge-lite-keep         # leaves uvicorn running

# In another shell, run your integration against 127.0.0.1:$PORT.
python -m your_agent.main

# When done:
kill $(pgrep -f "uvicorn server.app")
```

For CI, prefer the in-process pattern — see
`demo/agent_flow.py` — so you don't pay the port-bind + boot cost
per test.

---

## 10. Where to go next

- Live tools catalogue: `/mcp/tools`.
- Full API surface: `docs/API.md`.
- Risk scoring: `docs/RISK_SCORING.md`.
- Deployment reference: `docs/deployment/`.
- Distribution channels (packaging, registries): `docs/DISTRIBUTION.md`.
- Post-hackathon roadmap: `docs/POST_HACKATHON_ROADMAP.md`.
