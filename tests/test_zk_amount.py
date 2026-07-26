"""Tests for server/zk_amount.py — Pedersen commitments + range proofs (W.2).

Tests cover:
  * Generator determinism and independence
  * Commitment correctness + hiding + binding
  * Homomorphism (2-way and n-way sum)
  * Range proof soundness (valid proofs verify)
  * Range proof completeness (invalid proofs rejected)
  * Fiat-Shamir transcript binding
  * Wire (de)serialization round-trip
  * Edge cases: amount=0, amount=2^64-1, single-bit, 8-bit sanity

We keep bit-width small (8 or 16) for speed, and one 64-bit end-to-end test
gated behind `pytest.mark.slow` for CI.
"""

from __future__ import annotations

import pytest

from server import zk_amount as z

# ---------------------------------------------------------------------------
# Generators
# ---------------------------------------------------------------------------


class TestGenerators:
    def test_G_is_deterministic(self):
        assert z.generator_G() == z.generator_G()

    def test_H_is_deterministic(self):
        assert z.generator_H() == z.generator_H()

    def test_G_and_H_differ(self):
        assert z.generator_G() != z.generator_H()

    def test_G_is_standard_base_point(self):
        # SEC-1 compressed G starts with 0x02 (even Y) or 0x03 (odd Y).
        # secp256k1 G has y = 0x483A...D4B8, which is even → 0x02 prefix.
        assert z.generator_G()[0] == 0x02

    def test_H_is_valid_curve_point(self):
        pt = z._decode_point(z.generator_H())
        assert z._on_curve(pt)
        assert pt is not None
        assert pt != z._G  # not the base point


# ---------------------------------------------------------------------------
# Commitments
# ---------------------------------------------------------------------------


class TestCommitments:
    def test_commit_returns_commitment_and_blinding(self):
        c, r = z.commit(42)
        assert isinstance(c, z.Commitment)
        assert isinstance(r, int)
        assert 1 <= r < z._N
        assert len(c.to_bytes()) == 33

    def test_open_verifies_correct(self):
        c, r = z.commit(1234)
        assert z.verify_open(c, 1234, r)

    def test_open_rejects_wrong_amount(self):
        c, r = z.commit(1234)
        assert not z.verify_open(c, 1235, r)
        assert not z.verify_open(c, 0, r)

    def test_open_rejects_wrong_blinding(self):
        c, r = z.commit(1234)
        assert not z.verify_open(c, 1234, (r + 1) % z._N)

    def test_deterministic_given_blinding(self):
        c1, _ = z.commit(999, blinding=42)
        c2, _ = z.commit(999, blinding=42)
        assert c1.C == c2.C

    def test_different_blindings_give_different_commitments(self):
        c1, _ = z.commit(999, blinding=42)
        c2, _ = z.commit(999, blinding=43)
        assert c1.C != c2.C

    def test_hiding_property_across_amounts(self):
        # Given fixed blinding, different amounts produce visibly different
        # commitments. Hiding is the STATISTICAL property (uniform over group),
        # which we can't fully test here, but at least each commitment is a
        # valid curve point that doesn't leak the amount plaintext.
        c0, _ = z.commit(0, blinding=42)
        c1, _ = z.commit(1, blinding=42)
        c1m, _ = z.commit(2**63, blinding=42)
        assert len({c0.C, c1.C, c1m.C}) == 3

    def test_rejects_negative_amount(self):
        with pytest.raises(z.ZKError, match="amount must be"):
            z.commit(-1)

    def test_rejects_too_large_amount(self):
        with pytest.raises(z.ZKError, match="amount must be"):
            z.commit(1 << 64)

    def test_zero_amount_commits_correctly(self):
        c, r = z.commit(0)
        assert z.verify_open(c, 0, r)
        assert not z.verify_open(c, 1, r)


# ---------------------------------------------------------------------------
# Homomorphism
# ---------------------------------------------------------------------------


class TestHomomorphism:
    def test_two_way_sum(self):
        c1, r1 = z.commit(100)
        c2, r2 = z.commit(200)
        csum = z.add_commitments(c1, c2)
        expected, _ = z.commit(300, blinding=(r1 + r2) % z._N)
        assert csum.C == expected.C

    def test_batch_sum(self):
        amounts = [10, 20, 30, 40, 50]
        pairs = [z.commit(a) for a in amounts]
        commitments = [c for c, _ in pairs]
        blindings = [r for _, r in pairs]
        csum = z.sum_commitments(commitments)
        expected, _ = z.commit(sum(amounts), blinding=sum(blindings) % z._N)
        assert csum.C == expected.C

    def test_empty_sum_raises(self):
        with pytest.raises(z.ZKError, match="empty"):
            z.sum_commitments([])

    def test_batch_cap_conservation(self):
        # Batch cap use-case: sum of hidden amounts under a cap doesn't leak
        # the individual amounts, but the aggregate is verifiable.
        cap = 1000
        items = [200, 300, 400]  # sum = 900, under cap
        pairs = [z.commit(a) for a in items]
        csum = z.sum_commitments([c for c, _ in pairs])
        blinding_sum = sum(r for _, r in pairs) % z._N
        # Verify aggregate opens to the true total (only auditor knows total).
        assert z.verify_open(csum, sum(items), blinding_sum)
        assert sum(items) < cap


# ---------------------------------------------------------------------------
# Range proofs — small bit widths (fast)
# ---------------------------------------------------------------------------


