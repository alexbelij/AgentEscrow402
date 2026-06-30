# AgentEscrow402 — Roadmap

> x402-compatible payment middleware for AI agents on Casper Network

---

## Current State (Hackathon v1.0)

- [x] Smart contract deployed on Casper testnet (`5dd33e8e...134451`)
- [x] FastAPI backend with PostgreSQL (Neon) persistence
- [x] Python SDK (`EscrowClient`) + LangChain `EscrowPaymentTool`
- [x] MCP server exposing 7 escrow tools
- [x] React dashboard at ae402.xyz/dashboard
- [x] Reputation scoring with decay formula
- [x] Insurance pool (2% fee on release)
- [x] 103 tests passing (85 Python + 18 Rust)
- [x] CI/CD via GitHub Actions

## Phase 2 — Post-Hackathon

- [ ] Multi-token escrow (CSPR + CEP-18 tokens)
- [ ] Batch escrow creation (up to 20 per deploy)
- [ ] Arbiter election via on-chain stake-weighted voting
- [ ] Facilitator role for x402 payment channel setup
- [ ] Rate limiting and gas cost optimization
- [ ] SDK bindings for TypeScript and Go

## Phase 3 — Mainnet

- [ ] Security audit by third-party firm
- [ ] Mainnet deployment with governance multisig
- [ ] Plugin marketplace for payment verification strategies
- [ ] Analytics dashboard with historical charts
- [ ] Cross-chain escrow bridge (EVM ↔ Casper)

## Phase 4 — Ecosystem

- [ ] Agent registry (discover payable services)
- [ ] Payment channel spec (off-chain micro-transactions)
- [ ] Insurance claims UI and governance
- [ ] Compliance framework for regulated jurisdictions
