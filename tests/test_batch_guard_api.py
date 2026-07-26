"""API tests for `/escrows/batch-preview` (T3.3)."""

from __future__ import annotations

import hashlib

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from server import arbiter_crypto
from server import batch_guard as bg
from server.app import app, get_casper, get_config, get_sandbox
from server.config import Config
from server.sandbox import SandboxStore

RECEIVER_HEX = "ab" * 32
RECEIVER_HEX_2 = "cd" * 32
SENDER_HEX = "00" * 32


def _make_arbiter():
    sk = Ed25519PrivateKey.generate()
    pk_bytes = sk.public_key().public_bytes_raw()
    return sk, "01" + pk_bytes.hex()


def _sign_release(sk: Ed25519PrivateKey, sh: str) -> str:
    return "01" + sk.sign(arbiter_crypto.build_cap_approval_message("release", sh)).hex()


@pytest.fixture
def store():
    return SandboxStore()


@pytest.fixture
def cfg(monkeypatch):
    """Config with tight release_cap so above-cap tests are cheap."""
    monkeypatch.setenv("RELEASE_CAP_MOTES", "1000")
    monkeypatch.setenv("ARBITER_THRESHOLD", "2")
    monkeypatch.setenv("SANDBOX_MODE", "1")
    return Config()


@pytest.fixture
def client(store, cfg):
    async def _no_casper():
        return None

    app.dependency_overrides[get_sandbox] = lambda: store
    app.dependency_overrides[get_config] = lambda: cfg
    app.dependency_overrides[get_casper] = _no_casper
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _seed_escrow(store: SandboxStore, service_slug: str, amount: int) -> str:
    """Return the service_hash of a freshly created pending escrow."""
    sh = hashlib.sha256(service_slug.encode()).hexdigest()
    rec = store.create_escrow(
        sender=SENDER_HEX,
        receiver=RECEIVER_HEX,
        amount=amount,
        service_hash=sh,
        ttl=3600,
    )
    return rec.service_hash


def test_preview_below_cap_admits(client, store):
    sh = _seed_escrow(store, "svc-1", amount=100)
    r = client.post(
        "/escrows/batch-preview",
        json={"action": "release", "service_hashes": [sh]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["admit"] is True
    assert body["needs_quorum"] is False
    assert body["rejections"] == []
    assert body["max_batch_size"] == bg.MAX_BATCH_SIZE


def test_preview_missing_escrow_returns_typed_rejection(client):
    sh = "ff" * 32
    r = client.post(
        "/escrows/batch-preview",
        json={"action": "release", "service_hashes": [sh]},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["admit"] is False
    codes = [x["code"] for x in body["rejections"]]
    assert bg.CODE_ESCROW_NOT_FOUND in codes


def test_preview_duplicate_hash(client, store):
    sh = _seed_escrow(store, "svc-dup", amount=100)
    r = client.post(
        "/escrows/batch-preview",
        json={"action": "release", "service_hashes": [sh, sh]},
    )
    body = r.json()
    assert body["admit"] is False
    assert bg.CODE_DUPLICATE_SERVICE_HASH in [x["code"] for x in body["rejections"]]


def test_preview_above_cap_no_arbiters_admits(client, store, cfg, monkeypatch):
    """Parity with legacy escape-hatch: no registered arbiters => above-cap
    still admissible; the on-chain contract remains the last line of defence."""
    sh = _seed_escrow(store, "svc-big", amount=10_000)
    # Force empty arbiter set (default in this test config)
    r = client.post(
        "/escrows/batch-preview",
        json={"action": "release", "service_hashes": [sh]},
    )
    body = r.json()
    assert body["admit"] is True
    assert body["needs_quorum"] is False


def test_preview_above_cap_quorum_shortfall(client, store, cfg, monkeypatch):
    sk_a, pk_a = _make_arbiter()
    sk_b, pk_b = _make_arbiter()
    monkeypatch.setenv("ARBITER_PUBKEYS", f"{pk_a},{pk_b}")
    monkeypatch.setenv("ARBITER_THRESHOLD", "2")
    cfg2 = Config()
    app.dependency_overrides[get_config] = lambda: cfg2

    sh = _seed_escrow(store, "svc-shortfall", amount=10_000)
    r = client.post(
        "/escrows/batch-preview",
        json={
            "action": "release",
            "service_hashes": [sh],
            "arbiter_pubkeys": [pk_a],
            "arbiter_signatures": [_sign_release(sk_a, sh)],
        },
    )
    body = r.json()
    assert body["admit"] is False
    assert body["needs_quorum"] is True
    assert bg.CODE_QUORUM_SHORTFALL in [x["code"] for x in body["rejections"]]
    reason = next(x for x in body["rejections"] if x["code"] == bg.CODE_QUORUM_SHORTFALL)
    assert reason["detail"]["valid_votes"] == 1
    assert reason["detail"]["required"] == 2


def test_preview_above_cap_valid_quorum_admits(client, store, cfg, monkeypatch):
    sk_a, pk_a = _make_arbiter()
    sk_b, pk_b = _make_arbiter()
    monkeypatch.setenv("ARBITER_PUBKEYS", f"{pk_a},{pk_b}")
    monkeypatch.setenv("ARBITER_THRESHOLD", "2")
    cfg2 = Config()
    app.dependency_overrides[get_config] = lambda: cfg2

    sh = _seed_escrow(store, "svc-quorum-ok", amount=10_000)
    r = client.post(
        "/escrows/batch-preview",
        json={
            "action": "release",
            "service_hashes": [sh],
            "arbiter_pubkeys": [pk_a, pk_b],
            "arbiter_signatures": [_sign_release(sk_a, sh), _sign_release(sk_b, sh)],
        },
    )
    body = r.json()
    assert body["admit"] is True, body
    assert body["needs_quorum"] is True
    assert body["valid_arbiter_votes"] == 2


def test_preview_cancel_never_quorum(client, store):
    sh = _seed_escrow(store, "svc-cancel", amount=100_000_000)
    r = client.post(
        "/escrows/batch-preview",
        json={"action": "cancel", "service_hashes": [sh]},
    )
    body = r.json()
    assert body["admit"] is True
    assert body["needs_quorum"] is False


def test_preview_unknown_action(client, store):
    sh = _seed_escrow(store, "svc-x", amount=100)
    r = client.post(
        "/escrows/batch-preview",
        json={"action": "burn", "service_hashes": [sh]},
    )
    body = r.json()
    assert body["admit"] is False
    assert body["rejections"][0]["code"] == bg.CODE_UNKNOWN_ACTION


def test_preview_dry_run_does_not_mutate(client, store):
    sh = _seed_escrow(store, "svc-noop", amount=100)
    before = store.get_escrow(sh)
    r = client.post(
        "/escrows/batch-preview",
        json={"action": "release", "service_hashes": [sh]},
    )
    assert r.status_code == 200
    after = store.get_escrow(sh)
    assert before.status == after.status == "pending"


def test_batch_release_route_now_uses_guard(client, store, monkeypatch):
    """Regression: after refactor, batch-release must produce the same
    typed error as the preview endpoint for the same input."""
    sh = "de" * 32
    r_preview = client.post(
        "/escrows/batch-preview",
        json={"action": "release", "service_hashes": [sh]},
    )
    assert r_preview.json()["admit"] is False

    r_do = client.post(
        "/escrows/batch-release",
        json={"service_hashes": [sh]},
    )
    assert r_do.status_code == 404  # ESCROW_NOT_FOUND maps to 404
