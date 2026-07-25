# Insurance-pool anti-replay tests

**Status:** shipped in `feat/ae-odra-insurance-replay-test`. Closes the P0
Gate 1 gap "Casper/Odra negative integration test for insurance replay is
missing" from `AE402_FINAL_TASKS_V2.md`.

## What we test

`contracts/tests/src/insurance_replay_tests.rs` — 8 tests, all against the
exact message-binding rules of
`contracts/insurance-pool/src/main.rs::{build_claim_message,
build_withdraw_message}` and the DICT_CLAIMED_ESCROWS tombstone.

The insurance-pool contract is `#![no_std] #![no_main]` and only builds
for wasm32; its host imports (runtime/storage/system, `crypto::verify`)
can't be executed outside a Casper VM. The tests follow the pattern
already used by `integration_tests.rs` and `property_tests.rs`: mirror
the exact message-binding and tombstone logic on the host side, so we
can drive the negative paths (bad-message rejections, replay-after-
mutation) that a positive testnet deploy never exercises.

## Attack surface exercised

| # | Test | Attack modelled | Contract-side defence relied on |
|---|------|------------------|---------------------------------|
| 1 | `same_caller_identical_replay_rejected_by_tombstone` | Alice claims escrow X once, tries again on the same tuple. | `DICT_CLAIMED_ESCROWS` tombstone written before external transfer (A1 hardening). |
| 2 | `cross_caller_replay_fails_message_binding` | Mallory rebroadcasts Alice's arbiter signatures with `mallory` as caller. | `build_claim_message` binds `caller_str` — sig ceases to verify. Tombstone not written, so Alice's real claim stays available. |
| 3 | `cross_escrow_replay_fails_message_binding` | Attacker reuses sigs at a different `escrow_id`. | `escrow_id` inside the signed message. |
| 4 | `cross_amount_replay_fails_message_binding` | Attacker rebroadcasts sigs asking for a larger amount. | `amount` inside the signed message. |
| 5 | `withdraw_nonce_advances_message` (positive control) | Two legitimate withdraws of the same amount need two distinct signature sets. | `KEY_WITHDRAW_NONCE` — nonce read, message built with it, nonce advanced. |
| 6 | `withdraw_replay_with_stale_nonce_fails` | Attacker rebroadcasts a signed withdraw after the nonce has advanced. | Same message layout: post-advance the message being verified no longer matches what arbiters signed. |
| 7 / 8 | positive controls | Confirm the harness itself doesn't over-reject: valid sigs pass, unregistered signers are silently ignored. | Sanity checks so a future refactor of the mirror can't quietly pass every negative test. |

## What the tests do NOT claim

- They don't re-verify Ed25519. That's `casper-types` upstream territory
  and would just re-test a dependency.
- They don't exercise coverage caps, pool-balance checks, or cooldown —
  those are property-tested elsewhere and are orthogonal to replay.
- They can't catch bugs where the on-chain `build_*_message` function
  drifts to a different string format from what this file mirrors — if
  you touch `insurance-pool/src/main.rs::build_claim_message` or
  `build_withdraw_message`, update the mirrors in
  `insurance_replay_tests.rs`. The file's docstring calls this out.

## Running

```bash
export PATH="$HOME/.cargo/bin:$PATH"
cd contracts
cargo test -p tests --test insurance_replay_tests
# 8 passed
```

Full contract-workspace test run:

```bash
cd contracts
cargo test -p tests
# integration_tests: 31 passed
# property_tests: 9 passed
# insurance_replay_tests: 8 passed
# agent_identity_registry_property_tests: N passed
```

## Where it lives on the plan

`AE402_FINAL_TASKS_V2.md` → P0 Gate 1 → "Odra/Casper testnet regression"
originally required a *live testnet* deploy. This host-mirror harness
covers the negative-path invariants the testnet run can't cover
economically (an attacker mid-tx replay isn't observable on testnet
without a controlled Ed25519 keypair rotation). The testnet regression
that Victor owns still stands as the E2E complement.

## AE-2 closure decision (2026-07-25)

**Status: closed as-is for the hackathon submission.** Agent2's audit
(2026-07-24, AE-2) flagged this coverage "Partial" — the CEI/tombstone
logic and the host-mirror suite above (plus
`insurance_cooldown_replay_e2e_tests.rs`) are solid, but there is no
real Casper VM on-chain regression test: `casper-engine-test-support`
is commented out in `contracts/tests/Cargo.toml`.

**Decision:** sufficient for the hackathon submission, closed as-is.

**Rationale:**

- The invariant under test — does a tombstoned escrow survive a
  replay attempt — is a pure state-machine transition, fully covered
  by the host-side mirror (table above).
- Standing up a real VM harness in the final hours before a hard
  deadline is a build/toolchain risk this repo has already hit once
  (nightly pin + bulk-memory-ops, see `docs/DEPLOYMENT_LESSONS.md`),
  for no visible judge-facing payoff versus the existing suite.
