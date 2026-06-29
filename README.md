# AgentEscrow402

> x402-compatible payment middleware for autonomous AI agents on Casper Network

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://python.org)

## What is AgentEscrow402?

AgentEscrow402 brings the [x402 payment protocol](https://www.x402.org/) to Casper Network, enabling AI agents to exchange value through trustless escrow contracts. Agents can lock funds, deliver services, and release payments — all without human intervention.

### Key Features

- **x402 Payment Protocol** — Standard HTTP payment headers for agent-to-agent payments
- **Trustless Escrow** — Funds locked in smart contracts until service delivery is confirmed
- **Reputation System** — On-chain reputation scoring with exponential decay
- **Multi-sig Dispute Resolution** — 3-of-5 arbiter voting for contested payments
- **Insurance Pool** — 2% fee funds an insurance reserve for slashed agents
- **Sandbox Mode** — Full API simulation without Casper node dependency

## Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│   Agent (SDK)   │────▶│  Payment Server  │────▶│  Casper Network  │
│                 │     │   (FastAPI)       │     │  (Smart Contract)│
│  x402 headers   │     │  x402 middleware  │     │  escrow.wasm     │
│  escrow client  │     │  sandbox store    │     │  reputation      │
└─────────────────┘     │  event monitor    │     │  insurance       │
                        └──────────────────┘     └──────────────────┘
```

## Quick Start

### Prerequisites

- Python 3.11+
- Rust toolchain (for contract compilation)
- Casper client tools (optional, for mainnet deployment)

### Installation

```bash
# Clone the repository
git clone https://github.com/alexbelij/AgentEscrow402.git
cd AgentEscrow402

# Install Python dependencies
pip install -r requirements.txt

# Start the server in sandbox mode
python -m uvicorn server.app:app --host 0.0.0.0 --port 8000
```

### Using the SDK

```python
from sdk.client import EscrowClient

client = EscrowClient(base_url="http://localhost:8000", sender="agent-001")

# Create an escrow for a service
escrow = await client.create_escrow(
    receiver="agent-002",
    amount=5_000_000,  # 5 CSPR in motes
    ttl=300,
)

# After service delivery, release payment
await client.release(escrow["service_hash"])

# Check reputation
rep = await client.get_reputation("agent-002")
print(f"Trust score: {rep['score']}")
```

### LangChain Integration

```python
from sdk.langchain_tool import EscrowPaymentTool

tool = EscrowPaymentTool(base_url="http://localhost:8000", sender="my-agent")
result = await tool.run(
    action="create",
    receiver="target-agent",
    amount=1_000_000,
)
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Server health check |
| `POST` | `/escrow` | Create new escrow |
| `POST` | `/release` | Release escrowed funds |
| `POST` | `/refund` | Refund escrowed funds |
| `POST` | `/dispute` | Open a dispute |
| `GET` | `/escrow/{hash}` | Get escrow by service hash |
| `GET` | `/reputation/{agent}` | Get agent reputation |
| `POST` | `/compute-hash` | Compute service hash |

## x402 Payment Header

```
X-Payment: x402-v1;<escrow_hash>;<amount>;<sender>;<signature>
```

Protected endpoints return `402 Payment Required` with pricing info when the header is missing:

```json
{
  "error": "payment_required",
  "accepts": "x402-v1",
  "price": 1000000
}
```

## Smart Contract

The escrow contract (`contracts/escrow/src/main.rs`) implements:

- `create_escrow` — Lock funds with TTL and service hash
- `release` — Sender confirms delivery, funds go to receiver
- `refund` — Return funds to sender (after TTL or by sender)
- `dispute` — Either party can open a dispute
- `resolve` — 3-of-5 arbiters vote to resolve dispute
- `configure_fee` — Admin sets insurance pool fee
- `emergency_freeze` — Admin can freeze escrow in emergencies

Events follow the CEP-88 standard for indexing compatibility.

## Testing

```bash
# Run all tests
pytest tests/ -v

# Run specific test modules
pytest tests/test_sandbox.py -v
pytest tests/test_middleware.py -v
pytest tests/test_models.py -v
```

## Project Structure

```
AgentEscrow402/
├── contracts/escrow/      # Casper smart contract (Rust)
├── server/                # FastAPI payment server
│   ├── app.py             # API routes
│   ├── middleware.py       # x402 payment parsing
│   ├── sandbox.py         # Demo mode store
│   ├── casper_client.py   # Casper RPC wrapper
│   └── event_monitor.py   # CEP-88 event listener
├── sdk/                   # Python client SDK
│   ├── client.py          # HTTP client
│   └── langchain_tool.py  # LangChain tool wrapper
└── tests/                 # Test suite
```

## Casper Buildathon 2026

This project was built for the [Casper Agentic Buildathon 2026](https://devfolio.co/casper-agentic-buildathon).

**Track:** Agentic Infrastructure

## License

MIT License — see [LICENSE](LICENSE) for details.
