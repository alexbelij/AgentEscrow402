"""HTTP tests for `/vc/*` endpoints."""

from __future__ import annotations

import base64
import copy

import pytest
from fastapi.testclient import TestClient

from server.app import app
from server.vc_api import _decode_seed

# 32-byte seed for deterministic tests
SEED_BYTES = b"\x11" * 32
SEED_B64 = base64.b64encode(SEED_BYTES).decode()
SEED_HEX = SEED_BYTES.hex()


@pytest.fixture
def client_with_seed(monkeypatch):
    monkeypatch.setenv("VC_ISSUER_SEED", SEED_B64)
    monkeypatch.delenv("VC_AUTO_ISSUE_ON_RELEASE", raising=False)
    return TestClient(app)


@pytest.fixture
def client_no_seed(monkeypatch):
    monkeypatch.delenv("VC_ISSUER_SEED", raising=False)
    monkeypatch.delenv("VC_AUTO_ISSUE_ON_RELEASE", raising=False)
    return TestClient(app)


def _base_body():
    return {
        "event": "release",
        "service_hash": "0xabc",
        "escrow_id": "0xabc",
        "payer": "payer_pk",
        "receiver": "receiver_pk",
        "amount_motes": 1_000_000,
        "asset": "CSPR",
        "issuance_ts": 1_700_000_000,
    }


class TestSeedDecoder:
    def test_base64(self):
        assert _decode_seed(SEED_B64) == SEED_BYTES

    def test_base64url(self):
        b64url = base64.urlsafe_b64encode(SEED_BYTES).decode().rstrip("=")
        assert _decode_seed(b64url) == SEED_BYTES

    def test_hex(self):
        assert _decode_seed(SEED_HEX) == SEED_BYTES

    def test_raw_ascii_32(self):
        ascii_seed = "a" * 32
        assert _decode_seed(ascii_seed) == ascii_seed.encode()

    def test_too_short(self):
        assert _decode_seed("short") is None

    def test_empty(self):
        assert _decode_seed("") is None


class TestIssuerEndpoint:
    def test_returns_did(self, client_with_seed):
        r = client_with_seed.get("/vc/issuer")
        assert r.status_code == 200
        body = r.json()
        assert body["did"].startswith("did:key:z")
        assert body["proof_suite"] == "Ed25519Signature2020"
        assert set(body["supported_events"]) == {"release", "refund", "resolve"}
        assert len(body["public_key_hex"]) == 64

    def test_503_without_seed(self, client_no_seed):
        r = client_no_seed.get("/vc/issuer")
        assert r.status_code == 503
        assert "VC_ISSUER_SEED" in r.json()["detail"]


class TestIssueEndpoint:
    def test_happy(self, client_with_seed):
        r = client_with_seed.post("/vc/receipts/issue", json=_base_body())
        assert r.status_code == 200
        body = r.json()
        assert "credential" in body
        vc = body["credential"]
        assert "proof" in vc
        assert vc["credentialSubject"]["serviceHash"] == "0xabc"
        assert body["summary"]["event"] == "release"
        assert body["summary"]["amount_motes"] == 1_000_000

    def test_503_without_seed(self, client_no_seed):
        r = client_no_seed.post("/vc/receipts/issue", json=_base_body())
        assert r.status_code == 503

    def test_unknown_event(self, client_with_seed):
        body = _base_body()
        body["event"] = "cancel"
        r = client_with_seed.post("/vc/receipts/issue", json=body)
        assert r.status_code == 422
        assert "Unknown event" in r.json()["detail"]

    def test_negative_amount(self, client_with_seed):
        body = _base_body()
        body["amount_motes"] = -1
        r = client_with_seed.post("/vc/receipts/issue", json=body)
        assert r.status_code == 422  # pydantic ge=0

    def test_missing_field(self, client_with_seed):
        body = _base_body()
        del body["payer"]
        r = client_with_seed.post("/vc/receipts/issue", json=body)
        assert r.status_code == 422

    def test_escrow_id_defaults_to_service_hash(self, client_with_seed):
        body = _base_body()
        del body["escrow_id"]
        r = client_with_seed.post("/vc/receipts/issue", json=body)
        assert r.status_code == 200
        subj = r.json()["credential"]["credentialSubject"]
        assert subj["id"] == "urn:ae402:escrow:0xabc"

    def test_extra_claims_collision_422(self, client_with_seed):
        body = _base_body()
        body["extra_claims"] = {"serviceHash": "hijack"}
        r = client_with_seed.post("/vc/receipts/issue", json=body)
        assert r.status_code == 422
        assert "collide" in r.json()["detail"]

    def test_all_events_supported(self, client_with_seed):
        for event in ("release", "refund", "resolve"):
            body = _base_body()
            body["event"] = event
            r = client_with_seed.post("/vc/receipts/issue", json=body)
            assert r.status_code == 200
            assert r.json()["summary"]["event"] == event