- This is a deliberate, documented trade-off, not an oversight.

**Not closed — tracked separately as a pre-mainnet gate:** a real
on-chain Casper VM regression test for this same tombstone/replay
invariant, compiled from the actual `insurance-pool.wasm` and run
through `LmdbWasmTestBuilder` (the current API name — `casper-types`
6.x/`casper-engine-test-support` 8.x renamed the old
`InMemoryWasmTestBuilder` from earlier SDK generations). This is
**required** before any redeploy of the insurance-pool contract that
will hold real funds. See the deploy-gate note in `docs/DEPLOY.md` /
`docs/OPERATOR_RUNBOOK.md` once that harness lands.

## Real on-chain VM regression suite — landed (2026-07-25)

The pre-mainnet gate above is now closed: `contracts/tests/src/insurance_replay_onchain_vm_tests.rs`
drives the real, compiled `insurance-pool.wasm` through
`LmdbWasmTestBuilder` (a genuine Casper execution engine instance, not
a mirror). Three scenarios, all green:

- **A — happy path**: a valid `claim()` succeeds; pool purse balance
  drops by exactly the claimed amount.
- **B — replay (the AE-2 invariant)**: the identical deploy
  (escrow_id, caller, amount, arbiter signatures) submitted a second
  time reverts with `ApiError::User(9)` (`ERR_ESCROW_ALREADY_CLAIMED`)
  inside the real execution engine, and the pool balance is unchanged.
- **C — cross-escrow replay**: the same arbiter signatures/pubkeys
  reused against a *different* escrow_id fail message-binding —
  `ApiError::User(8)` (`ERR_INSUFFICIENT_ARBITER_SIGS`) — before the
  tombstone dictionary is even touched for that escrow_id.

Marked `#[ignore]` (heavy VM build + genesis); run explicitly or via
the `insurance-pool-vm-regression` nightly CI job
(`.github/workflows/contract-audit-nightly.yml`), never in the PR-gate
`ci.yml`. Deploy-gate line: `docs/DEPLOY.md` § step 3 (Insurance Pool).

### Real production bug this suite caught

Standing up the real-VM suite immediately caught a bug the host-mirror
suite above structurally could not: **every first-ever `claim()` call
reverted with `ERR_ESCROW_ALREADY_CLAIMED` (error 9), even for a
brand-new, never-touched `escrow_id`.**

Root cause: `claim()`'s first (tombstone) precondition check called the
shared `logic::check_claim_preconditions` with dummy zero arguments —
`check_claim_preconditions(already_claimed, 0, 0, U512::zero(), U512::zero())`
— reasoning that with `already_claimed` as the only "live" input, the
only reachable rejection was `ClaimRejection::AlreadyClaimed`, guarded
by a `debug_assert!` to enforce that invariant. But
`check_claim_preconditions`'s cooldown check runs *before* it would
ever return `Ok(())`: `now < last_claim_timestamp.saturating_add(COOLDOWN_SECONDS)`
evaluates `0 < 0 + 86_400 = true` whenever `already_claimed = false` —
so this call returned `Err(Cooldown)`, never `Ok(())`, on literally
every fresh claim. `debug_assert!` is compiled out entirely in a
release wasm build (it's a no-op outside debug builds), so the
mismatch — `Cooldown` reached where only `AlreadyClaimed` was assumed
possible — was silently swallowed, and the code fell through to
`runtime::revert(ApiError::User(ERR_ESCROW_ALREADY_CLAIMED))`
regardless of which rejection actually fired.

The host-mirror suite (`insurance_replay_tests.rs`,
`logic.rs`'s own unit tests) could not have caught this: they test
`check_claim_preconditions` directly with meaningful, non-dummy
arguments, never reproducing the specific `(already_claimed, 0, 0, ...)`
call shape `claim()`'s wasm entry point actually made. Only driving the
real compiled entry point through a real execution engine surfaced it.

**Fix** (`contracts/insurance-pool/src/main.rs::claim()`): the
tombstone check no longer delegates to `check_claim_preconditions` at
all — it checks `already_claimed` directly:

```rust
if already_claimed {
    runtime::revert(ApiError::User(ERR_ESCROW_ALREADY_CLAIMED));
}
```

The second, real `check_claim_preconditions` call further down in
`claim()` (with real `claims_record.0`/`now`/`amount`/`pool_balance`,
and hardcoded `already_claimed = false` since the tombstone was
already checked) is unchanged and still correctly handles
cooldown/coverage/balance rejections.

Separately, the VM test itself needed `ExecuteRequestBuilder::with_block_time`
set past `COOLDOWN_SECONDS` (genesis blocktime is 0, and a brand-new
caller's default `last_claim_timestamp` is also 0 — without advancing
blocktime, a first-ever claim legitimately trips the real cooldown
check too, which a real chain's non-zero blocktime would never hit).
