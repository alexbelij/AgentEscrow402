"""Tests for reputation-based premium pricing (E.3)."""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from server.rep_pricing import (
    BASE_RATE_BPS,
    MIN_PREMIUM_MOTES,
    insurance_fee,
    price_breakdown,
)


# --- Determinism ---------------------------------------------------------- #


def test_same_input_same_output() -> None:
    """Pure function — no randomness, no side effects."""
    assert insurance_fee(1_000_000_000, 50) == insurance_fee(1_000_000_000, 50)
    b1 = price_breakdown(500_000_000, 75)
    b2 = price_breakdown(500_000_000, 75)
    assert b1 == b2


# --- Tier boundaries ------------------------------------------------------ #


def test_tier_high_risk_below_30() -> None:
    b = price_breakdown(1_000_000_000, 20)
    assert b.tier == "high_risk"
    assert b.multiplier == 2.0


def test_tier_medium_30_to_49() -> None:
    b = price_breakdown(1_000_000_000, 40)
    assert b.tier == "medium_risk"
    assert b.multiplier == 1.5


def test_tier_neutral_50_to_70() -> None:
    b = price_breakdown(1_000_000_000, 60)
    assert b.tier == "neutral"
    assert b.multiplier == 1.0


def test_tier_low_above_70() -> None:
    b = price_breakdown(1_000_000_000, 85)
    assert b.tier == "low_risk"
    assert b.multiplier == 0.8


def test_reputation_clamped_below_zero() -> None:
    b = price_breakdown(1_000_000_000, -50)
    assert b.reputation_used == 0
    assert b.tier == "high_risk"


def test_reputation_clamped_above_hundred() -> None:
    b = price_breakdown(1_000_000_000, 500)
    assert b.reputation_used == 100
    assert b.tier == "low_risk"


# --- Monotonicity properties (Hypothesis) --------------------------------- #


@given(
    amount=st.integers(min_value=100_000_000, max_value=1_000_000_000_000),
    rep_a=st.integers(min_value=0, max_value=100),
    rep_b=st.integers(min_value=0, max_value=100),
)
@settings(max_examples=200, deadline=None)
def test_monotonic_in_reputation(amount: int, rep_a: int, rep_b: int) -> None:
    """Higher reputation → lower or equal fee."""
    if rep_a >= rep_b:
        assert insurance_fee(amount, rep_a) <= insurance_fee(amount, rep_b)


@given(
    amount_a=st.integers(min_value=100_000_000, max_value=1_000_000_000_000),
    amount_b=st.integers(min_value=100_000_000, max_value=1_000_000_000_000),
    rep=st.integers(min_value=0, max_value=100),
)
@settings(max_examples=200, deadline=None)
def test_monotonic_in_amount(amount_a: int, amount_b: int, rep: int) -> None:
    """Higher amount → higher or equal fee."""
    if amount_a >= amount_b:
        assert insurance_fee(amount_a, rep) >= insurance_fee(amount_b, rep)


# --- Bound invariants ----------------------------------------------------- #


@given(
    amount=st.integers(min_value=100_000_000, max_value=1_000_000_000_000),
    rep=st.integers(min_value=0, max_value=100),
)
@settings(max_examples=100, deadline=None)
def test_fee_never_exceeds_amount(amount: int, rep: int) -> None:
    assert insurance_fee(amount, rep) <= amount


@given(
    amount=st.integers(min_value=100_000_000, max_value=1_000_000_000_000),
    rep=st.integers(min_value=0, max_value=100),
)
@settings(max_examples=100, deadline=None)
def test_fee_never_below_floor(amount: int, rep: int) -> None:
    assert insurance_fee(amount, rep) >= MIN_PREMIUM_MOTES


def test_fee_capped_by_tiny_amount() -> None:
    """If MIN_PREMIUM_MOTES > amount, fee is clamped down to amount, not up."""
    tiny = MIN_PREMIUM_MOTES // 2
    fee = insurance_fee(tiny, 50)
    assert fee <= tiny


# --- Base rate anchor ----------------------------------------------------- #


def test_base_fee_at_neutral_tier() -> None:
    """At neutral tier the fee is exactly BASE_RATE_BPS of the amount."""
    amount = 1_000_000_000
    expected = (amount * BASE_RATE_BPS) // 10_000
    assert price_breakdown(amount, 60).fee == expected


def test_high_risk_is_2x_neutral() -> None:
    amount = 1_000_000_000
    fee_neutral = insurance_fee(amount, 60)
    fee_high = insurance_fee(amount, 15)
    assert fee_high == 2 * fee_neutral or fee_high == fee_neutral * 2


def test_low_risk_is_lower_than_neutral() -> None:
    amount = 1_000_000_000
    assert insurance_fee(amount, 90) < insurance_fee(amount, 60)


# --- Rejects garbage ----------------------------------------------------- #


def test_zero_amount_raises() -> None:
    import pytest

    with pytest.raises(ValueError):
        insurance_fee(0, 50)


def test_negative_amount_raises() -> None:
    import pytest

    with pytest.raises(ValueError):
        insurance_fee(-1, 50)
