# Changelog

All notable changes to AgentEscrow402 are documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Version numbers follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.1.0] — 2026-07-02

*Major feature expansion — pre-submission hardening*

### Added

#### Smart Contracts (Rust/Odra)
- **EscrowManager** (575 LOC) — advanced escrow lifecycle with multi-sig and batch support
- **VRF Arbiter** (308 LOC) — verifiable random function for fair dispute arbitration
- **InsurancePool** (268 LOC) — collective insurance fund with premium/payout tracking

#### Backend Modules (Python)
- **AI Arbitration Engine** (`server/ai_arbitration.py`, 299 LOC) — multi-model dispute resolution with evidence scoring, voting rounds, and appeal windows
- **Risk Scoring** (`server/risk_scoring.py`, 167 LOC) — composite risk analysis combining counterparty history, amount heuristics, and chain patterns
- **Identity Registry** (`server/identity_registry.py`, 240 LOC) — decentralized agent identity with Ed25519 credential verification and KYC-level attestation

#### MCP Server
- Expanded from 15 to 24 tools — new tools for arbitration, risk scoring, and identity management
- Fixed duplicate tool definitions in MCP manifest

#### Console
- 4 new tabs: Arbitration, Risk Analysis, Identity Registry, Contracts
- AI dispute verdict history with confidence scores
- Real-time risk factor breakdown with visual bars
- Identity registration and verification status

#### Tests
- 103 new business logic tests (3 files, 1,398 LOC)
- `test_ai_arbitration.py`: 40 tests — dispute resolution, voting, timeout handling
- `test_risk_scoring.py`: 35 tests — scoring models, boundary values, validation
- `test_identity_registry.py`: 28 tests — registration, verification, revocation

### Security
- Bounded nonce cache to prevent memory exhaustion
- Constant-time Ed25519 signature comparison
- Halt local state on transaction failure
- Sanitized error messages (no stack trace leakage)
- Capped pagination limits
- Thread-safe SandboxStore with Lock

---

## [1.0.0] — 2026-06-30

*Hackathon release — Casper Agentic Buildathon 2026*

### Added

#### Smart Contract (Rust/WASM — Casper Testnet)
- **Escrow contract deployed** to Casper Testnet at [`5dd33e8e...`](https://testnet.cspr.live/contract/5dd33e8e79789d386832a80c39006002383fa44dd76ba677cae3279f3a134451)
- `create_escrow` entry point — lock funds with time-to-live (TTL) and service hash
- `release` entry point — sender confirms delivery; funds transfer to receiver atomically
- `refund` entry point — sender reclaims funds after TTL expiry; no arbiter required
- `dispute` entry point — contested payments escalate to arbiter pool
- `resolve` entry point — 3-of-5 multi-sig arbiter vote; auto-payout on quorum
- `configure_fee` entry point — insurance pool fee in basis points (default 2%)
- `emergency_freeze` entry point — admin pause for all state changes
- On-chain reputation store with exponential decay scoring (`new = old × 0.95 + latest`)
- Insurance pool accumulating from configured fee on every release

#### Payment Server (Python / FastAPI)
- x402 middleware — parses and validates `X-Payment: x402-v1;...` headers on every request
- REST API with 9 endpoints: `/health`, `/escrow`, `/release`, `/refund`, `/dispute`, `/resolve`, `/escrow/{hash}`, `/reputation/{agent}`, `/compute-hash`
- Sandbox mode — in-memory store with full API surface; zero blockchain dependency for development
- Casper RPC client — wraps `casper-client` for testnet/mainnet deployments
- CEP-88 event monitor — listens for on-chain events and syncs local state
- `402 Payment Required` response format — machine-readable payment terms for agent consumption
- Database persistence layer (PostgreSQL) for production escrow records

#### AI Arbiter Integration
- Arbiter pool configuration with 3-of-5 threshold
- Dispute lifecycle: open → voting → resolved (release or refund)
- On-chain vote recording and quorum detection

#### Console (Next.js — ae402.xyz)
- Live escrow table with status badges (Locked / Released / Disputed / Expired)
- Real-time event feed via SSE
- Escrow creation form with sender/receiver/amount/TTL inputs
- Dispute management panel with FOR/AGAINST vote buttons
- On-chain transaction links (testnet.cspr.live)

#### SDK & Integrations
- Python async SDK (`sdk/client.py`) — `create_escrow`, `release`, `refund`, `dispute`
- LangChain tool (`sdk/langchain_tool.py`) — plug-and-play for LangChain agent pipelines
- MCP server (`sdk/mcp_server.py`) — exposes 7 tools via stdio and SSE transports

#### Developer Experience
- Sandbox mode default — no Casper node required for local development
- Docker Compose configuration — single `docker-compose up` starts the full stack
- `.env.example` with all configuration options documented
- `examples/quickstart.py` — working 10-line demo

#### Testing
- 85 Python tests across 5 suites — all passing
- 18 Rust contract integration tests — all passing
- CI pipeline: lint (ruff + black) → pytest → WASM build → cargo test
- Security audit: 18 findings identified and resolved; risk score reduced from 6/10 to 2/10

---

[1.0.0]: https://github.com/alexbelij/AgentEscrow402/releases/tag/v1.0.0
