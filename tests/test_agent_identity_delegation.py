"""Integration tests for POST /identity/register, /identity/delegate and
GET /identity/capabilities/{agent_id} (server/agent_identity.py).

These exercise the exact same signing contract the console frontend uses
(lib/demoSigner.ts + Agents.tsx's DelegateCapabilityModal): a real Ed25519
keypair signs sha256(f"{delegator_id}:{delegatee_id}:{capability_uri}:{expiry_timestamp}")
and the backend verifies it cryptographically against the delegator's
registered public key. No demo/x402 bypass applies to this endpoint.
"""
from __future__ import annotations

import hashlib
import time

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from server.app import app, get_config, get_sandbox
from server.config import Config
from server.sandbox import SandboxStore
from server import agent_identity as agent_identity_module


@pytest.fixture(autouse=True)
def _reset_identity_state():
    """Agent identity/capability/delegation state is module-level in-memory storage; isolate each test."""
    agent_identity_module._agent_identities.clear()
    agent_identity_module._capabilities.clear()
    agent_identity_module._delegations.clear()
    yield
    agent_identity_module._agent_identities.clear()
    agent_identity_module._capabilities.clear()
    agent_identity_module._delegations.clear()


@pytest.fixture
def client():
    cfg = Config(sandbox=True)
    app.dependency_overrides[get_config] = lambda: cfg
    app.dependency_overrides[get_sandbox] = lambda: SandboxStore()
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _keypair():
    priv = Ed25519PrivateKey.generate()
    pub_hex = priv.public_key().public_bytes_raw().hex()
    return priv, pub_hex


def _sign_delegation(priv: Ed25519PrivateKey, delegator_id: str, delegatee_id: str, capability_uri: str, expiry_timestamp: int) -> str:
    msg = f"{delegator_id}:{delegatee_id}:{capability_uri}:{expiry_timestamp}"
    msg_hash_hex = hashlib.sha256(msg.encode()).hexdigest()
    return priv.sign(msg_hash_hex.encode("utf-8")).hex()


def _register(client, agent_id: str, public_key_hex: str):
    res = client.post(
        "/identity/register",
        json={"agent_id": agent_id, "public_key": public_key_hex, "did_document_hash": "a" * 64},
    )
    assert res.status_code in (200, 201), res.text
    return res


class TestIdentityDelegationEndToEnd:
    def test_delegate_with_valid_signature_succeeds(self, client):
        delegator_priv, delegator_pub = _keypair()
        _, delegatee_pub = _keypair()
        _register(client, "delegator-agent", delegator_pub)
        _register(client, "delegatee-agent", delegatee_pub)

        expiry = int(time.time()) + 3600
        signature = _sign_delegation(delegator_priv, "delegator-agent", "delegatee-agent", "urn:escrow:release", expiry)

        res = client.post(
            "/identity/delegate",
            json={
                "delegator_id": "delegator-agent",
                "delegatee_id": "delegatee-agent",
                "capability_uri": "urn:escrow:release",
                "expiry_timestamp": expiry,
                "signature": signature,
            },
        )
        assert res.status_code == 202, res.text
        body = res.json()
        assert body["delegator_id"] == "delegator-agent"
        assert body["delegatee_id"] == "delegatee-agent"
        assert body["capability_uri"] == "urn:escrow:release"

        caps = client.get("/identity/capabilities/delegatee-agent")
        assert caps.status_code == 200
        caps_body = caps.json()
        assert "urn:escrow:release" in caps_body["delegated_capabilities"]
        assert caps_body["total"] == 1

    def test_delegate_with_wrong_signer_key_rejected(self, client):
        """A signature produced by a key that is NOT the delegator's registered public key must fail."""
        _, delegator_pub = _keypair()
        attacker_priv, _ = _keypair()
        _, delegatee_pub = _keypair()
        _register(client, "delegator-agent", delegator_pub)
        _register(client, "delegatee-agent", delegatee_pub)

        expiry = int(time.time()) + 3600
        forged_signature = _sign_delegation(attacker_priv, "delegator-agent", "delegatee-agent", "urn:escrow:release", expiry)

        res = client.post(
            "/identity/delegate",
            json={
                "delegator_id": "delegator-agent",
                "delegatee_id": "delegatee-agent",
                "capability_uri": "urn:escrow:release",
                "expiry_timestamp": expiry,
                "signature": forged_signature,
            },
        )
        assert res.status_code == 401

    def test_delegate_with_tampered_capability_rejected(self, client):
        """Signature is bound to the exact capability_uri/expiry; changing either after signing must fail."""
        delegator_priv, delegator_pub = _keypair()
        _, delegatee_pub = _keypair()
        _register(client, "delegator-agent", delegator_pub)
        _register(client, "delegatee-agent", delegatee_pub)

        expiry = int(time.time()) + 3600
        signature = _sign_delegation(delegator_priv, "delegator-agent", "delegatee-agent", "urn:escrow:release", expiry)

        res = client.post(
            "/identity/delegate",
            json={
                "delegator_id": "delegator-agent",
                "delegatee_id": "delegatee-agent",
                "capability_uri": "urn:escrow:refund",  # tampered
                "expiry_timestamp": expiry,
                "signature": signature,
            },
        )
        assert res.status_code == 401

    def test_delegate_unknown_delegator_404(self, client):
        _, delegatee_pub = _keypair()
        _register(client, "delegatee-agent", delegatee_pub)
        expiry = int(time.time()) + 3600
        res = client.post(
            "/identity/delegate",
            json={
                "delegator_id": "never-registered",
                "delegatee_id": "delegatee-agent",
                "capability_uri": "urn:escrow:release",
                "expiry_timestamp": expiry,
                "signature": "00" * 64,
            },
        )
        assert res.status_code == 404

    def test_delegate_expired_timestamp_rejected(self, client):
        delegator_priv, delegator_pub = _keypair()
        _, delegatee_pub = _keypair()
        _register(client, "delegator-agent", delegator_pub)
        _register(client, "delegatee-agent", delegatee_pub)

        past_expiry = int(time.time()) - 10
        # Pydantic's gt=now validator on the model itself should reject this before signature check.
        signature = _sign_delegation(delegator_priv, "delegator-agent", "delegatee-agent", "urn:escrow:release", past_expiry)
        res = client.post(
            "/identity/delegate",
            json={
                "delegator_id": "delegator-agent",
                "delegatee_id": "delegatee-agent",
                "capability_uri": "urn:escrow:release",
                "expiry_timestamp": past_expiry,
                "signature": signature,
            },
        )
        assert res.status_code == 422
