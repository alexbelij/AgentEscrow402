"""Tests for x402 payment middleware."""

from __future__ import annotations

import hashlib
import time

from server.middleware import (
    X402_VERSION,
    _build_signing_payload,
    _check_replay,
    _used_nonces,
    compute_service_hash,
    parse_x402_header,
)
from server.models import PaymentHeader


class TestParseX402Header:
    def test_valid_header(self):
        ts = str(int(time.time()))
        header = f"x402-v1;abc123;1000;sender-001;{ts};nonce1;sig-xyz"
        result = parse_x402_header(header)
        assert result is not None
        assert result.version == "x402-v1"
        assert result.escrow_hash == "abc123"
        assert result.amount == 1000
        assert result.sender == "sender-001"
        assert result.signature == "sig-xyz"
        assert result.nonce == "nonce1"

    def test_invalid_version(self):
        header = "x402-v2;abc;100;sender;1000;n;sig"
        result = parse_x402_header(header)
        assert result is None

    def test_missing_parts(self):
        header = "x402-v1;abc;100"
        result = parse_x402_header(header)
        assert result is None

    def test_non_numeric_amount(self):
        header = "x402-v1;abc;not-a-number;sender;0;n;sig"
        result = parse_x402_header(header)
        assert result is None

    def test_empty_string(self):
        result = parse_x402_header("")
        assert result is None

    def test_extra_semicolons(self):
        header = "x402-v1;abc;100;sender;0;n;sig;extra;parts"
        result = parse_x402_header(header)
        assert result is None

    def test_non_hex_hash_rejected(self):
        header = "x402-v1;GHIJ;100;sender;0;n;sig"
        result = parse_x402_header(header)
        assert result is None

    def test_valid_hex_hash_accepted(self):
        h = "abcdef1234567890" * 4
        header = f"x402-v1;{h};100;sender;0;n;sig"
        result = parse_x402_header(header)
        assert result is not None

    def test_negative_amount_still_parses(self):
        header = "x402-v1;aabbcc;-5;sender;0;n;sig"
        result = parse_x402_header(header)
        assert result is not None
        assert result.amount == -5

    def test_zero_amount(self):
        header = "x402-v1;aabbcc;0;sender;0;n;sig"
        result = parse_x402_header(header)
        assert result is not None
        assert result.amount == 0


class TestComputeServiceHash:
    def test_deterministic(self):
        h1 = compute_service_hash("s", "r", 100, "nonce")
        h2 = compute_service_hash("s", "r", 100, "nonce")
        assert h1 == h2

    def test_different_inputs(self):
        h1 = compute_service_hash("alice", "bob", 100, "n")
        h2 = compute_service_hash("alice", "bob", 200, "n")
        assert h1 != h2

    def test_correct_sha256(self):
        result = compute_service_hash("s", "r", 50, "abc")
        expected = hashlib.sha256(b"s:r:50:abc").hexdigest()
        assert result == expected

    def test_different_nonce(self):
        h1 = compute_service_hash("a", "b", 10, "n1")
        h2 = compute_service_hash("a", "b", 10, "n2")
        assert h1 != h2


class TestReplayProtection:
    def setup_method(self):
        _used_nonces.clear()

    def test_fresh_nonce_accepted(self):
        ts = int(time.time())
        err = _check_replay("unique-nonce-1", ts)
        assert err is None

    def test_reused_nonce_rejected(self):
        ts = int(time.time())
        _check_replay("dup-nonce", ts)
        err = _check_replay("dup-nonce", ts)
        assert err == "nonce_reused"

    def test_expired_timestamp_rejected(self):
        old_ts = int(time.time()) - 600
        err = _check_replay("old-nonce", old_ts)
        assert err == "timestamp_expired"

    def test_future_timestamp_rejected(self):
        future_ts = int(time.time()) + 600
        err = _check_replay("future-nonce", future_ts)
        assert err == "timestamp_expired"


class TestSigningPayload:
    def test_payload_format(self):
        ph = PaymentHeader(
            version="x402-v1",
            escrow_hash="abc",
            amount=100,
            sender="sender1",
            signature="sig",
            timestamp=9999,
            nonce="n1",
        )
        payload = _build_signing_payload(ph, method="POST", path="/escrow")
        expected = b"x402-v1;abc;100;sender1;9999;n1;POST;/escrow"
        assert payload == expected

    def test_payload_binds_path(self):
        ph = PaymentHeader(
            escrow_hash="abc", amount=100, sender="s", signature="sig",
            timestamp=0, nonce="n",
        )
        p1 = _build_signing_payload(ph, method="POST", path="/escrow")
        p2 = _build_signing_payload(ph, method="POST", path="/release")
        assert p1 != p2
