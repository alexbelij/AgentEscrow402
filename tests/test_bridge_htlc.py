"""Tests for `server.bridge_htlc` — deterministic HTLC atomic-swap bridge (T3.4-A)."""

from __future__ import annotations

import os

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from server import bridge_htlc as htlc

# ── Fixtures / helpers ────────────────────────────────────────────────


T0 = 1_700_000_000_000  # arbitrary "now" reference in ms


def _fresh() -> htlc.HTLCRegistry:
    return htlc.HTLCRegistry()


def _mk_swap(
    reg: htlc.HTLCRegistry,
    *,
    preimage: bytes | None = None,
    casper_timelock: int = T0 + 3600_000,  # T_a: farther
    evm_timelock: int = T0 + 1800_000,  # T_b: nearer (T_b < T_a required)
    casper_amount: int = 1_000_000,
    evm_amount: int = 500_000,
    now_ms: int = T0,
) -> tuple[htlc.HTLCSwap, bytes]:
    if preimage is None:
        preimage = os.urandom(32)
    hashlock = htlc.compute_hashlock(preimage)
    swap = reg.initiate_swap(
        hashlock_hex=hashlock,
        casper_initiator="casper-alice",
        casper_counterparty="casper-bob",
        casper_amount=casper_amount,
        casper_timelock_ms=casper_timelock,
        evm_initiator="0xEvmBob",
        evm_counterparty="0xEvmAlice",
        evm_amount=evm_amount,
        evm_timelock_ms=evm_timelock,
        now_ms=now_ms,
    )
    return swap, preimage


# ── Pure helpers ──────────────────────────────────────────────────────


def test_compute_hashlock_deterministic():
    a = htlc.compute_hashlock(b"\x00" * 32)
    b = htlc.compute_hashlock(b"\x00" * 32)
    assert a == b
    assert len(a) == 64  # sha256 hex


def test_compute_hashlock_diverges_on_different_input():
    assert htlc.compute_hashlock(b"a") != htlc.compute_hashlock(b"b")


def test_new_preimage_has_correct_length():
    p = htlc.new_preimage()
    assert len(p) == 32
    # not all zeroes
    assert p != b"\x00" * 32


def test_verify_timelock_ordering_ok():
    # T_b < T_a is required for atomicity
    htlc.verify_timelock_ordering(casper_timelock_ms=T0 + 3600_000, evm_timelock_ms=T0 + 1800_000)


def test_verify_timelock_ordering_rejects_equal():
    with pytest.raises(htlc.HTLCError) as e:
        htlc.verify_timelock_ordering(casper_timelock_ms=T0 + 1000, evm_timelock_ms=T0 + 1000)
    assert e.value.code == htlc.RejectCode.TIMELOCK_ORDERING


def test_verify_timelock_ordering_rejects_evm_farther():
    with pytest.raises(htlc.HTLCError) as e:
        htlc.verify_timelock_ordering(casper_timelock_ms=T0 + 1000, evm_timelock_ms=T0 + 2000)
    assert e.value.code == htlc.RejectCode.TIMELOCK_ORDERING


def test_validate_amount_zero_rejected():
    with pytest.raises(htlc.HTLCError) as e:
        htlc.validate_amount(0)
    assert e.value.code == htlc.RejectCode.INVALID_AMOUNT


def test_validate_amount_negative_rejected():
    with pytest.raises(htlc.HTLCError) as e:
        htlc.validate_amount(-1)
    assert e.value.code == htlc.RejectCode.INVALID_AMOUNT


# ── initiate_swap ─────────────────────────────────────────────────────


def test_initiate_creates_both_legs_proposed():
    reg = _fresh()
    swap, _ = _mk_swap(reg)
    assert swap.casper_leg is not None
    assert swap.evm_leg is not None
    assert swap.casper_leg.status == htlc.HTLCStatus.PROPOSED
    assert swap.evm_leg.status == htlc.HTLCStatus.PROPOSED
    assert swap.casper_leg.hashlock_hex == swap.evm_leg.hashlock_hex == swap.hashlock_hex


