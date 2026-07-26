"""AE-J8: /arbitration/analyze emits `arbitration_verdict` (and, on escalation,
`arbitration_escalated`) over the /events SSE bus so live subscribers can react
without polling /arbitration/history.

The bus itself is exercised by the existing SSE smoke tests; here we only
assert the two arbitration-specific event names + payload shape.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from server.ai_arbitration import ArbitrationRecommendation
from server.app import app


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def _fake_verdict(
    dispute_id: str,
    recommendation: str = "favor_receiver",
    confidence: float = 0.85,
    escalated: bool = False,
) -> ArbitrationRecommendation:
    return ArbitrationRecommendation(
        dispute_id=dispute_id,
        recommendation=recommendation,
        confidence=confidence,
        reasoning="test fixture",
        risk_factors=[],
        suggested_split_pct=50.0,
        analysis_hash="0" * 64,
        provider="heuristic",
        escalated_to_panel=escalated,
        escalation_reason=None if not escalated else "test escalation",
    )


@pytest.mark.asyncio
async def test_verdict_broadcasts_arbitration_verdict_event(client: TestClient) -> None:
    captured: list[dict] = []

    def _capture(ev: dict) -> None:
        captured.append(ev)

    verdict = _fake_verdict("dispute-abc")

    with (
        patch("server.app._arbitration_agent.analyze_dispute", return_value=verdict),
        patch("server.app._broadcast_event", side_effect=_capture),
    ):
        r = client.post(
            "/arbitration/analyze",
            json={
                "dispute_id": "dispute-abc",
                "sender_evidence": [],
                "receiver_evidence": [],
                "escrow_amount": 1_000_000,
            },
        )

    assert r.status_code == 200, r.text
    types = [e.get("type") for e in captured]
    assert "arbitration_verdict" in types, f"got {types}"
    ev = next(e for e in captured if e["type"] == "arbitration_verdict")
    assert ev["dispute_id"] == "dispute-abc"
    assert ev["recommendation"] == "favor_receiver"
    assert 0.0 <= ev["confidence"] <= 1.0
    assert ev["provider"] == "heuristic"
    assert isinstance(ev["ts"], int) and ev["ts"] > 0


@pytest.mark.asyncio
async def test_abstain_verdict_emits_verdict_plus_escalated_event(client: TestClient) -> None:
    captured: list[dict] = []

    def _capture(ev: dict) -> None:
        captured.append(ev)

    # Abstain verdict → _should_escalate() == True → _try_escalate_to_panel
    # sets escalated_to_panel=True (we short-circuit the actual panel election
    # via mock so this test is offline / deterministic).
    verdict = _fake_verdict("dispute-def", recommendation="abstain", confidence=0.1, escalated=True)

    async def _fake_escalate(v, req):
        v.escalated_to_panel = True
        v.escalation_reason = "abstain — routed to VRF panel"

    with (
        patch("server.app._arbitration_agent.analyze_dispute", return_value=verdict),
        patch("server.app._try_escalate_to_panel", side_effect=_fake_escalate),
        patch("server.app._broadcast_event", side_effect=_capture),
    ):
        r = client.post(
            "/arbitration/analyze",
            json={
                "dispute_id": "dispute-def",
                "sender_evidence": [],
                "receiver_evidence": [],
                "escrow_amount": 1_000_000,
                "sender_account": "a" * 64,
                "receiver_account": "b" * 64,
            },
        )
    assert r.status_code == 200, r.text

    types = [e.get("type") for e in captured]
    assert "arbitration_verdict" in types
    assert "arbitration_escalated" in types
    esc = next(e for e in captured if e["type"] == "arbitration_escalated")
    assert esc["dispute_id"] == "dispute-def"


def test_broadcast_never_crashes_on_arbitration_failure(client: TestClient) -> None:
    """A raised inside the LLM path must not fire arbitration_verdict on the
    /events bus — we only emit on success."""
    captured: list[dict] = []

    def _capture(ev: dict) -> None:
        captured.append(ev)

    async def _boom(*a, **kw):
        raise RuntimeError("simulated provider failure inside analyze_dispute")

    with (
        patch("server.app._arbitration_agent.analyze_dispute", side_effect=_boom),
        patch("server.app._broadcast_event", side_effect=_capture),
    ):
        r = client.post(
            "/arbitration/analyze",
            json={
                "dispute_id": "dispute-boom",
                "sender_evidence": [],
                "receiver_evidence": [],
                "escrow_amount": 1_000_000,
            },
        )
    assert r.status_code == 500, r.text
    types = [e.get("type") for e in captured]
    assert "arbitration_verdict" not in types
    assert "arbitration_escalated" not in types
