"""Tests for x402 payment middleware."""

from __future__ import annotations

from server.middleware import compute_service_hash, parse_x402_header


class TestParseX402Header:
    def test_valid_header(self):
        header = "x402-v1;abc123;1000;sender-001;sig-xyz"
        result = parse_x402_header(header)
        assert result is not None
        assert result.version == "x402-v1"
        assert result.escrow_hash == "abc123"
        assert result.amount == 1000
        assert result.sender == "sender-001"
        assert result.signature == "sig-xyz"

    def test_invalid_version(self):
        header = "x402-v2;abc;100;sender;sig"
        result = parse_x402_header(header)
        assert result is None

    def test_missing_parts(self):
        header = "x402-v1;abc;100"
        result = parse_x402_header(header)
        assert result is None

    def test_non_numeric_amount(self):
        header = "x402-v1;abc;not-a-number;sender;sig"
        result = parse_x402_header(header)
        assert result is None


class TestComputeServiceHash:
    def test_deterministic(self):
        h1 = compute_service_hash("s", "r", 100, "nonce1")
        h2 = compute_service_hash("s", "r", 100, "nonce1")
        assert h1 == h2

    def test_different_nonce_different_hash(self):
        h1 = compute_service_hash("s", "r", 100, "nonce1")
        h2 = compute_service_hash("s", "r", 100, "nonce2")
        assert h1 != h2

    def test_hash_is_hex_64_chars(self):
        h = compute_service_hash("s", "r", 100, "n")
        assert len(h) == 64
        int(h, 16)  # Should not raise
