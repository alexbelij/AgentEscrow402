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
        assert resp.json()["version"] == "0.1.0"


class TestEscrowEndpoint:
    def test_create_escrow(self, client):
        h = _hash("svc-001")
        resp = client.post("/escrow", json={
            "receiver": "receiver-001",
            "amount": 5000,
            "service_hash": h,
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["amount"] == 5000
        assert body["status"] == "pending"

    def test_create_duplicate_escrow_returns_409(self, client):
        h = _hash("svc-dup")
        client.post("/escrow", json={
            "receiver": "r", "amount": 100, "service_hash": h,
        })
        resp = client.post("/escrow", json={
            "receiver": "r", "amount": 100, "service_hash": h,
        })
        assert resp.status_code == 409

    def test_create_escrow_invalid_amount(self, client):
        h = _hash("invalid")
        resp = client.post("/escrow", json={
            "receiver": "r", "amount": 0, "service_hash": h,
        })
        assert resp.status_code == 422

    def test_get_escrow(self, client):
        h = _hash("get-test")
        client.post("/escrow", json={
            "receiver": "r", "amount": 100, "service_hash": h,
        })
        resp = client.get(f"/escrow/{h}")
        assert resp.status_code == 200
        assert resp.json()["service_hash"] == h

    def test_get_nonexistent_escrow(self, client):
        resp = client.get(f"/escrow/{_hash('missing')}")
        assert resp.status_code == 404


class TestReleaseEndpoint:
    def test_release(self, client):
        h = _hash("release-test")
        client.post("/escrow", json={
            "receiver": "r", "amount": 100, "service_hash": h,
        }, params={"sender": "alice"})
        resp = client.post("/release", json={
            "service_hash": h,
        }, params={"sender": "alice"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "released"

    def test_release_nonexistent(self, client):
        resp = client.post("/release", json={
            "service_hash": _hash("no-such"),
        })
        assert resp.status_code == 404


class TestRefundEndpoint:
    def test_refund(self, client):
        h = _hash("refund-test")
        client.post("/escrow", json={
            "receiver": "r", "amount": 100, "service_hash": h,
        }, params={"sender": "bob"})
        resp = client.post("/refund", json={
            "service_hash": h,
        }, params={"sender": "bob"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "refunded"


class TestDisputeEndpoint:
    def test_dispute(self, client):
        h = _hash("dispute-test")
        client.post("/escrow", json={
            "receiver": "r", "amount": 100, "service_hash": h,
        })
        resp = client.post("/dispute", json={
            "service_hash": h,
            "reason_hash": "b" * 64,
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "disputed"

    def test_dispute_nonexistent(self, client):
        resp = client.post("/dispute", json={
            "service_hash": _hash("gone"),
            "reason_hash": "c" * 64,
        })
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
        client.post("/escrow", json={
            "receiver": "good-agent", "amount": 100, "service_hash": h,
        }, params={"sender": "payer"})
        client.post("/release", json={
            "service_hash": h,
        }, params={"sender": "payer"})
        resp = client.get("/reputation/good-agent")
        assert resp.json()["completed"] == 1


class TestComputeHashEndpoint:
    def test_compute_hash(self, client):
        resp = client.post(
            "/compute-hash",
            params={"sender": "s", "receiver": "r", "amount": 100, "nonce": "n"},
        )
        assert resp.status_code == 200
        assert "service_hash" in resp.json()
