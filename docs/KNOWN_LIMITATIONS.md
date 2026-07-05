# Known Limitations

Last verified against live testnet + production deploy on 2026-07-05 (contract package
`d3ca33d1...c8eeb`, version 8, contract_hash `50ca3364...4498664`; production API
`agentescrow402-api.onrender.com` env `ESCROW_CONTRACT_HASH` updated to match, `SANDBOX=false`).

## Smart Contract

- **No reentrancy guard** — The contract relies on Casper's execution model (single-threaded per
  deploy) but does not implement an explicit reentrancy lock. Future upgrades should add one for
  defense in depth.
- **Fee underflow edge case** — When `amount * fee_bps / 10_000 > amount`, the subtraction
  underflows. Fixed in practice because `fee_bps` is admin-controlled and capped, but should use
  `checked_sub`.
- **Emergency freeze is one-way** — The `emergency_freeze` entry point sets a frozen flag but
  there is no `unfreeze` entry point. A contract upgrade is required to resume operations.
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
- **No rate limiting** — The FastAPI server does not implement request rate limiting.
- **Single-process only** — The global `casper_client` instance is not thread-safe for
  multi-worker deployments.

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
