# Changelog

All notable changes to AgentEscrow402 are documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Version numbers follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased] — 2026-07-28

### Docs

- `docs/BLOCKERS.md` was stale: it still listed Blocker 2 (AE-2 v2, real
  on-chain VM tests via `casper-engine-test-support`) as open, but it was
  actually resolved by commit `8e5ac03` on 2026-07-27
  (`insurance_replay_onchain_vm_tests.rs` +
  `insurance_cooldown_replay_e2e_tests.rs`, ~840 lines, real WASM execution
  in the Casper VM). Marked resolved. Blockers 1 (`amount_motes` DB
  migration) and 3 (`AE402:v1:` domain-tag versioning) confirmed still open
  in code — both are breaking changes that need an owner decision on
  migration/rollout strategy before any work starts.

---

## [Unreleased] — Post-Deadline Review Pass (2026-07-27)

Full review/reconciliation pass across docs, site, and CI, done after the
07-26 hardening block above and its own review agent ran out of budget
mid-audit. Found and fixed real, live-facing issues, not just doc drift.

### Fixed

- **Landing page staleness (live browser walkthrough)**: `TrustSignals.tsx`'s
  "Verify on Testnet" evidence list was missing the Casper HTLC bridge (9 of
  10 contracts shown). `GrowthPotential.tsx` presented 6 already-shipped
  features (threshold escrow, formal verification, FlashGuard, multi-chain
  bridge, agent marketplace, compliance) as future roadmap; rewritten into a
  "Shipped since Tier-1" section plus a corrected, genuinely-remaining
  roadmap. `Capabilities.tsx` was missing 3 live features (threshold escrow,
  gaming-reward escrow, multi-hop A2A) despite claiming to list every live
  module. Same roadmap staleness fixed in `docs/STATUS_AND_ROADMAP.md`.
- **Test-count drift**: my own RPC-fallback commit added 4 tests
  (2081→2085) but only the README badge was updated at the time; swept the
  repo and fixed 8 more files still quoting 2081/2331, including 3 live
  frontend components (`Hero.tsx`, `TrustSignals.tsx`, `WhyAE402.tsx`).
- **README screenshots were completely stale** — `docs/screenshots/01-homepage.png`
  showed an old landing-page design (different nav, "4 Deployed Contracts")
  that no longer exists on ae402.xyz. Regenerated all 5 gallery screenshots
  from the live site.
- Added a "try it live" CTA line linking each new-this-round feature to its
  console page, and a new `docs/VIDEO_SCRIPT_v3.md` reflecting current
  contract/test/endpoint counts (old script had been deleted from history
  in an earlier docs cleanup and quoted 8 contracts / 62 API / 13 pages).

### Verified (no action needed)

- Vercel auto-deploy and Render backend deploy both healthy and current.
- All demo scripts (`demo.agent_flow`, `demo.insurance_showcase`,
  `demo.multi_asset_flow`, `demo.agent_vs_agent_showcase`,
  `demo.bridge_e2e_showcase`) run clean end-to-end against the live API.
- No CasperProver/anna-stolbovskaja cross-contamination found in AE402 docs.

---

## [Unreleased] — Final-Round Hardening (2026-07-26)

Continuation of the submission block below: the four post-hackathon contracts
from the 07-25 batch were merged and the 10th contract (Casper HTLC bridge)
went live, plus a wide judge-facing and reliability pass. Summarized by theme
(137 commits) rather than commit-by-commit — see `git log` for the full diff.

### Added — Contracts & new capabilities

- **Casper HTLC bridge (ROADMAP L85)** — 10th live testnet contract. Hash-time-locked
  atomic swap between the Casper leg and an EVM (Sepolia) leg, sha256 hashlock shared
  on both sides so no adapter re-hashing is needed. `docs/CROSS_CHAIN_DEMO.md`.
- **Two-Key Account** (`f995927`, hardened `c708f4d`, merged 2026-07-24) — cold/hot
  key account-abstraction-style account so a compromised hot key alone can't drain
  funds. 14 Rust property tests. Code-complete, not yet deployed to testnet — see
  `docs/TWO_KEY_ACCOUNT.md`. *(This entry was previously missing from the changelog
  entirely — added 2026-07-27.)*
- **Zero-knowledge amount privacy (W.2)** — opt-in Pedersen commitment + 48-bit range
  proof on `POST /escrow`; every subsequent read redacts the amount unless revealed
  via the blinding factor. 41 new tests.
- **Compliance & travel-rule framework (T3.7)** — deterministic jurisdiction checks
  and KYC tiering from the Agent Identity Registry, inline on escrow creation.
- **Threshold escrow / Shamir MPC (T3.1)** — split a release secret into m-of-n
  shares; below-threshold coalitions learn nothing. `/threshold/*` router, 37 tests.
- **Gaming-reward escrow (T3.2)** — Merkle-root reward commitments with O(log N)
  inclusion-proof claims. `/gaming/*` router, 44 tests.
- **Multi-hop A2A choreography (AE-M1)** — chain an escrow across N agent hops with
  a verifiable hash-chain of attestations. `/intents` router, 28 tests.
- **Agent discovery marketplace UI (T3.6)** and **Agent-vs-Agent simulation
  framework (T3.5)** — new console/testing surfaces.
- **FlashGuard (T2.12)** fully wired onto release/refund/dispute with a block-delay
  half; **on-chain preflight** WASM validator + CI gate (C5); **cargo-fuzz** smoke
  over pure-Rust stubs, one overflow bug found and fixed (C12).