class TestRangeProof:
    def test_valid_proof_verifies_8bit(self):
        amount = 42
        c, r = z.commit(amount)
        C, proof = z.prove_range(amount, r, bits=8)
        assert C.C == c.C
        assert z.verify_range(C, proof)

    def test_valid_proof_verifies_zero(self):
        c, r = z.commit(0)
        C, proof = z.prove_range(0, r, bits=8)
        assert z.verify_range(C, proof)

    def test_valid_proof_verifies_max_8bit(self):
        amount = 255
        c, r = z.commit(amount)
        C, proof = z.prove_range(amount, r, bits=8)
        assert z.verify_range(C, proof)

    def test_transcript_binding(self):
        c, r = z.commit(42)
        C, proof = z.prove_range(42, r, transcript=b"escrow-1", bits=8)
        assert z.verify_range(C, proof, transcript=b"escrow-1")
        # Same proof with a different transcript must fail.
        assert not z.verify_range(C, proof, transcript=b"escrow-2")
        assert not z.verify_range(C, proof, transcript=b"")

    def test_tampered_bit_commitment_rejected(self):
        c, r = z.commit(42)
        C, proof = z.prove_range(42, r, bits=8)
        # Swap one bit commitment with a re-committed different bit.
        tampered = z.RangeProof(
            bit_commitments=[
                z.generator_G().hex() if i == 0 else bc  # first bit → G (arbitrary)
                for i, bc in enumerate(proof.bit_commitments)
            ],
            or_proofs=proof.or_proofs,
        )
        assert not z.verify_range(C, tampered)

    def test_tampered_or_proof_rejected(self):
        c, r = z.commit(42)
        C, proof = z.prove_range(42, r, bits=8)
        # Corrupt one OR-proof's z0.
        bad_or = z.ORProofBit(
            a0=proof.or_proofs[0].a0,
            a1=proof.or_proofs[0].a1,
            e0=proof.or_proofs[0].e0,
            e1=proof.or_proofs[0].e1,
            z0="00" * 32,  # zero out
            z1=proof.or_proofs[0].z1,
        )
        tampered = z.RangeProof(
            bit_commitments=proof.bit_commitments,
            or_proofs=[bad_or] + list(proof.or_proofs[1:]),
        )
        assert not z.verify_range(C, tampered)

    def test_swapped_bit_commitments_rejected(self):
        c, r = z.commit(0b10100000)  # 160 in 8 bits
        C, proof = z.prove_range(0b10100000, r, bits=8)
        # Swap bit-0 and bit-7 commitments — aggregate no longer matches.
        swapped_bits = list(proof.bit_commitments)
        swapped_bits[0], swapped_bits[7] = swapped_bits[7], swapped_bits[0]
        swapped_or = list(proof.or_proofs)
        swapped_or[0], swapped_or[7] = swapped_or[7], swapped_or[0]
        tampered = z.RangeProof(bit_commitments=swapped_bits, or_proofs=swapped_or)
        # OR-proofs may still individually pass, but the aggregate check fails.
        assert not z.verify_range(C, tampered)

    def test_out_of_range_amount_rejected_at_prove_time(self):
        _, r = z.commit(0)  # placeholder blinding
        with pytest.raises(z.ZKError, match="fit"):
            z.prove_range(256, r, bits=8)

    def test_proof_size_scales_with_bits(self):
        c8, r8 = z.commit(1)
        _, p8 = z.prove_range(1, r8, bits=8)
        c16, r16 = z.commit(1)
        _, p16 = z.prove_range(1, r16, bits=16)
        assert p8.bits() == 8
        assert p16.bits() == 16
        # Each bit = one commitment + one OR-proof.
        assert len(p8.bit_commitments) == 8
        assert len(p16.or_proofs) == 16


# ---------------------------------------------------------------------------
# Wire (de)serialization
# ---------------------------------------------------------------------------


class TestSerialization:
    def test_roundtrip(self):
        c, r = z.commit(42)
        C, proof = z.prove_range(42, r, bits=8)
        d = proof.to_dict()
        back = z.RangeProof.from_dict(d)
        assert back.bit_commitments == proof.bit_commitments
        assert back.or_proofs[0].a0 == proof.or_proofs[0].a0
        # Deserialized proof still verifies.
        assert z.verify_range(C, back)

    def test_malformed_proof_raises(self):
        with pytest.raises(z.ZKError, match="malformed"):
            z.RangeProof.from_dict({"bit_commitments": [], "or_proofs": [{}]})

    def test_confidential_helper(self):
        ca = z.confidential(500, transcript=b"escrow-99")
        pub = ca.to_public_dict()
        assert "commitment" in pub
        assert "range_proof" in pub
        # Reconstruct + verify from wire.
        commitment = z.Commitment(C=pub["commitment"])
        proof = z.RangeProof.from_dict(pub["range_proof"])
        # Note: `ca` uses full AMOUNT_BITS (64), so this is a slower verify.
        # We verify with matching transcript.
        assert z.verify_range(commitment, proof, transcript=b"escrow-99")
        # Legitimate holder can still open.
        amt, blind = ca.open()
        assert amt == 500
        assert z.verify_open(commitment, amt, blind)


# ---------------------------------------------------------------------------
# Slow tests — full 64-bit end-to-end
# ---------------------------------------------------------------------------


@pytest.mark.slow
class TestFullRange64:
    def test_full_64bit_valid(self):
        amount = 10_000_000_000  # 10 CSPR in motes
        c, r = z.commit(amount)
        C, proof = z.prove_range(amount, r, transcript=b"escrow-42")
        assert proof.bits() == z.AMOUNT_BITS == 64
        assert z.verify_range(C, proof, transcript=b"escrow-42")

    def test_full_64bit_max(self):
        amount = (1 << 64) - 1
        c, r = z.commit(amount)
        C, proof = z.prove_range(amount, r)
        assert z.verify_range(C, proof)
