"""Tests for adaptive arbiter panel sizing (A)."""

from __future__ import annotations

import pytest

from server.panel_sizing import is_odd_panel_size, panel_size_for_amount

_ONE_CSPR = 1_000_000_000
_CAP_10 = 10 * _ONE_CSPR
_CAP_100 = 100 * _ONE_CSPR


# --- Tier boundaries ---------------------------------------------------- #


def test_small_tier_below_1_cspr() -> None:
    r = panel_size_for_amount(500_000_000)  # 0.5 CSPR
    assert r.arbiters == 3
    assert r.quorum == 2
    assert r.tier == "small"


def test_medium_tier_1_to_10_cspr() -> None:
    r = panel_size_for_amount(_ONE_CSPR)
    assert r.arbiters == 5
    assert r.quorum == 3
    assert r.tier == "medium"


def test_large_tier_10_to_100_cspr() -> None:
    r = panel_size_for_amount(_CAP_10)
    assert r.arbiters == 7
    assert r.quorum == 4
    assert r.tier == "large"


def test_jumbo_tier_above_100_cspr() -> None:
    r = panel_size_for_amount(_CAP_100)
    assert r.arbiters == 9
    assert r.quorum == 5
    assert r.tier == "jumbo"


def test_jumbo_tier_far_above_100_cspr() -> None:
    r = panel_size_for_amount(10 * _CAP_100)
    assert r.arbiters == 9


# --- Invariants --------------------------------------------------------- #


def test_zero_amount_raises() -> None:
    with pytest.raises(ValueError):
        panel_size_for_amount(0)


def test_negative_amount_raises() -> None:
    with pytest.raises(ValueError):
        panel_size_for_amount(-1)


def test_all_panel_sizes_are_odd() -> None:
    for amount in [
        1,
        500_000_000,
        _ONE_CSPR,
        _ONE_CSPR + 1,
        _CAP_10 - 1,
        _CAP_10,
        _CAP_100 - 1,
        _CAP_100,
        _CAP_100 * 1_000,
    ]:
        r = panel_size_for_amount(amount)
        assert is_odd_panel_size(r.arbiters), f"{amount} → {r.arbiters}"


def test_quorum_is_simple_majority() -> None:
    for amount in [500_000_000, _ONE_CSPR, _CAP_10, _CAP_100]:
        r = panel_size_for_amount(amount)
        assert r.quorum == r.arbiters // 2 + 1


def test_monotonic_in_amount() -> None:
    """Panel size never shrinks as amount grows."""
    amounts = sorted(
        [
            500_000_000,
            _ONE_CSPR,
            5 * _ONE_CSPR,
            _CAP_10,
            50 * _ONE_CSPR,
            _CAP_100,
            _CAP_100 * 5,
        ]
    )
    prev = 0
    for a in amounts:
        n = panel_size_for_amount(a).arbiters
        assert n >= prev
        prev = n


def test_is_odd_helper() -> None:
    assert is_odd_panel_size(3) is True
    assert is_odd_panel_size(5) is True
    assert is_odd_panel_size(9) is True
    assert is_odd_panel_size(4) is False
    assert is_odd_panel_size(2) is False
    assert is_odd_panel_size(1) is False  # too small a panel is not valid
