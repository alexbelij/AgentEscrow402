import time
from unittest.mock import patch

import pytest

from server.ai_arbitration import (
    ArbitrationAgent,
    ArbitrationRecommendation,
    DisputeEvidence,
)


class TestDisputeEvidence:
    def test_valid_dispute_evidence(self):
        evidence = DisputeEvidence(
            escrow_id="escrow123",
            claimant="sender",
            evidence_type="text",
            content_hash="abc123",
            description="Test evidence",
            timestamp=int(time.time()),
        )
        assert evidence.escrow_id == "escrow123"
        assert evidence.claimant == "sender"
        assert evidence.evidence_type == "text"
        assert evidence.content_hash == "abc123"
        assert evidence.description == "Test evidence"

    def test_invalid_evidence_type(self):
        with pytest.raises(ValueError):
            DisputeEvidence(
                escrow_id="escrow123",
                claimant="sender",
                evidence_type="invalid_type",
                content_hash="abc123",
                description="Test evidence",
                timestamp=int(time.time()),
            )

    def test_negative_timestamp(self):
        with pytest.raises(ValueError, match="timestamp must be non-negative"):
            DisputeEvidence(
                escrow_id="escrow123",
                claimant="sender",
                evidence_type="text",
                content_hash="abc123",
                description="Test evidence",
                timestamp=-1,
            )

    def test_future_timestamp(self):
        future_time = int(time.time()) + 86401  # 1 day + 1 second
        with pytest.raises(ValueError, match="timestamp cannot be more than 1 day in the future"):
            DisputeEvidence(
                escrow_id="escrow123",
                claimant="sender",
                evidence_type="text",
                content_hash="abc123",
                description="Test evidence",
                timestamp=future_time,
            )

    def test_empty_description(self):
        evidence = DisputeEvidence(
            escrow_id="escrow123",
            claimant="sender",
            evidence_type="text",
            content_hash="abc123",
            description="",
            timestamp=int(time.time()),
        )
        assert evidence.description == ""


class TestArbitrationRecommendation:
    def test_valid_recommendation(self):
        rec = ArbitrationRecommendation(
            dispute_id="dispute123",
            recommendation="favor_sender",
            confidence=0.8,
            reasoning="Sender has stronger evidence",
            risk_factors=["high_value"],
            suggested_split_pct=75.0,
            analysis_hash="hash123",
        )
        assert rec.dispute_id == "dispute123"
        assert rec.recommendation == "favor_sender"
        assert rec.confidence == 0.8
        assert rec.suggested_split_pct == 75.0
        assert rec.analysis_hash == "hash123"

    def test_invalid_recommendation_type(self):
        with pytest.raises(ValueError):
            ArbitrationRecommendation(
                dispute_id="dispute123",
                recommendation="invalid",
                confidence=0.8,
                reasoning="Test",
                risk_factors=[],
                suggested_split_pct=50.0,
                analysis_hash="hash123",
            )

    def test_confidence_out_of_range(self):
        with pytest.raises(ValueError):
            ArbitrationRecommendation(
                dispute_id="dispute123",
                recommendation="favor_sender",
                confidence=1.1,
                reasoning="Test",
                risk_factors=[],
                suggested_split_pct=50.0,
                analysis_hash="hash123",
            )

    def test_split_pct_out_of_range(self):
        with pytest.raises(ValueError):
            ArbitrationRecommendation(
                dispute_id="dispute123",
                recommendation="split",
                confidence=0.5,
                reasoning="Test",
                risk_factors=[],
                suggested_split_pct=101.0,
                analysis_hash="hash123",
            )


