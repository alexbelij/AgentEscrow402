# Changelog

All notable changes to AgentEscrow402 are documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Version numbers follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

*Delivered the console/backend work the 1.1.0 entry below prematurely claimed as shipped.*

### Added (2026-07-17)
- **Red-team self-audit** (`docs/RED_TEAM.tmp`) — 15 attack-vector matrix with mitigation status; documents the one real gap (insurance-pool replay under specific reorg conditions) alongside the resistances (reentrancy, integer overflow, unauthorized cancellation, front-running, injection). Commit `15b6c44`.
- **verify.sh** — single-command proof of on-chain deployment: checks all 8 contracts exist on Casper testnet (via CSPR.cloud), API `/health`, escrow round-trip, frontend serving, and `onchain.json` parity. Commit `82d950c`, merged in `a7ab56e`.

### Added (2026-07-15)
- **RPC fallback chain** — CSPR.cloud → NowNodes → official node; escrow lifecycle survives any single provider outage (`server/casper_client.py`). Commit `808606b`, merged in `1c03529`.
- **`ABSTAIN` verdict** for arbiter conflict-of-interest — arbiters return `abstain` instead of a coerced vote when a party is a party (`server/vrf_election.py`). Commit `ce3db9c`.
- **`X-Request-ID` middleware** for request tracing across backend logs (`server/middleware.py`). Commit `4c37b5e`.
- **`/health`** returns `mode` (sandbox|live) and version bumped to `0.3.0`. Commit `0433916`.

### Added (2026-07-14 batch)
- `deploy-out/onchain.json` filled with CSPR.cloud-verified deploy hashes for all 8 contracts (`f31bd39`).
- `SECURITY.md` self-audit table (`3c6bb42`).

### Fixed (2026-07-14 batch)
- `checked_sub` / `checked_add` in test-token `transfer` and `transfer_from` — prevents integer underflow on custody-compatible tokens (`589d4a0`).
- Root `/` redirect to `/health` for Render probe (`c63ed61`).
- Pydantic v2 `model_` namespace warning suppressed via `ConfigDict` (`07b5a30`).
- Secret-scan workflow — removed `base`/`head` that fail on push events (`7b7b07c`).

### Added (2026-06-14 frontend polish batch, merged 2026-06-14 as `b165033`)
- Complete favicon set (16/32/apple-touch), sitemap.xml with all console routes, status badges, submission checklist table in README, skeleton loaders on Agents/Escrows tabs, CONTRIBUTING.md, frontend CI workflow, secret-scan workflow, Dependabot, `.well-known/casper-agent-card.json` for agent discovery, Telegram links in navbar and footer, ExplorerLink hardening (validation + `noopener`), wallet spinner during CSPR.click signing, confirmation modals for destructive actions, empty states, copy-to-clipboard utility + CopyButton, console.error suppression in production, real generated demo signature (no more placeholder), 404 page with console link and image fallback.

### Fixed (2026-06-14)
- Integer floor division in insurance-fee calculation avoids float precision loss (`43ed005`, closes #1).


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

### Added
- **Advanced Escrow console panel** (`AdvancedEscrow.tsx`) — alt-token escrow (CSPR/CEP-18/CEP-78), linear streaming payouts, and commit-reveal atomic swaps, backed by `server/multi_asset.py`.
- **Arbitration console panel** (`Arbitration.tsx`) — AI dispute evidence analysis (`server/ai_arbitration.py`, Groq → NVIDIA → heuristic fallback) and VRF-based neutral arbiter election (`server/vrf_election.py`).
- **Identity Registry console panel** (`IdentityRegistry.tsx`) — first-ever HTTP API (`server/identity_registry_api.py`, prefix `/identity-registry`) for the previously-unreachable `server/identity_registry.py` DID reputation/staking module: register, get, update reputation, apply decay, slash, verify, search, stats.
- `GET /arbitration/history` endpoint (previously no way to read back past AI arbitration verdicts).

### Fixed
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
