"""Tests for sdk/client.py — the standalone Python SDK used by external
agent integrations (and by examples/escrow_agent.py).

These specifically cover the signed (non-sandbox) auth path, since prior to
this test file it had *zero* coverage and, before the corresponding fix in
sdk/client.py, could not actually authenticate against a real (non-sandbox)
AgentEscrow402 deployment at all — every request would have hit
`_extract_sender`'s `raise HTTPException(401, "sender identity required")`
branch, because the old client only ever sent an unsigned `?sender=` query
param, which the real server only accepts when `cfg.sandbox` is True.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from sdk.client import EscrowClient, _canonical_payload
from server.app import app, get_casper, get_config, get_sandbox
from server.config import Config
from server.middleware import _build_signing_payload, _verify_ed25519, parse_x402_header
from server.sandbox import SandboxStore

RECEIVER_HEX = "ab" * 32


class TestSigningPrimitives:
    def test_generate_produces_valid_64_hex_sender(self):
        client = EscrowClient.generate("http://localhost:8000")
        assert len(client.sender) == 64
        assert all(c in "0123456789abcdef" for c in client.sender)

    def test_signed_header_parses_and_verifies_with_real_server_code(self):
        """The core proof: a header built by EscrowClient._sign(...) must be
        byte-for-byte compatible with server/middleware.py's own
        parse + canonical-payload + Ed25519-verify pipeline."""
        client = EscrowClient.generate("http://localhost:8000")
        escrow_hash = "11" * 32
        amount = 5000

        header_val = client._sign(escrow_hash, amount, "POST", "/escrow")
        parsed = parse_x402_header(header_val)

        assert parsed is not None
        assert parsed.sender == client.sender
        assert parsed.escrow_hash == escrow_hash
        assert parsed.amount == amount

        msg = _build_signing_payload(parsed, method="POST", path="/escrow")
        assert _verify_ed25519(parsed.sender, msg, parsed.signature) is True

    def test_signed_header_signature_bound_to_method_and_path(self):
        """A signature minted for one (method, path) must not verify for a
        different one — this is the whole point of binding it."""
        client = EscrowClient.generate("http://localhost:8000")
        escrow_hash = "22" * 32
        header_val = client._sign(escrow_hash, 1000, "POST", "/escrow")
        parsed = parse_x402_header(header_val)

        wrong_msg = _build_signing_payload(parsed, method="POST", path="/release")
        assert _verify_ed25519(parsed.sender, wrong_msg, parsed.signature) is False

    def test_unsigned_client_raises_on_sign(self):
        client = EscrowClient("http://localhost:8000", sender="plain-agent")
        with pytest.raises(RuntimeError):
            client._sign("33" * 32, 100, "POST", "/escrow")

    def test_canonical_payload_matches_server_format(self):
        from server.models import PaymentHeader

        ph = PaymentHeader(
            escrow_hash="ab" * 32,
            amount=100,
            sender="cd" * 32,
            signature="ef" * 64,
            timestamp=1234,
            nonce="noncenonce",
        )
        client_side = _canonical_payload(
            "x402-v1",
            ph.escrow_hash,
            ph.amount,
            ph.sender,
            ph.timestamp,
            ph.nonce,
            "POST",
            "/escrow",
        )
        server_side = _build_signing_payload(ph, method="POST", path="/escrow")
        assert client_side == server_side


@pytest.fixture
def sandbox_store():
    return SandboxStore()


@pytest.fixture
def live_client_app(sandbox_store, monkeypatch):
    """A non-sandbox app config (casper=None so it still uses the in-memory
    store, but `_extract_sender` now requires a real, verified Ed25519
    signature) — reproduces exactly what a live production deployment
    enforces, without needing a real Casper node.

    Note: `_extract_sender` calls `get_config()` as a *plain function call*
    (not via FastAPI `Depends`), so `app.dependency_overrides[get_config]`
    has no effect on it — it always resolves the real, `@lru_cache`'d
    `server.app.get_config()`. To flip `cfg.sandbox` for that direct call we
    have to go through the actual env var it reads and clear the cache.
    """
    monkeypatch.setenv("SANDBOX", "false")
    from server.app import get_config as app_get_config

    app_get_config.cache_clear()
    cfg = Config(sandbox=False)
    app.dependency_overrides[get_config] = lambda: cfg
    app.dependency_overrides[get_sandbox] = lambda: sandbox_store
    app.dependency_overrides[get_casper] = lambda: None
    yield
    app.dependency_overrides.clear()
    app_get_config.cache_clear()


class TestSignedRequestsAgainstRealServerAuth:
    """End-to-end proof: EscrowClient.generate() can complete a full escrow
    lifecycle against a server configured exactly like the live deployment
    (sandbox=False), which rejects any unsigned request with 401."""

    @pytest.mark.usefixtures("live_client_app")
    def test_unsigned_request_is_rejected_by_non_sandbox_server(self):
        with TestClient(app) as tc:
            resp = tc.post(
                "/escrow",
                json={
                    "receiver": RECEIVER_HEX,
                    "amount": 1000,
                    "service_hash": "44" * 32,
                    "ttl": 300,
                },
                params={"sender": "not-a-signature-plain-string"},
            )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("live_client_app")
    async def test_signed_create_and_release_succeeds_against_non_sandbox_server(self):
        client = EscrowClient.generate("http://testserver")
        # Point the client's HTTP transport directly at the in-process ASGI
        # app (no real network) so this test stays fast/deterministic while
        # still exercising the exact same signing + server-verification code
        # a request against a real deployment would use.
        client._http = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        )
        try:
            escrow = await client.create_escrow(receiver=RECEIVER_HEX, amount=2500)
            assert escrow["sender"] == client.sender
            assert escrow["status"] == "pending"

            released = await client.release(escrow["service_hash"], amount=2500)
            assert released["status"] == "released"
        finally:
            await client._http.aclose()
