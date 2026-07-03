# AgentEscrow402 — Roadmap

> x402-compatible payment middleware for AI agents on Casper Network

---

## Current State (Hackathon v1.0)

- [x] Smart contract deployed on Casper testnet (`5dd33e8e...134451`)
- [x] FastAPI backend with PostgreSQL (Neon) persistence
- [x] Python SDK (`EscrowClient`) + LangChain `EscrowPaymentTool`
- [x] MCP server exposing 7 escrow tools
- [x] React console at ae402.xyz/console
- [x] Reputation scoring with decay formula
- [x] Insurance pool (2% fee on release)
- [x] 103 tests passing (85 Python + 18 Rust)
- [x] CI/CD via GitHub Actions

## Phase 2 — Core Upgrades

- [ ] EscrowManager Factory (CEP-86) — single deploy manages all escrows
- [ ] Multi-token escrow (CSPR + CEP-18 + CEP-78 via `TokenAdapter` trait)
- [ ] VRF arbiter election via `casper_random_bytes` + keccak256
- [ ] AI arbitration agent — LLM-powered dispute analysis with recommendations
- [ ] Dynamic insurance pool — risk-based premiums with reputation decay
- [ ] Agent Identity Registry — on-chain DID (did:casper:) + capabilities + staking
- [ ] MCP server expansion to 15+ tools with JSON-Schema registry
- [ ] Property-based testing with invariant checks (Hypothesis + proptest)
- [ ] Post-quantum key encapsulation (ML-KEM, FIPS 203) for escrow metadata
- [ ] ML risk scoring (Isolation Forest) — anomaly detection in transaction patterns
- [ ] Commit-reveal for escrow creation (front-running protection)
- [ ] Demo/Real data toggle in console

## Phase 3 — Advanced

- [ ] Threshold escrow via MPC (Shamir Secret Sharing, n-of-m release)
- [ ] Flash loan protection (min_hold_period + block_delay checks)
- [ ] Gaming-reward escrow type with Merkle proof of results
- [ ] Agent-vs-Agent simulation testing framework
- [ ] Fuzz testing for smart contracts (cargo fuzz)
- [ ] Gas benchmark report

## Phase 4 — Mainnet & Ecosystem

- [ ] Security audit by third-party firm
- [ ] Mainnet deployment with governance multisig
- [ ] Multi-chain escrow bridge (Casper ↔ EVM chains)
- [ ] Agent discovery marketplace UI
- [ ] Formal verification (TLA+ specification for state machine invariants)
- [ ] Compliance framework for regulated jurisdictions

## Planned Infrastructure (stubs in codebase)

- `ChainAdapter` trait — multi-chain abstraction layer
- `ThresholdConfig` struct — MPC threshold parameters
- `EscrowType` enum — extensible escrow categories
- `FlashGuard` module — anti-manipulation checks
- `AgentRegistry` contract — DID + capabilities + staking
