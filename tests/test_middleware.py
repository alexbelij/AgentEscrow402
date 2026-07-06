"""Tests for x402 payment middleware."""

from __future__ import annotations

import hashlib
import time

import pytest
from cryptography.hazmat.primitives.asymmetric import ec, utils
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from starlette.requests import Request

from server.middleware import (
    _build_signing_payload,
    _check_replay,
    _used_nonces,
    _verify_secp256k1,
    _verify_signature,
    compute_service_hash,
    parse_x402_header,
    require_payment,
)
from server.models import PaymentHeader


class TestParseX402Header:
    def test_valid_header(self):
        # escrow_hash and sender must be strict 64-char hex, signature
        # 128-char hex — parse_x402_header rejects anything looser.
        ts = str(int(time.time()))
        escrow_hash = "ab" * 32
        sender = "cd" * 32
        signature = "ef" * 64
        header = f"x402-v1;{escrow_hash};1000;{sender};{ts};nonce123;{signature}"
        result = parse_x402_header(header)
        assert result is not None
        assert result.version == "x402-v1"
        assert result.escrow_hash == escrow_hash
        assert result.amount == 1000
        assert result.sender == sender
        assert result.signature == signature
        assert result.nonce == "nonce123"

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
        h = "abcdef1234567890" * 4  # 64-char hex
        sender = "1234567890abcdef" * 4
        signature = "ab" * 64
        header = f"x402-v1;{h};100;{sender};0;nonceabcd;{signature}"
        result = parse_x402_header(header)
        assert result is not None

    def test_negative_amount_still_parses(self):
        h = "aa" * 32
        sender = "bb" * 32
        signature = "cc" * 64
        header = f"x402-v1;{h};-5;{sender};0;nonceabcd;{signature}"
        result = parse_x402_header(header)
        assert result is not None
        assert result.amount == -5

    def test_zero_amount(self):
        h = "aa" * 32
        sender = "bb" * 32
        signature = "cc" * 64
        header = f"x402-v1;{h};0;{sender};0;nonceabcd;{signature}"
        result = parse_x402_header(header)
        assert result is not None
        assert result.amount == 0

    def test_secp256k1_length_sender_accepted(self):
        # 33-byte compressed secp256k1 pubkey = 66 hex chars (vs 64 for
        # Ed25519's raw 32 bytes) -- must not be rejected as malformed.
        h = "aa" * 32
        sender = "02" + "bb" * 32  # 66 hex chars, compressed-point-shaped
        signature = "cc" * 64
        header = f"x402-v1;{h};0;{sender};0;nonceabcd;{signature}"
        result = parse_x402_header(header)
        assert result is not None
        assert result.sender == sender

    def test_wrong_length_sender_rejected(self):
        h = "aa" * 32
        sender = "bb" * 30  # neither 64 nor 66 hex chars
        signature = "cc" * 64
        header = f"x402-v1;{h};0;{sender};0;nonceabcd;{signature}"
        result = parse_x402_header(header)
        assert result is None


class TestVerifySecp256k1:
    def _keypair_and_sign(self, message: bytes) -> tuple[str, str]:
        priv = ec.generate_private_key(ec.SECP256K1())
        pub_hex = priv.public_key().public_bytes(Encoding.X962, PublicFormat.CompressedPoint).hex()
        der_sig = priv.sign(message, ec.ECDSA(SHA256()))
        r, s = utils.decode_dss_signature(der_sig)
        sig_hex = (r.to_bytes(32, "big") + s.to_bytes(32, "big")).hex()
        return pub_hex, sig_hex

    def test_valid_signature_verifies(self):
        message = b"ae402 secp256k1 test message"
        pub_hex, sig_hex = self._keypair_and_sign(message)
        assert _verify_secp256k1(pub_hex, message, sig_hex) is True
        assert _verify_signature(pub_hex, message, sig_hex) is True

    def test_tampered_message_rejected(self):
        message = b"ae402 secp256k1 test message"
        pub_hex, sig_hex = self._keypair_and_sign(message)
        assert _verify_secp256k1(pub_hex, b"tampered message", sig_hex) is False

    def test_wrong_key_length_rejected(self):
        message = b"ae402 secp256k1 test message"
        _, sig_hex = self._keypair_and_sign(message)
        assert _verify_secp256k1("bb" * 32, message, sig_hex) is False  # 64 hex, not 66

    def test_dispatch_picks_ed25519_for_32_byte_key(self):
        priv = Ed25519PrivateKey.generate()
        pub_hex = priv.public_key().public_bytes_raw().hex()
        message = b"ae402 ed25519 dispatch test"
        sig_hex = priv.sign(message).hex()
        assert _verify_signature(pub_hex, message, sig_hex) is True


