"""API tests for `/compliance/*` (T3.7).

Exercises the router end to end through the real FastAPI app, same
convention as tests/test_identity_registry_api.py and
tests/test_batch_guard_api.py.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

import server.app as appmod
import server.identity_registry_api as id_api_mod
from server.identity_registry import IdentityRegistry


class _FakeCasper:
    async def close(self) -> None:
        return None


def _client() -> TestClient:
    appmod._casper = _FakeCasper()
    appmod._rate_limits.clear()
    # Fresh identity registry per test so evaluate-by-agent tests don't leak
    # state across test functions / files.
    id_api_mod._registry = IdentityRegistry()
    return TestClient(appmod.app)


MOTES = 10**9


# ── /compliance/jurisdictions ────────────────────────────────────────────


def test_list_jurisdictions_returns_default_table():
    client = _client()
    res = client.get("/compliance/jurisdictions")
    assert res.status_code == 200
    body = res.json()
    codes = {j["country_code"] for j in body}
    assert {"US", "GB", "SG", "NG", "TR", "VE", "KP", "IR"} <= codes


def test_list_jurisdictions_sorted_by_country_code():
    client = _client()
    body = client.get("/compliance/jurisdictions").json()
    codes = [j["country_code"] for j in body]
    assert codes == sorted(codes)


# ── /compliance/evaluate ──────────────────────────────────────────────────


def test_evaluate_unrestricted_permitted():
    client = _client()
    res = client.post(
        "/compliance/evaluate",
        json={"country_code": "US", "verification_level": "UNVERIFIED", "amount_motes": 5 * MOTES},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["permitted"] is True
    assert body["rejections"] == []
    assert body["requires_reporting"] is False


def test_evaluate_prohibited_blocked_with_reason():
    client = _client()
    res = client.post(
        "/compliance/evaluate",
        json={"country_code": "KP", "verification_level": "FULL", "amount_motes": 1},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["permitted"] is False
    assert "jurisdiction_prohibited" in body["rejections"]
    assert body["requires_reporting"] is True


def test_evaluate_restricted_insufficient_verification():
    client = _client()
    res = client.post(
        "/compliance/evaluate",
        json={"country_code": "NG", "verification_level": "UNVERIFIED", "amount_motes": 1 * MOTES},
    )
    body = res.json()
    assert body["permitted"] is False
    assert "insufficient_verification" in body["rejections"]


def test_evaluate_restricted_cap_exceeded():
    client = _client()
    res = client.post(
        "/compliance/evaluate",
        json={"country_code": "NG", "verification_level": "FULL", "amount_motes": 6_000 * MOTES},
    )
    body = res.json()
    assert body["permitted"] is False
    assert "transaction_cap_exceeded" in body["rejections"]


def test_evaluate_daily_volume_uses_prior_volume_field():
    client = _client()
    res = client.post(
        "/compliance/evaluate",
        json={
            "country_code": "NG",
            "verification_level": "FULL",
            "amount_motes": 3_000 * MOTES,
            "prior_volume_today_motes": 18_000 * MOTES,
        },
    )
    body = res.json()
    assert body["permitted"] is False
    assert "daily_volume_cap_exceeded" in body["rejections"]


def test_evaluate_unknown_jurisdiction_fails_closed():
    client = _client()
    res = client.post(
        "/compliance/evaluate",
        json={"country_code": "ZZ", "verification_level": "FULL", "amount_motes": 1},
    )
    assert res.status_code == 200  # not a mutation — a policy rejection in the body, not an HTTP error
    body = res.json()
    assert body["permitted"] is False
    assert "unknown_jurisdiction" in body["rejections"]


def test_evaluate_rejects_malformed_country_code():
    client = _client()
    res = client.post(
        "/compliance/evaluate",
        json={"country_code": "USA", "verification_level": "FULL", "amount_motes": 1},
    )
    assert res.status_code == 422  # 3-letter code violates min_length=2, max_length=2


def test_evaluate_rejects_negative_amount():
    client = _client()
    res = client.post(
        "/compliance/evaluate",
        json={"country_code": "US", "verification_level": "FULL", "amount_motes": -1},
    )
    assert res.status_code == 422


def test_evaluate_defaults_verification_to_unverified_when_omitted():
    client = _client()
    res = client.post("/compliance/evaluate", json={"country_code": "US", "amount_motes": 1})
    assert res.status_code == 200
    assert res.json()["verification_level"] == "UNVERIFIED"


# ── /compliance/evaluate-by-agent ─────────────────────────────────────────


def test_evaluate_by_agent_reads_live_verification_level():
    client = _client()
    reg_res = client.post(
        "/identity-registry/register",
        json={"account_hash": "acct-compliance-1", "display_name": "Agent Compliance", "capabilities": []},
    )
    assert reg_res.status_code == 201
    did = reg_res.json()["did"]

    # Freshly registered identity is UNVERIFIED — NG needs ENHANCED.
    res = client.post(
        "/compliance/evaluate-by-agent",
        json={"country_code": "NG", "did": did, "amount_motes": 1 * MOTES},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["permitted"] is False
    assert "insufficient_verification" in body["rejections"]
    assert body["verification_level"] == "UNVERIFIED"


def test_evaluate_by_agent_permits_after_verification_advances():
    client = _client()
    reg_res = client.post(
        "/identity-registry/register",
        json={"account_hash": "acct-compliance-2", "display_name": "Agent Compliance 2", "capabilities": []},
    )
    did = reg_res.json()["did"]

    verify_res = client.post(f"/identity-registry/{did}/verify", json={"level": "ENHANCED"})
    assert verify_res.status_code == 200

    res = client.post(
        "/compliance/evaluate-by-agent",
        json={"country_code": "NG", "did": did, "amount_motes": 1 * MOTES},
    )
    body = res.json()
    assert body["permitted"] is True
    assert body["verification_level"] == "ENHANCED"


def test_evaluate_by_agent_client_cannot_spoof_verification_level():
    # evaluate-by-agent has no verification_level field at all in its
    # request schema — the only way to raise the tier is to actually
    # advance it in the registry via /identity-registry/{did}/verify.
    client = _client()
    reg_res = client.post(
        "/identity-registry/register",
        json={"account_hash": "acct-compliance-3", "display_name": "Agent Compliance 3", "capabilities": []},
    )
    did = reg_res.json()["did"]

    res = client.post(
        "/compliance/evaluate-by-agent",
        json={"country_code": "NG", "did": did, "amount_motes": 1 * MOTES, "verification_level": "FULL"},
    )
    body = res.json()
    # Extra field is ignored by pydantic (not in the model) — still reads
    # UNVERIFIED from the registry, still rejected.
    assert body["verification_level"] == "UNVERIFIED"
    assert body["permitted"] is False


def test_evaluate_by_agent_unknown_did_returns_404():
    client = _client()
    res = client.post(
        "/compliance/evaluate-by-agent",
        json={"country_code": "US", "did": "did:casper:does-not-exist", "amount_motes": 1},
    )
    assert res.status_code == 404


# ── Read-only guarantees ───────────────────────────────────────────────────


def test_evaluate_never_mutates_identity_registry_state():
    client = _client()
    reg_res = client.post(
        "/identity-registry/register",
        json={"account_hash": "acct-compliance-4", "display_name": "Agent Compliance 4", "capabilities": []},
    )
    did = reg_res.json()["did"]
    before = client.get(f"/identity-registry/{did}").json()

    client.post(
        "/compliance/evaluate-by-agent",
        json={"country_code": "KP", "did": did, "amount_motes": 999_999 * MOTES},
    )

    after = client.get(f"/identity-registry/{did}").json()
    assert before == after
