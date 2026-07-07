# AgentEscrow402 — Roadmap

> x402-compatible payment middleware for AI agents on Casper Network

*Last verified against commit `4b125f1` / testnet contract v9 (`612cead2...ddd9ec`), 2026-07-07.*

---

## Current State (Hackathon submission)

- [x] Smart contract deployed on Casper testnet, package `d3ca33d1...c8eeb`, currently version 9
      (`612cead2...ddd9ec`) — 9 in-place upgrades preserving escrow state
- [x] FastAPI backend with PostgreSQL (Neon) persistence
- [x] Python SDK (`EscrowClient`) + LangChain `EscrowPaymentTool`
- [x] MCP server exposing **24** escrow/identity/risk/arbitration tools (`sdk/mcp_server.py`)
- [x] React console at ae402.xyz/console
- [x] Reputation scoring with exponential decay + staking-aware slashing
      (`server/identity_registry_api.py`)
- [x] Insurance pool (configurable fee on release)
- [x] EscrowManager Factory + Agent Identity Registry (DID-style, capabilities, staking) — real,
      wired endpoints, not stubs
- [x] VRF arbiter election endpoint (`/vrf/elect`) — deployed `vrf-arbiter` contract with a
      correctly-wired on-chain *read* path (fixed in `235d8ca`); the on-chain *write* path
      (submitting `select_arbiters`) is not called anywhere yet, so elections currently resolve
      via the labeled `local_csprng` fallback — see [README](README.md#vrf-assisted-arbiter-election)
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
- [x] MCP JSON-Schema registry for the existing 24 tools — see
      [docs/mcp_tools_schema.json](docs/mcp_tools_schema.json) (stale checkbox, feature already
      shipped in `69cd14f`)
- [ ] Demo/Real data toggle in console (partially done via `WalletStatus` demo-mode banner)

## Phase 3 — Advanced

- [ ] Threshold escrow via MPC (Shamir Secret Sharing, n-of-m release)
- [ ] Flash loan protection (min_hold_period + block_delay checks)
- [ ] Gaming-reward escrow type with Merkle proof of results
- [ ] Agent-vs-Agent simulation testing framework
- [ ] Fuzz testing for smart contracts (cargo fuzz)
- [x] Gas benchmark report — see [docs/GAS_BENCHMARK.md](docs/GAS_BENCHMARK.md), real testnet
      numbers per entry point sampled from the bulk-tx evidence log

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

## ID-1 — Agent Identity Registry (on-chain)

- [x] Brought `contracts/stubs/src/agent_registry.rs` from stub to a real, deployed, tested
      contract — see [docs/AGENT_IDENTITY_REGISTRY.md](docs/AGENT_IDENTITY_REGISTRY.md).
      Standalone contract (doesn't touch/upgrade the live escrow contracts), package hash
      `0b760bb7bf9be5a74ee4ed5626bcc74a8154f221a059e29fc9d768d45fb4a2ba`, 10 real on-chain txs
      (deploy + upgrade + full register/stake/slash/deregister/decay lifecycle across 3
      agents), 7 property-based tests, external-AI-reviewed (2 real bugs found and fixed
      before/after deploy).
- [ ] Not yet wired to `escrow`'s own reputation logic or gated behind arbiter-quorum for
      `slash` — see "Known gaps" in the doc above.