class TestCasperMessagePrefixFallback:
    """Browser wallets (Casper Wallet / CSPR.click's `signMessage()`) sign
    `b"Casper Message:\n" + message`, not the raw message, per the
    ecosystem-standard `formatMessageWithHeaders` convention. Agent SDKs
    signing directly with a held private key sign the raw message. Both
    must verify via `_verify_signature`."""

    def test_ed25519_wallet_prefixed_signature_verifies(self):
        priv = Ed25519PrivateKey.generate()
        pub_hex = priv.public_key().public_bytes_raw().hex()
        message = b"x402-v1;abc;100;sender;123;nonce;POST;/escrow/multi-asset"
        sig_hex = priv.sign(b"Casper Message:\n" + message).hex()
        assert _verify_signature(pub_hex, message, sig_hex) is True

    def test_secp256k1_wallet_prefixed_signature_verifies(self):
        priv = ec.generate_private_key(ec.SECP256K1())
        pub_hex = priv.public_key().public_bytes(Encoding.X962, PublicFormat.CompressedPoint).hex()
        message = b"x402-v1;abc;100;sender;123;nonce;POST;/escrow/multi-asset"
        der_sig = priv.sign(b"Casper Message:\n" + message, ec.ECDSA(SHA256()))
        r, s = utils.decode_dss_signature(der_sig)
        sig_hex = (r.to_bytes(32, "big") + s.to_bytes(32, "big")).hex()
        assert _verify_signature(pub_hex, message, sig_hex) is True

    def test_raw_agent_signature_still_verifies_directly(self):
        # Direct agent-key signing (no wallet prefix) must keep working.
        priv = Ed25519PrivateKey.generate()
        pub_hex = priv.public_key().public_bytes_raw().hex()
        message = b"x402-v1;abc;100;sender;123;nonce;POST;/escrow/multi-asset"
        sig_hex = priv.sign(message).hex()
        assert _verify_signature(pub_hex, message, sig_hex) is True

    def test_tampered_message_rejected_even_with_prefix_fallback(self):
        priv = Ed25519PrivateKey.generate()
        pub_hex = priv.public_key().public_bytes_raw().hex()
        message = b"x402-v1;abc;100;sender;123;nonce;POST;/escrow/multi-asset"
        sig_hex = priv.sign(b"Casper Message:\n" + message).hex()
        assert _verify_signature(pub_hex, b"different payload", sig_hex) is False


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
            escrow_hash="abc",
            amount=100,
            sender="s",
            signature="sig",
            timestamp=0,
            nonce="n",
        )
        p1 = _build_signing_payload(ph, method="POST", path="/escrow")
        p2 = _build_signing_payload(ph, method="POST", path="/release")
        assert p1 != p2


