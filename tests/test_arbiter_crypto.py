"""Tests for on-chain-equivalent arbiter vote signature verification.

Mirrors the crypto check performed inside the Rust `resolve()` entry point
(contracts/escrow/src/main.rs): each arbiter vote must be a real Ed25519
signature, from a registered pubkey, over the exact escrow + verdict.
"""

from __future__ import annotations

import tempfile

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat

from sdk.arbiter_signing import ED25519_TAG_HEX, sign_arbiter_vote
from server.arbiter_crypto import (
    _pubkey_from_hex,
    _signature_bytes_from_hex,
    build_insurance_claim_message,
    build_resolve_message,
    count_valid_insurance_claim_votes,
    count_valid_votes,
)


def _write_pem(private_key: Ed25519PrivateKey) -> str:
    pem = private_key.private_bytes(
        encoding=Encoding.PEM,
        format=PrivateFormat.PKCS8,
        encryption_algorithm=NoEncryption(),
    )
    f = tempfile.NamedTemporaryFile(mode="wb", suffix=".pem", delete=False)
    f.write(pem)
    f.close()
    return f.name


def _make_arbiter() -> tuple[str, Ed25519PrivateKey]:
    """Generate a throwaway Ed25519 keypair and return (pem_path, private_key)."""
    private_key = Ed25519PrivateKey.generate()
    return _write_pem(private_key), private_key


class TestSignAndVerifyRoundTrip:
    def test_valid_vote_verifies(self):
        pem_path, _ = _make_arbiter()
        pubkey_hex, sig_hex = sign_arbiter_vote(pem_path, "a" * 64, "receiver")
        valid = count_valid_votes([pubkey_hex], [sig_hex], (pubkey_hex,), "a" * 64, "receiver")
        assert valid == 1

    def test_threshold_met_with_enough_valid_votes(self):
        arbiters = [_make_arbiter() for _ in range(5)]
        registered = tuple(sign_arbiter_vote(pem, "b" * 64, "sender")[0] for pem, _ in arbiters)
        pubkeys, sigs = [], []
        for pem, _ in arbiters[:3]:
            pk, sig = sign_arbiter_vote(pem, "b" * 64, "sender")
            pubkeys.append(pk)
            sigs.append(sig)
        assert count_valid_votes(pubkeys, sigs, registered, "b" * 64, "sender") == 3


class TestRejectsForgedOrMisusedVotes:
    def test_signature_from_unregistered_key_is_rejected(self):
        pem_path, _ = _make_arbiter()
        other_pem, _ = _make_arbiter()
        pubkey_hex, sig_hex = sign_arbiter_vote(pem_path, "c" * 64, "receiver")
        other_pubkey_hex, _ = sign_arbiter_vote(other_pem, "c" * 64, "receiver")
        # pubkey_hex is a real signer but NOT in the registered set
        valid = count_valid_votes([pubkey_hex], [sig_hex], (other_pubkey_hex,), "c" * 64, "receiver")
        assert valid == 0

    def test_signature_cannot_be_replayed_for_different_escrow(self):
        pem_path, _ = _make_arbiter()
        pubkey_hex, sig_for_escrow_1 = sign_arbiter_vote(pem_path, "d" * 64, "receiver")
        # Same arbiter, same verdict word, but a DIFFERENT escrow hash --
        # the old signature must not verify against the new message.
        valid = count_valid_votes([pubkey_hex], [sig_for_escrow_1], (pubkey_hex,), "e" * 64, "receiver")
        assert valid == 0

    def test_signature_cannot_be_replayed_for_flipped_verdict(self):
        pem_path, _ = _make_arbiter()
        pubkey_hex, sig_for_receiver = sign_arbiter_vote(pem_path, "f" * 64, "receiver")
        # Same escrow, but flipping the verdict must invalidate the vote --
        # otherwise a "favor_receiver" vote could be replayed as "favor_sender".
        valid = count_valid_votes([pubkey_hex], [sig_for_receiver], (pubkey_hex,), "f" * 64, "sender")
        assert valid == 0

    def test_tampered_signature_bytes_rejected(self):
        pem_path, _ = _make_arbiter()
        pubkey_hex, sig_hex = sign_arbiter_vote(pem_path, "0" * 64, "sender")
        tampered = sig_hex[:-2] + ("00" if sig_hex[-2:] != "00" else "ff")
        valid = count_valid_votes([pubkey_hex], [tampered], (pubkey_hex,), "0" * 64, "sender")
        assert valid == 0

    def test_duplicate_vote_from_same_arbiter_counts_once(self):
        pem_path, _ = _make_arbiter()
        pubkey_hex, sig_hex = sign_arbiter_vote(pem_path, "1" * 64, "sender")
        # Same real (pubkey, signature) submitted 3x must not let one
        # arbiter satisfy the whole threshold alone.
        valid = count_valid_votes([pubkey_hex] * 3, [sig_hex] * 3, (pubkey_hex,), "1" * 64, "sender")
        assert valid == 1

    def test_malformed_hex_does_not_crash(self):
        valid = count_valid_votes(["not-hex-at-all"], ["also-not-hex"], ("not-hex-at-all",), "2" * 64, "sender")
        assert valid == 0


