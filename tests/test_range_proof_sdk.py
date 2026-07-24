"""
Range-Proof SDK — client-side unit tests.

Focus:
  * Pedersen commit / open round-trip (correctness + hiding invariants).
  * Byte-for-byte preimage parity with contracts/range-proof-registry.
  * Domain separation between attest and fraud (no cross-role replay).
  * Ed25519 sign / verify happy path + tamper rejection on every field.
  * :func:`build_register_bundle` full-workflow packing.
"""

from __future__ import annotations

import secrets

import pytest

from sdk.range_proof import (
    DOMAIN,
    RangeProof,
    build_attest_preimage,
    build_fraud_preimage,
    build_range_proof,
    build_register_bundle,
    pedersen_commit,
    sign_attest,
    sign_fraud,
    verify_attest,
    verify_fraud,
    verify_pedersen_opening,
    verify_range_proof,
)

try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    HAS_ED25519 = True
except ImportError:  # pragma: no cover
    HAS_ED25519 = False


# Reusable test vectors.
PKG = "aa" * 32
ESCROW = "bb" * 32
COMMIT_STUB = "cc" * 32
PROOF_HASH = "dd" * 32
REASON_HASH = "ee" * 32


# ══════════════════════════════════════════════════════════════════════
# Pedersen commit
# ══════════════════════════════════════════════════════════════════════


def test_pedersen_commit_round_trip():
    c = pedersen_commit(12345, randomness=42)
    assert verify_pedersen_opening(c.commitment_bytes, 12345, 42)


def test_pedersen_commit_zero_amount_ok():
    c = pedersen_commit(0)
    assert verify_pedersen_opening(c.commitment_bytes, 0, c.randomness)


def test_pedersen_commit_u64_max():
    c = pedersen_commit(2**64 - 1, randomness=1234)
    assert verify_pedersen_opening(c.commitment_bytes, 2**64 - 1, 1234)


def test_pedersen_commit_wrong_amount_fails_opening():
    c = pedersen_commit(100, randomness=42)
    assert not verify_pedersen_opening(c.commitment_bytes, 101, 42)


def test_pedersen_commit_wrong_randomness_fails_opening():
    c = pedersen_commit(100, randomness=42)
    assert not verify_pedersen_opening(c.commitment_bytes, 100, 43)


def test_pedersen_hiding_property():
    # Same amount with different randomness must produce different commitments
    # (statistical hiding — two random openings look unrelated).
    c1 = pedersen_commit(100, randomness=1)
    c2 = pedersen_commit(100, randomness=2)
    assert c1.commitment_bytes != c2.commitment_bytes


def test_pedersen_rejects_negative_amount():
    with pytest.raises(ValueError):
        pedersen_commit(-1)


def test_pedersen_rejects_amount_over_u64():
    with pytest.raises(ValueError):
        pedersen_commit(2**64)


def test_pedersen_rejects_zero_randomness():
    with pytest.raises(ValueError):
        pedersen_commit(100, randomness=0)


# ══════════════════════════════════════════════════════════════════════
# Range proof
# ══════════════════════════════════════════════════════════════════════


def test_range_proof_happy_path():
    c = pedersen_commit(200, randomness=7)
    proof = build_range_proof(c, 200, 100, 500)
    assert verify_range_proof(proof)


def test_range_proof_amount_out_of_range_rejected_at_build():
    c = pedersen_commit(600, randomness=7)
    with pytest.raises(ValueError, match="not in"):
        build_range_proof(c, 600, 100, 500)


def test_range_proof_min_gt_max_rejected():
    c = pedersen_commit(200, randomness=7)
    with pytest.raises(ValueError, match="min_amount"):
        build_range_proof(c, 200, 500, 100)


def test_range_proof_hash_deterministic():
    c = pedersen_commit(200, randomness=7)
    p1 = build_range_proof(c, 200, 100, 500)
    p2 = build_range_proof(c, 200, 100, 500)
    assert p1.proof_hash() == p2.proof_hash()


def test_range_proof_hash_changes_with_range():
    c = pedersen_commit(200, randomness=7)
    p1 = build_range_proof(c, 200, 100, 500)
    p2 = build_range_proof(c, 200, 100, 501)
    assert p1.proof_hash() != p2.proof_hash()


