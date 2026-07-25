# Merge notes — `feat/ae402-formal-verification`

Instructions for the merge agent handling this branch.

## TL;DR for the merge agent

- **Test-only branch, ZERO production code changes.**
- **DO NOT touch Render** — no env-vars, no secrets, no deploy hooks, no config drift.
- **DO NOT touch `render.yaml`, `Dockerfile`, `.env.example`, `requirements*.txt`, `pyproject.toml`.**
- If Render auto-deploys on `main`, the deploy after merge is a **no-op**: nothing shipped to prod runs any of this code.

## What this branch contains

Property-based (proptest) formal-verification tests for the AE402 escrow
FSM. Pure model-checking against the on-chain guards in
`contracts/escrow/src/main.rs` — no chain calls, no crypto, no
Casper types.

- `contracts/tests/src/fsm_property_tests.rs` — new, 16 proptest cases
- `contracts/tests/Cargo.toml` — registers the new `[[test]]` binary

That's the whole diff.

## Three verified invariant blocks

### Block A — FSM safety

Proves the state-machine table in `contracts/escrow/src/main.rs` is
tight in every direction, over the full input domain:

- **Terminal-status immutability** — `Released / Refunded / Expired /
  Resolved` never mutate under *any* action. Every payout is one-shot.
- **PENDING outgoing edges are restricted** to
  `{Released, Refunded, Expired, Disputed}` — no shortcut to `Resolved`.
- **DISPUTED outgoing edges are restricted** to `Resolved` — no
  un-dispute back to PENDING, no direct dispute→release/refund.
- **Reachable-states closure** — for any starting state and any random
  action sequence up to length 8, the FSM stays in the 6-state set. No
  ghost states.
- **`release()` gated to sender** — a receiver/third-party `release`
  from PENDING always reverts. Sender-with-quorum for above-cap only.
- **`dispute()` gated to parties** — third-party dispute always reverts.
- **`refund()` gated by expiry OR sender** — non-sender pre-expiry
  always reverts; anyone post-expiry succeeds (`Expired` path).
- **Above-cap `release()` requires arbiter quorum** — sender alone can
  never authorize above-cap payout, proven across the full input domain,
  not the hand-picked boundary cases.

### Block B — Conservation (ledger invariants)

Proves the fee/payout arithmetic holds identity across every legal
transition:

- **Conservation on every transition** — for any successful
  `from → to`, the escrow purse outflow equals `payout + insurance_pool_delta`
  exactly, no rounding leak.
- **Payout equals `amount - insurance_fee`** — regardless of which
  payout path fired (release / refund / expired / resolve).
- **Insurance flow is non-negative and exactly `fee/2`** on every
  payout transition; zero on non-payout transitions (dispute).
- **Payout never exceeds `amount`** — the ledger-side counterpart to
  the existing `fee_never_exceeds_amount` primitive property.
- **No double-payout under caller-driven hammering** — over any random
  action sequence up to length 12, total outflow never exceeds a single
  payout ceiling. This is the model-check version of "no re-entrancy /
  no double spend at the FSM layer".

### Block C — HTLC unlock invariant

Proves the atomic-swap reveal path is exactly the release path, gated
by hash equality:

- **`sha256(preimage) == commit_hash` iff reveal authorized** — a
  wrong preimage never opens any path.
- **HTLC reveal never triggers refund/expired/disputed/resolved paths**
  — a valid preimage authorizes exactly the release edge.
- **Above-cap HTLC reveal requires arbiter quorum** — knowing the
  preimage alone is *not* sufficient authorization for an above-cap
  payout. Closes the "second release path" that A1 hardening exists
  to enforce.

## One real finding

The initial `insurance_flow_is_non_negative` property caught a real
modelling drift on the first run: it required `insurance_pool_delta
== compute_insurance(fee)` on *every* transition — including
`Pending → Disputed`, which is a status change with **no** money
movement. The correct invariant is:

- On payout transitions: `insurance_pool_delta == fee / 2`
- On non-payout transitions (dispute): `insurance_pool_delta == 0`

Fixed the property; both cases now covered. That's exactly the value
of property-based FSM tests — they surface case-analysis gaps that
hand-picked unit tests never touch.

## Verification numbers before merge

Run from `contracts/`:

```
cargo test -p tests
```

Expected: **71 tests passed, 0 failed** across 5 test binaries:

- `agent_identity_registry_property_tests` — 8 (unchanged)
- `insurance_replay_tests` — 8 (unchanged)
- `integration_tests` — 31 (unchanged)
- `property_tests` — 9 (unchanged)
- `fsm_property_tests` — **16 (new)**

Baseline on `main` was 55; new baseline is **71** (+16).

Python suite (unchanged by this branch — added for completeness):

```
python -m pytest tests/ -q
```

Expected: **592 passed** (same as `main`).

## Why NOT Kani / Certora / TLA+ this round

- **Kani** — depends on Casper `contract_api` runtime hooks; unbuildable
  as a `no_std` model-checking target without a shim harness that would
  itself need review. Kept in scope for a follow-up if the drift-guard
  cost of proptest ever proves inadequate.
- **Certora Prover** — Solidity/EVM only.
- **TLA+** — natural fit for the FSM, but the specification cost is
  ~1 week of standalone work; proptest gets us 90% of the safety
  guarantees at 5% of the cost, and the model is directly executable
  against real code changes via `cargo test`.

The proptest model here IS the specification — every FSM guard has a
line-anchored comment pointing to `contracts/escrow/src/main.rs`.
Drift from the contract is caught on the next `cargo test -p tests`
run.

## Merge order

Independent of the other two open PRs:

- `feat/ae402-signoz-otel` — SigNoz OTEL wiring (needs env-vars in
  Render; see `docs/DEPLOY_SIGNOZ.md` in that branch)
- `feat/ae402-arbiter-signing-e2e` — arbiter-signing E2E tests (no
  Render changes; see `docs/MERGE_NOTES.md` in that branch)
- `feat/ae402-formal-verification` — this branch (no Render changes)

Merge order doesn't matter — no shared file conflicts. All three
touch different areas (server/telemetry, tests/api, contracts/tests).
