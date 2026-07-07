# AE402 — API / SDK / MCP Documentation

> **Interactive version:** [ae402.xyz/console/docs](https://ae402.xyz/console/docs)

---

## REST API Reference

**Base URL:** `https://ae402.xyz/backend`

All endpoints return JSON. Authenticated endpoints (marked 🔐) require an `X-Payment` header with x402 protocol signature.

### Authentication: x402 Payment Protocol

Endpoints marked 🔐 require an Ed25519-signed `X-Payment` header binding the request to the caller's on-chain identity:

```
X-Payment: x402-v1;<escrow_hash>;<amount>;<sender_pubkey>;<timestamp>;<nonce>;<signature>
```

Where `signature = Ed25519.sign(private_key, "x402-v1;<escrow_hash>;<amount>;<sender>;<timestamp>;<nonce>;<METHOD>;<path>")`.

The Python SDK handles this automatically.

---

### Core Escrow Lifecycle

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/escrow` | 🔐 | Create a new escrow payment |
| GET | `/escrow/{hash}` | | Get escrow details by service_hash |
| POST | `/release` | 🔐 | Release funds to receiver |
| POST | `/refund` | 🔐 | Refund funds to sender |
| POST | `/dispute` | 🔐 | Open a dispute on active escrow |
| POST | `/resolve` | 🔐 | Resolve a disputed escrow with arbiter signatures |
| GET | `/escrows` | | List escrows with pagination |
| GET | `/escrow/{hash}/history` | | Full state-change history |
| GET | `/estimate` | | Estimate fees (`?amount=5000`) |
| POST | `/compute-hash` | | Compute deterministic service_hash |

### Batch Operations (up to 50 per deploy)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/escrows/batch` | 🔐 | Create up to 50 escrows atomically |
| POST | `/escrows/batch-release` | 🔐 | Release multiple escrows |
| POST | `/escrows/batch-cancel` | 🔐 | Cancel multiple pending escrows |

### Multi-Asset Escrow (CEP-18 / CEP-78)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/escrow/multi-asset` | 🔐 | Create escrow with CSPR/CEP-18/CEP-78 |
| POST | `/escrow/multi-asset/{hash}/release` | 🔐 | Release multi-asset escrow |
| POST | `/escrow/multi-asset/{hash}/refund` | 🔐 | Refund multi-asset escrow |
| POST | `/escrow/multi-asset/{hash}/dispute` | 🔐 | Dispute multi-asset escrow |
| POST | `/escrow/multi-asset/{hash}/resolve` | 🔐 | Resolve multi-asset dispute |
| GET | `/escrow/cep18-permit-nonce` | | Get next CEP-18 permit nonce |

### Streaming Escrow (Linear Vesting)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/escrow/stream` | 🔐 | Create streaming escrow with vesting |
| GET | `/escrow/{hash}/stream-status` | | Get vesting progress |
| POST | `/escrow/{hash}/stream-claim` | 🔐 | Claim fully vested escrow |

### HTLC Atomic Swap

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/escrow/atomic-swap/commit` | 🔐 | Commit SHA-256(secret) |
| POST | `/escrow/atomic-swap/reveal` | 🔐 | Reveal preimage to release |

### Insurance Pool

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/insurance/pool-stats` | | Pool balance and stats |
| GET | `/insurance/premium-quote` | | Calculate premium |
| POST | `/insurance/deposit` | 🔐 | Deposit to pool |
| POST | `/insurance/claim` | 🔐 | File insurance claim |

### AI Arbitration

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/arbitration/analyze` | 🔐 | Submit dispute for AI analysis |
| GET | `/arbitration/history` | | Past AI arbitration results |

### VRF Arbiter Election

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/vrf/elect` | 🔐 | Elect arbiter via on-chain VRF |
| GET | `/vrf/election/{dispute_id}` | | Look up VRF election result |
| GET | `/vrf/arbiters` | | List registered arbiters |
| POST | `/vrf/arbiters/register` | | Register new arbiter |

### Agent Identity (DID)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/identity/register` | 🔐 | Register DID-style agent identity |
| GET | `/identity/{agent_id}` | | Look up agent identity |
| POST | `/identity/delegate` | 🔐 | Delegate identity authority |
| GET | `/identity/capabilities/{agent_id}` | | List agent capabilities |

### On-Chain Identity Registry

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/identity-registry/register` | 🔐 | Register agent on-chain |
| GET | `/identity-registry/{did}` | | Get registration details |
| GET | `/identity-registry/by-account/{hash}` | | Look up by account hash |
| GET | `/identity-registry/{did}/reputation` | | Get on-chain reputation |
| POST | `/identity-registry/{did}/decay` | | Apply reputation decay |
| POST | `/identity-registry/{did}/slash` | | Slash reputation |
| POST | `/identity-registry/{did}/verify` | | Verify identity |
| PUT | `/identity-registry/{did}/capabilities` | | Update capabilities |
| GET | `/identity-registry/search/agents` | | Search agents |
| GET | `/identity-registry/stats/summary` | | Registry statistics |

### Risk Scoring

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/risk/score/{agent}` | | IsolationForest risk score |
| GET | `/risk/dashboard` | | All agents risk dashboard |

### Reputation & Agents

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/reputation/{agent}` | | Agent reputation score |
| GET | `/agents` | | List all agents |

### Admin (deployer key required)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/admin/configure-fee` | | Set insurance fee BPS |
| POST | `/admin/set-release-cap` | | Set release cap threshold |
| POST | `/admin/set-arbiters` | | Configure arbiter quorum |
| POST | `/admin/emergency-freeze` | | Emergency circuit breaker |
| POST | `/admin/unfreeze` | | Resume operations |

### System

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/health` | | Health check |
| GET | `/stats` | | Protocol statistics |
| GET | `/contracts` | | List deployed contracts |
| GET | `/events` | | SSE event stream |
| GET | `/wasm/escrow_funder` | | Download escrow_funder.wasm |

### Error Responses

All errors return JSON with a `detail` field:

| Code | Meaning |
|------|---------|
| 400 | Invalid input |
| 401 | Missing/invalid X-Payment header |
| 404 | Resource not found |
| 409 | State conflict (e.g., escrow already released) |
| 422 | Validation error |

---

## Python SDK

Full-featured Python client with x402 authentication and Ed25519 signing.

### Installation

```bash
git clone https://github.com/alexbelij/AgentEscrow402.git
cd AgentEscrow402
pip install httpx cryptography
```

### Quick Start (Signed Mode)

```python
from sdk.client import EscrowClient

async with EscrowClient.generate("https://ae402.xyz/backend") as client:
    print(f"Agent identity: {client.sender}")
    
    escrow = await client.create_escrow(
        receiver="ab" * 32,
        amount=5000,
        ttl=300
    )
    print(f"Escrow: {escrow['service_hash']}")
    
    tx = await client.release(escrow["service_hash"], amount=5000)
    print(f"Released: {tx['deploy_hash']}")
```

### Persistent Identity

```python
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

key = Ed25519PrivateKey.generate()
private_bytes = key.private_bytes_raw().hex()
# Save to secure file, reuse in subsequent runs

key = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(private_bytes))
client = EscrowClient("https://ae402.xyz/backend", private_key=key)
```

### Dispute Lifecycle

```python
import hashlib
from sdk.client import EscrowClient

