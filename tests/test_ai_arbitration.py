import pytest
from unittest.mock import AsyncMock, patch
from datetime import datetime, timedelta
from server.ai_arbitration import (
    DisputeEvidence,
    ArbitrationRecommendation,
    ArbitrationAgent,
)
import time

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

    def test_insufficient_evidence(self, base_agent):
        result = base_agent.analyze_dispute(
            dispute_id="dispute1",
            sender_evidence=[],
            receiver_evidence=[],
            escrow_amount=100,
        )
        assert result.recommendation == "escalate"
        assert result.confidence == 0.0
        assert "Insufficient evidence" in result.reasoning
        assert "insufficient_evidence" in result.risk_factors

    def test_negative_escrow_amount(self, base_agent):
        with pytest.raises(ValueError, match="escrow_amount must be non-negative"):
            base_agent.analyze_dispute(
                dispute_id="dispute1",
                sender_evidence=[],
                receiver_evidence=[],
                escrow_amount=-100,
            )

    def test_excessive_evidence_truncation(self, base_agent, sample_evidence):
        # Create more evidence than max_evidence * 2
        sender_ev = [sample_evidence] * 25
        receiver_ev = [sample_evidence] * 25
        result = base_agent.analyze_dispute(
            dispute_id="dispute1",
            sender_evidence=sender_ev,
            receiver_evidence=receiver_ev,
            escrow_amount=1000,
        )
        # Should truncate to max_evidence each
        assert len(base_agent._agent_disputes["dispute1"]) == 1
        assert result.recommendation in ["favor_sender", "favor_receiver", "split", "escalate"]

    def test_low_confidence_escalation(self, base_agent, sample_evidence):
        # Mock low scores to trigger escalation
        with patch.object(base_agent, "_score_evidence_set", return_value={"score": 0.1}):
            with patch.object(base_agent, "_compute_confidence", return_value=0.2):
                result = base_agent.analyze_dispute(
                    dispute_id="dispute1",
                    sender_evidence=[sample_evidence],
                    receiver_evidence=[sample_evidence],
                    escrow_amount=100,
                )
                assert result.recommendation == "escalate"
                assert "Low confidence" in result.reasoning

    def test_split_recommendation(self, base_agent, sample_evidence):
        with patch.object(base_agent, "_score_evidence_set", side_effect=[
            {"score": 0.5}, {"score": 0.55}
        ]):
            with patch.object(base_agent, "_compute_confidence", return_value=0.5):
                result = base_agent.analyze_dispute(
                    dispute_id="dispute1",
                    sender_evidence=[sample_evidence],
                    receiver_evidence=[sample_evidence],
                    escrow_amount=100,
                )
                assert result.recommendation == "split"
                assert result.suggested_split_pct == 50.0

    def test_favor_sender_recommendation(self, base_agent, sample_evidence):
        with patch.object(base_agent, "_score_evidence_set", side_effect=[
            {"score": 0.7}, {"score": 0.3}
        ]):
            with patch.object(base_agent, "_compute_confidence", return_value=0.7):
                result = base_agent.analyze_dispute(
                    dispute_id="dispute1",
                    sender_evidence=[sample_evidence],
                    receiver_evidence=[sample_evidence],
                    escrow_amount=100,
                )
                assert result.recommendation == "favor_sender"
                assert result.suggested_split_pct > 50.0

    def test_favor_receiver_recommendation(self, base_agent, sample_evidence):
        with patch.object(base_agent, "_score_evidence_set", side_effect=[
            {"score": 0.3}, {"score": 0.7}
        ]):
            with patch.object(base_agent, "_compute_confidence", return_value=0.7):
                result = base_agent.analyze_dispute(
                    dispute_id="dispute1",
                    sender_evidence=[sample_evidence],
                    receiver_evidence=[sample_evidence],
                    escrow_amount=100,
                )
                assert result.recommendation == "favor_receiver"

    def test_risk_factors_detection(self, base_agent, sample_evidence):
        with patch.object(base_agent, "_score_evidence_set", return_value={"score": 0.5}):
            with patch.object(base_agent, "_compute_confidence", return_value=0.6):
                with patch.object(base_agent, "_detect_risk_factors", return_value=["high_value", "fraud_suspicion"]):
                    result = base_agent.analyze_dispute(
                        dispute_id="dispute1",
                        sender_evidence=[sample_evidence],
                        receiver_evidence=[sample_evidence],
                        escrow_amount=10000,
                    )
                    assert "high_value" in result.risk_factors
                    assert "fraud_suspicion" in result.risk_factors

    def test_history_tracking(self, base_agent, sample_evidence):
        result = base_agent.analyze_dispute(
            dispute_id="dispute1",
            sender_evidence=[sample_evidence],
            receiver_evidence=[sample_evidence],
            escrow_amount=100,
        )
        assert len(base_agent._history) == 1
        assert base_agent._history[0].dispute_id == "dispute1"

    def test_dispute_id_tracking(self, base_agent, sample_evidence):
        base_agent.analyze_dispute(
            dispute_id="dispute1",
            sender_evidence=[sample_evidence],
            receiver_evidence=[sample_evidence],
            escrow_amount=100,
        )
        assert "dispute1" in base_agent._agent_disputes
        assert len(base_agent._agent_disputes["dispute1"]) == 1

    def test_empty_evidence_lists(self, base_agent):
        result = base_agent.analyze_dispute(
            dispute_id="dispute1",
            sender_evidence=[],
            receiver_evidence=[],
            escrow_amount=100,
        )
        assert result.recommendation == "escalate"
        assert result.confidence == 0.0

    def test_single_evidence_each(self, base_agent, sample_evidence):
        result = base_agent.analyze_dispute(
            dispute_id="dispute1",
            sender_evidence=[sample_evidence],
            receiver_evidence=[sample_evidence],
            escrow_amount=100,
        )
        assert result.recommendation in ["split", "escalate"]

    def test_max_confidence_favor_sender(self, base_agent, sample_evidence):
        with patch.object(base_agent, "_score_evidence_set", side_effect=[
            {"score": 0.9}, {"score": 0.1}
        ]):
            with patch.object(base_agent, "_compute_confidence", return_value=1.0):
                result = base_agent.analyze_dispute(
                    dispute_id="dispute1",
                    sender_evidence=[sample_evidence],
                    receiver_evidence=[sample_evidence],
                    escrow_amount=100,
                )
                assert result.recommendation == "favor_sender"
                assert result.suggested_split_pct == 100.0

    def test_boundary_score_difference(self, base_agent, sample_evidence):
        with patch.object(base_agent, "_score_evidence_set", side_effect=[
            {"score": 0.55}, {"score": 0.45}
        ]):
            with patch.object(base_agent, "_compute_confidence", return_value=0.5):
                result = base_agent.analyze_dispute(
                    dispute_id="dispute1",
                    sender_evidence=[sample_evidence],
                    receiver_evidence=[sample_evidence],
                    escrow_amount=100,
                )
                assert result.recommendation == "split"

    def test_high_value_risk_factor(self, base_agent, sample_evidence):
        result = base_agent.analyze_dispute(
            dispute_id="dispute1",
            sender_evidence=[sample_evidence],
            receiver_evidence=[sample_evidence],
            escrow_amount=1000000,
        )
        assert "high_value" in result.risk_factors

    def test_multiple_disputes_tracking(self, base_agent, sample_evidence):
        base_agent.analyze_dispute(
            dispute_id="dispute1",
            sender_evidence=[sample_evidence],
            receiver_evidence=[sample_evidence],
            escrow_amount=100,
        )
        base_agent.analyze_dispute(
            dispute_id="dispute2",
            sender_evidence=[sample_evidence],
            receiver_evidence=[sample_evidence],
            escrow_amount=100,
        )
        assert len(base_agent._agent_disputes["dispute1"]) == 1
        assert len(base_agent._agent_disputes["dispute2"]) == 1

    def test_evidence_type_scoring(self, base_agent):
        text_evidence = DisputeEvidence(
            escrow_id="escrow1",
            claimant="sender",
            evidence_type="text",
            content_hash="hash1",
            description="Text evidence",
            timestamp=int(time.time()),
        )
        screenshot_evidence = DisputeEvidence(
            escrow_id="escrow1",
            claimant="sender",
            evidence_type="screenshot",
            content_hash="hash2",
            description="Screenshot evidence",
            timestamp=int(time.time()),
        )
        with patch.object(base_agent, "_compute_confidence", return_value=0.8):
            result = base_agent.analyze_dispute(
                dispute_id="dispute1",
                sender_evidence=[text_evidence],
                receiver_evidence=[screenshot_evidence],
                escrow_amount=100,
            )
            # Screenshot should score higher than text
            assert result.recommendation == "favor_receiver"

    async def test_async_analyze_dispute(self, base_agent, sample_evidence):
        # Test that the method is properly async
        with patch.object(base_agent, "_score_evidence_set", return_value={"score": 0.5}):
            with patch.object(base_agent, "_compute_confidence", return_value=0.5):
                result = await base_agent.analyze_dispute(
                    dispute_id="dispute1",
                    sender_evidence=[sample_evidence],
                    receiver_evidence=[sample_evidence],
                    escrow_amount=100,
                )
                assert isinstance(result, ArbitrationRecommendation)