def test_verify_range_proof_rejects_tampered_amount():
    c = pedersen_commit(200, randomness=7)
    proof = build_range_proof(c, 200, 100, 500)
    tampered = RangeProof(
        commitment_hex=proof.commitment_hex,
        min_amount=proof.min_amount,
        max_amount=proof.max_amount,
        amount=201,
        randomness=proof.randomness,
    )
    assert not verify_range_proof(tampered)


def test_verify_range_proof_rejects_tampered_randomness():
    c = pedersen_commit(200, randomness=7)
    proof = build_range_proof(c, 200, 100, 500)
    tampered = RangeProof(
        commitment_hex=proof.commitment_hex,
        min_amount=proof.min_amount,
        max_amount=proof.max_amount,
        amount=proof.amount,
        randomness=8,
    )
    assert not verify_range_proof(tampered)


def test_verify_range_proof_rejects_range_flip():
    c = pedersen_commit(200, randomness=7)
    proof = build_range_proof(c, 200, 100, 500)
    tampered = RangeProof(
        commitment_hex=proof.commitment_hex,
        min_amount=500,
        max_amount=100,
        amount=proof.amount,
        randomness=proof.randomness,
    )
    assert not verify_range_proof(tampered)


# ══════════════════════════════════════════════════════════════════════
# Canonical preimages — parity with contracts/range-proof-registry
# ══════════════════════════════════════════════════════════════════════


def test_attest_preimage_pinned_vector():
    """Byte-for-byte identical to the pinned vector in
    contracts/tests/src/range_proof_registry_property_tests.rs::attest_preimage_known_vector."""
    out = build_attest_preimage(PKG, ESCROW, COMMIT_STUB, PROOF_HASH, 100, 500)
    expected = (f"{DOMAIN}:attest:{PKG}:{ESCROW}:{COMMIT_STUB}:{PROOF_HASH}:100:500").encode("ascii")
    assert out == expected


def test_fraud_preimage_pinned_vector():
    out = build_fraud_preimage(PKG, ESCROW, COMMIT_STUB, PROOF_HASH, REASON_HASH)
    expected = (f"{DOMAIN}:fraud:{PKG}:{ESCROW}:{COMMIT_STUB}:{PROOF_HASH}:{REASON_HASH}").encode("ascii")
    assert out == expected


def test_attest_and_fraud_domain_separated():
    att = build_attest_preimage(PKG, ESCROW, COMMIT_STUB, PROOF_HASH, 1, 2)
    fr = build_fraud_preimage(PKG, ESCROW, COMMIT_STUB, PROOF_HASH, REASON_HASH)
    assert att != fr


def test_attest_preimage_rejects_bad_escrow_length():
    with pytest.raises(ValueError, match="escrow_id_hex must be"):
        build_attest_preimage(PKG, "aa", COMMIT_STUB, PROOF_HASH, 1, 2)


def test_attest_preimage_rejects_bad_proof_hash_length():
    with pytest.raises(ValueError, match="proof_hash_hex must be"):
        build_attest_preimage(PKG, ESCROW, COMMIT_STUB, "dd", 1, 2)


def test_attest_preimage_rejects_bad_min_max():
    with pytest.raises(ValueError, match="min_amount > max_amount"):
        build_attest_preimage(PKG, ESCROW, COMMIT_STUB, PROOF_HASH, 500, 100)


def test_attest_preimage_rejects_negative_min():
    with pytest.raises(ValueError, match="min_amount out of u64 range"):
        build_attest_preimage(PKG, ESCROW, COMMIT_STUB, PROOF_HASH, -1, 100)


def test_attest_preimage_rejects_max_over_u64():
    with pytest.raises(ValueError, match="max_amount out of u64 range"):
        build_attest_preimage(PKG, ESCROW, COMMIT_STUB, PROOF_HASH, 0, 2**64)


def test_fraud_preimage_rejects_bad_reason_length():
    with pytest.raises(ValueError, match="reason_hash_hex must be"):
        build_fraud_preimage(PKG, ESCROW, COMMIT_STUB, PROOF_HASH, "ee")


# Domain-separation matrix — flipping any single field must change preimage.