class TestCanonicalMessageFormat:
    def test_message_binds_service_hash_and_verdict(self):
        assert build_resolve_message("abc", "sender") == b"resolve:abc:sender"
        assert build_resolve_message("abc", "receiver") != build_resolve_message("abc", "sender")

    def test_insurance_claim_message_binds_escrow_claimant_and_amount(self):
        assert build_insurance_claim_message("e1", "aa" * 32, 1000) == f"claim:e1:{'aa' * 32}:1000".encode()
        # Changing any bound field must change the message (no cross-field replay).
        assert build_insurance_claim_message("e1", "aa" * 32, 1000) != build_insurance_claim_message(
            "e2", "aa" * 32, 1000
        )
        assert build_insurance_claim_message("e1", "aa" * 32, 1000) != build_insurance_claim_message(
            "e1", "bb" * 32, 1000
        )
        assert build_insurance_claim_message("e1", "aa" * 32, 1000) != build_insurance_claim_message(
            "e1", "aa" * 32, 2000
        )


def _sign_insurance_claim(
    private_key: Ed25519PrivateKey, escrow_id: str, claimant: str, amount: int
) -> tuple[str, str]:
    message = build_insurance_claim_message(escrow_id, claimant, amount)
    signature = private_key.sign(message)
    pubkey_hex = ED25519_TAG_HEX + private_key.public_key().public_bytes_raw().hex()
    return pubkey_hex, ED25519_TAG_HEX + signature.hex()


class TestCountValidInsuranceClaimVotes:
    def test_valid_quorum_counted(self):
        arbiters = [Ed25519PrivateKey.generate() for _ in range(3)]
        votes = [_sign_insurance_claim(pk, "e1", "cc" * 32, 500) for pk in arbiters]
        registered = tuple(v[0] for v in votes)
        valid = count_valid_insurance_claim_votes(
            [v[0] for v in votes], [v[1] for v in votes], registered, "e1", "cc" * 32, 500
        )
        assert valid == 3

    def test_vote_cannot_be_replayed_for_different_amount(self):
        pk = Ed25519PrivateKey.generate()
        pubkey_hex, sig_hex = _sign_insurance_claim(pk, "e1", "cc" * 32, 500)
        valid = count_valid_insurance_claim_votes([pubkey_hex], [sig_hex], (pubkey_hex,), "e1", "cc" * 32, 999)
        assert valid == 0

    def test_vote_cannot_be_replayed_for_different_claimant(self):
        pk = Ed25519PrivateKey.generate()
        pubkey_hex, sig_hex = _sign_insurance_claim(pk, "e1", "cc" * 32, 500)
        valid = count_valid_insurance_claim_votes([pubkey_hex], [sig_hex], (pubkey_hex,), "e1", "dd" * 32, 500)
        assert valid == 0

    def test_unregistered_signer_rejected(self):
        pk = Ed25519PrivateKey.generate()
        other_pk = Ed25519PrivateKey.generate()
        pubkey_hex, sig_hex = _sign_insurance_claim(pk, "e1", "cc" * 32, 500)
        other_pubkey_hex, _ = _sign_insurance_claim(other_pk, "e1", "cc" * 32, 500)
        valid = count_valid_insurance_claim_votes([pubkey_hex], [sig_hex], (other_pubkey_hex,), "e1", "cc" * 32, 500)
        assert valid == 0


class TestPubkeyFromHex:
    """Direct tests for the ed25519-tag-prefixed pubkey/signature hex
    decoders these routines feed into count_valid_votes -- previously only
    exercised indirectly through the "malformed hex does not crash" case."""

    def test_rejects_missing_ed25519_tag(self):
        assert _pubkey_from_hex("aa" * 32) is None  # no "01" tag prefix

    def test_rejects_invalid_hex_after_tag(self):
        assert _pubkey_from_hex("01" + "zz" * 32) is None

    def test_rejects_wrong_length_key(self):
        assert _pubkey_from_hex("01" + "aa" * 10) is None  # too short

    def test_accepts_valid_ed25519_pubkey(self):
        key = Ed25519PrivateKey.generate()
        raw_hex = key.public_key().public_bytes_raw().hex()
        assert _pubkey_from_hex("01" + raw_hex) is not None


class TestSignatureBytesFromHex:
    def test_rejects_missing_ed25519_tag(self):
        assert _signature_bytes_from_hex("bb" * 64) is None

    def test_rejects_invalid_hex_after_tag(self):
        assert _signature_bytes_from_hex("01" + "zz" * 64) is None

    def test_rejects_wrong_length_signature(self):
        assert _signature_bytes_from_hex("01" + "aa" * 10) is None

    def test_accepts_valid_length_signature(self):
        sig_hex = "01" + "aa" * 64
        result = _signature_bytes_from_hex(sig_hex)
        assert result is not None
        assert len(result) == 64