class TestRequirePaymentDecorator:
    """`require_payment` is a self-contained x402 payment guard exported by
    this module. Production (`server/app.py::_extract_sender`) inlines the
    same parse/replay/verify calls itself rather than using this decorator
    directly, but the decorator is still public API (used by any route
    that imports it) and had zero direct test coverage before this --
    only its sub-helpers were tested in isolation."""

    def _request(self, headers: dict[str, str], method: str = "POST", path: str = "/protected") -> Request:
        raw_headers = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
        scope = {
            "type": "http",
            "method": method,
            "path": path,
            "headers": raw_headers,
            "query_string": b"",
            "client": ("test", 0),
            "server": ("test", 80),
        }
        return Request(scope)

    def _sign(self, key: Ed25519PrivateKey, escrow_hash, amount, sender, ts, nonce, method, path):
        unsigned = PaymentHeader(
            escrow_hash=escrow_hash, amount=amount, sender=sender,
            signature="0" * 128, timestamp=ts, nonce=nonce,
        )
        msg = _build_signing_payload(unsigned, method=method, path=path)
        return key.sign(msg).hex()

    @pytest.mark.asyncio
    async def test_missing_header_returns_402(self):
        @require_payment()
        async def handler(request: Request):
            return {"ok": True}

        resp = await handler(self._request({}))
        assert resp.status_code == 402
        import json
        assert json.loads(resp.body)["error"] == "payment_required"

    @pytest.mark.asyncio
    async def test_malformed_header_returns_400(self):
        @require_payment()
        async def handler(request: Request):
            return {"ok": True}

        resp = await handler(self._request({"X-Payment": "garbage;not;valid"}))
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_insufficient_amount_returns_402(self):
        @require_payment(min_amount=10_000)
        async def handler(request: Request):
            return {"ok": True}

        key = Ed25519PrivateKey.generate()
        sender = key.public_key().public_bytes_raw().hex()
        ts, nonce = str(int(time.time())), "nonceabc"
        escrow_hash = "ab" * 32
        sig = self._sign(key, escrow_hash, 100, sender, ts, nonce, "POST", "/protected")
        header = f"x402-v1;{escrow_hash};100;{sender};{ts};{nonce};{sig}"
        resp = await handler(self._request({"X-Payment": header}))
        assert resp.status_code == 402

    @pytest.mark.asyncio
    async def test_invalid_signature_returns_401(self):
        @require_payment()
        async def handler(request: Request):
            return {"ok": True}

        key = Ed25519PrivateKey.generate()
        sender = key.public_key().public_bytes_raw().hex()
        ts, nonce = str(int(time.time())), "noncedef"
        escrow_hash = "ab" * 32
        bad_sig = "11" * 64  # well-formed hex, wrong signature
        header = f"x402-v1;{escrow_hash};100;{sender};{ts};{nonce};{bad_sig}"
        resp = await handler(self._request({"X-Payment": header}))
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_replayed_nonce_returns_401(self):
        @require_payment()
        async def handler(request: Request):
            return {"ok": True}

        key = Ed25519PrivateKey.generate()
        sender = key.public_key().public_bytes_raw().hex()
        ts, nonce = str(int(time.time())), "noncerepeat1"
        escrow_hash = "ab" * 32
        sig = self._sign(key, escrow_hash, 100, sender, ts, nonce, "POST", "/protected")
        header = f"x402-v1;{escrow_hash};100;{sender};{ts};{nonce};{sig}"
        first = await handler(self._request({"X-Payment": header}))
        assert first == {"ok": True}
        second = await handler(self._request({"X-Payment": header}))
        assert second.status_code == 401

    @pytest.mark.asyncio
    async def test_valid_signed_request_succeeds(self):
        @require_payment()
        async def handler(request: Request):
            return {"ok": True, "sender": request.state.payment.sender}

        key = Ed25519PrivateKey.generate()
        sender = key.public_key().public_bytes_raw().hex()
        ts, nonce = str(int(time.time())), "noncegood1"
        escrow_hash = "ab" * 32
        sig = self._sign(key, escrow_hash, 100, sender, ts, nonce, "POST", "/protected")
        header = f"x402-v1;{escrow_hash};100;{sender};{ts};{nonce};{sig}"
        result = await handler(self._request({"X-Payment": header}))
        assert result == {"ok": True, "sender": sender}

    @pytest.mark.asyncio
    async def test_signature_bound_to_path_rejects_reuse_on_other_route(self):
        """A signature valid for POST /protected must not verify against a
        different path -- proves method+path binding actually matters."""
        @require_payment()
        async def handler(request: Request):
            return {"ok": True}

        key = Ed25519PrivateKey.generate()
        sender = key.public_key().public_bytes_raw().hex()
        ts, nonce = str(int(time.time())), "noncebound1"
        escrow_hash = "ab" * 32
        sig = self._sign(key, escrow_hash, 100, sender, ts, nonce, "POST", "/protected")
        header = f"x402-v1;{escrow_hash};100;{sender};{ts};{nonce};{sig}"
        resp = await handler(self._request({"X-Payment": header}, path="/other"))
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_verify_sig_false_skips_signature_check(self):
        """Sandbox mode (verify_sig=False) accepts a well-formed but
        cryptographically bogus signature as long as replay checks pass --
        exactly the documented sandbox behavior, now actually exercised."""
        @require_payment(verify_sig=False)
        async def handler(request: Request):
            return {"ok": True}

        ts, nonce = str(int(time.time())), "noncesandbox1"
        escrow_hash = "ab" * 32
        sender = "cd" * 32
        header = f"x402-v1;{escrow_hash};100;{sender};{ts};{nonce};{'0' * 128}"
        result = await handler(self._request({"X-Payment": header}))
        assert result == {"ok": True}
