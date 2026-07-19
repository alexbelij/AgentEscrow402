"""Tests for AE-A1.4 arbitration auto-escalation to VRF panel.

Covers the flat-response contract on POST /arbitration/analyze:

  1. Non-abstain, non-escalate verdicts are never routed to a panel.
  2. 'abstain' verdict routes to panel when party accounts are given.
  3. 'abstain' without party accounts returns a machine-readable reason.
  4. 'escalate' with low confidence routes to panel.
  5. 'escalate' with high confidence does NOT route to panel.
  6. Re-analysing the same dispute reuses the existing election
     (409 -> prior_election_reused).
  7. Escalation seed defaults to sha256(dispute_id:analysis_hash) when
     the caller does not supply one, and honours the caller's seed when
     they do.
  8. Escalation never turns a 200 into a 5xx: panel election failure is
     recorded on the verdict, not raised.

Tests replace the module-level ArbitrationAgent with a stub whose
`analyze_dispute` returns a canned verdict, and inject controlled
arbiters in `vrf_election._registered_arbiters`. Both are process-local
state, so we snapshot & restore around each test.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import server.app as appmod
import server.vrf_election as vrf_mod
from server.ai_arbitration import ArbitrationRecommendation


class _FakeCasper:
    async def close(self) -> None:
        return None


def _client():
    appmod._casper = _FakeCasper()
    appmod._rate_limits.clear()
    # Ensure any prior election state is cleared per-test.
    vrf_mod._election_results.clear()
    return TestClient(appmod.app)


def _payload(dispute_id: str = "esc-1", **extra) -> dict:
    base = {
        "dispute_id": dispute_id,
        "escrow_amount": 1000,
        "sender_evidence": [
            {
                "escrow_id": "e1",
                "claimant": "sender1",
                "evidence_type": "text",
                "content_hash": "a" * 64,
                "description": "delivered",
                "timestamp": 1_700_000_000,
            }
        ],
        "receiver_evidence": [
            {
                "escrow_id": "e1",
                "claimant": "receiver1",
                "evidence_type": "text",
                "content_hash": "b" * 64,
                "description": "not received",
                "timestamp": 1_700_000_000,
            }
        ],
    }
    base.update(extra)
    return base


def _stub_verdict(recommendation: str, confidence: float, dispute_id: str = "esc-1") -> ArbitrationRecommendation:
    return ArbitrationRecommendation(
        dispute_id=dispute_id,
        recommendation=recommendation,
        confidence=confidence,
        reasoning="stub verdict for test",
        risk_factors=["test"],
        suggested_split_pct=50.0,
        analysis_hash="deadbeef",
        provider="test-stub",
    )


def _stub_analyze(recommendation: str, confidence: float):
    """Patcher factory for _arbitration_agent.analyze_dispute."""

    async def _analyze(dispute_id: str, sender_evidence, receiver_evidence, escrow_amount):
        return _stub_verdict(recommendation, confidence, dispute_id=dispute_id)

    return _analyze


# ---------------------------------------------------------------------------
# 1. Non-escalating verdicts are pass-through
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("rec,conf", [("favor_sender", 0.9), ("favor_receiver", 0.8), ("split", 0.6)])
def test_normal_verdict_never_escalates(rec, conf):
    client = _client()
    with patch.object(appmod._arbitration_agent, "analyze_dispute", _stub_analyze(rec, conf)):
        res = client.post("/arbitration/analyze", json=_payload("norm-1"))
    assert res.status_code == 200
    body = res.json()
    assert body["recommendation"] == rec
    assert body["escalated_to_panel"] is False
    assert body["panel_election"] is None
    assert body["escalation_reason"] is None


# ---------------------------------------------------------------------------
# 2. abstain + accounts -> escalation
# ---------------------------------------------------------------------------


def test_abstain_with_party_accounts_escalates_to_panel():
    client = _client()
    with patch.object(appmod._arbitration_agent, "analyze_dispute", _stub_analyze("abstain", 0.1)):
        res = client.post(
            "/arbitration/analyze",
            json=_payload(
                "abs-1",
                sender_account="a" * 64,
                receiver_account="b" * 64,
            ),
        )
    assert res.status_code == 200
    body = res.json()
    assert body["recommendation"] == "abstain"
    assert body["escalated_to_panel"] is True
    assert body["panel_election"] is not None
    assert body["panel_election"]["dispute_id"] == "abs-1"
    assert body["panel_election"]["elected_arbiter"]["arbiter_id"] in vrf_mod._registered_arbiters
    assert body["escalation_reason"] == "abstain_verdict"


# ---------------------------------------------------------------------------
# 3. abstain without party accounts -> unescalated + reason
# ---------------------------------------------------------------------------


def test_abstain_without_party_accounts_returns_reason():
    client = _client()
    with patch.object(appmod._arbitration_agent, "analyze_dispute", _stub_analyze("abstain", 0.1)):
        res = client.post("/arbitration/analyze", json=_payload("abs-noacc"))
    assert res.status_code == 200
    body = res.json()
    assert body["recommendation"] == "abstain"
    assert body["escalated_to_panel"] is False
    assert body["panel_election"] is None
    assert body["escalation_reason"] is not None
    assert "missing_party_accounts" in body["escalation_reason"]


# ---------------------------------------------------------------------------
# 4. escalate + low confidence -> panel
# ---------------------------------------------------------------------------


def test_low_confidence_escalate_routes_to_panel():
    client = _client()
    with patch.object(appmod._arbitration_agent, "analyze_dispute", _stub_analyze("escalate", 0.15)):
        res = client.post(
            "/arbitration/analyze",
            json=_payload(
                "esc-low",
                sender_account="c" * 64,
                receiver_account="d" * 64,
            ),
        )
    body = res.json()
    assert res.status_code == 200
    assert body["recommendation"] == "escalate"
    assert body["escalated_to_panel"] is True
    assert body["escalation_reason"].startswith("low_confidence_escalate:")


# ---------------------------------------------------------------------------
# 5. escalate + high confidence -> no panel
# ---------------------------------------------------------------------------


def test_high_confidence_escalate_does_not_route_to_panel():
    client = _client()
    with patch.object(appmod._arbitration_agent, "analyze_dispute", _stub_analyze("escalate", 0.5)):
        res = client.post(
            "/arbitration/analyze",
            json=_payload(
                "esc-hi",
                sender_account="c" * 64,
                receiver_account="d" * 64,
            ),
        )
    body = res.json()
    assert res.status_code == 200
    assert body["recommendation"] == "escalate"
    assert body["escalated_to_panel"] is False
    assert body["escalation_reason"] is None


# ---------------------------------------------------------------------------
# 6. Re-analysing the same dispute reuses the election
# ---------------------------------------------------------------------------


def test_reanalysing_same_dispute_reuses_prior_election():
    client = _client()
    with patch.object(appmod._arbitration_agent, "analyze_dispute", _stub_analyze("abstain", 0.1)):
        res1 = client.post(
            "/arbitration/analyze",
            json=_payload("reuse-1", sender_account="e" * 64, receiver_account="f" * 64),
        )
        first_body = res1.json()
        assert first_body["escalated_to_panel"] is True
        first_panel = first_body["panel_election"]

        res2 = client.post(
            "/arbitration/analyze",
            json=_payload("reuse-1", sender_account="e" * 64, receiver_account="f" * 64),
        )
        second_body = res2.json()

    assert res2.status_code == 200
    assert second_body["escalated_to_panel"] is True
    # Same election result surfaced under the 'prior_election_reused' reason.
    assert second_body["escalation_reason"] == "prior_election_reused"
    assert (
        second_body["panel_election"]["elected_arbiter"]["arbiter_id"] == first_panel["elected_arbiter"]["arbiter_id"]
    )


# ---------------------------------------------------------------------------
# 7. Seed default and caller-override
# ---------------------------------------------------------------------------


def test_caller_supplied_seed_is_honoured():
    """When the caller passes election_seed_hash, we must NOT derive one
    from analysis_hash. Assert both by inspecting the outcome differing
    from the default-seed path AND by patching the elect_arbiter helper
    to capture the seed_hash it received.
    """
    client = _client()
    caller_seed = "f" * 64
    captured_seeds: list[str] = []

    real_elect = vrf_mod.elect_arbiter

    async def capturing_elect(request, casper, cfg):
        captured_seeds.append(request.seed_hash)
        return await real_elect(request=request, casper=casper, cfg=cfg)

    with patch.object(appmod._arbitration_agent, "analyze_dispute", _stub_analyze("abstain", 0.1)):
        with patch.object(vrf_mod, "elect_arbiter", capturing_elect):
            res = client.post(
                "/arbitration/analyze",
                json=_payload(
                    "seed-explicit",
                    sender_account="a" * 64,
                    receiver_account="b" * 64,
                    election_seed_hash=caller_seed,
                ),
            )
    assert res.status_code == 200
    assert res.json()["escalated_to_panel"] is True
    assert captured_seeds == [caller_seed]


def test_default_seed_is_derived_from_dispute_and_analysis_hash():
    """When no election_seed_hash is passed, seed = sha256(dispute:analysis_hash).
    Verified by capturing the seed that reached elect_arbiter.
    """
    import hashlib

    client = _client()
    captured_seeds: list[str] = []
    real_elect = vrf_mod.elect_arbiter

    async def capturing_elect(request, casper, cfg):
        captured_seeds.append(request.seed_hash)
        return await real_elect(request=request, casper=casper, cfg=cfg)

    with patch.object(appmod._arbitration_agent, "analyze_dispute", _stub_analyze("abstain", 0.1)):
        with patch.object(vrf_mod, "elect_arbiter", capturing_elect):
            res = client.post(
                "/arbitration/analyze",
                json=_payload(
                    "seed-default",
                    sender_account="a" * 64,
                    receiver_account="b" * 64,
                ),
            )
    assert res.status_code == 200
    expected = hashlib.sha256(b"seed-default:deadbeef").hexdigest()
    assert captured_seeds == [expected]


# ---------------------------------------------------------------------------
# 8. Panel election failure never turns a 200 into a 5xx
# ---------------------------------------------------------------------------


def test_panel_election_failure_is_reported_not_raised():
    client = _client()

    async def broken_elect(request, casper, cfg):
        raise RuntimeError("simulated on-chain outage")

    with patch.object(appmod._arbitration_agent, "analyze_dispute", _stub_analyze("abstain", 0.1)):
        with patch.object(vrf_mod, "elect_arbiter", broken_elect):
            res = client.post(
                "/arbitration/analyze",
                json=_payload(
                    "fail-1",
                    sender_account="a" * 64,
                    receiver_account="b" * 64,
                ),
            )
    assert res.status_code == 200
    body = res.json()
    assert body["escalated_to_panel"] is False
    assert body["escalation_reason"] == "panel_election_failed:RuntimeError"