def test_initiate_rejects_bad_hashlock_length():
    reg = _fresh()
    with pytest.raises(htlc.HTLCError) as e:
        reg.initiate_swap(
            hashlock_hex="dead",
            casper_initiator="a",
            casper_counterparty="b",
            casper_amount=1,
            casper_timelock_ms=T0 + 100,
            evm_initiator="a",
            evm_counterparty="b",
            evm_amount=1,
            evm_timelock_ms=T0 + 50,
            now_ms=T0,
        )
    assert e.value.code == htlc.RejectCode.INVALID_HASHLOCK


def test_initiate_rejects_bad_timelock_ordering():
    reg = _fresh()
    with pytest.raises(htlc.HTLCError) as e:
        _mk_swap(reg, casper_timelock=T0 + 1000, evm_timelock=T0 + 2000)
    assert e.value.code == htlc.RejectCode.TIMELOCK_ORDERING


def test_initiate_rejects_duplicate_swap():
    reg = _fresh()
    preimage = os.urandom(32)
    _mk_swap(reg, preimage=preimage)
    with pytest.raises(htlc.HTLCError) as e:
        _mk_swap(reg, preimage=preimage)
    assert e.value.code == htlc.RejectCode.LEG_ALREADY_EXISTS


def test_initiate_deterministic_leg_ids():
    """Same inputs → same leg_ids across runs (needed for cross-chain observer)."""
    reg1 = _fresh()
    reg2 = _fresh()
    preimage = b"\x11" * 32
    s1, _ = _mk_swap(reg1, preimage=preimage)
    s2, _ = _mk_swap(reg2, preimage=preimage)
    assert s1.swap_id == s2.swap_id
    assert s1.casper_leg.leg_id == s2.casper_leg.leg_id
    assert s1.evm_leg.leg_id == s2.evm_leg.leg_id


# ── lock ──────────────────────────────────────────────────────────────


def test_lock_moves_proposed_to_locked():
    reg = _fresh()
    swap, _ = _mk_swap(reg)
    reg.lock(swap.casper_leg.leg_id, now_ms=T0)
    leg = reg.get_leg(swap.casper_leg.leg_id)
    assert leg.status == htlc.HTLCStatus.LOCKED
    assert leg.locked_at_ms == T0
    assert leg.lock_tx_hash is not None


def test_lock_is_idempotent():
    reg = _fresh()
    swap, _ = _mk_swap(reg)
    reg.lock(swap.evm_leg.leg_id, now_ms=T0)
    # second lock is a no-op
    leg = reg.lock(swap.evm_leg.leg_id, now_ms=T0 + 1)
    assert leg.status == htlc.HTLCStatus.LOCKED
    # locked_at_ms did NOT get bumped
    assert leg.locked_at_ms == T0


def test_lock_after_timelock_expired_rejected():
    reg = _fresh()
    swap, _ = _mk_swap(reg, evm_timelock=T0 + 1000)
    with pytest.raises(htlc.HTLCError) as e:
        reg.lock(swap.evm_leg.leg_id, now_ms=T0 + 2000)
    assert e.value.code == htlc.RejectCode.TIMELOCK_EXPIRED


def test_lock_unknown_leg_rejected():
    reg = _fresh()
    with pytest.raises(htlc.HTLCError) as e:
        reg.lock("nonexistent-leg-id", now_ms=T0)
    assert e.value.code == htlc.RejectCode.UNKNOWN_LEG


# ── claim ─────────────────────────────────────────────────────────────


def test_claim_with_correct_preimage_succeeds():
    reg = _fresh()
    swap, preimage = _mk_swap(reg)
    reg.lock(swap.casper_leg.leg_id, now_ms=T0)
    reg.lock(swap.evm_leg.leg_id, now_ms=T0)
    leg = reg.claim(swap.evm_leg.leg_id, preimage.hex(), now_ms=T0 + 100)
    assert leg.status == htlc.HTLCStatus.CLAIMED
    assert leg.preimage_hex == preimage.hex()
    assert leg.claim_tx_hash is not None