@pytest.mark.parametrize(
    "field,value",
    [
        ("self_package_hex", "bb" * 32),
        ("escrow_id_hex", "cc" * 32),
        ("commitment_hex", "dd" * 32),
        ("proof_hash_hex", "ee" * 32),
        ("min_amount", 50),
        ("max_amount", 999),
    ],
)
def test_attest_preimage_injective_in_every_field(field: str, value):
    base = dict(
        self_package_hex=PKG,
        escrow_id_hex=ESCROW,
        commitment_hex=COMMIT_STUB,
        proof_hash_hex=PROOF_HASH,
        min_amount=100,
        max_amount=500,
    )
    variant = dict(base)
    variant[field] = value
    a = build_attest_preimage(**base)
    b = build_attest_preimage(**variant)
    assert a != b, f"preimage did not change when flipping {field}"


# ══════════════════════════════════════════════════════════════════════
# Ed25519 sign / verify
# ══════════════════════════════════════════════════════════════════════


pytestmark = pytest.mark.skipif(not HAS_ED25519, reason="cryptography not installed")


def _mk_key() -> tuple[bytes, bytes]:
    priv = Ed25519PrivateKey.generate()
    pub_bytes = priv.public_key().public_bytes_raw()
    priv_bytes = priv.private_bytes_raw()
    return priv_bytes, pub_bytes


def test_sign_and_verify_attest_happy_path():
    priv, pub = _mk_key()
    sig = sign_attest(
        priv,
        self_package_hex=PKG,
        escrow_id_hex=ESCROW,
        commitment_hex=COMMIT_STUB,
        proof_hash_hex=PROOF_HASH,
        min_amount=100,
        max_amount=500,
    )
    assert verify_attest(
        pub,
        sig,
        self_package_hex=PKG,
        escrow_id_hex=ESCROW,
        commitment_hex=COMMIT_STUB,
        proof_hash_hex=PROOF_HASH,
        min_amount=100,
        max_amount=500,
    )


def test_sign_and_verify_fraud_happy_path():
    priv, pub = _mk_key()
    sig = sign_fraud(
        priv,
        self_package_hex=PKG,
        escrow_id_hex=ESCROW,
        commitment_hex=COMMIT_STUB,
        proof_hash_hex=PROOF_HASH,
        reason_hash_hex=REASON_HASH,
    )
    assert verify_fraud(
        pub,
        sig,
        self_package_hex=PKG,
        escrow_id_hex=ESCROW,
        commitment_hex=COMMIT_STUB,
        proof_hash_hex=PROOF_HASH,
        reason_hash_hex=REASON_HASH,
    )


def test_verify_attest_rejects_tampered_min():
    priv, pub = _mk_key()
    sig = sign_attest(
        priv,
        self_package_hex=PKG,
        escrow_id_hex=ESCROW,
        commitment_hex=COMMIT_STUB,
        proof_hash_hex=PROOF_HASH,
        min_amount=100,
        max_amount=500,
    )
    assert not verify_attest(
        pub,
        sig,
        self_package_hex=PKG,
        escrow_id_hex=ESCROW,
        commitment_hex=COMMIT_STUB,
        proof_hash_hex=PROOF_HASH,
        min_amount=101,  # ← tampered
        max_amount=500,
    )


def test_attest_signature_cannot_be_replayed_as_fraud():
    """Domain separation: an attest signature MUST NOT verify as fraud."""
    priv, pub = _mk_key()
    sig = sign_attest(
        priv,
        self_package_hex=PKG,
        escrow_id_hex=ESCROW,
        commitment_hex=COMMIT_STUB,
        proof_hash_hex=PROOF_HASH,
        min_amount=100,
        max_amount=500,
    )
    # Even with the same non-numeric fields plus zeroed reason, fraud verify
    # must reject the attest signature.
    assert not verify_fraud(
        pub,
        sig,
        self_package_hex=PKG,
        escrow_id_hex=ESCROW,
        commitment_hex=COMMIT_STUB,
        proof_hash_hex=PROOF_HASH,
        reason_hash_hex="00" * 32,
    )


