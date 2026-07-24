"""End-to-end HTTP tests for /macaroons/* — mint, attenuate, verify, discharge."""

from __future__ import annotations

import base64
import os
import time

import pytest
from fastapi.testclient import TestClient

ROOT_SECRET_HEX = "a" * 64  # 32 bytes hex; well over the 24-byte floor


@pytest.fixture(scope="module")
def client() -> TestClient:
    os.environ["MACAROON_ROOT_SECRET"] = ROOT_SECRET_HEX
    os.environ["SANDBOX"] = "true"
    from server.app import app
    from server.config import Config

    # Wipe cached Config so from_env re-reads MACAROON_ROOT_SECRET.
    if hasattr(Config, "_cached"):  # defensive; not currently used but future-proof
        Config._cached = None

    return TestClient(app)


def _mint(client: TestClient, **kwargs) -> dict:
    r = client.post("/macaroons/mint", json=kwargs or {})
    assert r.status_code == 200, r.text
    return r.json()


def test_policy_endpoint(client: TestClient) -> None:
    r = client.get("/macaroons/policy")
    assert r.status_code == 200
    body = r.json()
    assert body["version"] == 1
    assert "expires" in body["caveats"]
    assert "capability" in body["caveats"]


def test_mint_default_ttl_carries_expiry_caveat(client: TestClient) -> None:
    body = _mint(client, ttl_seconds=60)
    assert any(c.startswith("expires<") for c in body["caveats"])
    assert body["expires_at"] > int(time.time())


def test_mint_with_extra_caveats(client: TestClient) -> None:
    body = _mint(client, caveats=["capability=release", "escrow_id=e42"], ttl_seconds=120)
    assert "capability=release" in body["caveats"]
    assert "escrow_id=e42" in body["caveats"]


def test_verify_accepts_matching_facts(client: TestClient) -> None:
    body = _mint(client, caveats=["capability=release", "escrow_id=e42"], ttl_seconds=120)
    r = client.post(
        "/macaroons/verify",
        json={"token": body["token"], "facts": {"capability": "release", "escrow_id": "e42"}},
    )
    assert r.status_code == 200, r.text
    result = r.json()
    assert result["ok"] is True, result


def test_verify_rejects_missing_fact(client: TestClient) -> None:
    body = _mint(client, caveats=["capability=release"], ttl_seconds=120)
    r = client.post(
        "/macaroons/verify",
        json={"token": body["token"], "facts": {}},
    )
    assert r.status_code == 200
    result = r.json()
    assert result["ok"] is False
    assert "capability=release" in result["detail"]


def test_verify_rejects_expired_token(client: TestClient) -> None:
    body = _mint(client, ttl_seconds=1)
    time.sleep(1.5)
    r = client.post(
        "/macaroons/verify",
        json={"token": body["token"], "facts": {}},
    )
    assert r.status_code == 200
    result = r.json()
    assert result["ok"] is False
    assert "caveat failed" in result["detail"] or "expires" in result["detail"]


def test_verify_uses_supplied_now(client: TestClient) -> None:
    """`now` in the verify request lets a caller check acceptance at a
    hypothetical future time — but must not extend a token past its own
    expiry."""
    body = _mint(client, ttl_seconds=60)
    # Now-in-the-past: token still valid.
    r = client.post(
        "/macaroons/verify",
        json={"token": body["token"], "facts": {}, "now": int(time.time())},
    )
    assert r.json()["ok"] is True
    # Now = past expiry: token invalid.
    r = client.post(
        "/macaroons/verify",
        json={"token": body["token"], "facts": {}, "now": int(time.time()) + 3600},
    )
    assert r.json()["ok"] is False


def test_attenuate_via_endpoint_matches_client_side(client: TestClient) -> None:
    body = _mint(client, ttl_seconds=120)
    r = client.post(
        "/macaroons/attenuate",
        json={"token": body["token"], "caveats": ["capability=release", "amount<=100"]},
    )
    assert r.status_code == 200
    new_caveats = r.json()["caveats"]
    assert "capability=release" in new_caveats
    assert "amount<=100" in new_caveats
    # Verify with satisfying facts:
    v = client.post(
        "/macaroons/verify",
        json={
            "token": r.json()["token"],
            "facts": {"capability": "release", "amount": 50},
        },
    )
    assert v.json()["ok"] is True