def test_claim_with_wrong_preimage_rejected():
    reg = _fresh()
    swap, _ = _mk_swap(reg)
    reg.lock(swap.casper_leg.leg_id, now_ms=T0)
    with pytest.raises(htlc.HTLCError) as e:
        reg.claim(swap.casper_leg.leg_id, "aa" * 32, now_ms=T0 + 100)
    assert e.value.code == htlc.RejectCode.PREIMAGE_MISMATCH


def test_claim_before_lock_rejected():
    reg = _fresh()
    swap, preimage = _mk_swap(reg)
    with pytest.raises(htlc.HTLCError) as e:
        reg.claim(swap.casper_leg.leg_id, preimage.hex(), now_ms=T0)
    assert e.value.code == htlc.RejectCode.NOT_LOCKED


def test_claim_after_timelock_rejected():
    reg = _fresh()
    swap, preimage = _mk_swap(reg, evm_timelock=T0 + 1000)
    reg.lock(swap.evm_leg.leg_id, now_ms=T0)
    with pytest.raises(htlc.HTLCError) as e:
        reg.claim(swap.evm_leg.leg_id, preimage.hex(), now_ms=T0 + 1000)
    assert e.value.code == htlc.RejectCode.TIMELOCK_EXPIRED


def test_double_claim_rejected():
    reg = _fresh()
    swap, preimage = _mk_swap(reg)
    reg.lock(swap.evm_leg.leg_id, now_ms=T0)
    reg.claim(swap.evm_leg.leg_id, preimage.hex(), now_ms=T0 + 100)
    with pytest.raises(htlc.HTLCError) as e:
        reg.claim(swap.evm_leg.leg_id, preimage.hex(), now_ms=T0 + 200)
    assert e.value.code == htlc.RejectCode.ALREADY_CLAIMED


def test_claim_bad_hex_rejected():
    reg = _fresh()
    swap, _ = _mk_swap(reg)
    reg.lock(swap.evm_leg.leg_id, now_ms=T0)
    with pytest.raises(htlc.HTLCError) as e:
        reg.claim(swap.evm_leg.leg_id, "zzznotHex", now_ms=T0 + 100)
    assert e.value.code == htlc.RejectCode.INVALID_HASHLOCK


# ── refund ────────────────────────────────────────────────────────────


def test_refund_after_timelock_succeeds():
    reg = _fresh()
    swap, _ = _mk_swap(reg, evm_timelock=T0 + 1000)
    reg.lock(swap.evm_leg.leg_id, now_ms=T0)
    leg = reg.refund(swap.evm_leg.leg_id, now_ms=T0 + 1000)
    assert leg.status == htlc.HTLCStatus.REFUNDED
    assert leg.refund_tx_hash is not None


def test_refund_before_timelock_rejected():
    reg = _fresh()
    swap, _ = _mk_swap(reg, evm_timelock=T0 + 5000)
    reg.lock(swap.evm_leg.leg_id, now_ms=T0)
    with pytest.raises(htlc.HTLCError) as e:
        reg.refund(swap.evm_leg.leg_id, now_ms=T0 + 4999)
    assert e.value.code == htlc.RejectCode.TIMELOCK_NOT_EXPIRED


def test_refund_after_claim_rejected():
    reg = _fresh()
    swap, preimage = _mk_swap(reg, evm_timelock=T0 + 5000)
    reg.lock(swap.evm_leg.leg_id, now_ms=T0)
    reg.claim(swap.evm_leg.leg_id, preimage.hex(), now_ms=T0 + 100)
    with pytest.raises(htlc.HTLCError) as e:
        reg.refund(swap.evm_leg.leg_id, now_ms=T0 + 6000)
    assert e.value.code == htlc.RejectCode.ALREADY_CLAIMED


