# AgentEscrow402 — Roadmap

> x402-compatible payment middleware for AI agents on Casper Network

*Last verified against commit `5937c09` / testnet contract v8 (`50ca3364...4498664`), 2026-07-05.*

---

## Current State (Hackathon submission)

- [x] Smart contract deployed on Casper testnet, package `d3ca33d1...c8eeb`, currently version 8
      (`50ca3364...4498664`) — 8 in-place upgrades preserving escrow state
- [x] FastAPI backend with PostgreSQL (Neon) persistence
- [x] Python SDK (`EscrowClient`) + LangChain `EscrowPaymentTool`
- [x] MCP server exposing **24** escrow/identity/risk/arbitration tools (`sdk/mcp_server.py`)
- [x] React console at ae402.xyz/console
- [x] Reputation scoring with exponential decay + staking-aware slashing
      (`server/identity_registry_api.py`)
- [x] Insurance pool (configurable fee on release)
- [x] EscrowManager Factory + VRF arbiter election + Agent Identity Registry (DID-style,
      capabilities, staking) — all real, wired endpoints, not stubs
- [x] Multi-token escrow: real on-chain CEP-18 (fungible) and CEP-78 (NFT) transfers, verified
      live (mint/transfer/balance round-tripped against deployed test tokens)
- [x] On-chain HTLC atomic-swap (`commit_swap`/`reveal_swap`) — SHA-256 commit/reveal, verified
      live end-to-end with a different account revealing than the one that committed
- [x] ML risk scoring (IsolationForest) — `/risk/dashboard`, `/risk/score/{agent}`
- [x] Post-quantum ML-KEM metadata encryption
- [x] 437 Python + 40 Rust automated tests (477 total, incl. Hypothesis/proptest property-based
      invariant tests); see [Testing](README.md#-testing) for current pass rate
- [x] CI/CD via GitHub Actions

## Phase 2 — Remaining core upgrades

- [x] Property-based testing with invariant checks (Hypothesis + proptest) — 9 proptest cases
      (`contracts/tests/src/property_tests.rs`) covering fee/insurance/TTL/quorum/reputation/HTLC
      invariants, 3 Hypothesis cases (`tests/test_property_based.py`) for the API-layer fee split
- [ ] Payment streaming (`/escrow/stream`) currently computes streamed/remaining amounts at the
      API layer only — upgrading to real on-chain per-tick vesting is still open
- [ ] MCP JSON-Schema registry for the existing 24 tools (schema generation, not new tools)
- [ ] Demo/Real data toggle in console (partially done via `WalletStatus` demo-mode banner)

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