class TestVerifyEndpoint:
    def test_verify_ok(self, client_with_seed):
        issued = client_with_seed.post("/vc/receipts/issue", json=_base_body()).json()
        r = client_with_seed.post(
            "/vc/receipts/verify",
            json={"credential": issued["credential"]},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["valid"] is True
        assert body["summary"]["event"] == "release"

    def test_verify_works_without_seed(self, client_with_seed, monkeypatch):
        """Verification must succeed even if the server has no issuer seed —
        pubkey is embedded in the DID."""
        issued = client_with_seed.post("/vc/receipts/issue", json=_base_body()).json()

        # Now clear the seed and reissue the client
        monkeypatch.delenv("VC_ISSUER_SEED", raising=False)
        client2 = TestClient(app)
        r = client2.post(
            "/vc/receipts/verify",
            json={"credential": issued["credential"]},
        )
        assert r.status_code == 200
        assert r.json()["valid"] is True

    def test_verify_tampered(self, client_with_seed):
        issued = client_with_seed.post("/vc/receipts/issue", json=_base_body()).json()
        tampered = copy.deepcopy(issued["credential"])
        tampered["credentialSubject"]["amount"]["value"] = 999_999
        r = client_with_seed.post("/vc/receipts/verify", json={"credential": tampered})
        assert r.status_code == 200
        body = r.json()
        assert body["valid"] is False
        assert body["error_type"] == "SignatureInvalid"

    def test_verify_missing_proof(self, client_with_seed):
        issued = client_with_seed.post("/vc/receipts/issue", json=_base_body()).json()
        vc = issued["credential"]
        del vc["proof"]
        r = client_with_seed.post("/vc/receipts/verify", json={"credential": vc})
        assert r.status_code == 200
        body = r.json()
        assert body["valid"] is False
        assert body["error_type"] == "ProofMissing"

    def test_verify_expected_issuer_mismatch(self, client_with_seed):
        issued = client_with_seed.post("/vc/receipts/issue", json=_base_body()).json()
        r = client_with_seed.post(
            "/vc/receipts/verify",
            json={
                "credential": issued["credential"],
                "expected_issuer": "did:key:zSOMEOTHER",
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert body["valid"] is False
        assert body["error_type"] == "Verification"

    def test_verify_bad_schema(self, client_with_seed):
        r = client_with_seed.post("/vc/receipts/verify", json={"credential": {}})
        assert r.status_code == 200
        body = r.json()
        assert body["valid"] is False
        assert body["error_type"] == "Schema"


class TestAutoIssueHook:
    def test_disabled_by_default(self, monkeypatch):
        monkeypatch.setenv("VC_ISSUER_SEED", SEED_B64)
        monkeypatch.delenv("VC_AUTO_ISSUE_ON_RELEASE", raising=False)
        from server.vc_api import try_auto_issue

        r = try_auto_issue(
            event="release",
            service_hash="0xabc",
            payer="p",
            receiver="r",
            amount_motes=100,
        )
        assert r is None

    def test_enabled_returns_vc(self, monkeypatch):
        monkeypatch.setenv("VC_ISSUER_SEED", SEED_B64)
        monkeypatch.setenv("VC_AUTO_ISSUE_ON_RELEASE", "1")
        from server.vc_api import try_auto_issue

        r = try_auto_issue(
            event="release",
            service_hash="0xabc",
            payer="p",
            receiver="r",
            amount_motes=100,
        )
        assert r is not None
        assert "proof" in r

    def test_enabled_but_no_seed_returns_none(self, monkeypatch):
        monkeypatch.delenv("VC_ISSUER_SEED", raising=False)
        monkeypatch.setenv("VC_AUTO_ISSUE_ON_RELEASE", "1")
        from server.vc_api import try_auto_issue

        r = try_auto_issue(
            event="release",
            service_hash="0xabc",
            payer="p",
            receiver="r",
            amount_motes=100,
        )
        assert r is None

    def test_enabled_flag_variants(self, monkeypatch):
        from server.vc_api import auto_issue_enabled

        for on in ("1", "true", "True", "yes", "YES"):
            monkeypatch.setenv("VC_AUTO_ISSUE_ON_RELEASE", on)
            assert auto_issue_enabled(), on
        for off in ("0", "false", "no", ""):
            monkeypatch.setenv("VC_AUTO_ISSUE_ON_RELEASE", off)
            assert not auto_issue_enabled(), off
