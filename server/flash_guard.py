"""Flash-loan protection for escrow release/refund operations (T2.12).

Mirrors the on-chain Rust module `contracts/stubs/src/flash_guard.rs`
so server-side pre-checks agree with contract-side guards.

Two independent tests must pass before a fund can leave escrow:

  1. Wall-clock hold period    (>= MIN_HOLD_PERIOD_SECS since funding)
  2. Block-height delay        (>= MIN_BLOCK_DELAY blocks since funding)

Rationale
=========
A flash-borrowed principal can be used to open, immediately dispute
and drain an escrow within a single block. Enforcing both a time
delay and a block delay makes an attacker either

  (a) hold the borrowed liquidity long enough that the flash loan
      cannot cover their capital cost (economic infeasibility), or
  (b) advance the chain by MIN_BLOCK_DELAY blocks between borrow
      and release (requires attacker to control validators —
      infeasible on Casper PoS).

The constants MUST stay in sync with the Rust stub. A parity test
`test_flash_guard.py::test_constants_parity_with_rust_stub` verifies
this by reading the Rust source.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

# Keep in sync with contracts/stubs/src/flash_guard.rs
MIN_BLOCK_DELAY: Final[int] = 5
MIN_HOLD_PERIOD_SECS: Final[int] = 300  # 5 minutes


class FlashGuardError(RuntimeError):
    """Raised when a fund-movement violates flash-loan guards."""


@dataclass(frozen=True)
class GuardCheck:
    """Result of a guard evaluation — carries both pass/fail and diagnostics."""

    passed: bool
    reason: str
    remaining_seconds: int = 0
    remaining_blocks: int = 0

    @property
    def blocked(self) -> bool:  # ergonomic alias
        return not self.passed


def check_hold_period(funded_at_ts: int, current_ts: int) -> GuardCheck:
    """Return whether the wall-clock hold period has elapsed."""
    if funded_at_ts < 0 or current_ts < 0:
        raise ValueError("timestamps must be non-negative")
    elapsed = current_ts - funded_at_ts if current_ts >= funded_at_ts else 0
    if elapsed < MIN_HOLD_PERIOD_SECS:
        return GuardCheck(
            passed=False,
            reason="flash guard: hold period not met",
            remaining_seconds=MIN_HOLD_PERIOD_SECS - elapsed,
        )
    return GuardCheck(passed=True, reason="ok")


def check_block_delay(funded_block: int, current_block: int) -> GuardCheck:
    """Return whether the block-height delay has been reached."""
    if funded_block < 0 or current_block < 0:
        raise ValueError("block heights must be non-negative")
    blocks = current_block - funded_block if current_block >= funded_block else 0
    if blocks < MIN_BLOCK_DELAY:
        return GuardCheck(
            passed=False,
            reason="flash guard: block delay not met",
            remaining_blocks=MIN_BLOCK_DELAY - blocks,
        )
    return GuardCheck(passed=True, reason="ok")


def enforce(
    *,
    funded_at_ts: int,
    current_ts: int,
    funded_block: int,
    current_block: int,
    bypass: bool = False,
) -> None:
    """Raise FlashGuardError if either guard fails.

    `bypass=True` is honoured only for narrow test/admin scenarios and
    should never be set from user-controlled input.
    """
    if bypass:
        return
    hold = check_hold_period(funded_at_ts, current_ts)
    delay = check_block_delay(funded_block, current_block)
    if hold.blocked and delay.blocked:
        raise FlashGuardError(
            f"{hold.reason}; {delay.reason} " f"(need +{hold.remaining_seconds}s, +{delay.remaining_blocks} blocks)"
        )
    if hold.blocked:
        raise FlashGuardError(f"{hold.reason} (need +{hold.remaining_seconds}s)")
    if delay.blocked:
        raise FlashGuardError(f"{delay.reason} (need +{delay.remaining_blocks} blocks)")


__all__ = [
    "MIN_BLOCK_DELAY",
    "MIN_HOLD_PERIOD_SECS",
    "FlashGuardError",
    "GuardCheck",
    "check_hold_period",
    "check_block_delay",
    "enforce",
]
