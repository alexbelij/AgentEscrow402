"""Unit tests for the offline signature verifier.

Mirrors the coverage of ``sdk-ts/verify.test.ts`` — canonical-message
byte parity, malformed input tolerance, dedup by pubkey, non-registered
rejection, valid signature acceptance.
"""

from __future__ import annotations

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from agentescrow402_sdk.verify import (
    build_cap_approval_message,
    build_insurance_claim_message,
    build_resolve_message,
    count_valid_cap_approval_votes,
    count_valid_insurance_claim_votes,
    count_valid_votes,
    verify_ed25519_vote,
)

# ---------------------------------------------------------------------------
# Canonical message byte parity.
# ---------------------------------------------------------------------------


def test_build_resolve_message_shape():
    msg = build_resolve_message("service_hash_ab", "receiver_xy")
    assert msg == b"resolve:service_hash_ab:receiver_xy"


def test_build_cap_approval_message_shape():
    assert build_cap_approval_message("release", "sh1") == b"release:sh1:cap_approval"
    assert build_cap_approval_message("reveal_swap", "sh2") == b"reveal_swap:sh2:cap_approval"


def test_build_insurance_claim_message_shape():
    msg = build_insurance_claim_message("escrow_1", "ab" * 32, 12345)
    assert msg == b"claim:escrow_1:" + (b"ab" * 32) + b":12345"


# ---------------------------------------------------------------------------
# Malformed input tolerance — verify_ed25519_vote never raises.
# ---------------------------------------------------------------------------


def test_verify_rejects_empty_pubkey():
    assert verify_ed25519_vote("", "01" + "aa" * 64, b"msg") is False


def test_verify_rejects_wrong_tag():
    # Missing the "01" tag → immediately False.
    assert verify_ed25519_vote("02" + "aa" * 32, "01" + "aa" * 64, b"msg") is False


def test_verify_rejects_odd_length_hex():
    assert verify_ed25519_vote("01abc", "01" + "aa" * 64, b"msg") is False


def test_verify_rejects_wrong_pubkey_size():
    # 30 bytes instead of 32.
    assert verify_ed25519_vote("01" + "aa" * 30, "01" + "aa" * 64, b"msg") is False


def test_verify_rejects_wrong_sig_size():
    priv = Ed25519PrivateKey.generate()
    pub_hex = "01" + priv.public_key().public_bytes_raw().hex()
    # 60 bytes sig instead of 64.
    assert verify_ed25519_vote(pub_hex, "01" + "bb" * 60, b"msg") is False


def test_verify_rejects_forged_signature():
    priv = Ed25519PrivateKey.generate()
    pub_hex = "01" + priv.public_key().public_bytes_raw().hex()
    bad_sig = "01" + "cc" * 64  # random bytes, not a real signature.
    assert verify_ed25519_vote(pub_hex, bad_sig, b"msg") is False


# ---------------------------------------------------------------------------
# Positive path — real Ed25519 signature over canonical message verifies.
# ---------------------------------------------------------------------------


def _fresh_arbiter():
    """Return (pubkey_hex, private_key) with the "01" tag prefix."""
    priv = Ed25519PrivateKey.generate()
    pub_hex = "01" + priv.public_key().public_bytes_raw().hex()
    return pub_hex, priv


def _sign(priv: Ed25519PrivateKey, message: bytes) -> str:
    return "01" + priv.sign(message).hex()


def test_verify_valid_resolve_vote():
    pub_hex, priv = _fresh_arbiter()
    message = build_resolve_message("sh", "recv")
    sig_hex = _sign(priv, message)
    assert verify_ed25519_vote(pub_hex, sig_hex, message) is True


def test_verify_rejects_signature_for_wrong_message():
    pub_hex, priv = _fresh_arbiter()
    sig_hex = _sign(priv, build_resolve_message("sh", "recv"))
    # Verify against a *different* message → False.
    assert verify_ed25519_vote(pub_hex, sig_hex, b"other message") is False


# ---------------------------------------------------------------------------
# count_valid_votes — dedup, non-registered filtering, positive/negative mix.
# ---------------------------------------------------------------------------


def test_count_valid_votes_positive():
    pub1, priv1 = _fresh_arbiter()
    pub2, priv2 = _fresh_arbiter()
    pub3, priv3 = _fresh_arbiter()
    msg = build_resolve_message("sh", "recv")
    valid = count_valid_votes(
        pubkeys=[pub1, pub2, pub3],
        signatures=[_sign(priv1, msg), _sign(priv2, msg), _sign(priv3, msg)],
        registered=(pub1, pub2, pub3),
        service_hash="sh",
        in_favor_of="recv",
    )
    assert valid == 3


def test_count_valid_votes_dedup_by_pubkey():
    pub1, priv1 = _fresh_arbiter()
    msg = build_resolve_message("sh", "recv")
    sig = _sign(priv1, msg)
    # Same pubkey submitted 3 times → counted once.
    valid = count_valid_votes(
        pubkeys=[pub1, pub1, pub1],
        signatures=[sig, sig, sig],
        registered=(pub1,),
        service_hash="sh",
        in_favor_of="recv",
    )
    assert valid == 1


def test_count_valid_votes_rejects_non_registered():
    pub1, priv1 = _fresh_arbiter()
    pub2, _ = _fresh_arbiter()  # not in registered set
    msg = build_resolve_message("sh", "recv")
    valid = count_valid_votes(
        pubkeys=[pub1, pub2],
        signatures=[_sign(priv1, msg), "01" + "aa" * 64],
        registered=(pub1,),
        service_hash="sh",
        in_favor_of="recv",
    )
    assert valid == 1


def test_count_valid_votes_mixed_valid_and_forged():
    pub1, priv1 = _fresh_arbiter()
    pub2, _ = _fresh_arbiter()
    pub3, priv3 = _fresh_arbiter()
    msg = build_resolve_message("sh", "recv")
    valid = count_valid_votes(
        pubkeys=[pub1, pub2, pub3],
        signatures=[_sign(priv1, msg), "01" + "aa" * 64, _sign(priv3, msg)],
        registered=(pub1, pub2, pub3),
        service_hash="sh",
        in_favor_of="recv",
    )
    assert valid == 2


# ---------------------------------------------------------------------------
# count_valid_cap_approval_votes / count_valid_insurance_claim_votes smoke.
# ---------------------------------------------------------------------------


def test_count_valid_cap_approval_votes():
    pub1, priv1 = _fresh_arbiter()
    pub2, priv2 = _fresh_arbiter()
    msg = build_cap_approval_message("release", "sh")
    valid = count_valid_cap_approval_votes(
        pubkeys=[pub1, pub2],
        signatures=[_sign(priv1, msg), _sign(priv2, msg)],
        registered=(pub1, pub2),
        action="release",
        service_hash="sh",
    )
    assert valid == 2


def test_count_valid_insurance_claim_votes():
    pub1, priv1 = _fresh_arbiter()
    msg = build_insurance_claim_message("escrow_1", "ab" * 32, 500)
    valid = count_valid_insurance_claim_votes(
        pubkeys=[pub1],
        signatures=[_sign(priv1, msg)],
        registered=(pub1,),
        escrow_id="escrow_1",
        claimant_account_hash="ab" * 32,
        amount=500,
    )
    assert valid == 1
