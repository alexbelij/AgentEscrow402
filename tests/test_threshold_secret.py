"""Tests for T3.1 threshold secret sharing (Shamir SSS)."""

from __future__ import annotations

import os

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from server.threshold_secret import (
    Share,
    ThresholdReleaseBundle,
    build_threshold_release,
    decrypt_release_payload,
    encrypt_release_payload,
    reconstruct_secret,
    split_secret,
)


# ---------- split_secret / reconstruct_secret ----------


class TestSplitReconstruct:
    def test_basic_3_of_5(self):
        secret = os.urandom(32)
        shares = split_secret(secret, threshold=3, total_shares=5)
        assert len(shares) == 5
        assert reconstruct_secret(shares[:3]) == secret

    def test_any_subset_of_threshold(self):
        secret = os.urandom(32)
        shares = split_secret(secret, threshold=3, total_shares=5)
        # Try all combos of 3 out of 5 — all must reconstruct
        from itertools import combinations
        for combo in combinations(range(5), 3):
            subset = [shares[i] for i in combo]
            assert reconstruct_secret(subset) == secret, f"combo {combo} failed"

    def test_more_than_threshold_still_works(self):
        secret = os.urandom(32)
        shares = split_secret(secret, threshold=3, total_shares=5)
        assert reconstruct_secret(shares) == secret  # all 5
        assert reconstruct_secret(shares[:4]) == secret

    def test_share_indices_are_1_to_m(self):
        shares = split_secret(os.urandom(32), threshold=3, total_shares=7)
        assert [s.index for s in shares] == [1, 2, 3, 4, 5, 6, 7]

    def test_share_values_are_in_field(self):
        from server.threshold_secret import _PRIME
        shares = split_secret(os.urandom(32), threshold=3, total_shares=5)
        for s in shares:
            assert 0 <= s.value < _PRIME

    def test_hex_roundtrip(self):
        shares = split_secret(os.urandom(32), threshold=3, total_shares=5)
        for s in shares:
            h = s.to_hex()
            assert len(h) == 68  # 4 (index) + 64 (32-byte value)
            back = Share.from_hex(h)
            assert back == s

    def test_hex_invalid_length(self):
        with pytest.raises(ValueError, match="68 chars"):
            Share.from_hex("deadbeef")

    def test_edge_threshold_2_of_2(self):
        secret = os.urandom(32)
        shares = split_secret(secret, threshold=2, total_shares=2)
        assert reconstruct_secret(shares) == secret

    def test_edge_threshold_2_of_100(self):
        secret = os.urandom(32)
        shares = split_secret(secret, threshold=2, total_shares=100)
        # any 2 shares work
        assert reconstruct_secret([shares[7], shares[42]]) == secret

    def test_edge_threshold_equals_total(self):
        # n-of-n: all shares required
        secret = os.urandom(32)
        shares = split_secret(secret, threshold=5, total_shares=5)
        assert reconstruct_secret(shares) == secret


# ---------- validation ----------


class TestValidation:
    def test_secret_wrong_length(self):
        with pytest.raises(ValueError, match="32 bytes"):
            split_secret(b"\x00" * 16, threshold=2, total_shares=3)

    def test_secret_not_bytes(self):
        with pytest.raises(TypeError, match="must be bytes"):
            split_secret("thirty-two-character-string-abcd", threshold=2, total_shares=3)  # type: ignore

    def test_threshold_too_low(self):
        with pytest.raises(ValueError, match="threshold must be >= 2"):
            split_secret(os.urandom(32), threshold=1, total_shares=3)

    def test_threshold_gt_total(self):
        with pytest.raises(ValueError, match="< threshold"):
            split_secret(os.urandom(32), threshold=5, total_shares=3)

    def test_total_shares_too_high(self):
        with pytest.raises(ValueError, match="<= 255"):
            split_secret(os.urandom(32), threshold=2, total_shares=256)

    def test_reconstruct_too_few_shares(self):
        with pytest.raises(ValueError, match="at least 2"):
            reconstruct_secret([Share(1, 42)])

    def test_reconstruct_duplicate_indices(self):
        with pytest.raises(ValueError, match="duplicate"):
            reconstruct_secret([Share(1, 100), Share(1, 200)])


# ---------- security: fewer than threshold shares reveal nothing ----------


class TestSecurityProperty:
    def test_below_threshold_gives_wrong_answer(self):
        """With < threshold shares, reconstruction produces a value unrelated
        to the true secret. (Information-theoretic: any secret is equally
        likely given k-1 shares of a k-threshold poly.)"""
        secret = os.urandom(32)
        shares = split_secret(secret, threshold=3, total_shares=5)
        # 2 shares can be "combined" but the Lagrange interp gives a wrong result
        wrong = reconstruct_secret(shares[:2])
        assert wrong != secret

    def test_different_polynomials_each_split(self):
        """Two splits of the same secret produce independent shares."""
        secret = b"\x01" * 32
        shares1 = split_secret(secret, threshold=3, total_shares=5)
        shares2 = split_secret(secret, threshold=3, total_shares=5)
        # Same secret ⇒ same y at x=0, but different random coefficients
        # ⇒ different y values at x=1,2,3,4,5.
        # Both reconstruct to same secret:
        assert reconstruct_secret(shares1[:3]) == secret
        assert reconstruct_secret(shares2[:3]) == secret
        # But individual shares differ:
        differences = sum(1 for a, b in zip(shares1, shares2) if a.value != b.value)
        assert differences >= 4  # overwhelmingly likely all 5 differ


