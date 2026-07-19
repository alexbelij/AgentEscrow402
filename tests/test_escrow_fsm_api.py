"""HTTP-layer contract for the deny-by-default FSM (AE-14).

Ensures the FastAPI endpoints surface :class:`InvalidTransitionError`
as HTTP 409 with the stable JSON payload documented in ``docs/FSM.md``,
while unrelated ``ValueError`` still returns 400 and permission checks
return 403.

Sandbox identity is threaded via the ``?sender=`` query param, which
:func:`server.app._extract_sender` reads when ``config.sandbox`` is
true — no x402 header signing needed for these tests.
"""

from __future__ import annotations

import hashlib

import pytest
from fastapi.testclient import TestClient

from server.app import app, get_sandbox
from server.sandbox import SandboxStore


def _hash(payload: str) -> str:
    return hashlib.sha256(payload.encode()).hexdigest()


@pytest.fixture()
def fsm_sandbox() -> SandboxStore:
    """Local sandbox override — the conftest ``sandbox`` fixture is a
    bare :class:`SandboxStore` instance not wired into FastAPI's DI. We
    need the API layer to use our store so the seeded escrow is visible
    to the endpoints, hence the ``dependency_overrides`` dance.
    """
    store = SandboxStore()
    app.dependency_overrides[get_sandbox] = lambda: store
    try:
        yield store
    finally:
        app.dependency_overrides.pop(get_sandbox, None)


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture()
def hash_() -> str:
    return _hash("fsm-api-test-1")


@pytest.fixture()
def parties() -> tuple[str, str]:
    return ("a" * 64, "b" * 64)


def _seed(sandbox: SandboxStore, hash_: str, parties: tuple[str, str]) -> None:
    sender, receiver = parties
    sandbox.create_escrow(sender, receiver, 1000, hash_, 300)


def test_release_on_released_escrow_returns_409_payload(
    client: TestClient,
    fsm_sandbox: SandboxStore,
    hash_: str,
    parties: tuple[str, str],
) -> None:
    sender, _ = parties
    _seed(fsm_sandbox, hash_, parties)

    r1 = client.post(f"/release?sender={sender}", json={"service_hash": hash_})
    assert r1.status_code == 200, r1.text

    r2 = client.post(f"/release?sender={sender}", json={"service_hash": hash_})
    assert r2.status_code == 409, r2.text
    detail = r2.json().get("detail", {})
    assert detail["code"] == "invalid_transition"
    assert detail["current_state"] == "released"
    assert detail["action"] == "release"
    assert detail["allowed_actions"] == []
    assert "terminal state" in detail["message"]


def test_dispute_after_release_returns_409(
    client: TestClient,
    fsm_sandbox: SandboxStore,
    hash_: str,
    parties: tuple[str, str],
) -> None:
    sender, _ = parties
    _seed(fsm_sandbox, hash_, parties)
    client.post(f"/release?sender={sender}", json={"service_hash": hash_}).raise_for_status()

    reason = _hash("bad-service")
    r = client.post(
        f"/dispute?sender={sender}",
        json={"service_hash": hash_, "reason_hash": reason},
    )
    assert r.status_code == 409, r.text
    detail = r.json().get("detail", {})
    assert detail["code"] == "invalid_transition"
    assert detail["current_state"] == "released"
    assert detail["action"] == "dispute"


def test_refund_on_disputed_returns_409(
    client: TestClient,
    fsm_sandbox: SandboxStore,
    hash_: str,
    parties: tuple[str, str],
) -> None:
    sender, _ = parties
    _seed(fsm_sandbox, hash_, parties)
    reason = _hash("bad-service")
    client.post(
        f"/dispute?sender={sender}",
        json={"service_hash": hash_, "reason_hash": reason},
    ).raise_for_status()

    r = client.post(f"/refund?sender={sender}", json={"service_hash": hash_})
    assert r.status_code == 409, r.text
    detail = r.json().get("detail", {})
    assert detail["code"] == "invalid_transition"
    assert detail["current_state"] == "disputed"
    assert detail["action"] == "refund"
    assert "resolve_sender" in detail["allowed_actions"]
    assert "resolve_receiver" in detail["allowed_actions"]


def test_release_by_non_sender_leaves_state_pending(
    client: TestClient,
    fsm_sandbox: SandboxStore,
    hash_: str,
    parties: tuple[str, str],
) -> None:
    """A non-sender release attempt must never trigger the FSM.

    The endpoint refuses the request (403 for authenticated sandbox
    caller, 401 if a real x402 header pipeline is in front) and,
    crucially, the escrow stays in PENDING so the real sender can still
    complete the lifecycle. This locks in the ``PermissionError -> 403``
    upgrade shipped in the same batch (was 400 before).
    """
    _seed(fsm_sandbox, hash_, parties)
    stranger = "c" * 64
    r = client.post(
        f"/release?sender={stranger}",
        json={"service_hash": hash_},
    )
    assert r.status_code in (401, 403), r.text
    escrow = fsm_sandbox.get_escrow(hash_)
    assert escrow is not None
    assert escrow.status.value == "pending"


def test_release_missing_escrow_returns_404(
    client: TestClient,
    fsm_sandbox: SandboxStore,
    parties: tuple[str, str],
) -> None:
    sender, _ = parties
    r = client.post(
        f"/release?sender={sender}",
        json={"service_hash": _hash("nope")},
    )
    assert r.status_code == 404, r.text
