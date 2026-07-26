# AgentEscrow402 — Roadmap

> x402-compatible payment middleware for AI agents on Casper Network

*Last verified against commit `e19f865` / testnet contract v9 (`612cead2...ddd9ec`), 2026-07-07.*

---

## Current State (Hackathon submission)

- [x] **8 smart contracts deployed on Casper testnet** — Core Escrow (v9), Escrow Manager,
      Insurance Pool (hardened), VRF Arbiter, Agent Identity Registry (v2), MultiAssetEscrow,
      AETUSD + AEMAT test tokens
- [x] FastAPI backend with PostgreSQL (Neon) persistence
- [x] Python SDK (`EscrowClient`) + LangChain `EscrowPaymentTool`
- [x] MCP server exposing **26** escrow/identity/risk/arbitration tools (`sdk/mcp_server.py`)
- [x] React console at ae402.xyz/console — 12 tabs, all live-wired
- [x] Reputation scoring with exponential decay + staking-aware slashing, integrated with escrow lifecycle
- [x] Insurance pool (configurable fee on release)
- [x] EscrowManager Factory with batch create/release/cancel (server-side cap/quorum guard)
- [x] Agent Identity Registry — DID-style, capabilities, staking; on-chain contract + API + console UI;
      integrated with escrow lifecycle (reputation syncs on release/dispute/resolve)
- [x] VRF arbiter election — real on-chain write path to deployed `vrf-arbiter` contract,
      4 arbiters registered with staked purses, INVARIANT 5 (arbiter ≠ dispute party) enforced,
      local-CSPRNG fallback — see [evidence](docs/evidence/VRF_ONCHAIN_ELECTION.md)
- [x] Multi-token escrow — real on-chain CEP-18 contract custody via deployed `MultiAssetEscrow`,
      full lifecycle (approve → create → release/refund/dispute/resolve) verified on testnet
- [x] On-chain HTLC atomic-swap (`commit_swap`/`reveal_swap`) — SHA-256 commit/reveal, verified live
- [x] Payment streaming — API-timed linear vesting with on-chain settlement at maturity
      (`POST /escrow/{hash}/stream-claim` triggers real `release()` when 100% vested)
- [x] ML risk scoring (IsolationForest) — `/risk/dashboard`, `/risk/score/{agent}`
- [x] Post-quantum ML-KEM metadata encryption
- [x] **450 Python + 40 Rust automated tests** (490 total, incl. Hypothesis/proptest property-based
      invariant tests); see [Testing](README.md#-testing)
- [x] CI/CD via GitHub Actions
- [x] Property-based testing — 9 proptest + 3 Hypothesis invariant checks
- [x] Gas benchmark report — [docs/GAS_BENCHMARK.md](docs/GAS_BENCHMARK.md)
- [x] MCP JSON-Schema registry — [docs/mcp_tools_schema.json](docs/mcp_tools_schema.json)
- [x] 349 real testnet transactions as on-chain evidence

## Post-Hackathon Roadmap

### Phase 1 — Production hardening

- [ ] Security audit by third-party firm
- [ ] Mainnet deployment with governance multisig for upgrades
- [ ] On-chain batch cap/quorum guard (contract upgrade to match server-side logic)
- [ ] Multi-worker deployment (thread-safe casper_client)

### Phase 2 — Advanced features

- [ ] Threshold escrow via MPC (Shamir Secret Sharing, n-of-m release)
- [ ] Flash loan protection (min_hold_period + block_delay checks)
- [ ] Gaming-reward escrow type with Merkle proof of results
- [ ] Agent-vs-Agent simulation testing framework
- [ ] Fuzz testing for smart contracts (cargo fuzz)

### Phase 3 — Ecosystem

- [ ] Multi-chain escrow bridge (Casper ↔ EVM chains)
- [ ] Agent discovery marketplace UI
- [x] Formal verification (TLA+ specification for state machine invariants) —
      `docs/formal/AE402Escrow.tla` models the escrow FSM. TLC proves 5
      safety invariants (valid-transition, no-double-release, no-refund-
      after-release, tombstoned-no-replay, amount-conservation) and 1
      liveness property (pending eventually terminal) over 27k distinct
      states in ~5s. CI job `.github/workflows/tla.yml` guards drift
      between the model and `server/app.py`.
- [ ] Compliance framework for regulated jurisdictions

## Prepared Infrastructure

- `ChainAdapter` trait — multi-chain abstraction layer
- `ThresholdConfig` struct — MPC threshold parameters
- `EscrowType` enum — extensible escrow categories
- `FlashGuard` module — anti-manipulation checks
