"""API-level tests for the W.2 confidential-amount escrow lifecycle:
`POST /escrow` with `confidential: true`, `GET /escrow/{service_hash}`
re-redaction, and `POST /escrow/{service_hash}/reveal`.

Uses the same per-test isolated `client`/`sandbox_store` fixture pattern as
tests/test_api.py so confidential escrows created in one test never leak
into another test's SandboxStore or the module-level `_confidential_ledger`
in server/confidential_escrow.py.
"""

from __future__ import annotations

import hashlib

import pytest
from fastapi.testclient import TestClient

from server import confidential_escrow as ce
from server.app import app, get_config, get_sandbox
from server.config import Config
from server.sandbox import SandboxStore


def _hash(val: str) -> str:
    return hashlib.sha256(val.encode()).hexdigest()


RECEIVER_HEX = "ab" * 32


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


@pytest.fixture(autouse=True)
def _clean_confidential_ledger():
    """The private seal ledger in confidential_escrow.py is a module-global
    dict (deliberately outside SandboxStore/EscrowRecord — see that module's
    docstring). Clear entries this test file creates so a leftover seal from
    one test can't be picked up by a same-named service_hash in another."""
    yield
    ce._confidential_ledger.clear()


class TestCreateConfidentialEscrow:
    def test_confidential_flag_redacts_amount_in_response(self, client):
        h = _hash("conf-001")
        resp = client.post(
            "/escrow",
            json={"receiver": RECEIVER_HEX, "amount": 5000, "service_hash": h, "confidential": True},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["confidential"] is True
        assert body["amount"] == -1
        assert body["commitment"] is not None
        assert body["range_proof_bits"] == ce.ESCROW_RANGE_BITS

    def test_non_confidential_escrow_unaffected(self, client):
        h = _hash("conf-002")
        resp = client.post(
            "/escrow",
            json={"receiver": RECEIVER_HEX, "amount": 5000, "service_hash": h},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["confidential"] is False
        assert body["amount"] == 4900  # net after 2% insurance fee, plaintext as before
        assert body["commitment"] is None

    def test_confidential_escrow_seal_persisted_privately(self, client):
        h = _hash("conf-003")
        resp = client.post(
            "/escrow",
            json={"receiver": RECEIVER_HEX, "amount": 5000, "service_hash": h, "confidential": True},
        )
        assert resp.status_code == 200, resp.text
        seal = ce.get_seal(h)
        assert seal is not None
        assert "blinding" in seal
        assert resp.json()["commitment"] == seal["commitment"]

    def test_confidential_escrow_amount_too_large_for_range_bits_returns_422(self, client):
        h = _hash("conf-004")
        # The escrow-create path deducts a 2% insurance fee before sealing
        # (seal_amount is called on net_amount, not the raw request amount),
        # so the request amount must overshoot the bit cap by more than the
        # fee shaves off for net_amount to still land out of range.
        too_large = (1 << ce.ESCROW_RANGE_BITS) * 2
        resp = client.post(
            "/escrow",
            json={"receiver": RECEIVER_HEX, "amount": too_large, "service_hash": h, "confidential": True},
        )
        assert resp.status_code == 422, resp.text


class TestGetConfidentialEscrow:
    def test_get_reflects_redaction(self, client):
        h = _hash("conf-010")
        client.post(
            "/escrow",
            json={"receiver": RECEIVER_HEX, "amount": 7000, "service_hash": h, "confidential": True},
        )
        resp = client.get(f"/escrow/{h}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["amount"] == -1
        assert body["confidential"] is True
        assert body["commitment"] is not None

    def test_get_non_confidential_escrow_shows_real_amount(self, client):
        h = _hash("conf-011")
        client.post("/escrow", json={"receiver": RECEIVER_HEX, "amount": 7000, "service_hash": h})
        resp = client.get(f"/escrow/{h}")
        assert resp.status_code == 200
        assert resp.json()["amount"] == 6860  # net after fee


class TestRevealConfidentialAmount:
    def test_reveal_with_correct_blinding_succeeds(self, client):
        h = _hash("conf-020")
        create_resp = client.post(
            "/escrow",
            json={"receiver": RECEIVER_HEX, "amount": 10_000, "service_hash": h, "confidential": True},
        )
        seal = ce.get_seal(h)
        resp = client.post(f"/escrow/{h}/reveal", json={"blinding": seal["blinding"]})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["verified"] is True
        assert body["service_hash"] == h
        # net_amount after 2% insurance fee — same net_amount the sealed
        # commitment was built from, and what create returned before redaction.
        assert create_resp.json()["amount"] == -1
        assert body["amount"] == 9_800

    def test_reveal_with_wrong_blinding_returns_403(self, client):
        h = _hash("conf-021")
        client.post(
            "/escrow",
            json={"receiver": RECEIVER_HEX, "amount": 10_000, "service_hash": h, "confidential": True},
        )
        resp = client.post(f"/escrow/{h}/reveal", json={"blinding": "aa" * 32})
        assert resp.status_code == 403

    def test_reveal_on_non_confidential_escrow_returns_400(self, client):
        h = _hash("conf-022")
        client.post("/escrow", json={"receiver": RECEIVER_HEX, "amount": 1000, "service_hash": h})
        resp = client.post(f"/escrow/{h}/reveal", json={"blinding": "aa" * 32})
        assert resp.status_code == 400

    def test_reveal_on_nonexistent_escrow_returns_404(self, client):
        h = _hash("conf-does-not-exist")
        resp = client.post(f"/escrow/{h}/reveal", json={"blinding": "aa" * 32})
        assert resp.status_code == 404

    def test_reveal_rejects_malformed_blinding_shape(self, client):
        h = _hash("conf-023")
        client.post(
            "/escrow",
            json={"receiver": RECEIVER_HEX, "amount": 1000, "service_hash": h, "confidential": True},
        )
        # Not 64 hex chars -> pydantic 422, never reaches confidential_escrow.reveal
        resp = client.post(f"/escrow/{h}/reveal", json={"blinding": "not-hex"})
        assert resp.status_code == 422


class TestConfidentialEscrowLifecycleInteraction:
    """Confidentiality only affects presentation of `amount` — the escrow's
    FSM lifecycle (release/refund/dispute) must work exactly as it does for
    a plaintext escrow, since the server still tracks the real amount
    privately for actual fund movement."""

    def test_confidential_escrow_can_still_be_released(self, client):
        h = _hash("conf-030")
        create_resp = client.post(
            "/escrow",
            json={"receiver": RECEIVER_HEX, "amount": 3000, "service_hash": h, "confidential": True},
        )
        assert create_resp.status_code == 200, create_resp.text
        resp = client.post("/release", json={"service_hash": h})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "released"
        # Still redacted post-release — confidentiality survives the FSM transition.
        assert body["amount"] == -1
        assert body["confidential"] is True
