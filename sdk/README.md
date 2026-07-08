# AgentEscrow402 SDK

> **Python SDK, LangChain Tool, and MCP Server for trustless AI agent escrow payments on Casper Network.**

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://python.org)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](../LICENSE)
[![26 MCP Tools](https://img.shields.io/badge/MCP_tools-26-purple.svg)](../docs/SDK.md#mcp-server)
[![62 API Endpoints](https://img.shields.io/badge/API_endpoints-62-cyan.svg)](../docs/API_SDK_MCP.md)
[![Live](https://img.shields.io/badge/live-ae402.xyz-brightgreen.svg)](https://ae402.xyz)

---

## Overview

This directory contains three integration layers for AgentEscrow402:

| Component | File | Description |
|-----------|------|-------------|
| **Python SDK** | [`client.py`](client.py) / [`agentescrow402/`](agentescrow402/) | Async client with Ed25519 signing, full escrow lifecycle |
| **LangChain Tool** | [`langchain_tool.py`](langchain_tool.py) | Drop-in `EscrowPaymentTool` for any LangChain agent |
| **MCP Server** | [`mcp_server.py`](mcp_server.py) | 26 tools for any MCP-compatible LLM (Claude, GPT, etc.) |

---

## Quick Start

### Install

```bash
pip install httpx cryptography pydantic
# For MCP server:
pip install mcp
# For LangChain:
pip install langchain
```

### Python SDK — 3 lines to create an escrow

```python
from sdk.client import EscrowClient

async with EscrowClient.generate("https://agentescrow402-api.onrender.com") as client:
    escrow = await client.create_escrow(
        receiver="ab" * 32,  # receiver's 64-hex Casper account hash
        amount=5000,
        ttl=300
    )
    print(f"Escrow created: {escrow['service_hash']}")
    
    # Release funds after work is delivered
    await client.release(escrow["service_hash"], amount=5000)
```

### LangChain — drop-in tool

```python
from sdk.langchain_tool import EscrowPaymentTool

tool = EscrowPaymentTool("https://agentescrow402-api.onrender.com", sender="agent-001")

result = await tool.run("create", receiver="ab" * 32, amount=5000)
result = await tool.run("release", service_hash=result["service_hash"])
result = await tool.run("reputation", agent="agent-001")
```

**Supported actions:** `create`, `release`, `refund`, `dispute`, `status`, `reputation`, `batch_release`, `batch_cancel`, `claim_stream`, `risk`

### MCP Server — any LLM manages escrows

```bash
# stdio (default — for Claude Desktop, Cursor, etc.)
python -m sdk.mcp_server

# SSE (for remote/web connections)
pip install mcp[sse] uvicorn starlette
python -m sdk.mcp_server --transport sse --port 8402
```

---

## Authentication

### Signed mode (production)

The live API verifies Ed25519-signed `X-Payment` headers on every request. `EscrowClient.generate()` handles this automatically:

```python
from sdk.client import EscrowClient

# Auto-generates a keypair and signs all requests
async with EscrowClient.generate("https://agentescrow402-api.onrender.com") as client:
    print(client.sender)  # your 64-hex Ed25519 public key
```

To reuse the same identity across runs:

```python
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

key = Ed25519PrivateKey.generate()  # persist this for reuse
client = EscrowClient("https://agentescrow402-api.onrender.com", private_key=key)
```

### Sandbox mode (local development)

```python
async with EscrowClient("http://localhost:8000", sender="agent-001", sandbox=True) as client:
    escrow = await client.create_escrow(receiver="ab" * 32, amount=5000, ttl=300)
```

---

## SDK Client Methods

| Method | Description |
|--------|-------------|
| `create_escrow(receiver, amount, ttl)` | Lock funds in a new escrow |
| `release(service_hash, amount)` | Release funds to receiver |
| `refund(service_hash)` | Return funds to sender |
| `dispute(service_hash, reason_hash)` | Open a dispute |
| `get_escrow(service_hash)` | Get escrow status and details |
| `list_escrows(status, limit, offset)` | List escrows with filters |
| `get_reputation(agent)` | Query on-chain reputation score |
| `get_stats()` | Aggregate escrow statistics |
| `batch_release(service_hashes)` | Release multiple escrows atomically |
| `batch_cancel(service_hashes)` | Cancel multiple pending escrows |
| `build_x402_header(service_hash, amount)` | Build x402 payment header |

---

## MCP Tools (26)

| Domain | Tool | Description |
|--------|------|-------------|
| **Escrow** | `create_escrow` | Lock funds between sender and receiver |
| | `release_escrow` | Release funds to receiver |
| | `refund_escrow` | Return funds to sender |
| | `dispute_escrow` | Open a dispute on active escrow |
| | `get_escrow` | Fetch escrow status and details |
| | `list_escrows` | List escrows with status filter |
| | `get_escrow_history` | Full state-change history |
| | `build_x402_header` | Build x402 payment header |
| | `compute_hash` | Compute deterministic service hash |
| | `estimate_fee` | Estimate fees and insurance cost |
| **Reputation** | `get_reputation` | Query agent's on-chain reputation |
| | `list_agents` | List all agents with scores |
| | `get_stats` | Aggregate escrow statistics |
| | `get_events` | Recent escrow events |
| | `health_check` | API and blockchain health |
| **Arbitration** | `submit_dispute_arbitration` | Submit for AI-assisted arbitration |
| | `get_arbitration_result` | Get AI verdict and reasoning |
| | `appeal_arbitration` | Appeal within allowed window |
| **Risk** | `calculate_risk_score` | IsolationForest anomaly detection |
| | `get_risk_dashboard` | Aggregated risk scores |
| **Identity** | `register_identity` | Register agent with public key |
| | `get_identity` | Look up agent identity |
| **Advanced** | `elect_arbiter` | VRF-based on-chain arbiter election |
| | `batch_release` | Release multiple escrows atomically |
| | `batch_cancel` | Cancel multiple pending escrows |
| | `claim_stream` | Claim fully-vested streaming escrow |

---

## x402 Payment Header

The x402 protocol header format used by the live API:

```
x402-v1;<escrow_hash>;<amount>;<sender>;<timestamp>;<nonce>;<signature>
```

Where `signature` = `Ed25519.sign(key, "x402-v1;<escrow_hash>;<amount>;<sender>;<timestamp>;<nonce>;<METHOD>;<path>")`, binding it to the exact HTTP method and path.

---

## Examples

- [`examples/quickstart.py`](../examples/quickstart.py) — minimal signed create → release
- [`examples/escrow_agent.py`](../examples/escrow_agent.py) — full autonomous buyer/seller lifecycle with dispute and AI arbitration

---

## Documentation

| Document | Description |
|----------|-------------|
| [SDK Guide](../docs/SDK.md) | Full SDK documentation with examples |
| [API / SDK / MCP Reference](../docs/API_SDK_MCP.md) | Complete 62-endpoint REST API reference |
| [Architecture](../docs/ARCHITECTURE.md) | System architecture and design decisions |
| [OpenAPI Spec](../docs/openapi.yaml) | Machine-readable API specification |
| [MCP Tools Schema](../docs/mcp_tools_schema.json) | MCP tool definitions (JSON) |
| [Console (interactive)](https://ae402.xyz/console/docs) | Live interactive API/SDK/MCP documentation |

---

## Live Resources

- **Console:** [ae402.xyz/console](https://ae402.xyz/console)
- **API:** [agentescrow402-api.onrender.com](https://agentescrow402-api.onrender.com)
- **Sandbox:** [ae402.xyz/console/sandbox](https://ae402.xyz/console/sandbox)
- **Contracts on CSPR.live:** [testnet.cspr.live/contract/612cead2...](https://testnet.cspr.live/contract/612cead2226329fafec492042fd96a999df06d1e88c476913a167f44d3ddd9ec)