class TestArbitrationAgentInit:
    def test_valid_init(self):
        agent = ArbitrationAgent(slashing_rate=0.1, min_evidence=2, max_evidence=10)
        assert agent.slashing_rate == 0.1
        assert agent.min_evidence == 2
        assert agent.max_evidence == 10

    def test_invalid_slashing_rate_high(self):
        with pytest.raises(ValueError, match="slashing_rate must be between 0 and 1"):
            ArbitrationAgent(slashing_rate=1.1)

    def test_invalid_slashing_rate_negative(self):
        with pytest.raises(ValueError, match="slashing_rate must be between 0 and 1"):
            ArbitrationAgent(slashing_rate=-0.1)

    def test_invalid_min_evidence_zero(self):
        with pytest.raises(ValueError, match="min_evidence must be at least 1"):
            ArbitrationAgent(min_evidence=0)

    def test_invalid_max_evidence_less_than_min(self):
        with pytest.raises(ValueError, match="max_evidence must be >= min_evidence"):
            ArbitrationAgent(min_evidence=5, max_evidence=4)


# NOTE on this rewrite: the previous version of these two classes assumed a
# fictional, synchronous API surface directly on ArbitrationAgent
# (`_score_evidence_set`, `_compute_confidence`, `_detect_risk_factors`,
# risk-factor names like "fraud_suspicion"/"large_dispute" that never
# existed). The real implementation is async (`analyze_dispute` tries
# LLM providers, then falls back to a `_HeuristicArbitrator` instance with
# real methods `_score`/`_confidence`/`_risks`). No GROQ/NVIDIA/ZAI/
# OPENROUTER API keys are set in CI/test envs, so every provider call
# short-circuits to `None` immediately and the heuristic path always runs
# deterministically here.
@pytest.mark.asyncio
class TestArbitrationAgentAnalyzeDispute:
    @pytest.fixture
    def base_agent(self):
        return ArbitrationAgent(slashing_rate=0.05, min_evidence=1, max_evidence=20)

    @pytest.fixture
    def sample_evidence(self):
        return DisputeEvidence(
            escrow_id="escrow1",
            claimant="sender",
            evidence_type="text",
            content_hash="hash1",
            description="Valid evidence",
            timestamp=int(time.time()),
        )

    async def test_insufficient_evidence(self, base_agent):
        result = await base_agent.analyze_dispute(
            dispute_id="dispute1",
            sender_evidence=[],
            receiver_evidence=[],
            escrow_amount=100,
        )
        assert result.recommendation == "escalate"
        assert result.confidence == 0.0
        assert "Insufficient evidence" in result.reasoning
        assert "insufficient_evidence" in result.risk_factors

    async def test_negative_escrow_amount(self, base_agent):
        with pytest.raises(ValueError, match="escrow_amount must be non-negative"):
            await base_agent.analyze_dispute(
                dispute_id="dispute1",
                sender_evidence=[],
                receiver_evidence=[],
                escrow_amount=-100,
            )

    async def test_excessive_evidence_truncation(self, base_agent, sample_evidence):
        # Create more evidence than max_evidence * 2; distinct content hashes
        # so the dedup penalty in _score doesn't dominate the result.
        sender_ev = [sample_evidence.model_copy(update={"content_hash": f"s{i}"}) for i in range(25)]
        receiver_ev = [sample_evidence.model_copy(update={"content_hash": f"r{i}"}) for i in range(25)]
        result = await base_agent.analyze_dispute(
            dispute_id="dispute1",
            sender_evidence=sender_ev,
            receiver_evidence=receiver_ev,
            escrow_amount=1000,
        )
        assert result.recommendation in ["favor_sender", "favor_receiver", "split", "escalate"]
        # One append per submitted evidence item (all claimed by "sender"
        # here) — 25 sender items + 25 receiver items = 50 appends.
        assert base_agent._agent_disputes["sender"].count("dispute1") == 50

    async def test_low_confidence_escalation(self, base_agent, sample_evidence):
        with patch("server.ai_arbitration._heuristic._confidence", return_value=0.1):
            result = await base_agent.analyze_dispute(
                dispute_id="dispute1",
                sender_evidence=[sample_evidence],
                receiver_evidence=[sample_evidence],
                escrow_amount=100,
            )
            assert result.recommendation == "escalate"
            assert "Low confidence" in result.reasoning

    async def test_split_recommendation(self, base_agent, sample_evidence):
        with patch(
            "server.ai_arbitration._heuristic._score",
            side_effect=[{"score": 0.5, "factors": ["text"]}, {"score": 0.55, "factors": ["text"]}],
        ):
            with patch("server.ai_arbitration._heuristic._confidence", return_value=0.5):
                result = await base_agent.analyze_dispute(
                    dispute_id="dispute1",
                    sender_evidence=[sample_evidence],
                    receiver_evidence=[sample_evidence],
                    escrow_amount=100,
                )
                assert result.recommendation == "split"
                assert result.suggested_split_pct == 50.0

    async def test_favor_sender_recommendation(self, base_agent, sample_evidence):
        with patch(
            "server.ai_arbitration._heuristic._score",
            side_effect=[{"score": 0.7, "factors": ["text"]}, {"score": 0.3, "factors": ["text"]}],
        ):
            with patch("server.ai_arbitration._heuristic._confidence", return_value=0.7):
                result = await base_agent.analyze_dispute(
                    dispute_id="dispute1",
                    sender_evidence=[sample_evidence],
                    receiver_evidence=[sample_evidence],
                    escrow_amount=100,
                )
                assert result.recommendation == "favor_sender"
                assert result.suggested_split_pct > 50.0

    async def test_favor_receiver_recommendation(self, base_agent, sample_evidence):
        with patch(
            "server.ai_arbitration._heuristic._score",
            side_effect=[{"score": 0.3, "factors": ["text"]}, {"score": 0.7, "factors": ["text"]}],
        ):
            with patch("server.ai_arbitration._heuristic._confidence", return_value=0.7):
                result = await base_agent.analyze_dispute(
                    dispute_id="dispute1",
                    sender_evidence=[sample_evidence],
                    receiver_evidence=[sample_evidence],
                    escrow_amount=100,
                )
                assert result.recommendation == "favor_receiver"

    async def test_risk_factors_detection(self, base_agent, sample_evidence):
        with patch(
            "server.ai_arbitration._heuristic._risks", return_value=["high_value_escrow", "unilateral_evidence"]
        ):
            result = await base_agent.analyze_dispute(
                dispute_id="dispute1",
                sender_evidence=[sample_evidence],
                receiver_evidence=[sample_evidence],
                escrow_amount=10000,
            )
            assert "high_value_escrow" in result.risk_factors
            assert "unilateral_evidence" in result.risk_factors

    async def test_history_tracking(self, base_agent, sample_evidence):
        await base_agent.analyze_dispute(
            dispute_id="dispute1",
            sender_evidence=[sample_evidence],
            receiver_evidence=[sample_evidence],
            escrow_amount=100,
        )
        assert len(base_agent._history) == 1
        assert base_agent._history[0].dispute_id == "dispute1"

    async def test_dispute_id_tracking(self, base_agent, sample_evidence):
        await base_agent.analyze_dispute(
            dispute_id="dispute1",
            sender_evidence=[sample_evidence],
            receiver_evidence=[sample_evidence],
            escrow_amount=100,
        )
        assert "sender" in base_agent._agent_disputes
        assert "dispute1" in base_agent._agent_disputes["sender"]

    async def test_empty_evidence_lists(self, base_agent):
        result = await base_agent.analyze_dispute(
            dispute_id="dispute1",
            sender_evidence=[],
            receiver_evidence=[],
            escrow_amount=100,
        )
        assert result.recommendation == "escalate"
        assert result.confidence == 0.0

    async def test_single_evidence_each(self, base_agent, sample_evidence):
        result = await base_agent.analyze_dispute(
            dispute_id="dispute1",
            sender_evidence=[sample_evidence],
            receiver_evidence=[sample_evidence],
            escrow_amount=100,
        )
        assert result.recommendation in ["split", "escalate", "favor_sender", "favor_receiver"]

    async def test_max_confidence_favor_sender(self, base_agent, sample_evidence):
        with patch(
            "server.ai_arbitration._heuristic._score",
            side_effect=[{"score": 0.9, "factors": ["text"]}, {"score": 0.1, "factors": ["text"]}],
        ):
            with patch("server.ai_arbitration._heuristic._confidence", return_value=1.0):
                result = await base_agent.analyze_dispute(
                    dispute_id="dispute1",
                    sender_evidence=[sample_evidence],
                    receiver_evidence=[sample_evidence],
                    escrow_amount=100,
                )
                assert result.recommendation == "favor_sender"
                assert result.suggested_split_pct == 90.0  # split = min(100, 50 + diff*50), diff = 0.9-0.1 = 0.8 -> 90

    async def test_boundary_score_difference(self, base_agent, sample_evidence):
        with patch(
            "server.ai_arbitration._heuristic._score",
            side_effect=[{"score": 0.55, "factors": ["text"]}, {"score": 0.45, "factors": ["text"]}],
        ):
            with patch("server.ai_arbitration._heuristic._confidence", return_value=0.5):
                result = await base_agent.analyze_dispute(
                    dispute_id="dispute1",
                    sender_evidence=[sample_evidence],
                    receiver_evidence=[sample_evidence],
                    escrow_amount=100,
                )
                assert result.recommendation == "split"

    async def test_high_value_risk_factor(self, base_agent, sample_evidence):
        result = await base_agent.analyze_dispute(
            dispute_id="dispute1",
            sender_evidence=[sample_evidence],
            receiver_evidence=[sample_evidence],
            escrow_amount=2_000_000,  # strictly > 1_000_000 threshold in _risks
        )
        assert "high_value_escrow" in result.risk_factors

    async def test_multiple_disputes_tracking(self, base_agent, sample_evidence):
        await base_agent.analyze_dispute(
            dispute_id="dispute1",
            sender_evidence=[sample_evidence],
            receiver_evidence=[sample_evidence],
            escrow_amount=100,
        )
        await base_agent.analyze_dispute(
            dispute_id="dispute2",
            sender_evidence=[sample_evidence],
            receiver_evidence=[sample_evidence],
            escrow_amount=100,
        )
        # both sender_evidence and receiver_evidence items are claimed by
        # "sender" in this fixture, so each analyze_dispute call appends
        # the dispute id twice (once per submitted evidence item).
        assert base_agent._agent_disputes["sender"].count("dispute1") == 2
        assert base_agent._agent_disputes["sender"].count("dispute2") == 2

    async def test_evidence_type_scoring(self, base_agent):
        # Aged text evidence (60 of 90 max-age days old) scores well below the
        # 1.0 cap, while fresh screenshot evidence scores at/near the cap —
        # this keeps the two scores far enough apart (>= 0.15) that the
        # "too close, call it a split" branch in _HeuristicArbitrator.analyze
        # doesn't mask the type-multiplier difference being tested here.
        aged_ts = int(time.time()) - 60 * 86400
        text_evidence = DisputeEvidence(
            escrow_id="escrow1",
            claimant="sender",
            evidence_type="text",
            content_hash="hash1",
            description="Text evidence",
            timestamp=aged_ts,
        )
        screenshot_evidence = DisputeEvidence(
            escrow_id="escrow1",
            claimant="receiver",
            evidence_type="screenshot",
            content_hash="hash2",
            description="Screenshot evidence",
            timestamp=int(time.time()),
        )
        result = await base_agent.analyze_dispute(
            dispute_id="dispute1",
            sender_evidence=[text_evidence],
            receiver_evidence=[screenshot_evidence],
            escrow_amount=100,
        )
        # Fresh screenshot evidence outscores aged text evidence, so the
        # receiver (who submitted it) wins.
        assert result.recommendation == "favor_receiver"

    async def test_async_analyze_dispute(self, base_agent, sample_evidence):
        result = await base_agent.analyze_dispute(
            dispute_id="dispute1",
            sender_evidence=[sample_evidence],
            receiver_evidence=[sample_evidence],
            escrow_amount=100,
        )
        assert isinstance(result, ArbitrationRecommendation)


