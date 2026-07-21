"""Integration tests for the @require_signed_envelope decorator.

Wire the decorator onto a real FastAPI route and hit it with TestClient
to verify that:

* Well-formed envelope with correct domain → 200 and payload reaches
  the handler as ``envelope=`` kwarg.
* Missing header → 401.
* Malformed JSON → 400.
* Domain mismatch (chain / purpose) → 400.
* Timestamp stale / future → 401.
* Nonce reuse across two requests → first succeeds, second 401.
* Bad signature (tampered payload) → 401.
* Route decorated with unknown purpose refuses at import time.
"""

from __future__ import annotations

import json
import os
import time

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from server.middleware import ENVELOPE_HEADER, require_signed_envelope, _default_nonce_store
from server.signed_envelope import DomainSeparator, sign_envelope_ed25519

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


CHAIN_ID = "casper-testnet"


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    """Pin chain id and route the persistent nonce store into a fresh
    file per-test.  Also clears the lru_cache on the store getter so
    each test really does get a fresh store."""
    monkeypatch.setenv("AE402_CHAIN_ID", CHAIN_ID)
    monkeypatch.setenv("AE402_NONCE_STORE_PATH", str(tmp_path / "nonces.sqlite"))
    _default_nonce_store.cache_clear()
    yield
    _default_nonce_store.cache_clear()


@pytest.fixture
def keys():
    sk = os.urandom(32)
    priv = Ed25519PrivateKey.from_private_bytes(sk)
    pk = priv.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    return sk, pk


@pytest.fixture
def app():
    app = FastAPI()

    @app.post("/deposit")
    @require_signed_envelope(purpose="escrow.deposit")
    async def deposit_route(request: Request, envelope=None):
        assert envelope is not None
        return {
            "ok": True,
            "amount_motes": envelope.payload.get("amount_motes"),
            "nonce": envelope.nonce,
        }

    return app


@pytest.fixture
def client(app):
    return TestClient(app)


def _fresh_envelope(sk, pk, *, purpose="escrow.deposit", chain=CHAIN_ID, nonce=None, ts=None, payload=None):
    domain = DomainSeparator(
        protocol="AgentEscrow402",
        version="v1",
        chain_id=chain,
        purpose=purpose,
    )
    return sign_envelope_ed25519(
        domain=domain,
        payload=payload if payload is not None else {"amount_motes": 1_000_000_000},
        nonce=nonce or f"n-{os.urandom(6).hex()}",
        timestamp=ts if ts is not None else int(time.time()),
        private_key_bytes=sk,
        public_key_bytes=pk,
    )


def _post(client, envelope):
    return client.post(
        "/deposit",
        headers={ENVELOPE_HEADER: envelope.to_json()},
        json={},
    )


# ---------------------------------------------------------------------------

def test_happy_path(client, keys):
    sk, pk = keys
    env = _fresh_envelope(sk, pk)
    r = _post(client, env)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["amount_motes"] == 1_000_000_000
    assert body["nonce"] == env.nonce


def test_missing_header(client):
    r = client.post("/deposit", json={})
    assert r.status_code == 401
    assert r.json()["reason"] == "envelope_missing"


def test_malformed_json(client):
    r = client.post(
        "/deposit",
        headers={ENVELOPE_HEADER: "{not-json}"},
        json={},
    )
    assert r.status_code == 400
    assert r.json()["reason"] == "envelope_bad_json"


def test_bad_shape(client):
    r = client.post(
        "/deposit",
        headers={ENVELOPE_HEADER: json.dumps(["not", "an", "object"])},
        json={},
    )
    assert r.status_code == 400
    assert r.json()["reason"] == "envelope_bad_shape"


def test_missing_fields(client):
    r = client.post(
        "/deposit",
        headers={ENVELOPE_HEADER: json.dumps({"domain": {}})},
        json={},
    )
    assert r.status_code == 400
    assert r.json()["reason"] == "envelope_bad_fields"


def test_cross_chain_replay_rejected(client, keys):
    sk, pk = keys
    env = _fresh_envelope(sk, pk, chain="casper-mainnet")
    r = _post(client, env)
    assert r.status_code == 400
    assert r.json()["reason"] == "domain_mismatch"


def test_cross_purpose_replay_rejected(client, keys):
    sk, pk = keys
    # Envelope signed for a *different* purpose than the route enforces.
    env = _fresh_envelope(sk, pk, purpose="escrow.release")
    r = _post(client, env)
    assert r.status_code == 400
    assert r.json()["reason"] == "domain_mismatch"


def test_timestamp_stale_rejected(client, keys):
    sk, pk = keys
    env = _fresh_envelope(sk, pk, ts=int(time.time()) - 3600)
    r = _post(client, env)
    assert r.status_code == 401
    assert r.json()["reason"] == "timestamp_stale"


def test_nonce_reuse_rejected(client, keys):
    sk, pk = keys
    env = _fresh_envelope(sk, pk, nonce="n-persistent-1")
    r1 = _post(client, env)
    assert r1.status_code == 200, r1.text
    r2 = _post(client, env)
    assert r2.status_code == 401
    assert r2.json()["reason"] == "nonce_reused"


def test_tampered_payload_rejected(client, keys):
    sk, pk = keys
    env = _fresh_envelope(sk, pk)
    obj = json.loads(env.to_json())
    obj["payload"]["amount_motes"] = 9_999_999_999_999
    r = client.post(
        "/deposit",
        headers={ENVELOPE_HEADER: json.dumps(obj)},
        json={},
    )
    assert r.status_code == 401
    assert r.json()["reason"] == "bad_signature"


def test_unknown_purpose_at_decoration_time():
    with pytest.raises(ValueError, match="unknown purpose"):
        require_signed_envelope(purpose="totally.made.up")


def test_chain_id_unset_returns_500(client, keys, monkeypatch):
    sk, pk = keys
    monkeypatch.delenv("AE402_CHAIN_ID", raising=False)
    env = _fresh_envelope(sk, pk)
    r = _post(client, env)
    assert r.status_code == 500
    assert r.json()["reason"] == "chain_id_unset"
