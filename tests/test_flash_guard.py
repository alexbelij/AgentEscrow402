"""Tests for server/flash_guard.py (T2.12).

Ensures parity with the Rust stub and property-tests the guard
against a range of timing attacks.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from server import flash_guard as fg


# --- constants parity ---------------------------------------------------------


def test_constants_parity_with_rust_stub():
    """Python constants must match the Rust stub verbatim."""
    rust = Path("contracts/stubs/src/flash_guard.rs").read_text()
    m_block = re.search(r"MIN_BLOCK_DELAY:\s*u64\s*=\s*(\d+)", rust)
    m_hold = re.search(r"MIN_HOLD_PERIOD_SECS:\s*u64\s*=\s*(\d+)", rust)
    assert m_block is not None, "Rust stub missing MIN_BLOCK_DELAY"
    assert m_hold is not None, "Rust stub missing MIN_HOLD_PERIOD_SECS"
    assert int(m_block.group(1)) == fg.MIN_BLOCK_DELAY
    assert int(m_hold.group(1)) == fg.MIN_HOLD_PERIOD_SECS


# --- hold period --------------------------------------------------------------


def test_hold_period_rejects_zero_elapsed():
    r = fg.check_hold_period(1_000, 1_000)
    assert r.blocked
    assert r.remaining_seconds == fg.MIN_HOLD_PERIOD_SECS
    assert "hold period" in r.reason


def test_hold_period_rejects_just_under():
    r = fg.check_hold_period(1_000, 1_000 + fg.MIN_HOLD_PERIOD_SECS - 1)
    assert r.blocked
    assert r.remaining_seconds == 1


def test_hold_period_accepts_exact_boundary():
    r = fg.check_hold_period(1_000, 1_000 + fg.MIN_HOLD_PERIOD_SECS)
    assert r.passed


def test_hold_period_accepts_past_boundary():
    r = fg.check_hold_period(1_000, 1_000 + fg.MIN_HOLD_PERIOD_SECS + 1_000)
    assert r.passed


def test_hold_period_saturating_on_clock_skew():
    """If clock ran backwards, treat as zero elapsed — do NOT wrap-around."""
    r = fg.check_hold_period(1_000, 500)
    assert r.blocked
    assert r.remaining_seconds == fg.MIN_HOLD_PERIOD_SECS


def test_hold_period_rejects_negative_ts():
    with pytest.raises(ValueError):
        fg.check_hold_period(-1, 100)
    with pytest.raises(ValueError):
        fg.check_hold_period(100, -1)


# --- block delay --------------------------------------------------------------


def test_block_delay_rejects_zero_blocks():
    r = fg.check_block_delay(100, 100)
    assert r.blocked
    assert r.remaining_blocks == fg.MIN_BLOCK_DELAY


def test_block_delay_rejects_just_under():
    r = fg.check_block_delay(100, 100 + fg.MIN_BLOCK_DELAY - 1)
    assert r.blocked


def test_block_delay_accepts_exact_boundary():
    r = fg.check_block_delay(100, 100 + fg.MIN_BLOCK_DELAY)
    assert r.passed


def test_block_delay_saturating_on_reorg():
    """If chain height moved backwards, treat as zero delta."""
    r = fg.check_block_delay(100, 50)
    assert r.blocked
    assert r.remaining_blocks == fg.MIN_BLOCK_DELAY


# --- enforce combined ---------------------------------------------------------


def test_enforce_passes_when_both_guards_satisfied():
    fg.enforce(
        funded_at_ts=1_000,
        current_ts=1_000 + fg.MIN_HOLD_PERIOD_SECS,
        funded_block=100,
        current_block=100 + fg.MIN_BLOCK_DELAY,
    )  # no raise


def test_enforce_raises_when_only_hold_fails():
    with pytest.raises(fg.FlashGuardError, match="hold period"):
        fg.enforce(
            funded_at_ts=1_000,
            current_ts=1_010,
            funded_block=100,
            current_block=100 + fg.MIN_BLOCK_DELAY,
        )


def test_enforce_raises_when_only_delay_fails():
    with pytest.raises(fg.FlashGuardError, match="block delay"):
        fg.enforce(
            funded_at_ts=1_000,
            current_ts=1_000 + fg.MIN_HOLD_PERIOD_SECS,
            funded_block=100,
            current_block=101,
        )


def test_enforce_reports_both_when_both_fail():
    with pytest.raises(fg.FlashGuardError) as exc:
        fg.enforce(
            funded_at_ts=1_000,
            current_ts=1_010,
            funded_block=100,
            current_block=101,
        )
    assert "hold period" in str(exc.value)
    assert "block delay" in str(exc.value)


def test_enforce_bypass_flag_short_circuits():
    fg.enforce(
        funded_at_ts=1_000,
        current_ts=1_000,
        funded_block=100,
        current_block=100,
        bypass=True,
    )  # no raise


# --- property-based -----------------------------------------------------------


@given(
    funded_ts=st.integers(min_value=0, max_value=2**32),
    delta=st.integers(min_value=0, max_value=2**16),
)
def test_hold_period_monotonic_in_elapsed(funded_ts, delta):
    """More elapsed time can never move a passing guard to blocked."""
    small = fg.check_hold_period(funded_ts, funded_ts + delta)
    big = fg.check_hold_period(funded_ts, funded_ts + delta + fg.MIN_HOLD_PERIOD_SECS)
    if small.passed:
        assert big.passed


@given(
    funded_block=st.integers(min_value=0, max_value=2**32),
    delta=st.integers(min_value=0, max_value=2**16),
)
def test_block_delay_monotonic_in_delta(funded_block, delta):
    """More block-height delta can never move a passing guard to blocked."""
    small = fg.check_block_delay(funded_block, funded_block + delta)
    big = fg.check_block_delay(funded_block, funded_block + delta + fg.MIN_BLOCK_DELAY)
    if small.passed:
        assert big.passed


@given(
    funded_ts=st.integers(min_value=0, max_value=2**32),
    now_ts=st.integers(min_value=0, max_value=2**32),
    funded_block=st.integers(min_value=0, max_value=2**32),
    now_block=st.integers(min_value=0, max_value=2**32),
)
def test_enforce_never_panics(funded_ts, now_ts, funded_block, now_block):
    """`enforce` must either return cleanly or raise FlashGuardError — never crash."""
    try:
        fg.enforce(
            funded_at_ts=funded_ts,
            current_ts=now_ts,
            funded_block=funded_block,
            current_block=now_block,
        )
    except fg.FlashGuardError:
        pass  # expected outcome for insufficient timing


# --- attack scenarios ---------------------------------------------------------


def test_flash_loan_attack_in_single_block_is_blocked():
    """Attacker funds and tries to drain within the same block/second."""
    with pytest.raises(fg.FlashGuardError):
        fg.enforce(
            funded_at_ts=1_000,
            current_ts=1_000,  # same second
            funded_block=42,
            current_block=42,  # same block
        )


def test_attacker_cannot_bypass_via_block_only():
    """Even if attacker mines MIN_BLOCK_DELAY blocks, hold period still blocks."""
    with pytest.raises(fg.FlashGuardError, match="hold period"):
        fg.enforce(
            funded_at_ts=1_000,
            current_ts=1_000,  # zero seconds
            funded_block=42,
            current_block=42 + fg.MIN_BLOCK_DELAY + 10,
        )


def test_attacker_cannot_bypass_via_time_only():
    """Even after long wall-clock wait, insufficient blocks still block."""
    with pytest.raises(fg.FlashGuardError, match="block delay"):
        fg.enforce(
            funded_at_ts=1_000,
            current_ts=1_000 + fg.MIN_HOLD_PERIOD_SECS * 10,
            funded_block=42,
            current_block=42,  # no new blocks
        )
