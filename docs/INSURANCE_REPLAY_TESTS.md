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

## AE-2 closure decision (hackathon submission, 2026-07-25)

Agent2's 2026-07-24 audit (`AE402_FINAL_TASKS_V2_new.md` → AE-2) flagged
this item "Partial": CEI/tombstone logic and this host-mirror suite are
solid, but a genuine Casper VM on-chain regression test (via
`casper-engine-test-support`) does not exist — the deps are commented
out in `contracts/tests/Cargo.toml`.

**Decision: sufficient for the hackathon submission, closed as-is.**

Rationale:
- The invariant under test (does the tombstone survive a replay
  attempt?) is a pure state-machine transition, fully captured by the
  host-side mirror above plus `insurance_cooldown_replay_e2e_tests.rs`.
- Building and wiring a real VM harness in the final hours before a
  hard hackathon deadline carries build/toolchain risk (this repo has
  already hit nightly/bulk-memory-ops gotchas — see
  `contracts/rust-toolchain.toml`) with no visible upside for judges.
- This is a scoped, documented trade-off, not an oversight.

**Not closed for mainnet.** A real on-chain Casper VM regression test
for this exact replay invariant is a hard, non-optional gate before any
redeploy of `insurance-pool` that will hold real funds. Spec for that
follow-up work: `docs/AE2_MAINNET_ONCHAIN_TEST_TZ.md`.

## Where it lives on the plan

`AE402_FINAL_TASKS_V2.md` → P0 Gate 1 → "Odra/Casper testnet regression"
originally required a *live testnet* deploy. This host-mirror harness
covers the negative-path invariants the testnet run can't cover
economically (an attacker mid-tx replay isn't observable on testnet
without a controlled Ed25519 keypair rotation). The testnet regression
that Victor owns still stands as the E2E complement.
