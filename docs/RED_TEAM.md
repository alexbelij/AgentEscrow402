# AgentEscrow402 — Red-Team Self-Audit

Methodology: each row was checked against actual source, not assumed. Verdicts:
**RESIST** = mitigated in code today. **PARTIAL** = mitigated but with a known gap.
**OPEN** = not mitigated, needs a fix before submission.

Original audit 2026-07-18; re-verified 2026-07-24 against the current
codebase (post Key-fix redeploy, post insurance-replay fix, post Telegram
bridge).

| # | Attack Vector | Category | Result | Evidence / Notes |
|---|---|---|---|---|
| 1 | Unauthorized escrow release/cancel | Contract | RESIST | `escrow/src/main.rs::release/refund` — `caller == creator/counterparty` check, reverts `ERR_UNAUTHORIZED` otherwise |
| 2 | Duplicate escrow via replayed service hash | Contract | RESIST | `escrow()` checks dictionary for existing `service_hash`, reverts `ERR_DUPLICATE_HASH` |
| 3 | Commit/reveal front-running on `commit_swap`/`reveal_swap` | Contract | RESIST | preimage checked against stored hash; `ERR_ALREADY_COMMITTED` / `ERR_ALREADY_REVEALED` guards re-entry |
| 4 | Integer overflow/underflow on balances | Contract | RESIST | `test-token` uses `checked_add`/`checked_sub`; `multi-asset-escrow` fee math uses `saturating_*`/`checked_deduct_fee` (only raw `.unwrap()` in the whole contract tree is inside a `#[test]` module, not production code) |
| 5 | Unauthorized insurance-pool withdrawal | Contract | RESIST | `withdraw()`/`claim()` gated by `require_arbiter_quorum` (multi-sig threshold on arbiter pubkeys), not caller-only |
| 6 | Frozen-pool bypass (draining after emergency freeze) | Contract | RESIST | `require_not_frozen()` guard called at the top of every mutating entry point (`escrow`, `release`, `commit_swap`, `reveal_swap`, `refund`) |
| 7 | Arbiter over-registration / cap bypass | Contract | RESIST | `require_arbiter_cap_approval` checks registered-arbiter count against on-chain threshold before allowing new registration |
| 8 | Panic-based DoS (malformed input crashes the contract) | Contract | RESIST | Every fallible call site outside tests uses `unwrap_or_revert()` / `unwrap_or_revert_with()`, which converts to a clean revert, not a panic |
| 9 | SQL injection via agent ID / escrow ID | Backend | RESIST | All queries go through SQLAlchemy ORM with parameterized params, no raw string concatenation found |
| 10 | Secrets committed to repo | Backend/CI | RESIST | TruffleHog secret-scan on push+PR; manual grep of `server/` found no embedded keys. Re-verified 2026-07-24 for the Telegram bridge PR — token is env-only, redacted from `__repr__`, never logged. |
| 11 | API rate-limit bypass under demo/judge load | Backend | PARTIAL | In-memory per-IP limiter (60 req/min) in `app.py` — resets on process restart, bypassable via IP rotation/proxy, and not tied to agent identity. Acceptable for a hackathon demo, but call out as known limitation rather than "solved". Unchanged as of 2026-07-24. |
| 12 | NowNodes RPC outage cascading into request-level latency | Backend | PARTIAL | Fallback chain CSPR.cloud → NowNodes → official node exists (`casper_client.py`), but no circuit breaker — a 429 burst re-triggers the full fallback sequence on every request instead of short-circuiting past a known-down provider for N seconds. Unchanged as of 2026-07-24 — still queued, not yet fixed. |
| 13 | CORS misconfiguration enabling credentialed cross-origin abuse | Backend | RESIST | `allow_origins=["*"]` is set, but `allow_credentials` is **not** set to `True` — browsers won't attach cookies/credentials to wildcard-origin requests, so this is a safe combination for a public read/write API with bearer-style auth, not a cookie session |
| 14 | Front-running arbiter selection to bias verdicts | Contract | RESIST | VRF-based arbiter selection (`vrf-arbiter` contract); `ABSTAIN` verdict path added for conflict-of-interest cases |
| 15 | Repeat insurance claim on the same escrow_id after cooldown | Contract | **RESIST (fixed 2026-07-19, re-verified 2026-07-24)** | Was OPEN at the 2026-07-18 audit. Fixed: a global `claimed_escrow_ids` dictionary now rejects any resubmission of an already-claimed `escrow_id`, independent of the per-caller cooldown; the tombstone is written before payout and rolled back atomically on revert (CEI pattern). Re-verified this session: found and fixed a real drift where the mirrored test error-code constant (`11`) didn't match the actual contract constant (`9`) — the test was passing but not actually exercising the real revert path. Added `const_parity_tests.rs` to catch this class of drift going forward, plus a dedicated boundary test (`replay_after_cooldown_elapsed_still_rejected_by_tombstone`) proving the exact property this row describes. Both are now wired into CI (`cargo test -p insurance-pool --lib`). |
| 16 | Anyone can register an unauthenticated Telegram subscription | Backend | PARTIAL (new, 2026-07-24) | `POST /telegram/subscribe` has no caller-identity check — any client that knows the API URL can register an arbitrary `chat_id` to receive escrow lifecycle events. Accepted as low-severity: the underlying escrow data is already public via the unauthenticated SSE stream (`/events`), so this does not expose anything not already public. Documented in `docs/TELEGRAM_BRIDGE.md`. |
| 17 | Macaroon minting has no caller-identity check | Backend | PARTIAL (carried over, unchanged) | `POST /macaroons/mint` lets any caller mint a token claiming any capability string. Currently inert — nothing else in the codebase trusts a verified macaroon for real authority — but flagged as a known limitation in `docs/MACAROONS.md` before this becomes load-bearing. |

## Summary

0 production-code panics found across the contract tree. All fund-moving
entry points have explicit caller/quorum checks. Row #15 (the one real
fund-safety OPEN item from the original audit) is now fixed, tested, and
CI-enforced. The remaining PARTIAL items (#11 rate-limit durability, #12
RPC circuit breaker, #16 Telegram subscribe auth, #17 macaroon mint auth)
are real but lower severity — not fund-safety risks — and are
transparently documented rather than silently left as gaps.
