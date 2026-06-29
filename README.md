# AgentEscrow402

> x402-compatible payment middleware for autonomous AI agents on Casper Network

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE) [![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://python.org) [![Casper 2.x](https://img.shields.io/badge/Casper-2.x-red.svg)](https://casper.network) [![Tests](https://img.shields.io/badge/tests-passing-brightgreen.svg)](tests/)

## What is AgentEscrow402?

AgentEscrow402 brings the [x402 payment protocol](https://www.x402.org/) to Casper Network. AI agents can lock funds in trustless escrow, deliver services, and release payments without human intervention.

### Features

- **x402 Payment Protocol** — Standard HTTP 402 headers for agent-to-agent payments
- **Trustless Escrow** — Funds locked in Casper smart contracts until delivery confirmation
- **Reputation System** — On-chain scoring with exponential decay (`new = old * 0.95 + latest`)
- **Multi-sig Dispute Resolution** — 3-of-5 arbiter voting for contested payments
- **Insurance Pool** — Configurable fee (default 2%) funds a reserve for slashed agents
- **Sandbox Mode** — Full API simulation without a running Casper node

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

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for detailed Mermaid diagrams.

## Quick Start

### Prerequisites

- Python 3.11+
- Rust nightly (for contract compilation)
- Docker (optional, for one-command setup)

### Docker (recommended)

```bash
git clone https://github.com/alexbelij/AgentEscrow402.git
cd AgentEscrow402
cp .env.example .env
docker-compose up
```

The server starts at `http://localhost:8000` in sandbox mode.

### Manual Install

```bash
pip install -r requirements.txt
python -m uvicorn server.app:app --host 0.0.0.0 --port 8000
```

### Using the SDK

```python
from sdk.client import EscrowClient

client = EscrowClient(base_url="http://localhost:8000", sender="agent-001")

# Create escrow for a service
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
result = await tool.run(action="create", receiver="target-agent", amount=1_000_000)
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Server health check |
| `POST` | `/escrow` | Create new escrow |
| `POST` | `/release` | Release escrowed funds |
| `POST` | `/refund` | Refund escrowed funds |
| `POST` | `/dispute` | Open a dispute |
| `POST` | `/resolve` | 3-of-5 arbiter resolution |
| `GET` | `/escrow/{hash}` | Get escrow by service hash |
| `GET` | `/reputation/{agent}` | Get agent reputation |
| `POST` | `/compute-hash` | Compute service hash |

### x402 Payment Header

```
X-Payment: x402-v1;<escrow_hash>;<amount>;<sender>;<signature>
```

Protected endpoints return `402 Payment Required` when the header is missing:

```json
{
  "error": "payment_required",
  "accepts": "x402-v1",
  "price": 1000000
}
```

## Smart Contract

The escrow contract (`contracts/escrow/`) implements these entry points:

| Entry Point | Description |
|-------------|-------------|
| `create_escrow` | Lock funds with TTL and service hash |
| `release` | Sender confirms delivery, funds go to receiver |
| `refund` | Return funds after TTL expiry or by sender |
| `dispute` | Either party opens a dispute |
| `resolve` | 3-of-5 arbiters vote to resolve |
| `configure_fee` | Admin sets insurance pool fee (basis points) |
| `emergency_freeze` | Admin freeze for incident response |

Events follow the CEP-88 standard for indexer compatibility.

### Compile the contract

```bash
cd contracts
cargo build --release --target wasm32-unknown-unknown --no-default-features
# Output: target/wasm32-unknown-unknown/release/escrow.wasm
```

## Testing

```bash
# Unit tests
pytest tests/ -v

# Specific modules
pytest tests/test_sandbox.py -v
pytest tests/test_middleware.py -v

# Contract tests
cd contracts/tests && cargo test
```

## Project Structure

```
AgentEscrow402/
├── contracts/escrow/        # Casper smart contract (Rust)
│   └── src/main.rs
├── server/                  # FastAPI payment server
│   ├── app.py               # API routes
│   ├── middleware.py         # x402 payment parsing
│   ├── sandbox.py           # Demo mode store
│   ├── casper_client.py     # Casper RPC wrapper
│   ├── event_monitor.py     # CEP-88 event listener
│   └── models.py            # Pydantic schemas
├── sdk/                     # Python client SDK
│   ├── client.py            # HTTP client
│   └── langchain_tool.py    # LangChain tool wrapper
├── tests/                   # Test suite
├── examples/                # Quickstart scripts
├── landing/                 # Landing page
├── docs/                    # ARCHITECTURE.md, DEPLOYMENT.md
└── docker-compose.yml
```

## Hackathon

Developed during the Casper Buildathon 2026 ([info](https://dorahacks.io/hackathon/casper-the-friendly-buildathon)). Focus area: agent payment infrastructure.

## License

MIT License — see [LICENSE](LICENSE) for details.