def test_attest_signature_cannot_be_replayed_cross_deployment():
    """Package hash MUST bind: a signature made against deployment A
    must not verify against deployment B, even for identical inputs."""
    priv, pub = _mk_key()
    sig = sign_attest(
        priv,
        self_package_hex="aa" * 32,
        escrow_id_hex=ESCROW,
        commitment_hex=COMMIT_STUB,
        proof_hash_hex=PROOF_HASH,
        min_amount=100,
        max_amount=500,
    )
    assert not verify_attest(
        pub,
        sig,
        self_package_hex="bb" * 32,  # ← different deployment
        escrow_id_hex=ESCROW,
        commitment_hex=COMMIT_STUB,
        proof_hash_hex=PROOF_HASH,
        min_amount=100,
        max_amount=500,
    )


# ══════════════════════════════════════════════════════════════════════
# Full-workflow: build_register_bundle
# ══════════════════════════════════════════════════════════════════════


def test_build_register_bundle_happy_path():
    arbiter_set = tuple(secrets.token_hex(32) for _ in range(5))
    bundle = build_register_bundle(
        escrow_id_hex=ESCROW,
        amount=200,
        min_amount=100,
        max_amount=500,
        arbiter_set_hex=arbiter_set,
        threshold=3,
        randomness=42,
    )
    # Prover-only state.
    assert bundle.amount == 200
    assert bundle.randomness == 42
    # Public register_commitment args.
    assert bundle.min_amount == 100
    assert bundle.max_amount == 500
    assert bundle.threshold == 3
    assert bundle.arbiter_set_hex == arbiter_set
    # Range proof is verifiable.
    assert verify_range_proof(bundle.proof)
    # Commitment opens.
    assert verify_pedersen_opening(bytes.fromhex(bundle.commitment_hex), 200, 42)
    # Proof hash matches what an arbiter will re-compute.
    assert bundle.proof.proof_hash().hex() == bundle.proof_hash_hex


def test_build_register_bundle_rejects_duplicate_arbiters():
    with pytest.raises(ValueError, match="unique"):
        build_register_bundle(
            escrow_id_hex=ESCROW,
            amount=200,
            min_amount=100,
            max_amount=500,
            arbiter_set_hex=("aa" * 32, "aa" * 32),
            threshold=1,
            randomness=42,
        )


def test_build_register_bundle_rejects_bad_threshold():
    with pytest.raises(ValueError, match="threshold"):
        build_register_bundle(
            escrow_id_hex=ESCROW,
            amount=200,
            min_amount=100,
            max_amount=500,
            arbiter_set_hex=("aa" * 32,),
            threshold=2,
            randomness=42,
        )


def test_build_register_bundle_rejects_out_of_range_amount():
    with pytest.raises(ValueError, match="not in"):
        build_register_bundle(
            escrow_id_hex=ESCROW,
            amount=999,
            min_amount=100,
            max_amount=500,
            arbiter_set_hex=("aa" * 32,),
            threshold=1,
            randomness=42,
        )


def test_arbiter_verifies_proof_and_signs():
    """End-to-end arbiter workflow: get the bundle → verify proof →
    sign attest → on-chain verifies."""
    priv, pub = _mk_key()
    arbiter_hex = pub.hex()
    arbiter_set = (arbiter_hex, secrets.token_hex(32), secrets.token_hex(32))

    bundle = build_register_bundle(
        escrow_id_hex=ESCROW,
        amount=200,
        min_amount=100,
        max_amount=500,
        arbiter_set_hex=arbiter_set,
        threshold=1,
        randomness=42,
    )

    # Arbiter side.
    assert verify_range_proof(bundle.proof)
    sig = sign_attest(
        priv,
        self_package_hex=PKG,
        escrow_id_hex=bundle.escrow_id_hex,
        commitment_hex=bundle.commitment_hex,
        proof_hash_hex=bundle.proof_hash_hex,
        min_amount=bundle.min_amount,
        max_amount=bundle.max_amount,
    )
    # On-chain-equivalent verification.
    assert verify_attest(
        pub,
        sig,
        self_package_hex=PKG,
        escrow_id_hex=bundle.escrow_id_hex,
        commitment_hex=bundle.commitment_hex,
        proof_hash_hex=bundle.proof_hash_hex,
        min_amount=bundle.min_amount,
        max_amount=bundle.max_amount,
    )
