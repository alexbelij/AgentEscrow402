"""
Cross-check the Python two_key_account SDK against the Rust contract's
signed-message construction. The Rust invariant is enforced in
``contracts/tests/src/two_key_account_property_tests.rs``; here we verify
the Python side produces byte-for-byte identical output for the same
inputs, so on-chain and off-chain signers cannot disagree.
"""

import hashlib

import pytest

from sdk.two_key_account import (
    DOMAIN,
    AccountState,
    build_signed_message,
    payload_hash_of,
    prepare_call,
)


def test_domain_constant():
    assert DOMAIN == "ae402:two-key:v1"


@pytest.mark.parametrize(
    "action,contract_id,nonce,payload,expected",
    [
        (
            "exec",
            "abc123",
            0,
            "phash",
            b"ae402:two-key:v1:exec:abc123:0:phash",
        ),
        (
            "freeze",
            "deadbeef" * 4,
            42,
            hashlib.sha256(b"").hexdigest(),
            (b"ae402:two-key:v1:freeze:" + (b"deadbeef" * 4) + b":42:" + hashlib.sha256(b"").hexdigest().encode()),
        ),
        (
            "rotate_hot",
            "c",
            18446744073709551615,  # u64::MAX
            "p",
            b"ae402:two-key:v1:rotate_hot:c:18446744073709551615:p",
        ),
    ],
)
def test_signed_message_matches_rust_layout(action, contract_id, nonce, payload, expected):
    assert build_signed_message(action, contract_id, nonce, payload) == expected


def test_nonce_bounds_enforced():
    with pytest.raises(ValueError):
        build_signed_message("exec", "c", -1, "p")
    with pytest.raises(ValueError):
        build_signed_message("exec", "c", 2**64, "p")


def test_action_role_mismatch_raises():
    with pytest.raises(ValueError):
        build_signed_message("freeze", "c", 0, "p", role="hot")
    with pytest.raises(ValueError):
        build_signed_message("exec", "c", 0, "p", role="cold")


def test_action_no_colon():
    with pytest.raises(ValueError):
        build_signed_message("bad:action", "c", 0, "p")  # type: ignore[arg-type]


def test_payload_hash_of_matches_sha256_hex():
    payload = b"hello world"
    assert payload_hash_of(payload) == hashlib.sha256(payload).hexdigest()


def _dummy_sign(msg: bytes) -> bytes:
    # Deterministic dummy: sha256 of the message (NOT real Ed25519 — just
    # exercising SDK wiring here; real signers plug in ed25519-dalek/hardware).
    return hashlib.sha256(msg).digest()


def _state(**overrides):
    base = dict(
        contract_id="contract-abc",
        cold_pubkey_hex="0" * 66,
        hot_pubkey_hex="1" * 66,
        cold_nonce=3,
        hot_nonce=7,
        frozen=False,
        renounced=False,
        hot_spend_cap_motes=1_000_000_000,
    )
    base.update(overrides)
    return AccountState(**base)


def test_prepare_call_hot_uses_hot_nonce_and_hot_pubkey():
    state = _state()
    call = prepare_call(state, "exec", b"payload", _dummy_sign)
    assert call.role == "hot"
    assert call.nonce == 7
    assert call.pubkey_hex == state.hot_pubkey_hex
    assert call.payload_hash == payload_hash_of(b"payload")
    args = call.named_args()
    assert args["hot_pubkey"] == state.hot_pubkey_hex
    assert args["nonce"] == 7
    assert "cold_pubkey" not in args


def test_prepare_call_cold_uses_cold_nonce_and_cold_pubkey():
    state = _state()
    call = prepare_call(state, "freeze", b"", _dummy_sign)
    assert call.role == "cold"
    assert call.nonce == 3
    assert call.pubkey_hex == state.cold_pubkey_hex
    args = call.named_args()
    assert args["cold_pubkey"] == state.cold_pubkey_hex


def test_prepare_call_rejects_frozen_hot():
    state = _state(frozen=True)
    with pytest.raises(RuntimeError, match="frozen or renounced"):
        prepare_call(state, "exec", b"p", _dummy_sign)


def test_prepare_call_rejects_renounced_cold():
    state = _state(renounced=True)
    with pytest.raises(RuntimeError, match="renounced"):
        prepare_call(state, "rotate_hot", b"p", _dummy_sign)


def test_prepare_call_allows_admin_when_frozen_only():
    # Freeze is a hot-exec halt; cold key can still admin (unfreeze / renounce).
    state = _state(frozen=True)
    call = prepare_call(state, "unfreeze", b"", _dummy_sign)
    assert call.role == "cold"
