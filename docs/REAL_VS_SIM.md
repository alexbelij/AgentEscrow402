# AE402 — Real vs. Simulated

This document is the **honest ground-truth** of what runs against Casper
testnet (verifiable on-chain) vs. what is simulated in sandbox / heuristic
mode. It supersedes any marketing language elsewhere.

Two orthogonal axes govern behavior:

- **`SANDBOX` env** (`server/config.py: Config.sandbox`, default `True`
  in dev, set `SANDBOX=0` in prod) — when true, an in-memory
  `SandboxStore` (`server/sandbox.py`) is used instead of hitting the
  Casper RPC. Escrow lifecycle, reputation, and insurance are all
  simulated in memory. **No real testnet transactions are produced.**
- **Individual API keys** — even when `SANDBOX=0`, subcomponents may
  degrade to a lower fallback tier if their upstream is unconfigured
  (see AI arbitration chain below). This is by design, not a hidden
  simulation.
- **`AE402_STRICT=1`** (`server/config.py`, landed) disables every
  in-memory fallback below and forces the backend to return an HTTP 503
  instead of degrading silently — used for prod correctness proofs and
  CI verification runs.

## Current deployed contracts (authoritative source: `deploy-out/onchain.json`)

Do not hardcode contract hashes in this file — they change on redeploy.
The table below is regenerated from the manifest; always re-check
`deploy-out/onchain.json` directly for the live values a judge should
verify against `testnet.cspr.live`.

| Contract | Explorer |
|---|---|
| Core Escrow | https://testnet.cspr.live/contract/07527a37742b4da87c9cc38baf752f53b1525b53d0825269d9952a3813739ef1 |
| Escrow Manager (batch) | https://testnet.cspr.live/contract/bfa8c02cb3ab0f9d7bf03335f324973675200a597162e1e5fa4cb5a77dff675d |
| Insurance Pool | https://testnet.cspr.live/contract/ead90738d19ad7fcc88c9e079e12d8cf6d4fd09ddd3daafe565bf4fe4b95fff4 |
| VRF Arbiter | https://testnet.cspr.live/contract/78ae28702deeb2eadec573d95b870f68b928a82a3566e292ff33a9ae2c779c93 |
| Agent Identity Registry | https://testnet.cspr.live/contract/345c179cd28eae46bfcda5cd4d8b9192d631593f936af85ccfe3a2cece5c7b1f |
| MultiAssetEscrow (CEP-18) | https://testnet.cspr.live/contract/8080845bad4f12c4a720dd96551dc64d116208aa71e0ce1410b75afca8e8eb61 |
| CEP-18 test token (AETUSD) | https://testnet.cspr.live/contract/177ca5d88f72e1ca72fbe94a24ba34b03830dd1fe63d90d3d719cd6e6d4de754 |
| CEP-18 test token (AEMAT) | https://testnet.cspr.live/contract/2e319caa09768162144fed4c53f0259ef733ffd97e56a107064026022ac0377b |
| CEP-78 test NFT (AETNFT) | https://testnet.cspr.live/contract/c2dee0f1f40c3dae3f3106f70d69b8768d7426758b43040673f68e271f2bf70a |

The four contracts marked `key_fix_redeploy_note` in the manifest (Core
Escrow, Agent Identity Registry, MultiAssetEscrow, AEMAT test token) were
redeployed 2026-07-24 to fix a Casper 2.0 `Key::AddressableEntity`
compatibility bug (`into_hash_addr()` → `into_entity_hash_addr()`,
commit `a9d7071`). Package hashes are unchanged (in-place version bump);
only `contract_hash` / `deploy_hash` / `version` changed. Insurance Pool
was separately hardened 2026-07-19 (anti-replay tombstone).

---

## Component-by-component