def test_double_refund_rejected():
    reg = _fresh()
    swap, _ = _mk_swap(reg, evm_timelock=T0 + 1000)
    reg.lock(swap.evm_leg.leg_id, now_ms=T0)
    reg.refund(swap.evm_leg.leg_id, now_ms=T0 + 1000)
    with pytest.raises(htlc.HTLCError) as e:
        reg.refund(swap.evm_leg.leg_id, now_ms=T0 + 2000)
    assert e.value.code == htlc.RejectCode.ALREADY_REFUNDED


def test_refund_without_lock_rejected():
    reg = _fresh()
    swap, _ = _mk_swap(reg, evm_timelock=T0 + 1000)
    with pytest.raises(htlc.HTLCError) as e:
        reg.refund(swap.evm_leg.leg_id, now_ms=T0 + 1000)
    assert e.value.code == htlc.RejectCode.NOT_LOCKED


# ── Full happy-path atomic swap ───────────────────────────────────────


def test_atomic_swap_full_flow():
    """
    Alice on Casper wants EVM tokens from Bob.
    - Alice picks s, locks Casper leg first.
    - Bob sees hashlock H = sha256(s), locks EVM leg.
    - Alice reveals s claiming EVM leg → Bob observes s → claims Casper leg.
    Both claimed. atomic_outcome == "completed".
    """
    reg = _fresh()
    swap, preimage = _mk_swap(reg)

    reg.lock(swap.casper_leg.leg_id, now_ms=T0)  # step 1: Alice locks A
    reg.lock(swap.evm_leg.leg_id, now_ms=T0 + 60_000)  # step 2: Bob locks B (later)

    # step 3: Alice claims B by revealing s
    reg.claim(swap.evm_leg.leg_id, preimage.hex(), now_ms=T0 + 120_000)
    # step 4: Bob observes s, claims A
    reg.claim(swap.casper_leg.leg_id, preimage.hex(), now_ms=T0 + 180_000)

    summary = reg.swap_state_summary(swap.swap_id)
    assert summary["atomic_outcome"] == "completed"
    assert summary["safety_violation"] is False
    assert summary["revealed_preimage_hex"] == preimage.hex()


def test_both_refund_atomic_abort():
    reg = _fresh()
    swap, _ = _mk_swap(reg, casper_timelock=T0 + 2000, evm_timelock=T0 + 1000)
    reg.lock(swap.casper_leg.leg_id, now_ms=T0)
    reg.lock(swap.evm_leg.leg_id, now_ms=T0)
    reg.refund(swap.evm_leg.leg_id, now_ms=T0 + 1000)
    reg.refund(swap.casper_leg.leg_id, now_ms=T0 + 2000)
    summary = reg.swap_state_summary(swap.swap_id)
    assert summary["atomic_outcome"] == "aborted"
    assert summary["safety_violation"] is False


# ── Safety property: preimage-linkage & no mixed outcome via API ─────


def test_reveal_preimage_observer():
    """After claim on either side, reveal_preimage(swap_id) surfaces s."""
    reg = _fresh()
    swap, preimage = _mk_swap(reg)
    reg.lock(swap.evm_leg.leg_id, now_ms=T0)
    assert reg.reveal_preimage(swap.swap_id) is None
    reg.claim(swap.evm_leg.leg_id, preimage.hex(), now_ms=T0 + 100)
    assert reg.reveal_preimage(swap.swap_id) == preimage.hex()


def test_deterministic_tx_hashes():
    """Same inputs → identical mock tx hashes across runs (reproducibility)."""
    reg1 = _fresh()
    reg2 = _fresh()
    p = b"\x22" * 32
    s1, _ = _mk_swap(reg1, preimage=p)
    s2, _ = _mk_swap(reg2, preimage=p)
    reg1.lock(s1.evm_leg.leg_id, now_ms=T0)
    reg2.lock(s2.evm_leg.leg_id, now_ms=T0)
    l1 = reg1.get_leg(s1.evm_leg.leg_id)
    l2 = reg2.get_leg(s2.evm_leg.leg_id)
    assert l1.lock_tx_hash == l2.lock_tx_hash


# ── Hypothesis property tests ─────────────────────────────────────────