async with EscrowClient.generate("https://ae402.xyz/backend") as client:
    escrow = await client.create_escrow(receiver="ab"*32, amount=10000, ttl=600)
    
    reason = "AI model returned incorrect results"
    reason_hash = hashlib.sha256(reason.encode()).hexdigest()
    await client.dispute(escrow["service_hash"], reason_hash=reason_hash)
    
    analysis = await client.arbitration_analyze(
        escrow["service_hash"],
        evidence={"reason": reason}
    )
    print(f"AI verdict: {analysis['verdict']}")
```

### Available Methods

| Method | Description |
|--------|-------------|
| `create_escrow(receiver, amount, ttl)` | Create and fund escrow |
| `get_escrow(hash)` | Get escrow details |
| `release(hash, amount)` | Release funds |
| `refund(hash)` | Refund to sender |
| `dispute(hash, reason_hash)` | Open dispute |
| `resolve(hash, in_favor_of, pubkeys, sigs)` | Resolve dispute |
| `get_escrows(limit, offset, status)` | List escrows |
| `get_reputation(agent)` | Reputation score |
| `estimate_fee(amount)` | Fee estimate |
| `arbitration_analyze(hash, evidence)` | AI arbitration |
| `build_x402_header(hash, amount)` | Build payment header |

### LangChain Integration

```python
from sdk.langchain_tool import EscrowPaymentTool
from langchain.agents import initialize_agent, AgentType
from langchain_openai import ChatOpenAI

tool = EscrowPaymentTool("https://ae402.xyz/backend", sender="your-agent-identity")
llm = ChatOpenAI(model="gpt-4")
agent = initialize_agent(tools=[tool], llm=llm, agent=AgentType.OPENAI_FUNCTIONS)

result = agent.run("Create an escrow of 5000 CSPR for receiver ab...64hex")
```

---

## MCP Server (Model Context Protocol)

26 tools for any MCP-compatible LLM (Claude, GPT, Gemini) to manage escrow payments autonomously.

### Start the Server

```bash
# stdio transport (Claude Desktop, Cursor)
python -m sdk.mcp_server

# SSE transport (web clients)
python -m sdk.mcp_server --transport sse --port 8402
```

### Claude Desktop Config

```json
{
  "mcpServers": {
    "ae402-escrow": {
      "command": "python",
      "args": ["-m", "sdk.mcp_server"],
      "cwd": "/path/to/AgentEscrow402",
      "env": { "AE402_API_URL": "https://ae402.xyz/backend" }
    }
  }
}
```

### Cursor IDE Config

```json
{
  "mcpServers": {
    "ae402": {
      "command": "python",
      "args": ["-m", "sdk.mcp_server"],
      "cwd": "/path/to/AgentEscrow402"
    }
  }
}
```

### All 26 Tools

**Escrow Lifecycle:** `create_escrow`, `release_escrow`, `refund_escrow`, `dispute_escrow`, `get_escrow`, `list_escrows`, `get_escrow_history`, `build_x402_header`, `compute_hash`, `estimate_fee`

**Reputation & Stats:** `get_reputation`, `list_agents`, `get_stats`, `get_events`, `health_check`

**AI Arbitration:** `submit_dispute_arbitration`, `get_arbitration_result`, `appeal_arbitration`

**Risk Scoring:** `calculate_risk_score`, `get_risk_dashboard`

**Identity Registry:** `register_identity`, `get_identity`

**VRF, Batch & Streaming:** `elect_arbiter`, `batch_release`, `batch_cancel`, `claim_stream`

---

*Full interactive documentation with code examples: [ae402.xyz/console/docs](https://ae402.xyz/console/docs)*
