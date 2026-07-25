"""Unit tests for server/confidential_escrow.py — W.2 wired into the escrow
lifecycle (bridges server/zk_amount.py's standalone crypto primitive into
create/get/reveal instead of leaving it as a disconnected /zk/* demo).

Bit-width kept small (8/16) in most tests for speed, matching the convention
in tests/test_zk_amount.py; a couple of tests exercise the real
`ESCROW_RANGE_BITS=48` default explicitly (marked slow — each proves+verifies
in ~1-2s on this hardware) to prove the actual escrow-facing default works,
not just the fast-path bit counts.
"""

from __future__ import annotations

import pytest

from server import confidential_escrow as ce
from server import zk_amount as z

SH_A = "a" * 64
SH_B = "b" * 64


class TestSealAmount:
    def test_seal_returns_expected_shape(self):
        sealed = ce.seal_amount(100, SH_A, bits=8)
        assert set(sealed.keys()) == {"commitment", "range_proof", "range_proof_bits", "blinding"}
        assert sealed["range_proof_bits"] == 8
        assert len(sealed["blinding"]) == 64  # 32 bytes hex

    def test_seal_commitment_verifies_as_range_proof(self):
        sealed = ce.seal_amount(200, SH_A, bits=8)
        commitment = z.Commitment(C=sealed["commitment"])
        proof = z.RangeProof.from_dict(sealed["range_proof"])
        assert z.verify_range(commitment, proof, transcript=SH_A.encode())

    def test_seal_rejects_amount_out_of_range(self):
        with pytest.raises(ce.ConfidentialEscrowError):
            ce.seal_amount(256, SH_A, bits=8)  # 2**8 == 256, out of [0, 256)

    def test_seal_rejects_negative_amount(self):
        with pytest.raises(ce.ConfidentialEscrowError):
            ce.seal_amount(-1, SH_A, bits=8)

    def test_seal_max_value_fits(self):
        sealed = ce.seal_amount(255, SH_A, bits=8)  # 2**8 - 1, inclusive max
        commitment = z.Commitment(C=sealed["commitment"])
        proof = z.RangeProof.from_dict(sealed["range_proof"])
        assert z.verify_range(commitment, proof, transcript=SH_A.encode())

    def test_seal_default_bits_is_escrow_range_bits(self):
        sealed = ce.seal_amount(1000, SH_A)  # comfortably fits in 48 default bits
        assert sealed["range_proof_bits"] == ce.ESCROW_RANGE_BITS

    def test_two_seals_of_same_amount_produce_different_commitments(self):
        # Fresh random blinding each call — hiding property holds even for
        # the exact same (amount, transcript) pair.
        s1 = ce.seal_amount(200, SH_A, bits=8)
        s2 = ce.seal_amount(200, SH_A, bits=8)
        assert s1["commitment"] != s2["commitment"]
        assert s1["blinding"] != s2["blinding"]

    def test_different_transcripts_bind_differently(self):
        # Same amount+blinding-derivation-inputs but different service_hash
        # transcript must not let a proof for SH_A be replayed as SH_B's.
        sealed = ce.seal_amount(200, SH_A, bits=8)
        commitment = z.Commitment(C=sealed["commitment"])
        proof = z.RangeProof.from_dict(sealed["range_proof"])
        assert z.verify_range(commitment, proof, transcript=SH_A.encode())
        assert not z.verify_range(commitment, proof, transcript=SH_B.encode())


class TestRedactAmountField:
    def test_noop_when_not_confidential(self):
        record = {"amount": 100, "confidential": False}
        out = ce.redact_amount_field(record)
        assert out == record
        assert out is not record or out["amount"] == 100  # unchanged either way

    def test_noop_when_confidential_key_absent(self):
        record = {"amount": 100}
        out = ce.redact_amount_field(record)
        assert out["amount"] == 100

    def test_redacts_when_confidential_true(self):
        record = {"amount": 999_999, "confidential": True}
        out = ce.redact_amount_field(record)
        assert out["amount"] == ce.REDACTED_AMOUNT
        assert out["amount"] == -1

    def test_does_not_mutate_input(self):
        record = {"amount": 42, "confidential": True}
        ce.redact_amount_field(record)
        assert record["amount"] == 42  # original untouched

    def test_preserves_other_fields(self):
        record = {"amount": 42, "confidential": True, "sender": "abc", "status": "pending"}
        out = ce.redact_amount_field(record)
        assert out["sender"] == "abc"
        assert out["status"] == "pending"


