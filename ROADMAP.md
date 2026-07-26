# AgentEscrow402 — Roadmap

> x402-compatible payment middleware for AI agents on Casper Network

*Last verified against commit `7bec8ac` / testnet contract v10 (`07527a37...39ef1`), 2026-07-26.*

---

## Current State (Hackathon submission)

- [x] **9 smart contracts deployed on Casper testnet (13 total in `main`, 4 code-complete pending deploy)** — Core Escrow (v10), Escrow Manager,
      Insurance Pool (hardened), VRF Arbiter, Agent Identity Registry (v2), MultiAssetEscrow,
      AETUSD + AEMAT test tokens; Challenge Arbiter, Range Proof Registry, Governance DAO,
      Two-Key Account are code-complete but not yet deployed — see `TX_MANIFEST.md`
- [x] FastAPI backend with PostgreSQL (Neon) persistence
- [x] Python SDK (`EscrowClient`) + LangChain `EscrowPaymentTool`
- [x] MCP server exposing **26** escrow/identity/risk/arbitration tools (`sdk/mcp_server.py`)
- [x] React console at ae402.xyz/console — 19 tabs, all live-wired
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
- [x] **2081 Python + 250 Rust automated tests** (2331 total, incl. Hypothesis/proptest property-based
      invariant tests); see [Testing](README.md#-testing)
- [x] CI/CD via GitHub Actions
- [x] Property-based testing — 9 proptest + 3 Hypothesis invariant checks
- [x] Gas benchmark report — [docs/GAS_BENCHMARK.md](docs/GAS_BENCHMARK.md)
- [x] MCP JSON-Schema registry — [docs/mcp_tools_schema.json](docs/mcp_tools_schema.json)
- [x] 369 real testnet transactions as on-chain evidence

## Post-Hackathon Roadmap

### Phase 1 — Production hardening

- [ ] Security audit by third-party firm
- [ ] Mainnet deployment with governance multisig for upgrades
- [ ] On-chain batch cap/quorum guard (contract upgrade to match server-side logic)
- [ ] Multi-worker deployment (thread-safe casper_client)

### Phase 2 — Advanced features

- [x] Threshold escrow via MPC (Shamir Secret Sharing, n-of-m release) —
      T3.1 delivered the SSS split/reconstruct primitives; C13 wires them
      into the escrow lifecycle: `POST /escrow/{h}/threshold-arm` stores
      the sha256 commitment on the row (server never sees the secret or
      shares between calls), and `/release` refuses to proceed unless the
      caller presents >= n shares that reconstruct the committed secret.
      Backward-compatible (unarmed escrows behave as before).
- [x] Flash loan protection (min_hold_period + block_delay checks) — both
      halves wired into `/release`, `/refund`, `/dispute` (opt-in via
      `FLASH_GUARD_ENABLED`; block-delay half skips when funded_block or
      chain-tip is unknown so sandbox / offline runs are never punished)
- [x] Gaming-reward escrow type with Merkle proof of results — pure-Python
      Merkle helper (`server/gaming_merkle.py`) with domain-separated leaves
      and canonical-ordered pair-hashing so proofs are direction-bit-free.
      New endpoint `/escrow/{h}/gaming-arm` commits a result root to the
      escrow row; `/release` on a gaming-armed escrow requires a valid
      inclusion proof for the caller's `receiver_pubkey`. Backward-
      compatible (unarmed = standard escrow, no gate).
- [x] Agent-vs-Agent simulation testing framework —
      deterministic multi-agent simulator drives the real FSM and
      arbiter through scripted strategies (honest / withholding /
      dispute-spam / flaky-network); reproducible under a fixed seed.
      See [`server/agent_sim.py`](server/agent_sim.py) +
      [`demo/agent_vs_agent_showcase.py`](demo/agent_vs_agent_showcase.py)
      (7 adversarial scenarios + determinism probe).
- [x] Fuzz testing (cargo fuzz) — 5 libFuzzer targets over pure-Rust stubs
      (flash_guard × 3, escrow_types, threshold_config) + smoke CI job.
      First run already found an overflow panic in
      `EscrowType::Streaming::default_timeout_secs` (fixed, regression test
      added). See `contracts/fuzz/`.

### Phase 3 — Ecosystem

- [x] Multi-chain escrow bridge (Casper ↔ EVM chains) — mock relayer + mode-selector +
      diff-test shipped (`server/bridge_htlc.py`, `bridge_relayer.py`, `bridge_mode.py`);
      a real live Sepolia HTLC lock/claim path (`server/bridge_evm_adapter.py`) has also
      landed on `main` as a bonus proof-of-execution on top of the mock.
- [x] Agent discovery marketplace UI — `frontend/src/components/console/Marketplace.tsx`
- [x] Formal verification (TLA+ specification for state machine invariants) —
      `docs/formal/AE402Escrow.tla` models the escrow FSM. TLC proves 5
      safety invariants (valid-transition, no-double-release, no-refund-
      after-release, tombstoned-no-replay, amount-conservation) and 1
      liveness property (pending eventually terminal) over 27k distinct
      states in ~5s. CI job `.github/workflows/tla.yml` guards drift
      between the model and `server/app.py`.
- [x] Compliance framework for regulated jurisdictions — baseline policy engine shipped
      (`server/compliance.py`, `server/compliance_api.py`, `docs/tier3/T3.7-compliance-framework.md`)

## Prepared Infrastructure

- `ChainAdapter` trait — multi-chain abstraction layer
- `ThresholdConfig` struct — MPC threshold parameters
- `EscrowType` enum — extensible escrow categories
- `FlashGuard` module — anti-manipulation checks