@pytest.mark.asyncio
class TestScoringFunctions:
    """Exercises _HeuristicArbitrator's real scoring helpers directly (they
    live on the module-level `_heuristic` instance, not on ArbitrationAgent)."""

    @pytest.fixture
    def heuristic(self):
        from server.ai_arbitration import _HeuristicArbitrator

        return _HeuristicArbitrator()

    async def test_score_empty_evidence(self, heuristic):
        result = heuristic._score([])
        assert result["score"] == 0.0
        assert result["factors"] == ["no_evidence"]

    async def test_score_text_evidence(self, heuristic):
        evidence = DisputeEvidence(
            escrow_id="escrow1",
            claimant="sender",
            evidence_type="text",
            content_hash="hash1",
            description="Test evidence",
            timestamp=int(time.time()),
        )
        result = heuristic._score([evidence])
        assert result["score"] > 0
        assert "text" in result["factors"]

    async def test_screenshot_scores_higher_than_text(self, heuristic):
        # A single fresh item of either type clips to the 1.0 score ceiling,
        # masking the per-type multiplier — age the text item so its score
        # sits below the ceiling and the type multiplier becomes visible.
        aged_ts = int(time.time()) - 60 * 86400
        text_ev = DisputeEvidence(
            escrow_id="e1",
            claimant="sender",
            evidence_type="text",
            content_hash="h1",
            description="d",
            timestamp=aged_ts,
        )
        shot_ev = DisputeEvidence(
            escrow_id="e1",
            claimant="sender",
            evidence_type="screenshot",
            content_hash="h2",
            description="d",
            timestamp=int(time.time()),
        )
        assert heuristic._score([shot_ev])["score"] > heuristic._score([text_ev])["score"]

    async def test_confidence_equal_scores(self, heuristic):
        confidence = heuristic._confidence({"score": 0.5}, {"score": 0.5})
        assert confidence == 0.5

    async def test_confidence_different_scores_favors_dominant(self, heuristic):
        confidence = heuristic._confidence({"score": 0.8}, {"score": 0.2})
        assert confidence > 0.5

    async def test_risks_high_value_escrow(self, heuristic):
        ev = DisputeEvidence(
            escrow_id="e1",
            claimant="sender",
            evidence_type="text",
            content_hash="h1",
            description="d",
            timestamp=int(time.time()),
        )
        risks = heuristic._risks([ev], [ev], amount=2_000_000, agent_disputes={})
        assert "high_value_escrow" in risks

    async def test_risks_no_evidence(self, heuristic):
        risks = heuristic._risks([], [], amount=100, agent_disputes={})
        assert risks == ["no_evidence_submitted"]

    async def test_risks_unilateral_evidence(self, heuristic):
        ev = DisputeEvidence(
            escrow_id="e1",
            claimant="sender",
            evidence_type="text",
            content_hash="h1",
            description="d",
            timestamp=int(time.time()),
        )
        risks = heuristic._risks([ev], [], amount=100, agent_disputes={})
        assert "unilateral_evidence" in risks

    async def test_risks_repeat_disputes(self, heuristic):
        ev = DisputeEvidence(
            escrow_id="e1",
            claimant="serial-claimant",
            evidence_type="text",
            content_hash="h1",
            description="d",
            timestamp=int(time.time()),
        )
        risks = heuristic._risks(
            [ev],
            [ev],
            amount=100,
            agent_disputes={"serial-claimant": ["d1", "d2", "d3"]},
        )
        assert any(r.startswith("repeat_disputes:") for r in risks)
