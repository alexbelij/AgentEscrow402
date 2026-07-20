# Escrow lifecycle FSM (AE-14)

Every hosted state transition on an AE402 escrow flows through a single
deny-by-default finite state machine in
[`server/escrow_fsm.py`](../server/escrow_fsm.py). This document is the
contract: what states exist, what actions move between them, and what a
client sees when it attempts a disallowed one.

## Why deny-by-default

The prior implementation used ad-hoc `if status != "pending"` checks
inside each entry-point in `server/sandbox.py`. That style is
error-prone:

- adding a new state means auditing every guard;
- a typo in a status string silently downgrades the check;
- the on-chain contract's allow-list is not mirrored in Python, so a
  hosted API could accept transitions the contract would reject.

The FSM inverts the default: unless a `(current_state, action)` pair
is explicitly in the allow-matrix, it is refused. Widening the matrix
is a one-line diff that shows up in code review.

## The matrix

The allow-matrix is the single source of truth. It lives in
[`server/escrow_fsm.py`](../server/escrow_fsm.py) as `_TRANSITIONS`:

| From `EscrowStatus` | Action              | To `EscrowStatus` |
|---------------------|---------------------|-------------------|
| `pending`           | `release`           | `released`        |
| `pending`           | `refund`            | `refunded`        |
| `pending`           | `expire`            | `expired`         |
| `pending`           | `dispute`           | `disputed`        |
| `disputed`          | `resolve_sender`    | `resolved`        |
| `disputed`          | `resolve_receiver`  | `resolved`        |

Terminal states — `released`, `refunded`, `expired`, `resolved` — have
**no outgoing edges**. Any action from a terminal state is refused
regardless of caller identity, TTL, or signature validity.

`pending` is a **start-only** state: no transition re-enters it. This
prevents zombie re-openings of terminal escrows via a future misedit.

## What the FSM does NOT decide

The FSM is *pure state logic*. It does not check:

- **Caller identity** — "only sender can release" is enforced by the
  endpoint before calling the FSM; on a failure the API returns 403.
- **TTL** — `refund_escrow` inspects `created_at + ttl` and picks
  `EscrowAction.EXPIRE` versus `EscrowAction.REFUND` accordingly, then
  hands off to the FSM.
- **Cap approval** — the contract's Rust-side 3-of-5 arbiter signature
  requirement runs on-chain; the hosted API mirrors it with
  `arbiter_crypto.count_valid_votes` before the FSM step.

This split is intentional. If any of those checks fail, the API
responds with the appropriate 4xx and the FSM is never called; the
recorded state cannot drift.

## HTTP contract

When an FSM transition is refused, the endpoint returns **HTTP 409
Conflict** with a stable JSON payload:

```json
{
  "detail": {
    "code": "invalid_transition",
    "current_state": "released",
    "action": "release",
    "allowed_actions": [],
    "message": "Cannot perform action 'release' on escrow in terminal state 'released'. No further transitions are allowed."
  }
}
```

Frontends and integrations can key off `code` and `current_state` to
drive UX (e.g. disable a `Release` button whenever `allowed_actions`
does not contain `"release"`). The `message` field is human-readable
and stable enough for direct display but not part of the machine
contract — new details may be appended in a minor release.

Other error surfaces are unchanged:

| HTTP | Cause                                                              |
|------|--------------------------------------------------------------------|
| 400  | Non-FSM `ValueError` (e.g. `in_favor_of` not `sender`/`receiver`)  |
| 401  | Missing/invalid x402 header when required                          |
| 403  | Caller is not the sender / not sender or receiver / not an arbiter |
| 404  | Escrow not found for the given `service_hash`                      |
| 409  | Invalid FSM transition (this document)                             |
| 422  | Insufficient arbiter signatures on `/resolve`                      |
| 502  | On-chain call failed or transaction reverted                       |

## Test coverage

- [`tests/test_escrow_fsm.py`](../tests/test_escrow_fsm.py) — full
  matrix (`ALL_STATES × EscrowAction.ALL = 36` pairs), 6 allowed
  transitions, 30 denied transitions, plus targeted regressions
  (double-release, dispute-after-refund, resolve-on-pending).
- [`tests/test_escrow_fsm_api.py`](../tests/test_escrow_fsm_api.py) —
  HTTP contract: 409 body shape for release, dispute, and refund, plus
  the 403 for non-sender and 404 for missing escrow.

If you ever widen `_TRANSITIONS`, `test_matrix_size_is_expected`
fails; if you accidentally narrow it, the parametrised
allowed-transitions test fails. The matrix cannot drift silently.

## Adding a new transition

1. Add the `(state, action) -> next_state` entry to `_TRANSITIONS`.
2. Add the action name to `EscrowAction.ALL` (if new).
3. Add an allowed-row to `tests/test_escrow_fsm.py::ALLOWED`.
4. Bump `test_matrix_size_is_expected` to the new count.
5. If you exposed a new API endpoint, catch its `ValueError` with
   `_raise_fsm_or_generic` in `server/app.py`.
6. Update the table above.

## Notes for the on-chain contract

The Python matrix is intentionally *narrower* than or equal to the
Rust escrow contract's allowed transitions. If a chain-native
transition ever needs to be exposed via the hosted API — for example,
an arbiter-driven refund of a disputed escrow, once the contract
supports it — widen the matrix here first, then the hosted layer will
accept the corresponding entry point. Never reverse the order: a
hosted API that accepts a transition the contract will reject would
create a state gap where the ledger and the console disagree.
