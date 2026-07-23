# Threat Model — AgentEscrow402

This document expands on the summary in [`SECURITY.md`](../SECURITY.md) with
a structured threat model covering assets, actors, attack surfaces, and
mitigations. It is a living document — update it whenever a new contract,
endpoint, or trust boundary is added.

## 1. Assets

| Asset | Description | Impact if compromised |
|---|---|---|
| Escrowed funds (CSPR / AETUSD / AEMAT) | Value locked in `escrow`, `escrow-manager`, `multi-asset-escrow`, `insurance-pool` contract purses | Direct financial loss to agents |
| Agent private keys | Ed25519 / secp256k1 keys used to sign x402 payment intents and Casper deploys | Impersonation, unauthorized fund movement |
| Arbiter quorum integrity | 3-of-5 arbiter signatures gating disputed releases | Fraudulent release/refund if quorum is subverted |
| VRF seed / randomness | Used by `vrf-arbiter` to select arbiters | Biased or predictable arbiter selection |
| Backend service (FastAPI) | Hosts x402 flow, risk scoring, audit log, API surface | Availability loss, data tampering, secret leakage |
| Audit log / Merkle checkpoints | Append-only signed log of arbitration decisions | Loss of non-repudiation if forgeable |
| Nonce/replay cache | Prevents replay of signed payment intents | Double-spend / replay if bypassable |

## 2. Actors / Trust Boundaries

| Actor | Trust level | Notes |
|---|---|---|
| Buyer agent | Untrusted (external) | Signs payment intents; cannot unilaterally release funds |
| Seller agent | Untrusted (external) | Cannot unilaterally withdraw without confirmation/timeout |
| Arbiter (1 of 5, VRF-selected) | Semi-trusted | Individually cannot move funds; quorum of 3 required |
| Backend operator (deployer) | Trusted infra, NOT a contract admin backdoor | No special withdrawal rights on-chain (see SECURITY.md §Threat Model) |
| Casper network / validators | Trusted (base layer) | Standard blockchain consensus assumptions apply |
| External LLM API (arbitration assist) | Untrusted input source | Advisory only — deterministic rubric scoring supplements/overrides LLM verdict (see L-3) |

## 3. Attack Surfaces & Mitigations

### 3.1 Smart contracts (Rust/Wasm)
- **Integer overflow/underflow** — mitigated via `checked_add`/`checked_sub`/`checked_deduct_fee` on all balance math (escrow, insurance-pool, multi-asset-escrow, test tokens). Fuzzed under `contracts/tests/src/contract_fuzzing.rs` (proptest, 8 targets).
- **Unauthorized caller** — `get_immediate_caller` / `caller_key` guards on state-mutating entry points; admin-only ops explicitly gated (escrow-manager batch ops, vrf-arbiter seeding).
- **Reentrancy** — N/A: contracts make no external callbacks mid-execution.
- **Double-judge / replay of arbitration decisions** — VRF-elect and analyze-escalation paths reject replay (409) for a given `dispute_id`; see `tests/test_chaos_extended.py`.
- **Split-brain arbiter selection** — concurrent `/vrf/elect` races for the same dispute converge on a single elected arbiter regardless of on-chain-latency vs local-CSPRNG path (covered by chaos tests).

### 3.2 Backend API (FastAPI)
- **Authentication bypass** — every mutating request requires a valid x402 Ed25519/secp256k1 signature; verified server-side before any state change.
- **Replay attacks** — nonce + 5-minute timestamp window rejects reused signed intents. Extended replay-guard coverage: insurance cooldown replay (`tests/test_insurance_replay_guard.py`).
- **Rate-limit abuse / DoS** — 60 req/min/IP sliding window (known limitation: in-memory/per-process, not distributed — L-1/L-2).
- **Input validation / injection** — Pydantic models on all endpoints; parameterized SQL via SQLAlchemy/psycopg (no string-built queries).
- **Secret leakage** — env-var only secrets, never logged or echoed in responses; TruffleHog scans every push/PR.
- **Network partition** — API remains available and self-heals when the Casper RPC endpoint goes dark and recovers (chaos-tested full-outage recovery).

### 3.3 Audit trail / non-repudiation
- **Log tampering** — `server/audit_log.py` implements an append-only SHA-256 hash-chained log; any edited, deleted, or reordered entry breaks the chain and is detected (27 tests in `tests/test_audit_log.py`).
- **Forged checkpoints** — Merkle checkpoint roots are Ed25519-signed using the same tag-prefixed convention as `arbiter_crypto`/`arbiter_signing`; signature verification rejects forged/altered checkpoints.

### 3.4 Testnet / live-network dependency
- Opt-in `@pytest.mark.testnet` suite (`tests/test_testnet_integration.py`) exercises real Casper testnet RPC + deployed contract queries, and is excluded from default CI runs (`-m 'not testnet'`) so CI never depends on live-network availability; skips (not fails) on an unreachable node.

## 4. Explicit Non-Goals / Accepted Risk

Carried from `SECURITY.md` Known Limitations:

| # | Issue | Severity | Accepted because |
|---|---|---|---|
| L-1 | In-memory nonce cache | Low | Single testnet instance; Redis planned for production |
| L-2 | Per-process rate limiter | Low | Single Render instance; shared store planned for production |
| L-3 | LLM-assisted arbitration | Info | Deterministic rubric scoring is the binding verdict, LLM is advisory |
| L-4 | HTLC atomic swap not deployed | Info | Code complete; deployment planned post-mainnet |

## 5. Structural Guarantee (unchanged from SECURITY.md)

No agent — including the backend operator — can unilaterally move escrowed
funds. Every path to fund movement requires either mutual confirmation,
arbiter quorum (3-of-5), or timeout expiry, enforced on-chain by the
contracts themselves, not by backend logic.

## 6. Review Cadence

This threat model should be revisited whenever a new contract, entry point,
or external integration (e.g. a new LLM provider, a new asset type) is
added. Last written: 2026-07-23, alongside SBOM (T14) and SECURITY.md hardening (T15).
