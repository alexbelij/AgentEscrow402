"""Byte-parity + property tests for the Governance DAO Python SDK.

Every encode/decode/status/message function in ``sdk/governance.py`` is
byte-parity with ``contracts/ae402-governance-dao/src/lib.rs``. The Rust
side has proptest coverage in
``contracts/tests/src/governance_dao_property_tests.rs``; here we assert
the same invariants from Python and pin the exact byte-strings.
"""

from __future__ import annotations

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from sdk.governance import (
    EXECUTION_DOMAIN,
    QUORUM_PERCENT,
    Action,
    AdjustFeeBps,
    GovernanceError,
    PauseProtocol,
    RotateArbiterSet,
    Status,
    UpdateInsurancePool,
    UpdateRangeProof,
    UpdateTimelockDelay,
    build_execution_message,
    decode_params,
    encode_params,
    quorum_threshold,
    resolve_status,
)

# ── Pinned byte-strings (must match Rust proptest exec_msg_shape) ─────


def test_execution_message_shape():
    """Pinned against Rust ``exec_msg_shape``."""
    m = build_execution_message(1, Action.ADJUST_FEE_BPS, "bps=250")
    assert m == "ae402:governance-dao:exec:v1:1:0:bps=250"


def test_execution_domain_matches_rust():
    assert EXECUTION_DOMAIN == "ae402:governance-dao:exec:v1"


def test_quorum_percent_matches_rust():
    assert QUORUM_PERCENT == 30


# ── Encode / decode round-trip ────────────────────────────────────────


@pytest.mark.parametrize(
    "params",
    [
        AdjustFeeBps(bps=0),
        AdjustFeeBps(bps=250),
        AdjustFeeBps(bps=10_000),
        RotateArbiterSet(op="add", value="a" * 66),
        RotateArbiterSet(op="remove", value="b" * 66),
        RotateArbiterSet(op="threshold", value="5"),
        UpdateInsurancePool(max_coverage_bps=5000, cooldown_sec=3600),
        UpdateTimelockDelay(delay_sec=86400),
        UpdateRangeProof(min_bits=8, max_bits=16),
        PauseProtocol(pause=True),
        PauseProtocol(pause=False),
    ],
)
def test_encode_decode_roundtrip(params):
    action, s = encode_params(params)
    back = decode_params(action, s)
    assert back == params


# ── Encoded wire-string parity with Rust proptest cases ───────────────


@pytest.mark.parametrize(
    ("params", "expected_action", "expected_str"),
    [
        (AdjustFeeBps(bps=250), Action.ADJUST_FEE_BPS, "bps=250"),
        (
            RotateArbiterSet(op="threshold", value="5"),
            Action.ROTATE_ARBITER_SET,
            "op=threshold;value=5",
        ),
        (
            UpdateInsurancePool(max_coverage_bps=5000, cooldown_sec=3600),
            Action.UPDATE_INSURANCE_POOL_PARAMS,
            "max_coverage_bps=5000;cooldown_sec=3600",
        ),
        (
            UpdateTimelockDelay(delay_sec=86400),
            Action.UPDATE_TIMELOCK_DELAY,
            "delay_sec=86400",
        ),
        (
            UpdateRangeProof(min_bits=8, max_bits=16),
            Action.UPDATE_RANGE_PROOF_PARAMS,
            "min_bits=8;max_bits=16",
        ),
        (PauseProtocol(pause=True), Action.PAUSE_PROTOCOL, "mode=pause"),
        (PauseProtocol(pause=False), Action.PAUSE_PROTOCOL, "mode=unpause"),
    ],
)
def test_wire_string_parity(params, expected_action, expected_str):
    a, s = encode_params(params)
    assert a == expected_action
    assert s == expected_str


# ── Validation errors (mirror Rust rejection cases) ───────────────────


def test_adjust_fee_bps_over_10000_rejected():
    with pytest.raises(GovernanceError):
        encode_params(AdjustFeeBps(bps=10_001))


def test_rotate_arbiter_bad_op_rejected():
    with pytest.raises(GovernanceError):
        encode_params(RotateArbiterSet(op="nuke", value="1"))


def test_rotate_arbiter_short_hex_rejected():
    with pytest.raises(GovernanceError):
        encode_params(RotateArbiterSet(op="add", value="a" * 64))


def test_rotate_arbiter_non_hex_rejected():
    with pytest.raises(GovernanceError):
        encode_params(RotateArbiterSet(op="add", value="z" * 66))


def test_rotate_arbiter_threshold_zero_rejected():
    with pytest.raises(GovernanceError):
        encode_params(RotateArbiterSet(op="threshold", value="0"))


def test_rotate_arbiter_threshold_over_64_rejected():
    with pytest.raises(GovernanceError):
        encode_params(RotateArbiterSet(op="threshold", value="65"))


