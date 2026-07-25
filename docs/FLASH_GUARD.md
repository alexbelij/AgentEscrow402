# FlashGuard — Flash-loan protection for AE402

**Status:** activated (server-side gate + Rust stub parity).
**Ticket:** T2.12 — Tier 2 Security & Audit Block.

## What it protects

Prevents flash-loan-style manipulation where an attacker

1. borrows liquidity within a single block,
2. opens + disputes + drains an escrow, and
3. repays the loan in the same block —

leaving the pool with a permanent loss.

## The two-guard rule

A fund cannot leave escrow (release / refund) until **both** of these
conditions hold:

| Guard         | Constant                                | Value  | Reason                       |
| ------------- | --------------------------------------- | ------ | ---------------------------- |
| Wall-clock    | `MIN_HOLD_PERIOD_SECS`                  | 300 s  | 5-minute economic infeasibility band |
| Block-height  | `MIN_BLOCK_DELAY`                       | 5      | Attacker would need >4 blocks of validator control |

Both guards fire independently — an attacker who forges wall-clock time
still trips the block-height gate, and vice-versa.

## Layer parity

`server/flash_guard.py` (Python, server-side pre-check) and
`contracts/stubs/src/flash_guard.rs` (Rust, on-chain enforcement)
share identical constants and semantics. A parity test
(`tests/test_flash_guard.py::test_constants_parity_with_rust_stub`)
reads the Rust source at CI time and fails if the values drift.

## API

```python
from server import flash_guard as fg

# Fine-grained check (returns a GuardCheck dataclass):
r = fg.check_hold_period(funded_at_ts=<epoch>, current_ts=<epoch>)
if r.blocked:
    ...  # r.remaining_seconds tells the caller how long to wait

# Coarse "raise on any violation" for endpoint use:
fg.enforce(
    funded_at_ts=<epoch>,
    current_ts=<epoch>,
    funded_block=<height>,
    current_block=<height>,
)
# → FlashGuardError with human-readable remaining-delta on failure.
```

## Rollout state

- **Module + constants:** live.
- **Test coverage:** 22 unit + 3 hypothesis property tests + parity test.
- **Wire-into-endpoints:** deferred to a follow-up PR that updates the
  escrow release/refund handlers to call `fg.enforce(...)` before
  invoking the FSM transition. This PR ships the primitive so the
  wire-up is a single-line change per endpoint.

## Threat model bypass surface

`enforce(..., bypass=True)` exists only for two narrow contexts:

1. **Admin emergency refund** after a governance vote (already
   gated by multi-sig timelock — see `docs/GOVERNANCE.md`).
2. **NCTL local integration tests** where the harness pre-advances time
   and blocks, and re-checking here would double-count.

The `bypass` flag is **never** derived from user input in any handler
and MUST NOT become path-reachable from a public endpoint.