| Component | Status | Details |
|---|---|---|
| Smart contracts on Casper testnet | ✅ REAL | Deployed and verifiable — see table above and `deploy-out/onchain.json` for authoritative hashes/deploy tx links/explorer URLs. |
| Escrow create / release / refund / dispute | ✅ REAL when `SANDBOX=0` | Full lifecycle via Casper RPC (`server/casper_client.py` → Core Escrow contract). Falls back to `SandboxStore` in-memory when `SANDBOX=1` — sandbox mode is signposted in every API response. |
| Batch escrow ops | ✅ REAL when `SANDBOX=0` | Via the Escrow Manager contract, session WASM `batch_funder.wasm`. |
| HTLC atomic swap (commit / reveal) | ✅ REAL | On-chain `commit_swap()` / `reveal_swap()` entry points on Core Escrow. |
| Multi-asset escrow (CEP-18 tokens AETUSD / AEMAT) | ✅ REAL | MultiAssetEscrow contract + the two CEP-18 test tokens listed above. |
| Insurance pool (fund / claim / withdraw) | ✅ REAL | Insurance Pool contract. Fund flow: user → escrow (deducts `insurance_fee_bps` = 200 bps = 2%) → pool. Claim replay guarded by a global `claimed_escrow_ids` tombstone (see `docs/INSURANCE_REPLAY_TESTS.md`). |
| Reputation scoring | ✅ REAL | On-chain via Agent Identity Registry (9 entry points incl. `register`, `stake`, `slash`). Sandbox mirror kept in `_reputation` dict for demo without RPC. |
| VRF-based arbiter election | 🟢 REAL / 🟡 FALLBACK | Real: VRF Arbiter contract, `select_arbiters()` on-chain, backend reads `selected_arbiters_csv` from `elections_dict`. Fallback: local cryptographic HMAC-based selection if the contract is unavailable, unconfigured, or every on-chain candidate is excluded by the arbiter-≠-dispute-party invariant. Fallback is deterministic, not "simulated" — see `server/vrf_election.py`. |
| AI arbitration (LLM verdict) | 🟢 REAL / 🟡 HEURISTIC FALLBACK | Provider chain (`server/ai_arbitration.py`): Groq (llama-3.1-8b-instant, free) → NVIDIA NIM (meta/llama-3.1-8b-instruct, free) → OpenRouter (free tier) → deterministic heuristic scoring. First three require API keys in env; heuristic always works. Never invents a verdict; may return `abstain` or escalate to human/VRF panel when signals are insufficient. |
| x402 payment verification | 🟡 PARTIAL | Payment header (`X-402-Payment`) validated in `server/middleware.py` — signature and nonce checked. When `SANDBOX=1` the corresponding CSPR transfer is simulated (no on-chain tx); when `SANDBOX=0` the transfer goes through Casper RPC. |
| Event streaming (SSE) | 🟢 REAL | Backend `_broadcast_event` + `StreamingResponse` in `server/app.py` push escrow state changes to subscribed clients (`/events`). |
| Telegram bridge | 🟢 REAL, off by default | Fans out the same SSE events to Telegram chats when `TELEGRAM_BOT_TOKEN` is configured; every mutation endpoint returns 503 otherwise. See `docs/TELEGRAM_BRIDGE.md`. |
| Rate limiting | 🟢 REAL | Per-IP token bucket in `server/middleware.py`. |
| DID (Decentralized Identity) registry | 🟢 REAL | `identity_registry_api.py` → on-chain Agent Identity Registry. |
| Insurance claim adjudication | 🟢 REAL / 🟡 MANUAL | Automated eligibility check via on-chain state; final payout requires admin approval today (`server/admin_api.py`). Full auto-payout is planned once dispute resolution proves stable at scale. |
| Frontend console | ✅ REAL | React/Vite (`frontend/`). Talks to production backend or sandbox via `VITE_API_URL`. Wallet integration via CSPR.click. |
| Python SDK + MCP server + LangChain tool | ✅ REAL | `sdk/` — MCP tools exposed to LLMs. All calls transit the same backend as the console. |
| Macaroon capability delegation | 🟡 BUILT, opt-in, not yet load-bearing | `sdk/macaroons.py` / `server/macaroon_api.py` — cryptographically sound HMAC-chain, but nothing in the codebase currently *requires* a verified macaroon for authority, and `POST /macaroons/mint` has no caller-identity check yet. See `docs/MACAROONS.md` "Known limitation". |
| Timelocked admin changes | 🟡 BUILT, additive | `sdk/admin_timelock.py` / `server/timelock_api.py` — raw `/admin/*` routes still bypass the timelock by design; see `docs/TIMELOCK_ADMIN.md` "Non-goals". |
| W3C VC 2.0 escrow receipts | ✅ REAL, fail-closed | `sdk/vc_receipts.py` / `server/vc_api.py` — issuance disabled without `VC_ISSUER_SEED` configured. See `docs/VC_RECEIPTS.md`. |

---

## What "sandbox mode" hides

When `SANDBOX=1`:

- No Casper RPC calls are made. `casper_client.py` is bypassed.
- Escrows live in `SandboxStore._escrows` (in-memory dict), reset on
  restart.
- Deploy hashes are synthetic (`sandbox-<hex>`), NOT valid on
  `testnet.cspr.live`.
- Insurance pool balance is in-memory. Fund/claim operations do not touch
  the on-chain pool.
- VRF election uses local HMAC selection over the seeded demo arbiters.

Every API response served in sandbox mode carries an `X-Sandbox: 1`
header, which the console reads to show its "sandbox mode" banner.

## What `AE402_STRICT=1` enforces

- Backend refuses to fall back to `SandboxStore` when a real RPC call
  fails. Returns HTTP 503 with a clear error message instead.
- Refuses to serve AI-arbitration verdicts from the heuristic fallback
  when no LLM provider is configured (returns HTTP 503 instead of a
  deterministic-but-degraded verdict).
- Refuses to run VRF election off-chain when the on-chain contract is
  unavailable (returns HTTP 503 instead of local HMAC fallback).

Effect: `AE402_STRICT=1` turns the entire backend into an all-real-or-die
mode, useful for prod correctness proofs and for CI verification runs.

---

_Ground-truth check: `deploy-out/onchain.json` (contract hashes),
`server/config.py` (env flags), `server/ai_arbitration.py` (LLM chain),
`server/vrf_election.py` (VRF fallback), `server/sandbox.py`
(in-memory store), `docs/ARCHITECTURE.md` (system diagram)._
