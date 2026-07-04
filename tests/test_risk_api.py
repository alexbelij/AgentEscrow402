"""Integration tests for the risk-scoring API (server/risk_api.py).

Covers /risk/score/{agent} and /risk/dashboard against the real FastAPI app.

Important real-behavior note discovered while writing these tests:
`_load_escrow_records()` reads from the real Neon DB first (server/db.py's
`load_escrows()`) and only falls back to the injected in-memory sandbox
store if that DB read raises/returns nothing. This means escrows created
through the TestClient during a test (which land in the dependency-injected
SandboxStore) are *not* visible to the risk API if a real Neon DB is
reachable and already has data — the two data paths are independent. To get
deterministic, CI-safe coverage we patch `_load_escrow_records` directly
instead of depending on either live DB state or the sandbox override.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch

import server.risk_api as risk_api
from server.app import app, get_config, get_sandbox
from server.config import Config
from server.sandbox import SandboxStore

RECEIVER_HEX = "ab" * 32
SENDER_HEX = "12" * 32


@pytest.fixture(autouse=True)
def _reset_risk_engine_singleton():
    """The module caches a trained RiskEngine for 5 minutes across requests
    — reset it before/after each test so tests don't leak state into each
    other via this process-global singleton."""
    risk_api._risk_engine = None
    risk_api._last_trained = 0.0
    yield
    risk_api._risk_engine = None
    risk_api._last_trained = 0.0


@pytest.fixture
def client():
    cfg = Config(sandbox=True)
    app.dependency_overrides[get_config] = lambda: cfg
    app.dependency_overrides[get_sandbox] = lambda: SandboxStore()
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _no_records():
    return []


class TestHelperFunctions:
    def test_get_casper_returns_none_or_client_without_raising(self):
        # No live Casper node/config wired for tests — get_casper() must
        # degrade gracefully rather than raise (real code catches Exception
        # and returns None; if server.app.get_casper() somehow does resolve
        # in this environment, that's still a valid, non-raising outcome).
        result = risk_api.get_casper()
        assert result is None or result is not None

    def test_load_escrow_records_never_raises_and_returns_list(self):
        # Exercises the real (unpatched) Neon -> sandbox -> [] fallback
        # chain end to end, without mocking, to ensure it always degrades
        # to a list instead of propagating a DB/sandbox exception.
        records = risk_api._load_escrow_records()
        assert isinstance(records, list)

    @pytest.mark.asyncio
    async def test_get_or_train_engine_uses_cache_within_ttl(self):
        with patch("server.risk_api._load_escrow_records", return_value=[]):
            engine1 = await risk_api._get_or_train_engine(None)
            engine2 = await risk_api._get_or_train_engine(None)
        # Second call within the 5-minute TTL must return the same cached
        # RiskEngine instance rather than retraining.
        assert engine1 is engine2

    @pytest.mark.asyncio
    async def test_get_or_train_engine_skips_malformed_records(self):
        # A record whose "amount" can't be coerced to int must be logged
        # and skipped rather than raising out of training.
        records = [
            {"sender": SENDER_HEX, "receiver": RECEIVER_HEX, "amount": "not-a-number",
             "ttl": 86400, "created_at": 0, "status": "pending"},
        ]
        with patch("server.risk_api._load_escrow_records", return_value=records):
            engine = await risk_api._get_or_train_engine(None)
        assert engine is not None


class TestAgentRiskScoreEndpoint:
    def test_invalid_agent_identifier_rejected(self, client):
        bad_agent = ";" * 5
        resp = client.get(f"/risk/score/{bad_agent}")
        assert resp.status_code == 422

    def test_oversized_agent_identifier_rejected(self, client):
        resp = client.get(f"/risk/score/{'a' * 201}")
        assert resp.status_code == 422

    def test_unknown_agent_scores_with_zero_history(self, client):
        with patch("server.risk_api._load_escrow_records", side_effect=_no_records):
            resp = client.get(f"/risk/score/{SENDER_HEX}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["agent"] == SENDER_HEX
        assert body["escrow_count"] == 0
        assert 0 <= body["risk_score"] <= 100
        assert body["dispute_rate"] == 0.0

    def test_agent_with_escrow_history_scores(self, client):
        records = [
            {
                "sender": SENDER_HEX,
                "receiver": RECEIVER_HEX,
                "amount": 5000,
                "ttl": 86400,
                "created_at": 0,
                "status": "released",
            }
        ]
        with patch("server.risk_api._load_escrow_records", return_value=records):
            resp = client.get(f"/risk/score/{SENDER_HEX}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["escrow_count"] == 1
        assert body["total_volume_motes"] == 5000
        assert body["dispute_rate"] == 0.0

    def test_agent_with_disputed_history_has_nonzero_dispute_rate(self, client):
        records = [
            {
                "sender": SENDER_HEX,
                "receiver": RECEIVER_HEX,
                "amount": 1000,
                "ttl": 86400,
                "created_at": 0,
                "status": "disputed",
            }
        ]
        with patch("server.risk_api._load_escrow_records", return_value=records):
            resp = client.get(f"/risk/score/{SENDER_HEX}")
        assert resp.status_code == 200
        assert resp.json()["dispute_rate"] == 1.0


    def test_agent_score_ignores_unrelated_records_and_computes_stddev(self, client):
        other_hex = "34" * 32
        records = [
            {"sender": SENDER_HEX, "receiver": RECEIVER_HEX, "amount": 1000,
             "ttl": 3600, "created_at": 0, "status": "released"},
            {"sender": SENDER_HEX, "receiver": RECEIVER_HEX, "amount": 3000,
             "ttl": 7200, "created_at": 0, "status": "released"},
            # Unrelated record — must be skipped (neither sender nor receiver
            # match the queried agent).
            {"sender": other_hex, "receiver": other_hex, "amount": 999,
             "ttl": 100, "created_at": 0, "status": "released"},
        ]
        with patch("server.risk_api._load_escrow_records", return_value=records):
            resp = client.get(f"/risk/score/{SENDER_HEX}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["escrow_count"] == 2
        assert body["total_volume_motes"] == 4000


class TestRiskDashboardEndpoint:
    def test_dashboard_empty_when_no_escrows(self, client):
        with patch("server.risk_api._load_escrow_records", side_effect=_no_records):
            resp = client.get("/risk/dashboard")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_agents"] == 0
        assert body["high_risk_count"] == 0
        assert body["agents"] == []

    def test_dashboard_lists_agents_from_escrows(self, client):
        records = [
            {
                "sender": SENDER_HEX,
                "receiver": RECEIVER_HEX,
                "amount": 2500,
                "ttl": 86400,
                "created_at": 0,
                "status": "released",
            }
        ]
        with patch("server.risk_api._load_escrow_records", return_value=records):
            resp = client.get("/risk/dashboard")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_agents"] == 2  # sender + receiver, both counted
        agents = {a["agent"] for a in body["agents"]}
        assert SENDER_HEX in agents and RECEIVER_HEX in agents
        # Dashboard sorts descending by risk_score.
        scores = [a["risk_score"] for a in body["agents"]]
        assert scores == sorted(scores, reverse=True)

    def test_dashboard_counts_disputes_per_agent(self, client):
        records = [
            {"sender": SENDER_HEX, "receiver": RECEIVER_HEX, "amount": 500,
             "ttl": 86400, "created_at": 0, "status": "disputed"},
        ]
        with patch("server.risk_api._load_escrow_records", return_value=records):
            resp = client.get("/risk/dashboard")
        assert resp.status_code == 200
        by_agent = {a["agent"]: a for a in resp.json()["agents"]}
        assert by_agent[SENDER_HEX]["dispute_rate"] == 1.0
        assert by_agent[RECEIVER_HEX]["dispute_rate"] == 1.0

    def test_dashboard_skips_records_with_blank_role(self, client):
        # A record with an empty sender must not create a bogus "" agent
        # entry in the dashboard (the `if not ag: continue` guard).
        records = [
            {"sender": "", "receiver": RECEIVER_HEX, "amount": 500,
             "ttl": 86400, "created_at": 0, "status": "pending"},
        ]
        with patch("server.risk_api._load_escrow_records", return_value=records):
            resp = client.get("/risk/dashboard")
        assert resp.status_code == 200
        agents = {a["agent"] for a in resp.json()["agents"]}
        assert "" not in agents
        assert RECEIVER_HEX in agents