def test_attenuate_amount_boundary(client: TestClient) -> None:
    body = _mint(client, ttl_seconds=120)
    a = client.post(
        "/macaroons/attenuate",
        json={"token": body["token"], "caveats": ["amount<=100"]},
    ).json()
    # Amount exactly at boundary: accepted.
    v_ok = client.post("/macaroons/verify", json={"token": a["token"], "facts": {"amount": 100}}).json()
    assert v_ok["ok"] is True
    # Amount 101: rejected.
    v_no = client.post("/macaroons/verify", json={"token": a["token"], "facts": {"amount": 101}}).json()
    assert v_no["ok"] is False


def test_discharge_flow(client: TestClient) -> None:
    # 1. Mint root.
    body = _mint(client, ttl_seconds=120)
    # 2. Attach third-party caveat pointing at "arb-1".
    tp = client.post(
        "/macaroons/add-third-party",
        json={
            "token": body["token"],
            "discharge_identifier": "arb-1",
            "location": "arbiter",
            "predicate_hint": "authorised",
        },
    ).json()
    # 3. Discharger mints its discharge macaroon.
    d = client.post(
        "/macaroons/discharge",
        json={"discharge_identifier": "arb-1", "location": "arbiter", "ttl_seconds": 60},
    ).json()
    # 4. Verify with the discharge attached.
    v = client.post(
        "/macaroons/verify",
        json={"token": tp["token"], "facts": {}, "discharges": [d["token"]]},
    ).json()
    assert v["ok"] is True, v


def test_verify_rejects_missing_discharge(client: TestClient) -> None:
    body = _mint(client, ttl_seconds=120)
    tp = client.post(
        "/macaroons/add-third-party",
        json={"token": body["token"], "discharge_identifier": "arb-1", "location": "arbiter"},
    ).json()
    v = client.post("/macaroons/verify", json={"token": tp["token"], "facts": {}}).json()
    assert v["ok"] is False
    assert "missing discharge" in v["detail"]


def test_verify_rejects_garbage_token(client: TestClient) -> None:
    r = client.post("/macaroons/verify", json={"token": "@@@nonsense@@@", "facts": {}})
    assert r.status_code == 400


def test_missing_root_secret_yields_503() -> None:
    # Spin up an isolated client with the env var cleared.
    os.environ.pop("MACAROON_ROOT_SECRET", None)
    from importlib import reload

    import server.config as config_mod

    reload(config_mod)
    import server.app as app_mod

    reload(app_mod)
    isolated_client = TestClient(app_mod.app)
    r = isolated_client.post("/macaroons/mint", json={})
    assert r.status_code == 503
    assert "macaroon_root_secret" in r.json()["detail"]

    # Restore for other tests in this module (setUp guarantee).
    os.environ["MACAROON_ROOT_SECRET"] = ROOT_SECRET_HEX
    reload(config_mod)
    reload(app_mod)


def test_short_root_secret_rejected() -> None:
    os.environ["MACAROON_ROOT_SECRET"] = "shorty"  # < 24 bytes after any decoding
    from importlib import reload

    import server.config as config_mod

    reload(config_mod)
    import server.app as app_mod

    reload(app_mod)
    isolated_client = TestClient(app_mod.app)
    r = isolated_client.post("/macaroons/mint", json={})
    assert r.status_code == 503
    assert ">=24 bytes" in r.json()["detail"]

    os.environ["MACAROON_ROOT_SECRET"] = ROOT_SECRET_HEX
    reload(config_mod)
    reload(app_mod)


def test_root_secret_accepts_base64url(client: TestClient) -> None:
    """A base64url-encoded root secret must also work — the config decoder
    tries base64 first."""
    b64 = base64.urlsafe_b64encode(b"z" * 32).rstrip(b"=").decode("ascii")
    os.environ["MACAROON_ROOT_SECRET"] = b64
    from importlib import reload

    import server.config as config_mod

    reload(config_mod)
    import server.app as app_mod

    reload(app_mod)
    isolated_client = TestClient(app_mod.app)
    r = isolated_client.post("/macaroons/mint", json={"ttl_seconds": 60})
    assert r.status_code == 200, r.text
    assert r.json()["token"]

    os.environ["MACAROON_ROOT_SECRET"] = ROOT_SECRET_HEX
    reload(config_mod)
    reload(app_mod)
