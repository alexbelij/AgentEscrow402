"""API tests for `/simulate/agent-vs-agent` and `/simulate/strategies` (T3.5)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from server.app import app

client = TestClient(app)


class TestListStrategies:
    def test_returns_reference_strategies(self):
        resp = client.get("/simulate/strategies")
        assert resp.status_code == 200
        body = resp.json()
        for name in ("honest", "withholding", "dispute_spam", "flaky_network"):
            assert name in body["strategies"]


class TestSimulateAgentVsAgent:
    def test_honest_vs_honest_all_released(self):
        resp = client.post(
            "/simulate/agent-vs-agent",
            json={"num_escrows": 20, "sender_strategy": "honest", "receiver_strategy": "honest", "seed": 1},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["outcome_counts"] == {"released": 20}
        assert body["dispute_rate"] == 0.0
        assert len(body["outcomes"]) == 20

    def test_withholding_sender_produces_disputes(self):
        resp = client.post(
            "/simulate/agent-vs-agent",
            json={
                "num_escrows": 15,
                "sender_strategy": "withholding",
                "receiver_strategy": "dispute_spam",
                "seed": 7,
                "max_rounds": 8,
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["dispute_rate"] == 1.0
        assert all(o["disputed"] for o in body["outcomes"])

    def test_same_seed_same_report_hash(self):
        payload = {
            "num_escrows": 30,
            "sender_strategy": "flaky_network",
            "receiver_strategy": "dispute_spam",
            "seed": 42,
        }
        r1 = client.post("/simulate/agent-vs-agent", json=payload).json()
        r2 = client.post("/simulate/agent-vs-agent", json=payload).json()
        assert r1["report_hash"] == r2["report_hash"]

    def test_unknown_strategy_returns_422(self):
        resp = client.post(
            "/simulate/agent-vs-agent",
            json={"num_escrows": 5, "sender_strategy": "not_a_real_strategy"},
        )
        assert resp.status_code == 422

    def test_num_escrows_over_limit_returns_422(self):
        resp = client.post("/simulate/agent-vs-agent", json={"num_escrows": 100000})
        assert resp.status_code == 422

    def test_num_escrows_zero_returns_422(self):
        resp = client.post("/simulate/agent-vs-agent", json={"num_escrows": 0})
        assert resp.status_code == 422

    def test_defaults_apply_when_body_minimal(self):
        resp = client.post("/simulate/agent-vs-agent", json={})
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["outcomes"]) == 100  # default num_escrows
