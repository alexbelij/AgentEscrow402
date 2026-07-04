"""Integration tests for server/multi_asset.py: /escrow/multi-asset,
/escrow/stream, /escrow/{hash}/stream-status, /escrow/atomic-swap/commit
and /escrow/atomic-swap/reveal.

Before this test file existed these 4 endpoints had zero test coverage and
were, in fact, completely non-functional end-to-end:

1. `Depends(parse_x402_header)` was used with `parse_x402_header(raw: str)`
   (a plain positional-string function) as the FastAPI dependency, so
   FastAPI required a `raw` *query* parameter instead of reading the
   `X-Payment` header. Every request 422'd unconditionally.
2. `Depends(get_token_adapter)` had an un-annotated `token_id: TokenIdentifier`
   parameter, which FastAPI treated as a second required top-level request
   body field, breaking the documented single-JSON-body contract.
3. All DB calls (`db.create_escrow`, `db.get_escrow`, `db.update_escrow_status`)
   were made against `InMemoryDB`, which only implements
   `get_collection`/`insert`/`find` - none of the called methods exist
   anywhere in `server/db.py`. Every call past bug #1/#2 would have crashed
   with AttributeError.
4. The hosted-console demo-identity bypass only recognized one fixed sender
   identity, but atomic-swap inherently needs two (sender commits, receiver
   reveals) - the reveal step could never succeed via the console's demo
   bypass.

These tests exercise the real, fixed code paths using the same
hosted-console demo-identity bypass the frontend console uses
(`lib/api.ts`'s `buildDemoPaymentHeaders`), via `SandboxStore` as the shared
escrow store (same one the main /escrow lifecycle endpoints use).
"""
from __future__ import annotations

import hashlib
import time

import pytest
from fastapi.testclient import TestClient

import server.app as appmod
from server.sandbox import SandboxStore

DEMO_SENDER = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
DEMO_RECEIVER = "fedcba9876543210fedcba9876543210fedcba9876543210fedcba9876543210"
DEMO_SIG = "a" * 128


def _demo_header(service_hash: str, amount: int, sender: str, nonce: str) -> dict[str, str]:
    return {
        "X-Payment": f"x402-v1;{service_hash};{amount};{sender};{int(time.time())};{nonce};{DEMO_SIG}",
        "X-AE402-Demo-Identity": "hosted-console",
    }


@pytest.fixture(autouse=True)
def _allow_hosted_demo_identity(monkeypatch):
    # server.config.get_config() (used by server/multi_asset.py's own
    # Depends(get_config)) reads this env var fresh on every call, unlike
    # app.py's own @lru_cache'd get_config - setting the env var is what
    # actually takes effect for this router regardless of dependency_overrides.
    monkeypatch.setenv("ALLOW_HOSTED_DEMO_IDENTITY", "true")


class _FakeCasper:
    """Truthy stand-in for a real CasperClient - the simulated token
    adapters never actually call any of its methods, but app.py's lifespan
    shutdown calls `await casper.close()` unconditionally."""

    async def close(self) -> None:
        return None


@pytest.fixture
def client(monkeypatch):
    store = SandboxStore()
    monkeypatch.setattr(appmod, "_casper", _FakeCasper(), raising=False)
    appmod.app.dependency_overrides[appmod.get_sandbox] = lambda: store
    with TestClient(appmod.app) as c:
        yield c
    appmod.app.dependency_overrides.clear()


