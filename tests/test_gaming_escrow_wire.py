"""C14 \u2014 tests for the gaming-arm + gaming-gated /release wire.

Complements test_gaming_merkle.py (pure helper): here we drive the actual
HTTP endpoints and confirm the escrow row + /release gate behave.
"""

from __future__ import annotations

import hashlib

import pytest
from fastapi.testclient import TestClient

from server.app import app, get_sandbox
from server.gaming_merkle import compute_root_and_proofs
from server.sandbox import SandboxStore

RECEIVER_HEX = "c" * 64


def _sh(seed: str) -> str:
    return hashlib.sha256(seed.encode()).hexdigest()


@pytest.fixture
def store() -> SandboxStore:
    return SandboxStore()


@pytest.fixture
def client(store: SandboxStore):
    app.dependency_overrides[get_sandbox] = lambda: store
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _create(client: TestClient, sh: str) -> None:
    r = client.post(
        "/escrow",
        json={
            "receiver": RECEIVER_HEX,
            "amount": 100,
            "service_hash": sh,
            "ttl": 86400,
        },
        params={"sender": "alice"},
    )
    assert r.status_code == 200, r.text


class TestArm:
    def test_arm_sets_type_and_root(self, client, store):
        sh = _sh("arm-set")
        _create(client, sh)
        root_hex = "ab" * 32
        r = client.post(
            f"/escrow/{sh}/gaming-arm",
            json={"service_hash": sh, "result_root_hex": root_hex},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["escrow_type"] == "gaming"
        assert body["gaming_result_root"] == root_hex

    def test_arm_rejects_non_hex_root(self, client):
        sh = _sh("arm-badroot")
        _create(client, sh)
        r = client.post(
            f"/escrow/{sh}/gaming-arm",
            json={"service_hash": sh, "result_root_hex": "z" * 64},
        )
        assert r.status_code == 422

    def test_double_arm_same_root_ok(self, client):
        sh = _sh("arm-idem")
        _create(client, sh)
        root_hex = "cd" * 32
        r1 = client.post(f"/escrow/{sh}/gaming-arm", json={"service_hash": sh, "result_root_hex": root_hex})
        r2 = client.post(f"/escrow/{sh}/gaming-arm", json={"service_hash": sh, "result_root_hex": root_hex})
        assert r1.status_code == 200 and r2.status_code == 200

    def test_double_arm_different_root_refused(self, client):
        sh = _sh("arm-race")
        _create(client, sh)
        r1 = client.post(f"/escrow/{sh}/gaming-arm", json={"service_hash": sh, "result_root_hex": "01" * 32})
        r2 = client.post(f"/escrow/{sh}/gaming-arm", json={"service_hash": sh, "result_root_hex": "02" * 32})
        assert r1.status_code == 200
        assert r2.status_code == 409


class TestReleaseGate:
    def _arm_with_leaves(self, client, sh, leaves: list[bytes]):
        root, proofs = compute_root_and_proofs(leaves)
        r = client.post(
            f"/escrow/{sh}/gaming-arm",
            json={"service_hash": sh, "result_root_hex": root.hex()},
        )
        assert r.status_code == 200, r.text
        return proofs

    def test_release_without_proof_refused(self, client):
        sh = _sh("rel-noproof")
        _create(client, sh)
        self._arm_with_leaves(client, sh, [b"winner-1", b"winner-2"])
        r = client.post("/release", json={"service_hash": sh}, params={"sender": "alice"})
        assert r.status_code == 422
        assert "gaming_leaf_hex is required" in r.json()["detail"]

    def test_release_with_valid_proof_succeeds(self, client):
        sh = _sh("rel-ok")
        _create(client, sh)
        proofs = self._arm_with_leaves(client, sh, [b"w1", b"w2", b"w3"])
        # Pick winner w2 and prove it.
        p = proofs[1]
        r = client.post(
            "/release",
            json={
                "service_hash": sh,
                "gaming_leaf_hex": p.leaf_value.hex(),
                "gaming_proof_hex": [s.hex() for s in p.siblings],
            },
            params={"sender": "alice"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "released"

    def test_release_with_wrong_leaf_refused(self, client):
        sh = _sh("rel-wrong-leaf")
        _create(client, sh)
        proofs = self._arm_with_leaves(client, sh, [b"w1", b"w2", b"w3"])
        p = proofs[0]
        r = client.post(
            "/release",
            json={
                "service_hash": sh,
                "gaming_leaf_hex": (b"NOT_A_WINNER").hex(),
                "gaming_proof_hex": [s.hex() for s in p.siblings],
            },
            params={"sender": "alice"},
        )
        assert r.status_code == 422
        assert "does not verify" in r.json()["detail"]

    def test_release_on_non_gaming_escrow_bypasses(self, client):
        # No arming \u2014 the gate must be inactive.
        sh = _sh("rel-nongaming")
        _create(client, sh)
        r = client.post("/release", json={"service_hash": sh}, params={"sender": "alice"})
        assert r.status_code == 200
        assert r.json()["status"] == "released"
