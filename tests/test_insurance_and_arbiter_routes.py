"""Tests for server/insurance.py and server/vrf_election.py HTTP routers.

Replaces the deleted tests/test_batch3_modules.py, which fabricated CRUD
endpoints (POST/GET/PUT/DELETE /escrow/{id} with EscrowStatus.COMPLETED /
FAILED values) that never existed on server.multi_asset, server.insurance,
or server.vrf_election — none of these routers implement integer-ID CRUD,
and EscrowStatus has no COMPLETED/FAILED members. These tests instead
exercise the real routes: /insurance/pool-stats, /insurance/premium-quote,
/insurance/deposit (auth-gated), /insurance/claim (auth-gated), and the
vrf_election arbiter registration/election/list flow.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

import server.app as appmod
import server.vrf_election as vrf_mod


class _FakeCasper:
    async def close(self) -> None:
        return None


def _client() -> TestClient:
    appmod._casper = _FakeCasper()
    appmod._rate_limits.clear()
    return TestClient(appmod.app)


class TestInsurancePoolStats:
    def test_pool_stats_available_without_auth(self):
        client = _client()
        res = client.get("/insurance/pool-stats")
        assert res.status_code == 200
        body = res.json()
        assert body["total_assets"] > 0
        assert "coverage_ratio" in body


class TestPremiumQuote:
    def test_premium_quote_basic(self):
        client = _client()
        res = client.get(
            "/insurance/premium-quote",
            params={"agent_id": "agent-x", "escrow_amount": 1_000_000_000},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["premium_amount"] >= 1_000_000  # minimum premium floor
        assert body["base_rate_bps"] == 50

    def test_premium_quote_requires_positive_escrow_amount(self):
        client = _client()
        res = client.get(
            "/insurance/premium-quote",
            params={"agent_id": "agent-x", "escrow_amount": 0},
        )
        assert res.status_code == 422


class TestInsuranceAuthGating:
    def test_deposit_requires_x_payment_header(self):
        client = _client()
        res = client.post("/insurance/deposit", json={"amount": 1000})
        assert res.status_code == 401

    def test_claim_requires_x_payment_header(self):
        client = _client()
        res = client.post(
            "/insurance/claim",
            json={"escrow_hash": "a" * 64, "reason": "escrow never delivered"},
        )
        assert res.status_code == 401


class TestArbiterElection:
    def _reset(self):
        vrf_mod._registered_arbiters.clear()
        vrf_mod._election_results.clear()

    def test_register_and_list_arbiters(self):
        self._reset()
        client = _client()
        res = client.post(
            "/vrf/arbiters/register",
            json={"agent": "arbiter-1", "score": 80, "completed": 5, "disputed": 0},
        )
        assert res.status_code == 201
        res = client.get("/vrf/arbiters")
        assert res.status_code == 200
        body = res.json()
        assert body["count"] == 1
        assert body["arbiters"][0]["agent"] == "arbiter-1"

    def test_elect_arbiter_excludes_dispute_parties(self):
        self._reset()
        client = _client()
        client.post(
            "/vrf/arbiters/register",
            json={"agent": "buyer-x", "score": 90, "completed": 1, "disputed": 0},
        )
        client.post(
            "/vrf/arbiters/register",
            json={"agent": "neutral-arbiter", "score": 70, "completed": 3, "disputed": 0},
        )
        res = client.post(
            "/vrf/elect",
            json={
                "dispute_id": "dispute-1",
                "sender": "buyer-x",
                "receiver": "seller-y",
                "seed_hash": "ab" * 32,
            },
        )
        assert res.status_code == 201
        elected = res.json()["elected_arbiter"]["arbiter_id"]
        assert elected == "neutral-arbiter"  # buyer-x is excluded as a dispute party

    def test_elect_arbiter_no_eligible_candidates(self):
        self._reset()
        client = _client()
        res = client.post(
            "/vrf/elect",
            json={
                "dispute_id": "dispute-empty",
                "sender": "s",
                "receiver": "r",
                "seed_hash": "cd" * 32,
            },
        )
        assert res.status_code == 503

    def test_duplicate_election_conflicts(self):
        self._reset()
        client = _client()
        client.post(
            "/vrf/arbiters/register",
            json={"agent": "arbiter-1", "score": 80, "completed": 5, "disputed": 0},
        )
        payload = {
            "dispute_id": "dispute-dup",
            "sender": "s",
            "receiver": "r",
            "seed_hash": "ef" * 32,
        }
        first = client.post("/vrf/elect", json=payload)
        assert first.status_code == 201
        second = client.post("/vrf/elect", json=payload)
        assert second.status_code == 409

    def test_get_election_result_not_found(self):
        self._reset()
        client = _client()
        res = client.get("/vrf/election/nonexistent-dispute")
        assert res.status_code == 404