def test_insurance_over_10000_rejected():
    with pytest.raises(GovernanceError):
        encode_params(UpdateInsurancePool(max_coverage_bps=10_001, cooldown_sec=0))


def test_timelock_below_hour_rejected():
    with pytest.raises(GovernanceError):
        encode_params(UpdateTimelockDelay(delay_sec=3599))


def test_range_proof_zero_bits_rejected():
    with pytest.raises(GovernanceError):
        encode_params(UpdateRangeProof(min_bits=0, max_bits=8))


def test_range_proof_over_32_bits_rejected():
    with pytest.raises(GovernanceError):
        encode_params(UpdateRangeProof(min_bits=1, max_bits=33))


def test_range_proof_min_greater_than_max_rejected():
    with pytest.raises(GovernanceError):
        encode_params(UpdateRangeProof(min_bits=16, max_bits=8))


# ── Decode error paths ────────────────────────────────────────────────


def test_decode_unknown_action_rejected():
    with pytest.raises(GovernanceError):
        decode_params(999, "bps=1")


def test_decode_missing_key_rejected():
    with pytest.raises(GovernanceError):
        decode_params(Action.ADJUST_FEE_BPS, "wrong_key=1")


def test_decode_malformed_kv_rejected():
    with pytest.raises(GovernanceError):
        decode_params(Action.ADJUST_FEE_BPS, "bpsis1")


def test_decode_empty_pause_mode_rejected():
    with pytest.raises(GovernanceError):
        decode_params(Action.PAUSE_PROTOCOL, "mode=maybe")


# ── Quorum math parity (mirrors Rust proptests) ───────────────────────


def test_quorum_zero():
    assert quorum_threshold(0) == 0


@pytest.mark.parametrize(
    ("total", "percent", "expected"),
    [(1_000, 30, 300), (1_000, 50, 500), (1_000, 100, 1_000)],
)
def test_quorum_matches_percent(total, percent, expected):
    assert quorum_threshold(total, percent) == expected


@given(total=st.integers(min_value=0, max_value=2**63 - 1))
def test_quorum_never_exceeds_total(total: int):
    assert quorum_threshold(total, QUORUM_PERCENT) <= total


@given(total=st.integers(min_value=0, max_value=10**9))
def test_quorum_monotonic_in_percent(total: int):
    assert quorum_threshold(total, 30) <= quorum_threshold(total, 50)
    assert quorum_threshold(total, 50) <= quorum_threshold(total, 100)


# ── Status transitions parity ─────────────────────────────────────────


def test_status_open_below_quorum():
    assert resolve_status(10, 5, 100, 500, 1000) == Status.ACTIVE


def test_status_open_quorum_passed():
    assert resolve_status(25, 5, 100, 500, 1000) == Status.PASSED


def test_status_open_quorum_tie_rejected():
    assert resolve_status(15, 15, 100, 500, 1000) == Status.REJECTED


def test_status_closed_no_quorum_expired():
    assert resolve_status(5, 3, 100, 2000, 1000) == Status.EXPIRED


def test_status_closed_quorum_passed():
    assert resolve_status(20, 15, 100, 2000, 1000) == Status.PASSED


def test_status_closed_quorum_rejected():
    assert resolve_status(15, 20, 100, 2000, 1000) == Status.REJECTED


@given(
    vf=st.integers(min_value=0, max_value=1_000_000),
    va=st.integers(min_value=0, max_value=1_000_000),
    total=st.integers(min_value=0, max_value=1_000_000),
    t=st.integers(min_value=0, max_value=2**63 - 1),
    ve=st.integers(min_value=0, max_value=2**63 - 1),
)
def test_status_only_emits_known_codes(vf, va, total, t, ve):
    s = resolve_status(vf, va, total, t, ve)
    assert s in {Status.ACTIVE, Status.PASSED, Status.REJECTED, Status.EXPIRED}


# ── Execution message injective (mirrors Rust proptests) ──────────────


@given(
    id1=st.integers(min_value=0, max_value=2**63 - 1),
    id2=st.integers(min_value=0, max_value=2**63 - 1),
)
def test_exec_msg_injective_in_id(id1, id2):
    assume(id1 != id2)
    a = build_execution_message(id1, Action.ADJUST_FEE_BPS, "bps=250")
    b = build_execution_message(id2, Action.ADJUST_FEE_BPS, "bps=250")
    assert a != b


@given(
    a1=st.integers(min_value=0, max_value=5),
    a2=st.integers(min_value=0, max_value=5),
    pid=st.integers(min_value=0, max_value=2**32 - 1),
)
def test_exec_msg_injective_in_action(pid, a1, a2):
    assume(a1 != a2)
    m1 = build_execution_message(pid, a1, "x=y")
    m2 = build_execution_message(pid, a2, "x=y")
    assert m1 != m2