class TestScoringFunctions:
    @pytest.fixture
    def agent(self):
        return ArbitrationAgent()

    def test_score_evidence_set_empty(self, agent):
        result = agent._score_evidence_set([])
        assert result["score"] == 0.0
        assert result["type_scores"] == {}

    def test_score_evidence_set_text(self, agent):
        evidence = DisputeEvidence(
            escrow_id="escrow1",
            claimant="sender",
            evidence_type="text",
            content_hash="hash1",
            description="Test evidence",
            timestamp=int(time.time()),
        )
        result = agent._score_evidence_set([evidence])
        assert result["score"] > 0
        assert result["type_scores"]["text"] > 0

    def test_score_evidence_set_screenshot(self, agent):
        evidence = DisputeEvidence(
            escrow_id="escrow1",
            claimant="sender",
            evidence_type="screenshot",
            content_hash="hash1",
            description="Test evidence",
            timestamp=int(time.time()),
        )
        result = agent._score_evidence_set([evidence])
        assert result["score"] > result["type_scores"]["text"]

    def test_compute_confidence_equal_scores(self, agent):
        confidence = agent._compute_confidence({"score": 0.5}, {"score": 0.5})
        assert confidence == 0.5

    def test_compute_confidence_different_scores(self, agent):
        confidence = agent._compute_confidence({"score": 0.8}, {"score": 0.2})
        assert confidence > 0.5

    def test_detect_risk_factors_high_value(self, agent):
        risk_factors = agent._detect_risk_factors([], [], escrow_amount=1000000)
        assert "high_value" in risk_factors

    def test_detect_risk_factors_insufficient_evidence(self, agent):
        risk_factors = agent._detect_risk_factors([], [], escrow_amount=100)
        assert "insufficient_evidence" in risk_factors

    def test_detect_risk_factors_multiple(self, agent):
        risk_factors = agent._detect_risk_factors([], [], escrow_amount=500000)
        assert "high_value" in risk_factors
        assert "large_dispute" in risk_factors
