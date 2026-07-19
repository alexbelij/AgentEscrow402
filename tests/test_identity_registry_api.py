"""Tests for server/identity_registry_api.py - the HTTP router that exposes
server/identity_registry.py's DID identity/reputation system.

Before this file, identity_registry.py had zero HTTP endpoints despite the
CHANGELOG documenting an "Identity Registry" console tab - the whole module
was unreachable from any client. These tests exercise the router end to end
through the real FastAPI app.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

import server.app as appmod
import server.identity_registry_api as api_mod


class _FakeCasper:
    async def close(self) -> None:
        return None


def _client():
    appmod._casper = _FakeCasper()
    # rate_limit_middleware's _rate_limits dict is module-level, shared for
    # the whole pytest session (TestClient always uses the same IP) - clear
    # it so earlier test files can't 429 these requests.
    appmod._rate_limits.clear()
    # Each test gets an identity registry with no leftover state from other
    # tests in this file / other files that happen to import the module.
    api_mod._registry = api_mod.IdentityRegistry()
    return TestClient(appmod.app)


def test_register_get_and_duplicate_conflict():
    client = _client()
    res = client.post(
        "/identity-registry/register",
        json={"account_hash": "acct1", "display_name": "Agent One", "capabilities": []},
    )
    assert res.status_code == 201
    body = res.json()
    assert body["did"] == "did:casper:acct1"
    assert body["verification_level"] == "UNVERIFIED"
    assert body["reputation_score"] == 50

    res = client.get(f"/identity-registry/{body['did']}")
    assert res.status_code == 200
    assert res.json()["account_hash"] == "acct1"

    res = client.get("/identity-registry/by-account/acct1")
    assert res.status_code == 200

    # Duplicate registration for the same account must be rejected, not
    # silently overwrite the existing identity.
    dup = client.post(
        "/identity-registry/register",
        json={"account_hash": "acct1", "display_name": "Agent One Again"},
    )
    assert dup.status_code == 409


def test_get_unknown_did_is_404():
    client = _client()
    res = client.get("/identity-registry/did:casper:doesnotexist")
    assert res.status_code == 404


def test_reputation_verify_and_capability_flow():
    client = _client()
    reg = client.post(
        "/identity-registry/register",
        json={"account_hash": "acct2", "display_name": "Agent Two"},
    ).json()
    did = reg["did"]

    res = client.post(f"/identity-registry/{did}/reputation", json={"completed": 9, "disputed": 1})
    assert res.status_code == 200
    body = res.json()
    assert body["total_deals"] == 10
    assert body["reputation_score"] == 90

    res = client.post(f"/identity-registry/{did}/verify", json={"level": "ENHANCED"})
    assert res.status_code == 200
    assert res.json()["verification_level"] == "ENHANCED"

    res = client.post(
        f"/identity-registry/{did}/capabilities",
        json={"capability": {"name": "compute", "version": "1.0", "description": "runs jobs"}},
    )
    assert res.status_code == 200
    assert any(c["name"] == "compute" for c in res.json()["capabilities"])


def test_slash_reduces_stake_and_reputation():
    client = _client()
    did = client.post(
        "/identity-registry/register",
        json={"account_hash": "acct3", "display_name": "Agent Three"},
    ).json()["did"]
    client.post(f"/identity-registry/{did}/reputation", json={"completed": 10, "disputed": 0})

    res = client.post(f"/identity-registry/{did}/slash", json={"amount": 20, "reason": "no-show"})
    assert res.status_code == 200
    body = res.json()
    assert body["slashed_count"] == 1
    assert body["risk_score"] == 60
    assert body["reputation_score"] == 80


def test_action_on_unknown_did_is_404():
    client = _client()
    res = client.post(
        "/identity-registry/did:casper:ghost/reputation",
        json={"completed": 1, "disputed": 0},
    )
    assert res.status_code == 404


def test_decay_slash_verify_capability_on_unknown_did_are_404():
    client = _client()
    ghost = "did:casper:ghost2"

    res = client.post(f"/identity-registry/{ghost}/decay")
    assert res.status_code == 404

    res = client.post(
        f"/identity-registry/{ghost}/slash",
        json={"amount": 10, "reason": "test"},
    )
    assert res.status_code == 404

    res = client.post(
        f"/identity-registry/{ghost}/verify",
        json={"level": "BASIC"},
    )
    assert res.status_code == 404

    res = client.post(
        f"/identity-registry/{ghost}/capabilities",
        json={"capability": {"name": "escrow.dispute", "version": "1.0", "description": "d"}},
    )
    assert res.status_code == 404


def test_get_by_account_unknown_is_404():
    client = _client()
    res = client.get("/identity-registry/by-account/no-such-account")
    assert res.status_code == 404


def test_search_filters_by_capability_and_reputation():
    client = _client()
    a = client.post(
        "/identity-registry/register",
        json={
            "account_hash": "acct-search-a",
            "display_name": "Searchable A",
            "capabilities": [{"name": "compute", "version": "1.0", "description": "d"}],
        },
    ).json()
    client.post(
        "/identity-registry/register",
        json={"account_hash": "acct-search-b", "display_name": "Searchable B"},
    )
    client.post(f"/identity-registry/{a['did']}/reputation", json={"completed": 20, "disputed": 0})

    res = client.get("/identity-registry/search/agents", params={"capability": "compute"})
    assert res.status_code == 200
    dids = [i["did"] for i in res.json()]
    assert a["did"] in dids
    assert len(dids) == 1

    res = client.get("/identity-registry/search/agents", params={"min_reputation": 90})
    assert res.status_code == 200
    assert all(i["reputation_score"] >= 90 for i in res.json())


def test_stats_summary_reflects_registered_agents():
    client = _client()
    client.post(
        "/identity-registry/register",
        json={"account_hash": "acct-stats-1", "display_name": "Stats One"},
    )
    client.post(
        "/identity-registry/register",
        json={"account_hash": "acct-stats-2", "display_name": "Stats Two"},
    )

    res = client.get("/identity-registry/stats/summary")
    assert res.status_code == 200
    body = res.json()
    assert body["total_agents"] == 2
    assert body["distribution_by_level"]["UNVERIFIED"] == 2
