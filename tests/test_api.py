"""Integration tests for the FastAPI application."""

from __future__ import annotations

import hashlib

import pytest
from fastapi.testclient import TestClient

from server.app import app, get_config, get_sandbox
from server.config import Config
from server.sandbox import SandboxStore


def _hash(val: str) -> str:
    return hashlib.sha256(val.encode()).hexdigest()


# EscrowRequest.receiver requires a raw 64-hex string (optionally
# "account-hash-" prefixed) — see server/models.py. Plain slugs like "r" or
# "receiver-001" fail pydantic validation with a 422, so tests use these
# realistic-looking hex receivers instead.
RECEIVER_HEX = "ab" * 32
RECEIVER_HEX_2 = "cd" * 32


@pytest.fixture
def sandbox_store():
    return SandboxStore()


@pytest.fixture
def client(sandbox_store):
    cfg = Config(sandbox=True)
    app.dependency_overrides[get_config] = lambda: cfg
    app.dependency_overrides[get_sandbox] = lambda: sandbox_store
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


class TestHealthEndpoint:
    def test_health(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["sandbox"] is True

    def test_health_version(self, client):
        resp = client.get("/health")
        assert resp.json()["version"] == "0.2.0"


class TestEscrowEndpoint:
    def test_create_escrow(self, client):
        h = _hash("svc-001")
        resp = client.post(
            "/escrow",
            json={
                "receiver": RECEIVER_HEX,
                "amount": 5000,
                "service_hash": h,
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["amount"] == 4900  # net after 2% insurance fee
        assert body["status"] == "pending"

    def test_create_duplicate_escrow_returns_409(self, client):
        h = _hash("svc-dup")
        client.post(
            "/escrow",
            json={
                "receiver": RECEIVER_HEX,
                "amount": 100,
                "service_hash": h,
            },
        )
        resp = client.post(
            "/escrow",
            json={
                "receiver": RECEIVER_HEX,
                "amount": 100,
                "service_hash": h,
            },
        )
        assert resp.status_code == 409

    def test_create_escrow_invalid_amount(self, client):
        h = _hash("invalid")
        resp = client.post(
            "/escrow",
            json={
                "receiver": RECEIVER_HEX,
                "amount": 0,
                "service_hash": h,
            },
        )
        assert resp.status_code == 422

    def test_get_escrow(self, client):
        h = _hash("get-test")
        client.post(
            "/escrow",
            json={
                "receiver": RECEIVER_HEX,
                "amount": 100,
                "service_hash": h,
            },
        )
        resp = client.get(f"/escrow/{h}")
        assert resp.status_code == 200
        assert resp.json()["service_hash"] == h

    def test_get_nonexistent_escrow(self, client):
        resp = client.get(f"/escrow/{_hash('missing')}")
        assert resp.status_code == 404


class TestReleaseEndpoint:
    def test_release(self, client):
        h = _hash("release-test")
        client.post(
            "/escrow",
            json={
                "receiver": RECEIVER_HEX,
                "amount": 100,
                "service_hash": h,
            },
            params={"sender": "alice"},
        )
        resp = client.post(
            "/release",
            json={
                "service_hash": h,
            },
            params={"sender": "alice"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "released"

    def test_release_nonexistent(self, client):
        resp = client.post(
            "/release",
            json={
                "service_hash": _hash("no-such"),
            },
        )
        assert resp.status_code == 404


class TestRefundEndpoint:
    def test_refund(self, client):
        h = _hash("refund-test")
        client.post(
            "/escrow",
            json={
                "receiver": RECEIVER_HEX,
                "amount": 100,
                "service_hash": h,
            },
            params={"sender": "bob"},
        )
        resp = client.post(
            "/refund",
            json={
                "service_hash": h,
            },
            params={"sender": "bob"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "refunded"


class TestDisputeEndpoint:
    def test_dispute(self, client):
        h = _hash("dispute-test")
        client.post(
            "/escrow",
            json={
                "receiver": RECEIVER_HEX,
                "amount": 100,
                "service_hash": h,
            },
        )
        resp = client.post(
            "/dispute",
            json={
                "service_hash": h,
                "reason_hash": "b" * 64,
            },
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "disputed"

    def test_dispute_nonexistent(self, client):
        resp = client.post(
            "/dispute",
            json={
                "service_hash": _hash("gone"),
                "reason_hash": "c" * 64,
            },
        )
        assert resp.status_code == 404


class TestReputationEndpoint:
    def test_default_reputation(self, client):
        resp = client.get("/reputation/unknown-agent")
        assert resp.status_code == 200
        body = resp.json()
        assert body["completed"] == 0
        assert body["score"] == 50

    def test_reputation_increases_on_release(self, client):
        h = _hash("rep-test")
        client.post(
            "/escrow",
            json={
                "receiver": RECEIVER_HEX_2,
                "amount": 100,
                "service_hash": h,
            },
            params={"sender": "payer"},
        )
        client.post(
            "/release",
            json={
                "service_hash": h,
            },
            params={"sender": "payer"},
        )
        resp = client.get(f"/reputation/{RECEIVER_HEX_2}")
        assert resp.json()["completed"] == 1


class TestResolveEndpoint:
    """`/resolve` now requires real Ed25519 arbiter vote signatures, verified
    locally against `Config.arbiter_pubkeys` (mirrors the on-chain check)."""

    @staticmethod
    def _make_arbiters(n: int):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        keys = [Ed25519PrivateKey.generate() for _ in range(n)]
        pubkeys = tuple("01" + k.public_key().public_bytes_raw().hex() for k in keys)
        return keys, pubkeys

    @staticmethod
    def _sign(key, service_hash: str, in_favor_of: str) -> str:
        message = f"resolve:{service_hash}:{in_favor_of}".encode()
        return "01" + key.sign(message).hex()

    def _client_with_arbiters(self, sandbox_store, pubkeys):
        cfg = Config(sandbox=True, arbiter_pubkeys=pubkeys, arbiter_threshold=3)
        app.dependency_overrides[get_config] = lambda: cfg
        app.dependency_overrides[get_sandbox] = lambda: sandbox_store
        client = TestClient(app)
        return client

    def _open_disputed_escrow(self, client, h: str):
        client.post(
            "/escrow",
            json={"receiver": RECEIVER_HEX, "amount": 100, "service_hash": h},
        )
        resp = client.post(
            "/dispute", json={"service_hash": h, "reason_hash": "b" * 64}
        )
        assert resp.status_code == 200

    def test_resolve_with_valid_threshold_signatures_succeeds(self, sandbox_store):
        keys, pubkeys = self._make_arbiters(5)
        client = self._client_with_arbiters(sandbox_store, pubkeys)
        try:
            h = _hash("resolve-ok")
            self._open_disputed_escrow(client, h)
            sigs = [self._sign(k, h, "receiver") for k in keys[:3]]
            resp = client.post(
                "/resolve",
                json={
                    "service_hash": h,
                    "in_favor_of": "receiver",
                    "arbiter_pubkeys": list(pubkeys[:3]),
                    "arbiter_signatures": sigs,
                },
            )
            assert resp.status_code == 200, resp.text
            assert resp.json()["status"] == "resolved"
        finally:
            app.dependency_overrides.clear()

    def test_resolve_rejects_below_threshold(self, sandbox_store):
        keys, pubkeys = self._make_arbiters(5)
        client = self._client_with_arbiters(sandbox_store, pubkeys)
        try:
            h = _hash("resolve-too-few")
            self._open_disputed_escrow(client, h)
            sigs = [self._sign(k, h, "receiver") for k in keys[:2]]  # only 2, need 3
            resp = client.post(
                "/resolve",
                json={
                    "service_hash": h,
                    "in_favor_of": "receiver",
                    "arbiter_pubkeys": list(pubkeys[:2]),
                    "arbiter_signatures": sigs,
                },
            )
            assert resp.status_code == 422
        finally:
            app.dependency_overrides.clear()

    def test_resolve_rejects_forged_signatures_from_unregistered_key(self, sandbox_store):
        keys, pubkeys = self._make_arbiters(5)
        client = self._client_with_arbiters(sandbox_store, pubkeys)
        try:
            h = _hash("resolve-forged")
            self._open_disputed_escrow(client, h)
            outsider_keys, outsider_pubkeys = self._make_arbiters(3)
            sigs = [self._sign(k, h, "receiver") for k in outsider_keys]
            resp = client.post(
                "/resolve",
                json={
                    "service_hash": h,
                    "in_favor_of": "receiver",
                    "arbiter_pubkeys": list(outsider_pubkeys),
                    "arbiter_signatures": sigs,
                },
            )
            assert resp.status_code == 422
        finally:
            app.dependency_overrides.clear()

    def test_resolve_rejects_replayed_signature_for_flipped_verdict(self, sandbox_store):
        keys, pubkeys = self._make_arbiters(5)
        client = self._client_with_arbiters(sandbox_store, pubkeys)
        try:
            h = _hash("resolve-replay")
            self._open_disputed_escrow(client, h)
            # Sign for "receiver" but submit claiming "sender" -- must fail.
            sigs = [self._sign(k, h, "receiver") for k in keys[:3]]
            resp = client.post(
                "/resolve",
                json={
                    "service_hash": h,
                    "in_favor_of": "sender",
                    "arbiter_pubkeys": list(pubkeys[:3]),
                    "arbiter_signatures": sigs,
                },
            )
            assert resp.status_code == 422
        finally:
            app.dependency_overrides.clear()


class TestReleaseCapApproval:
    """A1 hardening: /release requires arbiter-quorum cap-approval when the
    escrow amount exceeds Config.release_cap_motes (mirrors the on-chain
    require_arbiter_cap_approval check in contracts/escrow/src/main.rs)."""

    @staticmethod
    def _make_arbiters(n: int):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        keys = [Ed25519PrivateKey.generate() for _ in range(n)]
        pubkeys = tuple("01" + k.public_key().public_bytes_raw().hex() for k in keys)
        return keys, pubkeys

    @staticmethod
    def _sign(key, service_hash: str) -> str:
        message = f"release:{service_hash}:cap_approval".encode()
        return "01" + key.sign(message).hex()

    def _client_with_arbiters(self, sandbox_store, pubkeys, release_cap_motes=1000):
        cfg = Config(
            sandbox=True,
            arbiter_pubkeys=pubkeys,
            arbiter_threshold=3,
            release_cap_motes=release_cap_motes,
        )
        app.dependency_overrides[get_config] = lambda: cfg
        app.dependency_overrides[get_sandbox] = lambda: sandbox_store
        return TestClient(app)

    def test_below_cap_release_succeeds_without_signatures(self, sandbox_store):
        _, pubkeys = self._make_arbiters(5)
        client = self._client_with_arbiters(sandbox_store, pubkeys, release_cap_motes=1000)
        try:
            h = _hash("cap-below")
            client.post(
                "/escrow",
                json={"receiver": RECEIVER_HEX, "amount": 100, "service_hash": h},
                params={"sender": "payer"},
            )
            resp = client.post("/release", json={"service_hash": h}, params={"sender": "payer"})
            assert resp.status_code == 200, resp.text
            assert resp.json()["status"] == "released"
        finally:
            app.dependency_overrides.clear()

    def test_above_cap_release_without_signatures_rejected(self, sandbox_store):
        _, pubkeys = self._make_arbiters(5)
        client = self._client_with_arbiters(sandbox_store, pubkeys, release_cap_motes=100)
        try:
            h = _hash("cap-above-no-sig")
            client.post(
                "/escrow",
                json={"receiver": RECEIVER_HEX, "amount": 1000, "service_hash": h},
                params={"sender": "payer"},
            )
            resp = client.post("/release", json={"service_hash": h}, params={"sender": "payer"})
            assert resp.status_code == 422
        finally:
            app.dependency_overrides.clear()

    def test_above_cap_release_with_valid_quorum_succeeds(self, sandbox_store):
        keys, pubkeys = self._make_arbiters(5)
        client = self._client_with_arbiters(sandbox_store, pubkeys, release_cap_motes=100)
        try:
            h = _hash("cap-above-ok")
            client.post(
                "/escrow",
                json={"receiver": RECEIVER_HEX, "amount": 1000, "service_hash": h},
                params={"sender": "payer"},
            )
            sigs = [self._sign(k, h) for k in keys[:3]]
            resp = client.post(
                "/release",
                json={
                    "service_hash": h,
                    "arbiter_pubkeys": list(pubkeys[:3]),
                    "arbiter_signatures": sigs,
                },
                params={"sender": "payer"},
            )
            assert resp.status_code == 200, resp.text
            assert resp.json()["status"] == "released"
        finally:
            app.dependency_overrides.clear()

    def test_above_cap_release_below_threshold_rejected(self, sandbox_store):
        keys, pubkeys = self._make_arbiters(5)
        client = self._client_with_arbiters(sandbox_store, pubkeys, release_cap_motes=100)
        try:
            h = _hash("cap-above-too-few")
            client.post(
                "/escrow",
                json={"receiver": RECEIVER_HEX, "amount": 1000, "service_hash": h},
                params={"sender": "payer"},
            )
            sigs = [self._sign(k, h) for k in keys[:2]]  # only 2, need 3
            resp = client.post(
                "/release",
                json={
                    "service_hash": h,
                    "arbiter_pubkeys": list(pubkeys[:2]),
                    "arbiter_signatures": sigs,
                },
                params={"sender": "payer"},
            )
            assert resp.status_code == 422
        finally:
            app.dependency_overrides.clear()


class TestAdminRoutes:
    """Installer-only admin endpoints (server/admin_api.py). Sandbox/no-key
    combinations are exercised here; live on-chain submission is covered by
    the CasperClient unit tests, not here (no real chain in CI)."""

    def _client(self, admin_api_key="", sandbox=True):
        from server.config import get_config as admin_get_config

        cfg = Config(sandbox=sandbox, admin_api_key=admin_api_key)
        app.dependency_overrides[get_config] = lambda: cfg
        app.dependency_overrides[admin_get_config] = lambda: cfg
        return TestClient(app)

    def test_disabled_without_admin_api_key(self):
        client = self._client(admin_api_key="")
        try:
            resp = client.post("/admin/configure-fee", json={"new_fee_bps": 300})
            assert resp.status_code == 503
        finally:
            app.dependency_overrides.clear()

    def test_rejects_missing_header(self):
        client = self._client(admin_api_key="secret123")
        try:
            resp = client.post("/admin/configure-fee", json={"new_fee_bps": 300})
            assert resp.status_code == 403
        finally:
            app.dependency_overrides.clear()

    def test_rejects_wrong_header(self):
        client = self._client(admin_api_key="secret123")
        try:
            resp = client.post(
                "/admin/configure-fee",
                json={"new_fee_bps": 300},
                headers={"X-Admin-Key": "wrong"},
            )
            assert resp.status_code == 403
        finally:
            app.dependency_overrides.clear()

    def test_accepted_key_but_sandbox_mode_rejected(self):
        # Right key, but admin ops require live mode (a real Casper client) --
        # sandbox mode has nothing on-chain to configure.
        client = self._client(admin_api_key="secret123", sandbox=True)
        try:
            resp = client.post(
                "/admin/configure-fee",
                json={"new_fee_bps": 300},
                headers={"X-Admin-Key": "secret123"},
            )
            assert resp.status_code == 409
        finally:
            app.dependency_overrides.clear()

    def test_configure_fee_validates_bps_range(self):
        client = self._client(admin_api_key="secret123", sandbox=True)
        try:
            resp = client.post(
                "/admin/configure-fee",
                json={"new_fee_bps": 5000},  # > 1000 max
                headers={"X-Admin-Key": "secret123"},
            )
            assert resp.status_code == 422
        finally:
            app.dependency_overrides.clear()

    def test_set_arbiters_rejects_empty_list(self):
        client = self._client(admin_api_key="secret123", sandbox=True)
        try:
            resp = client.post(
                "/admin/set-arbiters",
                json={"arbiters": []},
                headers={"X-Admin-Key": "secret123"},
            )
            assert resp.status_code == 422
        finally:
            app.dependency_overrides.clear()

    def test_emergency_freeze_endpoint_reachable(self):
        client = self._client(admin_api_key="secret123", sandbox=True)
        try:
            resp = client.post(
                "/admin/emergency-freeze",
                headers={"X-Admin-Key": "secret123"},
            )
            # Sandbox mode => 409 (no live Casper client), not 404/403 --
            # confirms the route + auth gate are wired correctly.
            assert resp.status_code == 409
        finally:
            app.dependency_overrides.clear()


class TestComputeHashEndpoint:
    def test_compute_hash(self, client):
        resp = client.post(
            "/compute-hash",
            params={"sender": "s", "receiver": RECEIVER_HEX, "amount": 100, "nonce": "n"},
        )
        assert resp.status_code == 200
        assert "service_hash" in resp.json()