### Added — Judge-facing & operational

- **Judge-lite reproducibility CLI** (C1) — 60-second Python-only replay.
- **Observability foundation** (C2) — request-latency histograms, JSON logs, Grafana
  dashboard.
- **Agentic-slice end-to-end tests + `demo/agent_flow.py`** (C3).
- **SDK release automation** — publish workflow + PR version gate + runbook.
- **OpenAPI drift gate** — deterministic regeneration + CI enforcement.
- Numbers reconciled across README/ARCHITECTURE/ROADMAP/API docs to the current
  10 live + 4 pending contracts, 140 endpoints, 2331 tests, 369+ testnet deploys,
  19 console pages; `sitemap.xml` fixed from 13 to 19 pages; stale CP/CasperProver
  mentions removed from AE402 docs.

### Fixed

- Dockerfile was missing `COPY docs/ docs/` — the deployed API's `/mcp/tools`
  endpoint silently returned an empty tool list in production (found live on
  ae402.xyz's MCP Playground: "0 tools" / "vunknown").
- Write-path Casper RPC calls (escrow create/release/etc., via Node subprocess)
  had no fallback across `self._rpc_endpoints` — unlike reads. A write hitting a
  rejecting primary endpoint failed outright with no retry. Fixed in
  `server/casper_client.py` (`_run_node_script_with_fallback`), 2026-07-27.
- CI gates (black formatting, SBOM regeneration guard, dependency resolution)
  fixed after drifting since earlier merges.

---

## [Unreleased] — Hackathon Submission Block (2026-07-19 → 2026-07-25)

Submission-grade hardening across contracts, evidence, and judge-facing surfaces. All items below either landed on `main` or are on-branch in an open PR with tests green.

### Added — New contracts (post-hackathon block, on-branch)

- **Challenge Arbiter with commit-reveal + bond/slash** ([PR #55](https://github.com/alexbelij/AgentEscrow402/pull/55), `feat/ae402-challenge-arbiter`). Two-phase arbiter selection: submit `commit(H(seed))`, reveal `seed`, run VRF-weighted quorum. Bonds slashed on no-reveal, malicious reveal (mismatched hash), or losing minority in ternary arbitration. 26 Rust property tests + 31 Python parity tests. ~160 KB WASM. Threat model: `docs/CHALLENGE_ARBITER.md`.
- **Range Proof Registry** ([PR #62](https://github.com/alexbelij/AgentEscrow402/pull/62), `feat/ae402-range-proofs`). Threshold-attested amount-range proofs using mod-exp on a 3072-bit safe prime — no ZK-precompile dependency. Pedersen commitments; verifier accepts (proof, commitment, range) tuple; 3-of-5 attester quorum. 32 Rust property tests + 42 Python parity tests. ~180 KB WASM. Design + verifier calibration: `docs/RANGE_PROOFS.md`.
- **Governance DAO with AE402 action layer** ([PR #63](https://github.com/alexbelij/AgentEscrow402/pull/63), `feat/ae402-governance-dao`). Ported voting/quorum/delegation primitives from RWA-Sentinel under Apache-2.0 (see `contracts/ae402-governance-dao/PROVENANCE.md`), replaced action layer with 6 AE402-specific actions (`ADJUST_FEE_BPS`, `ROTATE_ARBITER_SET`, `UPDATE_INSURANCE_POOL_PARAMS`, `UPDATE_TIMELOCK_DELAY`, `UPDATE_RANGE_PROOF_PARAMS`, `PAUSE_PROTOCOL`) with cross-contract execution via `exec_log`. 30% quorum, 7-day voting, veto path, late-finalization. 49 Rust property tests + 58 Python (51 parity + 7 lifecycle). 159 KB WASM. Full threat model: `docs/GOVERNANCE.md`.

### Added — Multi-hop A2A choreography (AE-M1)

- **`server/intent_chain.py` + `/intents` router** — agent-to-agent choreography across N escrow hops (e.g. `agent A -> agent B -> agent C`), built as a pure Python orchestration layer on top of the existing `/escrow` + `/release` endpoints (zero changes to the on-chain `escrow`/`escrow-manager` contracts). Declare an intent with a planned `agent_path`; register each hop's `service_hash` in order via `chain_escrow`; attest a hop after its escrow is released via `attest_hop`, which emits a redacted `hop_attested` audit event (`server/audit_trace.py`) and folds it into a running `chain_root_hash` (linear hash chain over ordered attestation `event_id`s, `audit_trace.compute_chain_root`). Anyone holding the returned `attestation_event_ids` can independently recompute `chain_root_hash` and confirm no hop was skipped, reordered, or substituted. 19 unit tests (`tests/test_intent_chain.py`) + 9 API tests (`tests/test_intent_chain_api.py`, including a full real `/escrow` + `/release` two-hop integration scenario).

### Added — Judge-facing surfaces (Tier 1 pre-submission)

- **`BACKLOG.md`** — single-source-of-truth tracker for all remaining work (Tier 1/2/3/Wow), consolidated from pre-hackathon tails, ROADMAP, drop-list, dangling branches, and 6-persona consensus.
- **`TX_MANIFEST.md`** — canonical registry: 9 live production contracts + 3 post-hackathon contracts, all package/contract/deploy hashes, explorer links, 369+ testnet activity deploys pointed to via bulk logs, 3 verification recipes, and a regeneration procedure.

### Test coverage snapshot (submission block)

- **Rust:** 119 tests passing (property + unit + integration).
- **Python:** 1067 tests passing.
- **Regressions from the submission block:** 0.
- **New tests added by the submission block:** 107 (49 governance property + 51 governance parity + 7 governance lifecycle in this batch alone; earlier batches added 42 range-proof parity + 32 range-proof property + 31 challenge-arbiter parity + 26 challenge-arbiter property). *(Corrected 2026-07-27: the Rust property-test counts for Challenge Arbiter and Range Proof Registry were originally recorded as 45 and 34 respectively — those were stale/aspirational figures from when the PRs were opened. `TX_MANIFEST.md`'s 26 / 32 are the ones verified by actually running the package-scoped `cargo test` commands, confirmed again here by a static count of `#[test]`/`#[proptest]` attributes in `contracts/tests/src/{challenge_arbiter,range_proof_registry}_property_tests.rs`.)*

### Fixed / verified

- **500-on-existing-PR gotcha logged (dev workflow):** GitHub `POST /pulls` occasionally returns `500` after the PR was already created server-side; subsequent create returns `422 "already exists"`. Root-cause noted in `docs/LESSONS.md`; before retry always `GET /pulls?head=…`.
- **Ambient PAT auth precedence:** classic PAT works over Basic auth (`https://<user>:<token>@github.com/…`) rather than `Bearer`; documented in `sdk/README.md` deployment section.

---

## [Previous unreleased entries] — up to 2026-07-19

*Delivered the console/backend work the 1.1.0 entry below prematurely claimed as shipped.*

### Fixed (2026-07-25) — AE-2 pre-mainnet gate: real on-chain VM regression test + production bug
- **`contracts/tests/src/insurance_replay_onchain_vm_tests.rs`** — new real Casper VM regression suite for insurance-pool's tombstone/replay invariant (closes the AE-2 pre-mainnet gate tracked in `docs/INSURANCE_REPLAY_TESTS.md`). Drives the actual compiled `insurance-pool.wasm` through `casper-engine-test-support`'s `LmdbWasmTestBuilder` — a real execution engine, not the existing host-side mirror (`insurance_replay_tests.rs`). Three scenarios: happy-path claim + purse debit, same-deploy replay rejected by the tombstone (`ApiError::User(9)`), cross-escrow replay rejected by message-binding (`ApiError::User(8)`). Marked `#[ignore]`; wired into a new nightly CI job (`insurance-pool-vm-regression` in `contract-audit-nightly.yml`), not the PR-gate `ci.yml`. Deploy-gate line added to `docs/DEPLOY.md` § step 3.
- **`contracts/insurance-pool/src/main.rs::claim()`** — fixed a real production bug the new VM suite caught immediately: every first-ever `claim()` call reverted with `ERR_ESCROW_ALREADY_CLAIMED` (error 9), even for a brand-new, never-touched `escrow_id`. Root cause: the tombstone precondition check called the shared `check_claim_preconditions` with dummy `(0, 0)` timestamp args, relying on a `debug_assert!` to guarantee the only reachable rejection was `AlreadyClaimed` — but the cooldown branch inside that function evaluates `0 < 0 + COOLDOWN_SECONDS = true` first, returning `Cooldown` instead, on every fresh claim. `debug_assert!` is a no-op in release wasm builds, so the mismatch was silently swallowed and every call fell through to reverting with the tombstone's error code regardless of which rejection actually fired. Fixed by checking `already_claimed` directly instead of delegating to `check_claim_preconditions` for that first check. Full root-cause writeup: `docs/INSURANCE_REPLAY_TESTS.md` § "Real production bug this suite caught".

### Added (2026-07-25) — Judge-facing submission artifacts + T2.12
- **T2.12 — Flash-loan protection activated in the escrow release lifecycle** (`server/flash_guard.py`, wired into `POST /release` in `server/app.py`, gated behind new `Config.flash_guard_enabled` / `FLASH_GUARD_ENABLED` env var, default `false` so the existing sandbox/demo happy path is unaffected). The `flash_guard` module already ships both the wall-clock hold-period check and the block-height delay check (`docs/FLASH_GUARD.md`); this wires its `enforce()` gate into `/release`: when enabled, a release attempted before either the minimum hold period or the minimum block delay has elapsed since the escrow's `created_at` is rejected with a `422`. Uses the existing, more complete `flash_guard` module rather than introducing a second implementation. 4 new API tests in `tests/test_api.py::TestReleaseEndpoint` covering blocked/allowed/default-off/boundary cases; full suite green, zero regressions.
- **`docs/ROI_CALCULATOR.md`** — per-transaction cost breakdown for a potential integrator, built entirely on real measured gas numbers from `docs/GAS_BENCHMARK.md` (no new gas claims introduced): happy-path vs. disputed-path cost, the 2% default insurance fee with a worked example, what the fee buys vs. a bare transfer, and a break-even framing for build-vs-integrate.

### Added (2026-07-25) — Tier Wow / Tier 3 block
- **W.2 — Zero-knowledge amount privacy wired into the escrow lifecycle** (`server/confidential_escrow.py` + updates to `server/app.py`, `server/models.py`, `docs/ZK_AMOUNT_PRIVACY.md`). Closes the gap that doc's own "Future work #1" flagged: the Pedersen-commitment + range-proof primitive (`server/zk_amount.py`, shipped earlier) previously only existed as a standalone `/zk/*` audit surface, never touching a real escrow. Now `POST /escrow` takes an opt-in `confidential: true` flag — the server still computes the real net amount (fund movement needs it; there is no on-chain amount-hiding contract) but seals it behind a Pedersen commitment + 48-bit range proof (`confidential_escrow.ESCROW_RANGE_BITS`, narrower than `/zk/*`'s 64-bit default to keep synchronous request latency in the ~0.7-1.1s range) bound to the escrow's own `service_hash` as its Fiat-Shamir transcript. Every subsequent read — the create response, `GET /escrow/{service_hash}`, and the `EscrowRecord` returned by `/release`, `/refund`, `/dispute`, `/resolve` — redacts `amount` to a `-1` sentinel; the plaintext amount and blinding factor live only in a private, in-process ledger (`confidential_escrow._confidential_ledger`, deliberately outside `EscrowRecord`/`SandboxStore` so it can never round-trip into an API response or best-effort Postgres write). New `POST /escrow/{service_hash}/reveal` endpoint discloses the amount to whoever supplies the correct blinding — a cryptographic gate (Pedersen binding), not yet paired with sender/receiver/arbiter authorization (flagged as follow-up). An amount whose net value doesn't fit the 48-bit cap gets a `422` *before* any escrow is created — no state where the client sees an error but a plaintext escrow silently exists anyway (a real bug caught and fixed during this work, before the pre-flight check was added). 41 new tests (29 unit in `tests/test_confidential_escrow.py` incl. 3 slow tests at the real 48-bit default + 12 API in `tests/test_confidential_escrow_api.py` incl. redaction round-trip through `/release`); full suite 1362 passed / 1 skipped / 3 deselected (network), zero regressions.
- **T3.7 — Compliance framework for regulated jurisdictions** (`server/compliance.py` + `server/compliance_api.py` + `docs/tier3/T3.7-compliance-framework.md`). Pure, deterministic policy engine — no I/O, no chain calls, no hidden clock. Three axes: (1) jurisdiction classification (`UNRESTRICTED` / `RESTRICTED` / `PROHIBITED`, illustrative default table for US/GB/SG/NG/TR/VE/KP/IR — explicitly not a real sanctions list, swappable wholesale via `ComplianceEngine(policies=...)`); (2) KYC tiering that reuses `identity_registry.VerificationLevel` as the single source of truth instead of a second drifting notion of "how verified is this agent"; (3) travel-rule-style reporting thresholds, independent of the permit/reject verdict (a permitted transaction can still `requires_reporting`). Unknown jurisdictions fail closed (`unknown_jurisdiction` rejection), not silently pass. `/compliance/*` router: `GET /jurisdictions` (read-only table listing), `POST /evaluate` (dry-run, never mutates state — same non-mutating-preview convention as T3.3's `/batch-preview`), `POST /evaluate-by-agent` (resolves KYC tier live from the identity registry by DID so a client cannot spoof a higher tier than what's on file — the request schema has no `verification_level` field to spoof). 55 new tests (40 unit incl. 3 hypothesis property tests + 15 API incl. a DID-spoofing-is-impossible check and a registry-non-mutation check); full suite 1321 passed / 1 skipped, zero regressions.
- **T3.6 — Agent discovery marketplace UI** (`frontend/src/components/console/Marketplace.tsx`). A discovery-first console page distinct from `IdentityRegistry.tsx` (which is the admin/testing surface for registering and simulating identity activity): browse every agent in the DID reputation registry (`server/identity_registry.py`) as a card grid, filter by capability (multi-select chips derived client-side from the full result set — the backend has no distinct-capability endpoint), minimum reputation and verification level, free-text search on display name/DID/account hash, and sort by reputation, deals completed, verification level, or recent activity. Click a card to open a detail view with the full reputation/risk/stake breakdown and verified-capability badges. No backend changes — reuses the existing `/identity-registry/search` and `/identity-registry/stats/summary` endpoints (empty-filter search already returns every agent, so the frontend fetches once and filters/sorts client-side). Wired into the console nav under "Trust & resolution" at `/console/marketplace`. No frontend test framework exists in this repo (UI pages are verified via `tsc --noEmit` + `vite build`, both clean); backend regression suite re-run to confirm zero impact (1278 passed, 1 skipped, offline).
- **T3.5 — Agent-vs-Agent simulation framework (testing tool)** (`server/agent_sim.py` + `server/agent_sim_api.py`). Deterministic multi-agent simulator that drives the *real* `EscrowFSM` + heuristic `ai_arbitration` arbitrator through configurable adversarial scenarios instead of reimplementing escrow/dispute logic — the simulator is a harness, not a parallel model. Seeded RNG gives byte-identical `report_hash` across repeated runs of the same scenario. 4 reference strategies: `honest`, `withholding` (malicious counterparty), `dispute_spam` (evidence flooding), `flaky_network` (unstable network, no real sleep). `POST /simulate/agent-vs-agent` runs a batch of rounds and returns per-round outcomes + aggregate stats; `GET /simulate/strategies` lists the available strategies. Fixed an off-by-one in round accounting found by the honest-vs-honest test (`continue` after a terminal FSM transition re-entered the loop and incremented `round_no` before the `is_terminal` break — corrected to `break` immediately on terminal transition, keeping `rounds_taken` accurate). 38 new tests (30 unit + 8 API), all passing; full suite 1278 passed / 1 skipped, zero regressions.
- **T3.4-B — HTLC atomic-swap bridge (real Sepolia)** (`contracts/HTLC.sol` + `server/bridge_evm_adapter.py` + `docs/tier3/T3.4-B-bridge-evm-sepolia.md`). Real Solidity HTLC contract deployed to Ethereum Sepolia — deploy tx `0xc1c6e1a9920fb2c45a8fd82508b734246986e6f558a0c6912531cd7dad2d3b79` (block `11348069`), contract address `0xF9d55d029280741162488a4ae8517716Eb80A910`, verified independently on-chain (non-empty bytecode at the recorded address, receipt `status == 1`). Same semantics as T3.4-A's mock: `sha256(preimage) == hashlock`, `msg.sender == recipient` on claim, absolute `timelock`, one-way `EMPTY → LOCKED → CLAIMED | REFUNDED`. Web3.py adapter (`bridge_evm_adapter.py`) drives `lock`/`claim`/`refund`/`getStatus` against the live chain, decoding Solidity custom errors (`PreimageMismatch`, `TimelockExpired`, `NotRecipient`, `NotSender`, `AlreadyLocked`, …) into a single `EvmAdapterError`. New pytest marker `network` gates the 3 real-chain integration tests (deployment-matches-chain, lock→claim happy path on a freshly deployed instance, forged-preimage on-chain rejection) out of the default/offline run — offline suite stays at 1240 passed/1 skipped with 3 deselected; network suite run explicitly (`pytest -m network`) is 3 passed. Diff-tested by inspection against the T3.4-A mock oracle: identical revert conditions on both `claim` (not-locked / expired / preimage-mismatch) and `refund` (wrong signer / not-yet-expired).
- **T3.4-A — HTLC atomic-swap bridge (mock)** (`server/bridge_htlc.py` + `server/bridge_htlc_api.py` + `docs/tier3/T3.4-A-bridge-htlc-mock.md`). Deterministic, in-memory Hash Time-Locked Contract state machine mirroring a real cross-chain atomic swap between Casper and an EVM chain. Two legs, one shared hashlock `H = sha256(preimage)`, ordered timelocks (`T_b < T_a` enforced at initiate). State machine: `INIT → PROPOSED → LOCKED → CLAIMED | REFUNDED`. Safety invariants asserted by tests: either both legs claim (swap completes) or both refund (swap aborts), never a mixed outcome; no preimage from swap A ever claims swap B; forged preimage always rejects; lock/claim after timelock rejects; refund before timelock rejects. `/bridge/htlc/*` router: `POST /preimage/new` (demo helper), `POST /initiate`, `POST /legs/{id}/lock|claim|refund`, `GET /legs/{id}`, `GET /swaps/{id}`, `GET /swaps/{id}/summary` (`atomic_outcome` ∈ {completed, aborted, in_progress} + `safety_violation` flag), `GET /swaps`. Typed rejection codes stable for SDK consumers (`preimage_mismatch`, `timelock_not_expired`, `timelock_expired`, `already_claimed`, `already_refunded`, `not_locked`, `not_proposed`, `unknown_leg`, `leg_already_exists`, `invalid_hashlock`, `invalid_amount`, `timelock_ordering`). Deterministic ids: `leg_id`, `swap_id`, mock tx hashes are all sha256 of the input tuple — the same inputs across independent processes produce byte-identical outputs (needed as an oracle for the real Sepolia adapter in T3.4-B). 56 new tests (37 unit + 19 API): all state transitions, all typed rejections, full atomic-swap happy path, both-refund abort, cross-swap isolation, 2 hypothesis property tests (happy-path always completes, forged preimage never claims), deterministic tx-hash reproducibility across registries. Real Sepolia integration is the T3.4-B follow-up ticket.
- **T3.3 — On-chain batch cap/quorum guard** (`server/batch_guard.py` + `server/batch_guard_api.py` + `docs/tier3/T3.3-batch-cap-quorum-guard.md`). Extracts the ad-hoc server-side batch-release validation from `server/app.py` into a *pure*, deterministic validator with a stable typed `BatchDecision`. Same policy as the inlined logic (release-cap check + arbiter-quorum bound per escrow), now organised as an oracle the future WASM guard can be diff-tested against. New `POST /escrows/batch-preview` dry-run endpoint returns the exact admit/reject decision without hitting Casper or mutating state (200 is not an admit — clients inspect `admit`). `/escrows/batch-release` and `/escrows/batch-cancel` refactored to delegate to the same guard, so the two paths cannot drift. Stable rejection codes (`empty_batch`, `batch_too_large`, `unknown_action`, `arbiter_list_length_mismatch`, `duplicate_service_hash`, `escrow_not_found`, `escrow_not_pending`, `quorum_shortfall`) safe to switch on client-side. Invariants: all-or-nothing atomicity; vote-to-escrow binding (a cap-approval signature over `release:<sh>:cap_approval` credits ONE escrow only, never any other in the same batch); duplicate pubkey de-duplication per escrow; cancel never needs quorum; empty registered arbiter set retains legacy escape-hatch parity (on-chain guard remains authoritative). 29 new tests (19 unit + 10 API), including forged-signature rejection, vote-binding across escrows, deterministic replay (same inputs → byte-identical decision), and dry-run non-mutation. Rust WASM transliteration is the follow-up.
- **T3.2 — Gaming-reward escrow with Merkle proof of results** (`server/gaming_reward.py` + `server/gaming_reward_api.py` + `tests/test_gaming_reward{,_api}.py` + `docs/tier3/T3.2-gaming-reward.md`). Trust-minimised prize distribution for on-chain gaming/tournaments: operator commits a reward sheet `{player_id → (amount, rank)}` by publishing only its Merkle root; each winner independently claims their share by presenting an O(log N) inclusion proof. Reuses the same binary-Merkle tree math as `merkle_provenance.py` with a reward-shaped leaf pre-image (`sha256("<player_id>:<amount>:<rank>")`) so proofs are cross-verifiable in TS. Empty sheet has stable root `sha256("empty-rewards")`. `/gaming/*` router: `POST /commit`, `POST /lock`, `GET /proof/{root}/{player}`, `POST /claim`, `GET /escrow/{id}`. Solvency guard on lock (`total_committed ≤ prize_pool_motes`); per-escrow asyncio lock serialises claim decrements. `evaluate_claim` typed rejections: `proof_invalid` / `already_claimed` / `exceeds_pool`. 44 new tests (31 core + 13 API), including 2 hypothesis property tests (all-winners-verify, amount-tampering-always-fails) and an async parallel-claim safety test. Losers' scores stay private (their leaves are never revealed). Storage is in-memory; Postgres persistence is a mechanical follow-up.
- **T3.1 — Threshold escrow MPC (Shamir SSS)** (`server/threshold_secret.py` + `server/threshold_api.py` + `docs/tier3/T3.1-threshold-mpc.md`). Pure-Python Shamir Secret Sharing over the secp256k1 group order (≈2²⁵⁶ prime, reuse of W.2 crypto choice) — no new deps. Split any 32-byte release secret into `m` shares with `n`-of-`m` reconstruction; below-threshold coalitions learn nothing (information-theoretic). Above the SSS primitive: `build_threshold_release(payload, threshold, total)` generates a random 32-byte AEAD key, encrypts the payload (HKDF-SHA256 → HMAC-SHA256 CTR + MAC), splits the key. Any share tamper → wrong K → AEAD MAC fails at reconstruction. `/threshold/*` router: `POST /split`, `POST /reconstruct`, `GET /config`. Typical parameterisations (3-of-5 HA, 2-of-3 dev, 5-of-7 high-value) documented. Non-goals for v1: VSS, proactive resharing, threshold signatures (FROST) — deferred. 37 new tests (31 core + 6 API), including hypothesis property tests and cross-bundle share-swap attack resistance.
- **W.4 — Pilot outreach kit** (`docs/outreach/`). Sales-side work is Quentin's; this is the reusable material: `OUTREACH_TEMPLATES.md` (cold-DM/email templates for LangChain / X / AutoGen channels + warm-referral + follow-up + anti-patterns), `PILOT_PITCH.md` (one-page problem → insight → product → why Casper → pilot ask), `QUICKSTART_5MIN.md` (5-min integration path optimized for time-to-first-value: pip install → API key → create/release/dispute code snippets → advanced W.2/W.3 hooks), `TESTIMONIAL_INTAKE.md` (6-question post-pilot intake with permission + attribution rules). Success metric: one external agent-dev quoted on the hackathon submission page by demo day. No fake testimonials — the intake path requires explicit written permission.
- **W.3 — Cross-chain escrow demo** (`server/cross_chain.py` + `server/cross_chain_api.py` + `docs/CROSS_CHAIN_DEMO.md`). `create()` on Casper, `release()` triggered by an EVM event via a mocked `ChainAdapter`. Python protocol mirrors the Rust trait in `contracts/stubs/src/chain_adapter.rs` (`verify_remote_tx`, `remote_block_height`, `supported_chains`); `MockEVMAdapter` + `MockCasperAdapter` implementations. `CrossChainRegistry` enforces double-spend prevention via `(chain_id, tx_hash)` index; settlement is idempotent; deterministic escrow ids via `sha256(sender|receiver|chain|tx)`. `/crosschain/*` router: create/settle/cancel/get/list/chains + mock event injection + block advance for the demo. Configurable `min_confirmations` per escrow (default 12). 24 new tests covering adapter behavior, registry CRUD, full settlement lifecycle, cancel/expire, and full E2E via FastAPI TestClient (create → try-settle-fails → inject event → settle-succeeds → idempotent-resettle → cancel-fails).
- **W.2 — Zero-knowledge amount privacy** (`server/zk_amount.py` + `server/zk_amount_api.py` + `docs/ZK_AMOUNT_PRIVACY.md`). Pedersen commitments on secp256k1 (`C = r·G + v·H`) + bit-decomposition Chaum-Pedersen OR range proofs (Fiat-Shamir) covering `0 ≤ v < 2^64`. Second generator `H` is hash-to-curve of `AE402/ZK/H/v1` (no known DLOG). Homomorphic sum enables batch-cap conservation without seeing individual amounts. Stateless `/zk/*` router: `POST /zk/prove`, `POST /zk/verify`, `POST /zk/aggregate`, `POST /zk/open`, `GET /zk/generators`. Opt-in demo/audit surface — plain amounts remain the fast path. 41 new tests (33 unit + 8 API), including tamper-resistance, transcript-binding replay resistance, and full 64-bit end-to-end (~1.4s prove/verify per proof, ~33KB proof size).

### Added (2026-07-19)
- **`AE402_STRICT=1` fail-loud mode** (`server/strict.py`, feat/ae402-strict-mode). Opt-in operator guarantee that a 200 response corresponds to a real testnet write: every documented silent-fallback branch raises `StrictModeError` -> 503 with a structured JSON body instead of returning a synthesised / mock response. Startup refuses to boot if `AE402_STRICT=1` is set but any of the three preconditions is missing (empty `CASPER_NODE_URL`, empty `ESCROW_CONTRACT_HASH`, `SANDBOX=true`). `/health` exposes a `strict_mode` capability breakdown ({enabled, preconditions_ok, violations, guarantees}) so a judge can see the guarantee level at a glance. `verify.sh` gained a `verify_strict_mode` check that reports the picture without forcing strict on for the hosted demo. 17 unit + integration tests in `tests/test_strict_mode.py` cover the config-precondition matrix, the runtime `guard()` no-op / raise asymmetry, the `/health` shape in all three states (off / on+ok / on+misconfigured), and the FastAPI exception handler round-trip. Guard call sites inside chain / RPC / DB paths are staged separately (see `docs/STRICT_MODE_ROLLOUT.md`).

### Added (2026-07-17)
- **Red-team self-audit** (`docs/RED_TEAM.tmp`) — 15 attack-vector matrix with mitigation status; documents the one real gap (insurance-pool replay under specific reorg conditions) alongside the resistances (reentrancy, integer overflow, unauthorized cancellation, front-running, injection). Commit `a10e6a6`.
- **verify.sh** — single-command proof of on-chain deployment: checks all 8 contracts exist on Casper testnet (via CSPR.cloud), API `/health`, escrow round-trip, frontend serving, and `onchain.json` parity. Commit `5b64081`, merged in `9184dbc`.
- **RPC fallback chain** — CSPR.cloud → NowNodes → official node; escrow lifecycle survives any single provider outage (`server/casper_client.py`). Commit `d241726`, merged in `ce136ff`.
- **`ABSTAIN` verdict** for arbiter conflict-of-interest — arbiters return `abstain` instead of a coerced vote when a party is a party (`server/vrf_election.py`). Commit `038585a`.
- **`X-Request-ID` middleware** for request tracing across backend logs (`server/middleware.py`). Commit `80f376c`.
- **`/health`** returns `mode` (sandbox|live) and version bumped to `0.3.0`. Commit `0dc28d1`.
- `deploy-out/onchain.json` filled with CSPR.cloud-verified deploy hashes for all 8 contracts (`cdcbe92`).
- `SECURITY.md` self-audit table (`a2b6273`).
- Complete favicon set (16/32/apple-touch), sitemap.xml with all console routes, status badges, submission checklist table in README, skeleton loaders on Agents/Escrows tabs, CONTRIBUTING.md, frontend CI workflow, secret-scan workflow, Dependabot, `.well-known/casper-agent-card.json` for agent discovery, Telegram links in navbar and footer, ExplorerLink hardening (validation + `noopener`), wallet spinner during CSPR.click signing, confirmation modals for destructive actions, empty states, copy-to-clipboard utility + CopyButton, console.error suppression in production, real generated demo signature (no more placeholder), 404 page with console link and image fallback.

### Fixed (2026-07-17)
- `checked_sub` / `checked_add` in test-token `transfer` and `transfer_from` — prevents integer underflow on custody-compatible tokens (`72f9594`).
- Root `/` redirect to `/health` for Render probe (`089b3f5`).
- Pydantic v2 `model_` namespace warning suppressed via `ConfigDict` (`577db34`).
- Secret-scan workflow — removed `base`/`head` that fail on push events (`ef5302c`).

> **Note (2026-07-18 changelog audit):** the entries above were previously misdated (spread across fictional "2026-07-15", "2026-07-14 batch" and "2026-06-14" labels); git history confirms all of them landed on 2026-07-17. Corrected in place. A block of ~30 real commits from 2026-07-06 (live-wallet escrow creation, secp256k1 x402 support, insurance-pool arbiter-quorum hardening, gasless CEP-18 permits, VRF read-path fix, and more) currently has **no changelog entries at all** — flagged for whoever picks up the changelog next, not written up here to avoid guessing at intent from commit messages alone.

### Fixed (2026-07-08)
- Integer floor division in insurance-fee calculation avoids float precision loss (`37ac252`, closes #1).

### Fixed (2026-07-05)
- **v8 contract deploy**: `read_release_cap()` used `storage::read::<u64>(uref).unwrap_or_revert()`,
  which reverted `release()`/`reveal_swap()` with `ApiError::EarlyEndOfStream [17]` whenever a
  `release_cap` named key existed with the wrong stored type (not just when missing). Fixed to
  fall back to the default cap on any read failure. Deployed as contract package version 8
  (`d3ca33d1...c8eeb`, contract_hash `50ca3364...4498664`), verified live with a fresh
  create → release round trip. Production API's `ESCROW_CONTRACT_HASH` env var was still pointing
  at the stale v3 hash despite running in live mode — updated and force-redeployed.
- **Docs audit**: full pass over every doc file (README, ROADMAP, STATUS_AND_ROADMAP, SECURITY,
  SUBMISSION, BUIDL_SUBMISSION, docs/ARCHITECTURE, docs/SDK, BLOG_POST, SOCIAL_POSTS,
  VIDEO_SCRIPT) for accuracy against current code. Found and fixed: stale contract hashes (some
  files still referenced the very first v1 deployment), stale test counts (85/18 instead of
  333/29), stale MCP tool count (7 instead of 24 — SDK.md's tool table was also missing 17 of the
  24 real tools), a wrong production API URL (`ae402-backend.onrender.com`, which 404s — real one
  is `agentescrow402-api-ywm8.onrender.com`), a wrong frontend framework claim (Next.js — it's actually
  React + Vite), a wrong dispute-resolution diagram (showed 3 arbiters / 2-of-3 majority instead
  of the real 5 arbiters / 3-of-5 quorum), an inaccurate STATUS_AND_ROADMAP/SECURITY claim that the
  contract has no upgrade mechanism and arbiters can't be rotated (both are real, working
  entry points), and a non-working curl example in BLOG_POST.md (the live API requires a signed
  x402 header and a `service_hash` field the example didn't include — replaced with the working
  Python SDK snippet).
- **CI coverage gate**: `pytest --cov-fail-under=70` had been red on every push since
  2026-07-04 (all tests passing, coverage stuck at ~67%) as new modules (`casper_client.py`,
  `db.py`, `event_monitor.py`) grew faster than their test coverage. Added 43 new tests covering
  previously-untested real logic: the `require_payment` x402 guard's full error-path matrix
  (missing/malformed header, insufficient amount, invalid signature, replay, method+path binding),
  `_run_node_script`'s error branches (timeout, malformed JSON, script-reported failure),
  `release`/`refund`/`dispute`/`resolve`/`commit_swap`/`reveal_swap` input validation and success
  paths, all 4 admin routes' (`set-release-cap`/`set-arbiters`/`emergency-freeze`, alongside the
  already-tested `configure-fee`) sandbox/live/upstream-failure paths, and the ed25519-tag pubkey
  and signature hex decoders in `arbiter_crypto.py`. Coverage is now 70.11% (376 Python tests, up
  from 333) with the gate met honestly, not by lowering the threshold or excluding files.

### Added (2026-07-04)
- **Advanced Escrow console panel** (`AdvancedEscrow.tsx`) — alt-token escrow (CSPR/CEP-18/CEP-78), linear streaming payouts, and commit-reveal atomic swaps, backed by `server/multi_asset.py`.
- **Arbitration console panel** (`Arbitration.tsx`) — AI dispute evidence analysis (`server/ai_arbitration.py`, Groq → NVIDIA → heuristic fallback) and VRF-based neutral arbiter election (`server/vrf_election.py`).
- **Identity Registry console panel** (`IdentityRegistry.tsx`) — first-ever HTTP API (`server/identity_registry_api.py`, prefix `/identity-registry`) for the previously-unreachable `server/identity_registry.py` DID reputation/staking module: register, get, update reputation, apply decay, slash, verify, search, stats.
- `GET /arbitration/history` endpoint (previously no way to read back past AI arbitration verdicts).

### Fixed (2026-07-04)
- `lib/api.ts`'s `getArbiters()` called a non-existent `/arbitration/arbiters` path; corrected to the real `/vrf/arbiters` endpoint and fixed its response field mapping.
- 4 backend bugs in `server/multi_asset.py` that made atomic swaps/streaming escrows non-functional (broken auth/token-adapter dependencies, fictional DB calls, a demo-identity bypass that blocked two-party swaps).
- `IdentityRegistry.update_reputation()` reset `reputation_score` to 0 on any call with zero new deals (e.g. a bare "touch"), instead of leaving it unchanged.
- `AgentIdentity.stake` had no non-negative constraint despite `slash()` assuming stake can't go below 0.
- 7 pre-existing failing tests in `tests/test_identity_registry.py` — all were test bugs (float-vs-int equality, `model_dump()` kwarg collisions, an unfounded ordering assumption under `asyncio.gather`, and second-resolution timestamp flakiness), not product bugs, once the `reputation_score` fix above was applied.
- `rate_limit_middleware`'s module-level `_rate_limits` dict (60 req/min per IP) was never reset between test files, causing cross-file 429s once the full suite grew large enough.

### Corrected (docs)
- The `[1.1.0]` entry below overclaimed a console tab and backend capabilities that did not exist in the repository. See inline corrections in that section.

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
- **Identity Registry** (`server/identity_registry.py`, ~250 LOC) — DID-based (`did:casper:<account>`) agent reputation/staking system: verification levels, cumulative reputation from completed/disputed deals, time-based reputation decay, stake slashing, and capability search. *(Corrected 2026-07-04: this entry previously claimed "Ed25519 credential verification and KYC-level attestation" and a console tab — neither existed anywhere in the codebase; the module had zero HTTP endpoints and no UI until the fix below. See the Unreleased section.)*

#### MCP Server
- Expanded from 15 to 24 tools — new tools for arbitration, risk scoring, and identity management
- Fixed duplicate tool definitions in MCP manifest

#### Console
- 4 new tabs: Advanced Escrow, Arbitration, Identity Registry, plus the pre-existing Risk Analysis and Contracts tabs. *(Corrected 2026-07-04: this line originally listed "Arbitration, Risk Analysis, Identity Registry, Contracts" as if all 4 shipped together — Risk Analysis and Contracts already existed, and Arbitration/Identity Registry did not exist yet at all. See Unreleased.)*
- AI dispute verdict history with confidence scores
- Real-time risk factor breakdown with visual bars
- Identity registration, reputation, decay, slashing, and verification status

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
- **Escrow contract deployed** to Casper Testnet at [`50ca3364...`](https://testnet.cspr.live/contract/50ca336428601e9920f3493112cad452c4b9359b1a88fd8893441b41c4498664)
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