@settings(max_examples=40, deadline=None)
@given(
    preimage=st.binary(min_size=32, max_size=32),
    casper_amt=st.integers(min_value=1, max_value=10**12),
    evm_amt=st.integers(min_value=1, max_value=10**12),
    t_a=st.integers(min_value=1_000_000, max_value=10_000_000),
    delta=st.integers(min_value=1, max_value=999_999),  # T_a - T_b > 0
)
def test_property_happy_path_always_completes(preimage, casper_amt, evm_amt, t_a, delta):
    """For any valid inputs, a full happy-path flow ends with atomic_outcome=completed."""
    reg = _fresh()
    t_b = t_a - delta  # ensure T_b < T_a
    swap, _ = _mk_swap(
        reg,
        preimage=preimage,
        casper_timelock=T0 + t_a,
        evm_timelock=T0 + t_b,
        casper_amount=casper_amt,
        evm_amount=evm_amt,
    )
    reg.lock(swap.casper_leg.leg_id, now_ms=T0)
    reg.lock(swap.evm_leg.leg_id, now_ms=T0)
    reg.claim(swap.evm_leg.leg_id, preimage.hex(), now_ms=T0 + 10)
    reg.claim(swap.casper_leg.leg_id, preimage.hex(), now_ms=T0 + 20)
    summary = reg.swap_state_summary(swap.swap_id)
    assert summary["atomic_outcome"] == "completed"
    assert summary["safety_violation"] is False


@settings(max_examples=30, deadline=None)
@given(
    preimage=st.binary(min_size=32, max_size=32),
    forged=st.binary(min_size=32, max_size=32),
)
def test_property_forged_preimage_never_claims(preimage, forged):
    """No preimage other than the exact secret ever produces a CLAIMED status."""
    if forged == preimage:
        return  # trivial equality — skip
    reg = _fresh()
    swap, _ = _mk_swap(reg, preimage=preimage)
    reg.lock(swap.evm_leg.leg_id, now_ms=T0)
    with pytest.raises(htlc.HTLCError) as e:
        reg.claim(swap.evm_leg.leg_id, forged.hex(), now_ms=T0 + 10)
    assert e.value.code == htlc.RejectCode.PREIMAGE_MISMATCH


# ── Cross-leg isolation ───────────────────────────────────────────────


def test_two_swaps_isolated():
    """Two swaps with different hashlocks in the same registry don't share state."""
    reg = _fresh()
    p1 = b"\x33" * 32
    p2 = b"\x44" * 32
    s1, _ = _mk_swap(reg, preimage=p1)
    s2, _ = _mk_swap(reg, preimage=p2)
    reg.lock(s1.evm_leg.leg_id, now_ms=T0)
    reg.lock(s2.evm_leg.leg_id, now_ms=T0)
    reg.claim(s1.evm_leg.leg_id, p1.hex(), now_ms=T0 + 10)
    # s2 must NOT be claimed
    leg2 = reg.get_leg(s2.evm_leg.leg_id)
    assert leg2.status == htlc.HTLCStatus.LOCKED
    assert reg.reveal_preimage(s2.swap_id) is None


def test_preimage_from_swap_A_cannot_claim_swap_B():
    reg = _fresh()
    p1 = b"\x55" * 32
    p2 = b"\x66" * 32
    s1, _ = _mk_swap(reg, preimage=p1)
    s2, _ = _mk_swap(reg, preimage=p2)
    reg.lock(s2.evm_leg.leg_id, now_ms=T0)
    with pytest.raises(htlc.HTLCError) as e:
        reg.claim(s2.evm_leg.leg_id, p1.hex(), now_ms=T0 + 10)
    assert e.value.code == htlc.RejectCode.PREIMAGE_MISMATCH


# ── Snapshot / summary edge cases ─────────────────────────────────────


def test_summary_for_unknown_swap_is_none():
    reg = _fresh()
    assert reg.swap_state_summary("does-not-exist") is None
    assert reg.reveal_preimage("does-not-exist") is None
    assert reg.get_swap("does-not-exist") is None
