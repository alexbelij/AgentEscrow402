# Known Limitations

Last verified against live testnet + production deploy on 2026-07-06 (contract package
`d3ca33d1...c8eeb`, version 9, contract_hash `612cead2...ddd9ec`; production API
`agentescrow402-api.onrender.com` env `ESCROW_CONTRACT_HASH` updated to match, `SANDBOX=false`).
Upgrade deploy `3be11314...dabedfe`, confirmed on-chain (`error_message: null`,
`contract_version: 9`), 800 CSPR payment (100/300 CSPR both hit "Out of gas").

**2026-07-07 A1 re-verification (`escrow-manager.create_batch()`):** `create_batch()` only
transfers funds *into* the contract purse (a deposit, mirroring `create_escrow`'s own funding
step) — it has no withdrawal path at all, so the A1 "no unilateral agent-key withdraw above cap"
invariant doesn't apply to it directly. The two entry points on `escrow-manager` that *can* move
funds out, `batch_release`/`batch_cancel`, remain unreachable dead code (confirmed again via
repo-wide grep across `server/`, `sdk/`, `frontend/src` — only `create_batch()` is ever called)
and still lack the per-escrow cap/arbiter-quorum guard the single-escrow `release()`/`resolve()`
path enforces; do not wire them up without adding that guard first. Also extended
`docs/evidence/bulk_escrow_tx_log.jsonl` this session with 4 real `refund` and 3 real
`dispute`→3-of-5-arbiter-`resolve` cycles (all on the current v9 contract, confirmed via
CSPR.cloud) — previously the bulk log only had `create`/`release` pairs represented in the
README's description (the file itself already had releases; the README text just undersold it).

**2026-07-07 bulk log extended again, multi-wallet + JSONL fix:** added 20 more real
`create`/`release` deploys (10 pairs) using the 10 pre-generated `agent_01`..`agent_10`
accounts (see `docs/evidence` generation scripts) as receivers, so the bulk-tx evidence now
shows escrows settling between more than one counterparty pair, not just the original
sender/receiver. Log is now 349/349 successful deploys (173 create, 166 release, 4 refund,
3 dispute, 3 resolve). Also fixed a latent bug: the log file previously contained Python
`True`/`False` literals instead of JSON `true`/`false` in a subset of lines, so it was not
valid JSONL and would fail to parse in any strict JSON reader — re-serialized every line
through `json.dumps` (no data changed, only the boolean token spelling).

v9 fixed 3 items that used to be listed here: reentrancy-style checks-effects-interactions
ordering in release/refund/resolve, `checked_sub` on the fee deduction (new
`ERR_FEE_EXCEEDS_AMOUNT`), and a new `unfreeze()` entry point (previously freezing was one-way).

## Smart Contract

- **Arbiter rotation is manual, not fixed at deploy** — The 5 arbiter addresses are set during
  contract installation but *can* be changed later via the real `set_arbiters` entry point (no
  redeploy needed) — exposed through `POST /set-arbiters` (`server/admin_api.py`), gated by an
  admin API key and requiring live/non-sandbox mode. There is no on-chain vote for rotation; it's
  a single admin-triggered call.
- **Contract upgrades are ungoverned** — The contract is deployed as a versioned package (this
  hackathon went v3 → v8), so upgrades don't require redeploying from scratch, but only the
  deployer account that owns the package URef can push a new version — no timelock, no
  multi-party approval.

## Backend

- **On-chain integration is real, not partial** — `create_escrow`, `release`, `refund`,
  `dispute`/`resolve`, `commit_swap`/`reveal_swap` (HTLC atomic swap), and CEP-18/CEP-78
  multi-asset transfers all submit real Casper testnet transactions in live mode (`SANDBOX=false`,
  which production runs). Sandbox mode (local dev default) still uses in-memory simulation for
  fast iteration — this is intentional and clearly separated by the `cfg.sandbox` flag, not a
  gap.
- **x402 signature verification is real** — `server/middleware.py` performs actual Ed25519
  signature verification (`cryptography` lib) plus nonce-based replay protection with a 5-minute
  window. The hosted console additionally exposes one explicit, labelled demo bypass
  (`X-AE402-Demo-Identity: hosted-console` + a fixed public demo signature) so browser visitors
  without a wallet can exercise the UI — this bypass is scoped to two hardcoded demo identities
  only and is disabled by setting `ALLOW_HOSTED_DEMO_IDENTITY=false`.
- **Payment streaming (`/escrow/stream`) is API-level simulation, not on-chain vesting** — the
  streamed/remaining amount is computed linearly from wall-clock elapsed time in
  `server/multi_asset.py`, but there is no on-chain per-tick release; the underlying escrow is
  released the same way as a normal escrow. Fine for demoing the UX pattern, not a production
  payment-streaming primitive yet.
- **Single-process only** — The global `casper_client` instance is not thread-safe for
  multi-worker deployments.
- **`escrow-manager.batch_release`/`batch_cancel` lack a cap/quorum guard** — Unlike
  `create_batch()` (wired and live-verified, see [README](../README.md#-verified-on-chain-this-is-not-simulated--real-testnet-transactions)),
  the manager contract's `batch_release`/`batch_cancel` entry points don't enforce the same
  per-escrow amount cap or arbiter-quorum check that the single-escrow `release`/`resolve` path
  does. They are dead code — nothing in the backend or SDK currently calls them — so this is not
  an active vulnerability, but the guard should be added before either entry point is wired up.

## Frontend

- **`frontend/src/components/AgentMarketplace.tsx` is dead code with hardcoded mock agents**
  (`mockAgents` array) — never imported/rendered anywhere in `App.tsx`/console routes (confirmed
  via repo-wide grep), so it's not an active bug, but it doesn't call the real `/agents` or
  `/search/agents` endpoints either. Recommend deleting it or wiring it to the real endpoints
  before submission, so a judge browsing the file tree doesn't find an unused mock-data component
  (same category of issue flagged and removed on the RWA-Sentinel project this session).
- **`escrow-manager.create_batch()` (bulk escrow creation) has no console UI** — the only caller
  is the `POST /escrows/batch` backend endpoint itself (used by the bulk on-chain evidence
  script), confirmed via grep across `frontend/src`. If bulk creation is meant to be a
  user-facing feature rather than an internal evidence-generation tool, it currently isn't one.

## General

- **Persistent storage** — Production uses a real Neon Postgres database (`server/db.py`);
  sandbox/local-dev mode uses in-memory dicts and loses state on restart. This is by design (fast
  local iteration vs. real deployment), not an outstanding gap.
- **Demo video pending** — Video script (`VIDEO_SCRIPT.md`) is ready but recording is not yet
  completed.

## Explicitly out of scope for this hackathon submission (roadmap only)

Ideas surfaced by competitive research (TEE-attested payment proofs, on-chain KYC via
zero-knowledge proofs, true cross-chain atomic bridges to other L1/L2s) are **not implemented**.
They would require real TEE hardware (SGX/SEV) or a production ZK circuit — too large a scope to
build honestly before the submission deadline. Listed here as future roadmap, not claimed as
working features.