class TestReveal:
    def test_reveal_succeeds_with_correct_blinding(self):
        sealed = ce.seal_amount(7777, SH_A, bits=16)
        result = ce.reveal(7777, sealed["blinding"], sealed["commitment"])
        assert result == {"amount": 7777, "verified": True}

    def test_reveal_fails_with_wrong_blinding(self):
        sealed = ce.seal_amount(7777, SH_A, bits=16)
        wrong_blinding = "ab" * 32
        with pytest.raises(ce.ConfidentialEscrowError):
            ce.reveal(7777, wrong_blinding, sealed["commitment"])

    def test_reveal_fails_with_wrong_stored_amount(self):
        # Simulates a tampered/corrupted ledger amount not matching the
        # commitment — should fail exactly like a wrong blinding would,
        # since both are just "wrong opening" from the crypto's perspective.
        sealed = ce.seal_amount(7777, SH_A, bits=16)
        with pytest.raises(ce.ConfidentialEscrowError):
            ce.reveal(7778, sealed["blinding"], sealed["commitment"])

    def test_reveal_rejects_malformed_blinding_hex(self):
        sealed = ce.seal_amount(100, SH_A, bits=8)
        with pytest.raises(ce.ConfidentialEscrowError):
            ce.reveal(100, "not-hex-at-all!!", sealed["commitment"])

    def test_reveal_rejects_malformed_commitment(self):
        with pytest.raises(ce.ConfidentialEscrowError):
            ce.reveal(100, "aa" * 32, "not-a-valid-commitment")


class TestVerifySeal:
    def test_verify_seal_true_for_valid_seal(self):
        sealed = ce.seal_amount(3000, SH_A, bits=16)
        assert ce.verify_seal(sealed["commitment"], sealed["range_proof"], SH_A, bits=16) is True

    def test_verify_seal_false_for_wrong_transcript(self):
        sealed = ce.seal_amount(3000, SH_A, bits=16)
        assert ce.verify_seal(sealed["commitment"], sealed["range_proof"], SH_B, bits=16) is False

    def test_verify_seal_false_for_wrong_bit_count(self):
        sealed = ce.seal_amount(3000, SH_A, bits=16)
        assert ce.verify_seal(sealed["commitment"], sealed["range_proof"], SH_A, bits=8) is False

    def test_verify_seal_false_for_malformed_commitment(self):
        sealed = ce.seal_amount(3000, SH_A, bits=16)
        assert ce.verify_seal("garbage", sealed["range_proof"], SH_A, bits=16) is False

    def test_verify_seal_false_for_tampered_proof(self):
        sealed = ce.seal_amount(3000, SH_A, bits=16)
        tampered = dict(sealed["range_proof"])
        # Flip a hex character in the first bit commitment.
        original = tampered["bit_commitments"][0]
        flipped = ("f" if original[2] != "f" else "0") + original[3:]
        tampered["bit_commitments"] = [original[:2] + flipped] + tampered["bit_commitments"][1:]
        assert ce.verify_seal(sealed["commitment"], tampered, SH_A, bits=16) is False


class TestLedgerStore:
    def setup_method(self):
        ce.clear_seal("ledger-test-hash" + "0" * 47)

    def test_store_and_get_seal_roundtrip(self):
        sh = "ledger-test-hash" + "0" * 47
        sealed = ce.seal_amount(100, sh, bits=8)
        ce.store_seal(sh, sealed)
        fetched = ce.get_seal(sh)
        assert fetched is not None
        assert fetched["commitment"] == sealed["commitment"]
        assert fetched["blinding"] == sealed["blinding"]

    def test_get_seal_none_when_absent(self):
        assert ce.get_seal("never-sealed-" + "0" * 51) is None

    def test_clear_seal_removes_entry(self):
        sh = "ledger-test-hash" + "0" * 47
        sealed = ce.seal_amount(100, sh, bits=8)
        ce.store_seal(sh, sealed)
        ce.clear_seal(sh)
        assert ce.get_seal(sh) is None


@pytest.mark.slow
class TestEscrowRangeBitsDefault:
    """Exercise the real ESCROW_RANGE_BITS=48 default end-to-end. Slow
    (~1-2s per test on the hackathon pod) — see docs/ZK_AMOUNT_PRIVACY.md
    perf table; gated the same way test_zk_amount.py gates its 64-bit test."""

    def test_default_bits_seal_and_reveal_roundtrip(self):
        amount = 50_000_000_000  # 50 CSPR in motes
        sealed = ce.seal_amount(amount, SH_A)
        result = ce.reveal(amount, sealed["blinding"], sealed["commitment"])
        assert result["verified"] is True
        assert result["amount"] == amount

    def test_default_bits_max_value_fits(self):
        max_value = (1 << ce.ESCROW_RANGE_BITS) - 1
        sealed = ce.seal_amount(max_value, SH_A)
        assert ce.verify_seal(sealed["commitment"], sealed["range_proof"], SH_A) is True

    def test_default_bits_rejects_over_cap(self):
        over_cap = 1 << ce.ESCROW_RANGE_BITS
        with pytest.raises(ce.ConfidentialEscrowError):
            ce.seal_amount(over_cap, SH_A)
