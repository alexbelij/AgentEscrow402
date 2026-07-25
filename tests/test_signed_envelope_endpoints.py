"""End-to-end tests for advisory signed-envelope enforcement on
existing escrow endpoints (/escrow, /release, /refund, /dispute).

Two rollout modes:

1. **Advisory (default)** — no ``AE402_ENFORCE_SIGNED_ENVELOPES``:
   * Missing header → handler runs as before.
   * Present + valid → handler runs, ``request.state.ae402_envelope``
     is populated.
   * Present + tampered / replayed / wrong-domain → 4xx.

2. **Strict (``AE402_ENFORCE_SIGNED_ENVELOPES=1``)**:
   * Missing header → 401.
   * Rest identical to advisory.
"""

from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from typing import Iterator

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from fastapi.testclient import TestClient

from server import app as app_module
from server.middleware import (
    ENFORCE_ENVELOPES_ENV,
    ENVELOPE_HEADER,
    _default_nonce_store,
)
from server.signed_envelope import (
    DomainSeparator,
    SignedEnvelope,
    sign_envelope_ed25519,
)


CHAIN_ID = "casper-test"


@pytest.fixture(autouse=True)
def _env_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AE402_CHAIN_ID", CHAIN_ID)
    monkeypatch.setenv("AE402_NONCE_STORE_PATH", ":memory:")
    # Ensure the LRU-cached nonce store picks up the fresh in-memory backend.
    _default_nonce_store.cache_clear()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app_module.app)


