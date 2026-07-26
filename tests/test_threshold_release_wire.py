"""C13 \u2014 tests for the threshold-arm + threshold-gated /release wire.

Baseline T3.1 gave us `/threshold/*` endpoints for split / reconstruct, but
they lived alongside the escrow lifecycle rather than gating it. This suite
covers the actual gating semantics added in C13:

  1. Arming an escrow stores only the commitment hash; shares come back in
     the response exactly once.
  2. /release on an armed escrow with < n shares is refused.
  3. /release on an armed escrow with n valid shares succeeds.
  4. /release on an armed escrow with n shares whose secret is WRONG is
     refused (commitment mismatch).
  5. An unarmed escrow still releases without the shares field.
  6. Arming an already-armed escrow is refused (409, no clobber).
"""

from __future__ import annotations

import hashlib

import pytest
from fastapi.testclient import TestClient

from server.app import app, get_sandbox
from server.sandbox import SandboxStore


RECEIVER_HEX = "b" * 64


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


def _arm(client: TestClient, sh: str, n: int = 2, m: int = 3) -> list[str]:
    r = client.post(
        f"/escrow/{sh}/threshold-arm",
        json={"service_hash": sh, "threshold": n, "total": m},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["threshold_n"] == n and body["threshold_m"] == m
    assert len(body["shares_hex"]) == m
    # Commitment must be a hex sha256 digest.
    assert len(body["threshold_commitment_hex"]) == 64
    return body["shares_hex"]


class TestArmingSemantics:
    def test_arm_stores_only_commitment(self, client, store):
        sh = _sh("arm-commit")
        _create(client, sh)
        shares = _arm(client, sh, n=2, m=3)

        rec = store._escrows[sh]
        assert rec["threshold_n"] == 2 and rec["threshold_m"] == 3
        assert len(rec["threshold_commitment_hex"]) == 64
        # Shares are the only place the secret exists after arming \u2014 they
        # must NOT be anywhere on the row.
        for k, v in rec.items():
            for s in shares:
                assert v != s, f"share leaked into escrow.{k}"

    def test_double_arm_refused(self, client):
        sh = _sh("arm-double")
        _create(client, sh)
        _arm(client, sh)
        r = client.post(
            f"/escrow/{sh}/threshold-arm",
            json={"service_hash": sh, "threshold": 2, "total": 3},
        )
        assert r.status_code == 409

    def test_threshold_greater_than_total_refused(self, client):
        sh = _sh("arm-bad-nm")
        _create(client, sh)
        r = client.post(
            f"/escrow/{sh}/threshold-arm",
            json={"service_hash": sh, "threshold": 5, "total": 3},
        )
        assert r.status_code == 422


class TestReleaseGate:
    def test_release_without_shares_refused(self, client):
        sh = _sh("rel-no-shares")
        _create(client, sh)
        _arm(client, sh)
        r = client.post("/release", json={"service_hash": sh}, params={"sender": "alice"})
        assert r.status_code == 422
        assert "threshold release" in r.json()["detail"]

    def test_release_with_insufficient_shares_refused(self, client):
        sh = _sh("rel-short")
        _create(client, sh)
        shares = _arm(client, sh, n=3, m=5)
        # Present only 2 when 3 are needed.
        r = client.post(
            "/release",
            json={"service_hash": sh, "threshold_shares_hex": shares[:2]},
            params={"sender": "alice"},
        )
        assert r.status_code == 422
        assert "need >= 3 shares" in r.json()["detail"]

    def test_release_with_valid_shares_succeeds(self, client):
        sh = _sh("rel-ok")
        _create(client, sh)
        shares = _arm(client, sh, n=2, m=3)
        r = client.post(
            "/release",
            json={"service_hash": sh, "threshold_shares_hex": shares[:2]},
            params={"sender": "alice"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "released"

    def test_release_with_forged_shares_refused(self, client):
        # Fabricate 2 syntactically-valid shares that do NOT reconstruct
        # to the committed secret. The gate must reject with a specific
        # \"does not match commitment\" reason (not a malformed-share error).
        sh = _sh("rel-forged")
        _create(client, sh)
        _arm(client, sh, n=2, m=3)
        fake_share_1 = "0001" + "aa" * 32
        fake_share_2 = "0002" + "bb" * 32
        r = client.post(
            "/release",
            json={
                "service_hash": sh,
                "threshold_shares_hex": [fake_share_1, fake_share_2],
            },
            params={"sender": "alice"},
        )
        assert r.status_code == 422
        assert "does not match commitment" in r.json()["detail"]

    def test_unarmed_escrow_releases_without_shares_field(self, client):
        sh = _sh("rel-unarmed")
        _create(client, sh)
        # No arming \u2014 default sandbox happy-path must still work.
        r = client.post("/release", json={"service_hash": sh}, params={"sender": "alice"})
        assert r.status_code == 200
        assert r.json()["status"] == "released"
