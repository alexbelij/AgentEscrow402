"""Tests for GET /arbitration/history (server/app.py) and the
GET /vrf/arbiters shape it depends on the frontend agreeing with.

Before this test, `/arbitration/history` did not exist at all: the console's
Arbitration panel had nowhere to read back past LLM-arbitration verdicts, and
frontend/src/lib/api.ts's `getArbiters()` called a non-existent
`/arbitration/arbiters` path (the real registered-arbiter list lives at
`/vrf/arbiters`) - dead code that would have 404'd the first time any UI
called it.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

import server.app as appmod


class _FakeCasper:
    async def close(self) -> None:
        return None


def _client():
    appmod._casper = _FakeCasper()
    # rate_limit_middleware's _rate_limits dict is module-level and shared
    # across the whole pytest session (TestClient always uses the same
    # "testclient" IP) - clear it so earlier tests in the suite can't 429
    # these requests.
    appmod._rate_limits.clear()
    return TestClient(appmod.app)


def _analyze(client, dispute_id: str):
    return client.post(
        "/arbitration/analyze",
        json={
            "dispute_id": dispute_id,
            "escrow_amount": 1000,
            "sender_evidence": [
                {
                    "escrow_id": "e1",
                    "claimant": "sender1",
                    "evidence_type": "text",
                    "content_hash": "a" * 64,
                    "description": "delivered on time",
                    "timestamp": 1_700_000_000,
                }
            ],
            "receiver_evidence": [
                {
                    "escrow_id": "e1",
                    "claimant": "receiver1",
                    "evidence_type": "text",
                    "content_hash": "b" * 64,
                    "description": "never received",
                    "timestamp": 1_700_000_000,
                }
            ],
        },
    )


def test_history_empty_returns_list():
    client = _client()
    # history is process-lifetime state on the singleton _arbitration_agent;
    # just assert the endpoint responds with a list (may be non-empty if
    # other tests ran first in-process).
    res = client.get("/arbitration/history")
    assert res.status_code == 200
    assert isinstance(res.json(), list)


def test_history_reflects_new_analysis_newest_first():
    client = _client()
    a1 = _analyze(client, "hist-dispute-1")
    assert a1.status_code == 200
    a2 = _analyze(client, "hist-dispute-2")
    assert a2.status_code == 200

    res = client.get("/arbitration/history?limit=2")
    assert res.status_code == 200
    body = res.json()
    assert len(body) == 2
    assert body[0]["dispute_id"] == "hist-dispute-2"
    assert body[1]["dispute_id"] == "hist-dispute-1"


def test_history_limit_validation():
    client = _client()
    res = client.get("/arbitration/history?limit=0")
    assert res.status_code == 400
    res = client.get("/arbitration/history?limit=201")
    assert res.status_code == 400


def test_vrf_arbiters_shape_matches_frontend_expectations():
    client = _client()
    res = client.get("/vrf/arbiters")
    assert res.status_code == 200
    body = res.json()
    assert "arbiters" in body and "count" in body
    assert body["count"] == len(body["arbiters"])
    for arbiter in body["arbiters"]:
        assert set(arbiter.keys()) == {"agent", "score", "completed", "disputed"}