@contextmanager
def _enforce_on(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv(ENFORCE_ENVELOPES_ENV, "1")
    try:
        yield
    finally:
        monkeypatch.delenv(ENFORCE_ENVELOPES_ENV, raising=False)


def _make_envelope(purpose: str, nonce: str, *, payload: dict | None = None) -> str:
    """Build a valid envelope header value for a given purpose."""
    sk = Ed25519PrivateKey.generate()
    priv_bytes = sk.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub_bytes = sk.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    domain = DomainSeparator(
        protocol="AgentEscrow402",
        version="v1",
        chain_id=CHAIN_ID,
        purpose=purpose,
    )
    env = sign_envelope_ed25519(
        domain=domain,
        payload=payload or {"op": purpose, "amount_motes": 1_000_000_000},
        nonce=nonce,
        timestamp=int(time.time()),
        private_key_bytes=priv_bytes,
        public_key_bytes=pub_bytes,
    )
    return env.to_json()


def _envelope_reason_codes() -> set[str]:
    return {
        "envelope_missing",
        "envelope_bad_json",
        "envelope_bad_shape",
        "envelope_bad_fields",
        "envelope_rejected",
        "bad_signature",
        "nonce_reused",
        "domain_mismatch",
        "timestamp_stale",
        "timestamp_future",
    }


def _valid_escrow_body() -> dict:
    """Minimum body accepted by /escrow's Pydantic model.

    Business logic may still 4xx after middleware runs (e.g. sandbox
    signature check), but at least Pydantic body-validation passes and
    the advisory decorator gets a chance to inspect the envelope.
    """
    return {
        "receiver": "a" * 64,
        "amount": 1_000_000_000,
        "service_hash": "b" * 64,
    }


# ---------------------------------------------------------------------------
# Advisory mode: existing clients keep working, new clients are verified.
# ---------------------------------------------------------------------------


def test_advisory_missing_header_allows_request(client: TestClient) -> None:
    """/escrow without header should reach the handler (may fail on business
    logic, but must not be blocked by envelope middleware)."""
    resp = client.post("/escrow", json=_valid_escrow_body())
    assert resp.status_code != 401, resp.text


def test_advisory_present_valid_envelope_passes(client: TestClient) -> None:
    header = _make_envelope("escrow.deposit", nonce="nonce-advisory-1")
    resp = client.post(
        "/escrow", json=_valid_escrow_body(), headers={ENVELOPE_HEADER: header}
    )
    assert resp.status_code != 401, resp.text
    if resp.status_code >= 400:
        try:
            body = resp.json()
        except ValueError:
            body = {}
        assert body.get("reason") not in _envelope_reason_codes(), body


def test_advisory_tampered_envelope_rejected(client: TestClient) -> None:
    header = _make_envelope("escrow.deposit", nonce="nonce-tamper")
    obj = json.loads(header)
    # Flip a byte in the signature hex — must be rejected even in advisory mode.
    sig_hex = obj["signature"]
    first_byte = int(sig_hex[:2], 16) ^ 0xFF
    obj["signature"] = f"{first_byte:02x}" + sig_hex[2:]
    resp = client.post(
        "/escrow",
        json=_valid_escrow_body(),
        headers={ENVELOPE_HEADER: json.dumps(obj)},
    )
    assert resp.status_code == 401, resp.text
    assert resp.json()["reason"] == "bad_signature"


def test_advisory_wrong_purpose_rejected(client: TestClient) -> None:
    """An envelope with purpose=escrow.release presented at /escrow (deposit)
    must be rejected — domain separation prevents cross-endpoint replay."""
    header = _make_envelope("escrow.release", nonce="nonce-wrongpurp")
    resp = client.post(
        "/escrow", json=_valid_escrow_body(), headers={ENVELOPE_HEADER: header}
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["reason"] == "domain_mismatch"


def test_advisory_replayed_nonce_rejected(client: TestClient) -> None:
    header = _make_envelope("escrow.deposit", nonce="nonce-replay-1")
    body = _valid_escrow_body()
    r1 = client.post("/escrow", json=body, headers={ENVELOPE_HEADER: header})
    # First call: envelope accepted (business logic may still 4xx, but not from middleware).
    if r1.status_code == 401:
        try:
            assert r1.json().get("reason") != "nonce_reused"
        except ValueError:
            pass
    r2 = client.post("/escrow", json=body, headers={ENVELOPE_HEADER: header})
    assert r2.status_code == 401, r2.text
    assert r2.json()["reason"] == "nonce_reused"


# ---------------------------------------------------------------------------
# Strict mode: enforce flag makes header mandatory.
# ---------------------------------------------------------------------------


def test_strict_missing_header_returns_401(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    with _enforce_on(monkeypatch):
        resp = client.post("/escrow", json=_valid_escrow_body())
    assert resp.status_code == 401
    assert resp.json()["reason"] == "envelope_missing"


def test_strict_valid_envelope_passes(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    header = _make_envelope("escrow.deposit", nonce="nonce-strict-ok")
    with _enforce_on(monkeypatch):
        resp = client.post(
            "/escrow",
            json=_valid_escrow_body(),
            headers={ENVELOPE_HEADER: header},
        )
    if resp.status_code == 401:
        try:
            assert resp.json().get("reason") not in _envelope_reason_codes()
        except ValueError:
            pytest.fail(f"unexpected 401 body: {resp.text}")


# ---------------------------------------------------------------------------
# All four escrow verbs wired.
# ---------------------------------------------------------------------------


def _body_for(path: str) -> dict:
    svc = "c" * 64
    if path == "/escrow":
        return _valid_escrow_body()
    if path == "/release":
        return {"service_hash": svc}
    if path == "/refund":
        return {"service_hash": svc}
    if path == "/dispute":
        return {"service_hash": svc, "reason_hash": "d" * 64}
    raise ValueError(path)


@pytest.mark.parametrize(
    "path,purpose,nonce",
    [
        ("/escrow", "escrow.deposit", "wire-nonce-deposit"),
        ("/release", "escrow.release", "wire-nonce-release"),
        ("/refund", "escrow.refund", "wire-nonce-refund"),
        ("/dispute", "escrow.dispute", "wire-nonce-dispute"),
    ],
)
def test_all_four_endpoints_wired(
    client: TestClient, path: str, purpose: str, nonce: str
) -> None:
    """Sanity: every endpoint accepts its own purpose and rejects a wrong one."""
    body = _body_for(path)
    ok_header = _make_envelope(purpose, nonce=nonce + "-ok")
    r_ok = client.post(path, json=body, headers={ENVELOPE_HEADER: ok_header})
    if r_ok.status_code == 401:
        try:
            assert r_ok.json().get("reason") not in _envelope_reason_codes(), (
                path, r_ok.text
            )
        except ValueError:
            pytest.fail(f"unexpected 401 body: {r_ok.text}")

    wrong_purpose = "arbiter.resolve_vote"
    bad_header = _make_envelope(wrong_purpose, nonce=nonce + "-bad")
    r_bad = client.post(path, json=body, headers={ENVELOPE_HEADER: bad_header})
    assert r_bad.status_code == 400, (path, r_bad.text)
    assert r_bad.json()["reason"] == "domain_mismatch", (path, r_bad.text)