def _hash(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def test_create_multi_asset_escrow_success(client):
    service_hash = _hash("multi-asset-ok")
    res = client.post(
        "/escrow/multi-asset",
        json={
            "receiver": DEMO_RECEIVER,
            "amount": 1000,
            "token": {"token_type": "cspr"},
            "service_hash": service_hash,
            "ttl": 300,
        },
        headers=_demo_header(service_hash, 1000, DEMO_SENDER, "n" * 16),
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["sender"] == DEMO_SENDER
    assert body["receiver"] == DEMO_RECEIVER
    assert body["amount"] == 1000
    assert body["status"] == "pending"
    assert body["deploy_hash"]


def test_create_multi_asset_escrow_amount_mismatch_rejected(client):
    service_hash = _hash("multi-asset-mismatch")
    res = client.post(
        "/escrow/multi-asset",
        json={
            "receiver": DEMO_RECEIVER,
            "amount": 500,
            "token": {"token_type": "cspr"},
            "service_hash": service_hash,
            "ttl": 300,
        },
        # x402 header carries amount=1000, body says 500 -> must be rejected
        headers=_demo_header(service_hash, 1000, DEMO_SENDER, "m" * 16),
    )
    assert res.status_code == 400


def test_create_multi_asset_escrow_requires_x_payment_header(client):
    service_hash = _hash("multi-asset-no-auth")
    res = client.post(
        "/escrow/multi-asset",
        json={
            "receiver": DEMO_RECEIVER,
            "amount": 1000,
            "token": {"token_type": "cspr"},
            "service_hash": service_hash,
            "ttl": 300,
        },
    )
    assert res.status_code == 401


def test_create_stream_escrow_and_status(client):
    service_hash = _hash("stream-ok")
    now = int(time.time())
    res = client.post(
        "/escrow/stream",
        json={
            "receiver": DEMO_RECEIVER,
            "amount": 2000,
            "token": {"token_type": "cspr"},
            "service_hash": service_hash,
            "start_time": now,
            "end_time": now + 3600,
        },
        headers=_demo_header(service_hash, 2000, DEMO_SENDER, "s" * 16),
    )
    assert res.status_code == 201, res.text

    status_res = client.get(f"/escrow/{service_hash}/stream-status")
    assert status_res.status_code == 200
    status_body = status_res.json()
    assert status_body["total_amount"] == 2000
    assert status_body["receiver"] == DEMO_RECEIVER
    assert status_body["status"] in ("pending", "active")


def test_stream_status_not_found(client):
    res = client.get(f"/escrow/{_hash('never-created')}/stream-status")
    assert res.status_code == 404


def test_atomic_swap_commit_then_reveal_full_flow(client):
    service_hash = _hash("swap-ok")
    create_res = client.post(
        "/escrow/multi-asset",
        json={
            "receiver": DEMO_RECEIVER,
            "amount": 1000,
            "token": {"token_type": "cspr"},
            "service_hash": service_hash,
            "ttl": 300,
        },
        headers=_demo_header(service_hash, 1000, DEMO_SENDER, "c" * 16),
    )
    assert create_res.status_code == 201

    commit_hash = _hash("swap-secret")
    commit_res = client.post(
        "/escrow/atomic-swap/commit",
        json={"service_hash": service_hash, "commit_hash": commit_hash},
        headers=_demo_header(service_hash, 0, DEMO_SENDER, "d" * 16),
    )
    assert commit_res.status_code == 202, commit_res.text

    reveal_res = client.post(
        "/escrow/atomic-swap/reveal",
        json={"service_hash": service_hash, "preimage": "swap-secret"},
        headers=_demo_header(service_hash, 0, DEMO_RECEIVER, "e" * 16),
    )
    assert reveal_res.status_code == 200, reveal_res.text


def test_atomic_swap_reveal_wrong_preimage_rejected(client):
    service_hash = _hash("swap-wrong-preimage")
    client.post(
        "/escrow/multi-asset",
        json={
            "receiver": DEMO_RECEIVER,
            "amount": 1000,
            "token": {"token_type": "cspr"},
            "service_hash": service_hash,
            "ttl": 300,
        },
        headers=_demo_header(service_hash, 1000, DEMO_SENDER, "f" * 16),
    )
    commit_hash = _hash("real-secret")
    client.post(
        "/escrow/atomic-swap/commit",
        json={"service_hash": service_hash, "commit_hash": commit_hash},
        headers=_demo_header(service_hash, 0, DEMO_SENDER, "g" * 16),
    )
    res = client.post(
        "/escrow/atomic-swap/reveal",
        json={"service_hash": service_hash, "preimage": "wrong-secret"},
        headers=_demo_header(service_hash, 0, DEMO_RECEIVER, "h" * 16),
    )
    assert res.status_code == 400


def test_atomic_swap_commit_requires_escrow_sender(client):
    service_hash = _hash("swap-wrong-committer")
    client.post(
        "/escrow/multi-asset",
        json={
            "receiver": DEMO_RECEIVER,
            "amount": 1000,
            "token": {"token_type": "cspr"},
            "service_hash": service_hash,
            "ttl": 300,
        },
        headers=_demo_header(service_hash, 1000, DEMO_SENDER, "i" * 16),
    )
    # Receiver (not sender) tries to commit -> forbidden.
    res = client.post(
        "/escrow/atomic-swap/commit",
        json={"service_hash": service_hash, "commit_hash": _hash("x")},
        headers=_demo_header(service_hash, 0, DEMO_RECEIVER, "j" * 16),
    )
    assert res.status_code == 403


def test_atomic_swap_commit_missing_escrow_404(client):
    res = client.post(
        "/escrow/atomic-swap/commit",
        json={"service_hash": _hash("no-such-escrow"), "commit_hash": _hash("x")},
        headers=_demo_header(_hash("no-such-escrow"), 0, DEMO_SENDER, "k" * 16),
    )
    assert res.status_code == 404


def test_atomic_swap_double_reveal_conflicts(client):
    service_hash = _hash("swap-double-reveal")
    client.post(
        "/escrow/multi-asset",
        json={
            "receiver": DEMO_RECEIVER,
            "amount": 1000,
            "token": {"token_type": "cspr"},
            "service_hash": service_hash,
            "ttl": 300,
        },
        headers=_demo_header(service_hash, 1000, DEMO_SENDER, "l" * 16),
    )
    commit_hash = _hash("double-reveal-secret")
    client.post(
        "/escrow/atomic-swap/commit",
        json={"service_hash": service_hash, "commit_hash": commit_hash},
        headers=_demo_header(service_hash, 0, DEMO_SENDER, "o" * 16),
    )
    first = client.post(
        "/escrow/atomic-swap/reveal",
        json={"service_hash": service_hash, "preimage": "double-reveal-secret"},
        headers=_demo_header(service_hash, 0, DEMO_RECEIVER, "p" * 16),
    )
    assert first.status_code == 200
    second = client.post(
        "/escrow/atomic-swap/reveal",
        json={"service_hash": service_hash, "preimage": "double-reveal-secret"},
        headers=_demo_header(service_hash, 0, DEMO_RECEIVER, "q" * 16),
    )
    assert second.status_code == 409
