"""API tests for T3.1 threshold-secret endpoints."""

from __future__ import annotations

import base64

from fastapi.testclient import TestClient

from server.app import app


def _client():
    return TestClient(app)


def test_config_endpoint():
    with _client() as c:
        r = c.get("/threshold/config")
        assert r.status_code == 200
        data = r.json()
        assert data["min_threshold"] == 2
        assert data["max_total_shares"] == 255
        assert "Shamir" in data["algorithm"]


def test_split_and_reconstruct_roundtrip():
    with _client() as c:
        payload = b"release-authorization-for-escrow-abc123"
        r = c.post(
            "/threshold/split",
            json={
                "payload_b64": base64.b64encode(payload).decode(),
                "threshold": 3,
                "total_shares": 5,
            },
        )
        assert r.status_code == 200, r.text
        bundle = r.json()
        assert len(bundle["shares_hex"]) == 5
        assert bundle["threshold"] == 3

        # Reconstruct
        r2 = c.post(
            "/threshold/reconstruct",
            json={
                "encrypted_payload_b64": bundle["encrypted_payload_b64"],
                "shares_hex": bundle["shares_hex"][:3],
                "threshold": 3,
            },
        )
        assert r2.status_code == 200, r2.text
        recovered = base64.b64decode(r2.json()["payload_b64"])
        assert recovered == payload


def test_reconstruct_insufficient_shares_rejected():
    with _client() as c:
        payload = b"test"
        r = c.post(
            "/threshold/split",
            json={
                "payload_b64": base64.b64encode(payload).decode(),
                "threshold": 3,
                "total_shares": 5,
            },
        )
        bundle = r.json()
        r2 = c.post(
            "/threshold/reconstruct",
            json={
                "encrypted_payload_b64": bundle["encrypted_payload_b64"],
                "shares_hex": bundle["shares_hex"][:2],
                "threshold": 3,
            },
        )
        assert r2.status_code == 400
        assert "need 3 shares" in r2.json()["detail"]


def test_split_invalid_base64_rejected():
    with _client() as c:
        r = c.post(
            "/threshold/split",
            json={"payload_b64": "!!!not-base64!!!", "threshold": 3, "total_shares": 5},
        )
        assert r.status_code == 400


def test_split_total_lt_threshold_rejected():
    with _client() as c:
        r = c.post(
            "/threshold/split",
            json={
                "payload_b64": base64.b64encode(b"x").decode(),
                "threshold": 5,
                "total_shares": 3,
            },
        )
        assert r.status_code == 400


def test_reconstruct_tampered_shares_fails_mac():
    with _client() as c:
        payload = b"x"
        r = c.post(
            "/threshold/split",
            json={
                "payload_b64": base64.b64encode(payload).decode(),
                "threshold": 3,
                "total_shares": 5,
            },
        )
        bundle = r.json()
        # Corrupt one share's value byte
        tampered = list(bundle["shares_hex"][:3])
        tampered[0] = tampered[0][:4] + ("f" * 64)  # zero out
        r2 = c.post(
            "/threshold/reconstruct",
            json={
                "encrypted_payload_b64": bundle["encrypted_payload_b64"],
                "shares_hex": tampered,
                "threshold": 3,
            },
        )
        # Reconstruct will yield wrong secret → MAC fails
        assert r2.status_code == 400
        assert "MAC" in r2.json()["detail"]
