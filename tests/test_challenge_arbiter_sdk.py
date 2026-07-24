"""Python SDK tests for `sdk.challenge_arbiter`.

Cross-checks the Python helpers against the byte-for-byte Rust
`canonical_reveal_preimage` format documented in the contract, and validates
the commit-hex determinism + signature roundtrip.
"""

from __future__ import annotations

import hashlib

import pytest

from sdk.challenge_arbiter import (
    DOMAIN,
    STATUS_FINALIZED_CHALLENGER_WINS,
    STATUS_FINALIZED_FAILED_QUORUM,
    STATUS_FINALIZED_STATUS_QUO,
    VERDICT_RECEIVER,
    VERDICT_SENDER,
    build_commit_bundle,
    canonical_reveal_preimage,
    compute_commit_hex,
    generate_nonce,
    verify_reveal_signature,
)

# ── Preimage byte-for-byte parity with Rust ──────────────────────────


def test_preimage_shape_matches_rust_layout():
    m = canonical_reveal_preimage("pkg-abc", "d1", VERDICT_SENDER, "aabbcc", "010203")
    expected = f"{DOMAIN}:reveal:pkg-abc:d1:1:aabbcc:010203"
    assert m == expected


def test_preimage_rejects_invalid_verdict():
    with pytest.raises(ValueError):
        canonical_reveal_preimage("pkg", "d1", 3, "aa", "bb")
    with pytest.raises(ValueError):
        canonical_reveal_preimage("pkg", "d1", 0, "aa", "bb")


def test_preimage_deterministic():
    a = canonical_reveal_preimage("pkg", "d1", VERDICT_SENDER, "aa", "bb")
    b = canonical_reveal_preimage("pkg", "d1", VERDICT_SENDER, "aa", "bb")
    assert a == b


def test_preimage_diverges_on_any_input_change():
    base = canonical_reveal_preimage("pkg", "d1", VERDICT_SENDER, "aa", "bb")
    assert base != canonical_reveal_preimage("pkg-other", "d1", VERDICT_SENDER, "aa", "bb")
    assert base != canonical_reveal_preimage("pkg", "d2", VERDICT_SENDER, "aa", "bb")
    assert base != canonical_reveal_preimage("pkg", "d1", VERDICT_RECEIVER, "aa", "bb")
    assert base != canonical_reveal_preimage("pkg", "d1", VERDICT_SENDER, "ab", "bb")
    assert base != canonical_reveal_preimage("pkg", "d1", VERDICT_SENDER, "aa", "bc")


# ── Commit hex = blake2b-256(preimage) ───────────────────────────────


def test_compute_commit_hex_matches_blake2b_256():
    preimage = "ae402:challenge:v1:reveal:pkg:d1:1:aa:bb"
    expected = hashlib.blake2b(preimage.encode("utf-8"), digest_size=32).hexdigest()
    assert compute_commit_hex(preimage) == expected


def test_compute_commit_hex_stable_length():
    for _ in range(8):
        h = compute_commit_hex("some canonical preimage")
        assert len(h) == 64  # 32 bytes hex


# ── Nonce quality ────────────────────────────────────────────────────


def test_generate_nonce_produces_unique_64char_hex():
    n1 = generate_nonce()
    n2 = generate_nonce()
    assert n1 != n2
    assert len(n1) == 64 and len(n2) == 64
    int(n1, 16)  # doesn't raise
    int(n2, 16)


# ── build_commit_bundle roundtrip ────────────────────────────────────


def test_build_commit_bundle_without_key_leaves_signature_none():
    bundle = build_commit_bundle("pkg", "d1", VERDICT_SENDER, "01aabbcc", private_key_pem=None)
    assert bundle.signature_hex is None
    assert len(bundle.nonce_hex) == 64
    assert bundle.commit_hex == compute_commit_hex(bundle.preimage)
    with pytest.raises(ValueError):
        bundle.as_reveal_args()


def test_build_commit_bundle_with_key_signs_and_verifies():
    pytest.importorskip("cryptography")
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    priv = Ed25519PrivateKey.generate()
    pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub_hex = (
        priv.public_key()
        .public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        .hex()
    )

    bundle = build_commit_bundle("pkg", "d1", VERDICT_RECEIVER, pub_hex, private_key_pem=pem)
    assert bundle.signature_hex is not None
    assert verify_reveal_signature(pub_hex, bundle.preimage, bundle.signature_hex)


def test_verify_rejects_wrong_signature():
    pytest.importorskip("cryptography")
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    priv = Ed25519PrivateKey.generate()
    pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub_hex = (
        priv.public_key()
        .public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        .hex()
    )

    bundle = build_commit_bundle("pkg", "d1", VERDICT_RECEIVER, pub_hex, private_key_pem=pem)
    # Flip one hex nibble in the signature to make it invalid
    bad_sig = list(bundle.signature_hex)
    bad_sig[0] = "0" if bad_sig[0] != "0" else "1"
    assert not verify_reveal_signature(pub_hex, bundle.preimage, "".join(bad_sig))


def test_verify_rejects_wrong_preimage():
    pytest.importorskip("cryptography")
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    priv = Ed25519PrivateKey.generate()
    pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub_hex = (
        priv.public_key()
        .public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        .hex()
    )

    bundle = build_commit_bundle("pkg", "d1", VERDICT_RECEIVER, pub_hex, private_key_pem=pem)
    tampered = bundle.preimage + "TAMPER"
    assert not verify_reveal_signature(pub_hex, tampered, bundle.signature_hex)


def test_as_reveal_args_shape():
    pytest.importorskip("cryptography")
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    priv = Ed25519PrivateKey.generate()
    pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub_hex = (
        priv.public_key()
        .public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        .hex()
    )

    bundle = build_commit_bundle("pkg", "abc", VERDICT_SENDER, pub_hex, private_key_pem=pem)
    args = bundle.as_reveal_args()
    assert set(args.keys()) == {
        "dispute_id",
        "arbiter_pk",
        "verdict",
        "nonce_hex",
        "recomputed_commit_hex",
        "signature_hex",
    }
    assert args["dispute_id"] == "abc"
    assert args["verdict"] == VERDICT_SENDER
    assert args["recomputed_commit_hex"] == bundle.commit_hex


def test_status_enum_values_match_contract():
    # Basic sanity that the constants exported to callers match the on-chain
    # STATUS_* enum in main.rs.
    assert STATUS_FINALIZED_CHALLENGER_WINS == 4
    assert STATUS_FINALIZED_STATUS_QUO == 5
    assert STATUS_FINALIZED_FAILED_QUORUM == 6


def test_deterministic_bundle_with_fixed_nonce():
    """If the caller provides a nonce, the resulting commit is fully deterministic."""
    bundle1 = build_commit_bundle(
        "pkg",
        "d1",
        VERDICT_SENDER,
        "01deadbeef",
        private_key_pem=None,
        nonce_hex="a" * 64,
    )
    bundle2 = build_commit_bundle(
        "pkg",
        "d1",
        VERDICT_SENDER,
        "01deadbeef",
        private_key_pem=None,
        nonce_hex="a" * 64,
    )
    assert bundle1.commit_hex == bundle2.commit_hex
    assert bundle1.preimage == bundle2.preimage