# ---------- AEAD wrapper ----------


class TestAEAD:
    def test_roundtrip(self):
        secret = os.urandom(32)
        pt = b"release the funds to alice"
        ct = encrypt_release_payload(secret, pt)
        assert decrypt_release_payload(secret, ct) == pt

    def test_mac_failure_on_tamper(self):
        secret = os.urandom(32)
        ct = encrypt_release_payload(secret, b"payload")
        tampered = ct[:-1] + bytes([ct[-1] ^ 1])
        with pytest.raises(ValueError, match="MAC"):
            decrypt_release_payload(secret, tampered)

    def test_mac_failure_on_wrong_key(self):
        secret = os.urandom(32)
        wrong = os.urandom(32)
        ct = encrypt_release_payload(secret, b"payload")
        with pytest.raises(ValueError, match="MAC"):
            decrypt_release_payload(wrong, ct)

    def test_empty_plaintext(self):
        secret = os.urandom(32)
        ct = encrypt_release_payload(secret, b"")
        assert decrypt_release_payload(secret, ct) == b""

    def test_large_plaintext(self):
        secret = os.urandom(32)
        pt = os.urandom(10_000)
        ct = encrypt_release_payload(secret, pt)
        assert decrypt_release_payload(secret, ct) == pt

    def test_wrong_key_length(self):
        with pytest.raises(ValueError, match="32 bytes"):
            encrypt_release_payload(b"\x00" * 16, b"x")


# ---------- ThresholdReleaseBundle ----------


class TestBundle:
    def test_full_flow(self):
        payload = b"authorization: release 100 CSPR to acct-X"
        bundle = build_threshold_release(payload, threshold=3, total=5)
        assert isinstance(bundle, ThresholdReleaseBundle)
        assert len(bundle.shares_hex) == 5
        assert bundle.threshold == 3
        assert bundle.total == 5

        # Correct: 3 shares
        result = bundle.collect_and_decrypt(bundle.shares_hex[:3])
        assert result == payload

    def test_insufficient_shares_rejected(self):
        bundle = build_threshold_release(b"data", threshold=3, total=5)
        with pytest.raises(ValueError, match="need 3 shares"):
            bundle.collect_and_decrypt(bundle.shares_hex[:2])

    def test_wrong_shares_fail_mac(self):
        """Shares from one bundle should not decrypt another bundle."""
        b1 = build_threshold_release(b"payload-1", threshold=3, total=5)
        b2 = build_threshold_release(b"payload-2", threshold=3, total=5)
        with pytest.raises(ValueError, match="MAC"):
            # Feed b1's ciphertext + b2's shares
            ThresholdReleaseBundle(
                encrypted_payload=b1.encrypted_payload,
                shares_hex=b2.shares_hex,
                threshold=3,
                total=5,
            ).collect_and_decrypt(b2.shares_hex[:3])

    def test_share_indices_do_not_leak_order(self):
        """Shares can be presented in any order — Lagrange doesn't care."""
        payload = b"my-secret"
        bundle = build_threshold_release(payload, threshold=3, total=5)
        # Reverse order
        assert bundle.collect_and_decrypt(list(reversed(bundle.shares_hex[:3]))) == payload
        # Skip middle
        assert bundle.collect_and_decrypt([bundle.shares_hex[0], bundle.shares_hex[2], bundle.shares_hex[4]]) == payload


# ---------- Property-based tests via hypothesis ----------


class TestPropertyBased:
    @given(
        secret=st.binary(min_size=32, max_size=32),
        threshold=st.integers(min_value=2, max_value=8),
        extra=st.integers(min_value=0, max_value=10),
    )
    @settings(max_examples=50, deadline=None)
    def test_split_reconstruct_always_recovers(self, secret, threshold, extra):
        total = threshold + extra
        shares = split_secret(secret, threshold=threshold, total_shares=total)
        # Take exactly `threshold` shares
        assert reconstruct_secret(shares[:threshold]) == secret

    @given(
        payload=st.binary(min_size=0, max_size=200),
        threshold=st.integers(min_value=2, max_value=5),
    )
    @settings(max_examples=30, deadline=None)
    def test_bundle_roundtrip_arbitrary_payload(self, payload, threshold):
        total = threshold + 2
        bundle = build_threshold_release(payload, threshold=threshold, total=total)
        recovered = bundle.collect_and_decrypt(bundle.shares_hex[:threshold])
        assert recovered == payload
