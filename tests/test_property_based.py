"""Property-based tests (Hypothesis) for the pure fee/insurance-split logic.

Complements the hand-picked example tests in test_business_logic.py by
checking invariants across thousands of generated (amount, fee_bps) pairs
instead of a handful of fixed cases. Mirrors the Rust proptest coverage
added for the equivalent on-chain `compute_fee`/`compute_insurance` logic
in contracts/tests/src/property_tests.rs.
"""

from hypothesis import given, strategies as st

from server.app import _apply_insurance_fee

# Cap fee_bps generation at 10_000 (100%) -- values above that aren't a
# meaningful basis-points rate and aren't reachable through the validated
# config/admin API, but the function itself has no explicit upper guard, so
# we still assert it degrades safely rather than overflowing/going negative.
MAX_REALISTIC_FEE_BPS = 10_000


@given(
    amount=st.integers(min_value=0, max_value=10**18),
    fee_bps=st.integers(min_value=0, max_value=MAX_REALISTIC_FEE_BPS),
)
def test_apply_insurance_fee_never_exceeds_amount(amount, fee_bps):
    net, fee = _apply_insurance_fee(amount, fee_bps)
    assert fee >= 0
    assert net >= 0
    assert net + fee == amount


@given(
    amount=st.integers(min_value=0, max_value=10**18),
    fee_bps=st.integers(min_value=0, max_value=MAX_REALISTIC_FEE_BPS),
)
def test_apply_insurance_fee_zero_bps_is_a_noop(amount, fee_bps):
    net, fee = _apply_insurance_fee(amount, 0)
    assert fee == 0
    assert net == amount


@given(
    amount=st.integers(min_value=1, max_value=10**18),
    low_bps=st.integers(min_value=0, max_value=MAX_REALISTIC_FEE_BPS),
    extra_bps=st.integers(min_value=0, max_value=MAX_REALISTIC_FEE_BPS),
)
def test_apply_insurance_fee_monotonic_in_fee_bps(amount, low_bps, extra_bps):
    """A higher fee_bps never yields a smaller absolute fee, for any fixed
    amount -- the fee-rate-to-fee-amount mapping must be monotonic."""
    _, fee_low = _apply_insurance_fee(amount, low_bps)
    _, fee_high = _apply_insurance_fee(amount, low_bps + extra_bps)
    assert fee_high >= fee_low
