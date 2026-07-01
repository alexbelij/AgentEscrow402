import hashlib
import time
from typing import Any
from collections import defaultdict

from pydantic import BaseModel, Field, field_validator


class DisputeEvidence(BaseModel):
    escrow_id: str
    claimant: str
    evidence_type: str = Field(..., pattern="^(text|screenshot|hash|transaction)$")
    content_hash: str
    description: str
    timestamp: int

    @field_validator("timestamp")
    @classmethod
    def validate_timestamp(cls, v: int) -> int:
        if v < 0:
            raise ValueError("timestamp must be non-negative")
        if v > int(time.time()) + 86400:
            raise ValueError("timestamp cannot be more than 1 day in the future")
        return v


class ArbitrationRecommendation(BaseModel):
    dispute_id: str
    recommendation: str = Field(..., pattern="^(favor_sender|favor_receiver|split|escalate)$")
    confidence: float = Field(..., ge=0.0, le=1.0)
    reasoning: str
    risk_factors: list[str]
    suggested_split_pct: float = Field(..., ge=0.0, le=100.0)
    analysis_hash: str


class ArbitrationAgent:
    def __init__(self, slashing_rate: float = 0.05, min_evidence: int = 1, max_evidence: int = 20):
        if not 0.0 <= slashing_rate <= 1.0:
            raise ValueError("slashing_rate must be between 0 and 1")
        if min_evidence < 1:
            raise ValueError("min_evidence must be at least 1")
        if max_evidence < min_evidence:
            raise ValueError("max_evidence must be >= min_evidence")
        
        self.slashing_rate = slashing_rate
        self.min_evidence = min_evidence
        self.max_evidence = max_evidence
        self._history: list[ArbitrationRecommendation] = []
        self._agent_disputes: dict[str, list[str]] = defaultdict(list)

    async def analyze_dispute(
        self,
        dispute_id: str,
        sender_evidence: list[DisputeEvidence],
        receiver_evidence: list[DisputeEvidence],
        escrow_amount: int,
    ) -> ArbitrationRecommendation:
        if escrow_amount < 0:
            raise ValueError("escrow_amount must be non-negative")
        
        total_evidence = len(sender_evidence) + len(receiver_evidence)
        if total_evidence < self.min_evidence:
            return ArbitrationRecommendation(
                dispute_id=dispute_id,
                recommendation="escalate",
                confidence=0.0,
                reasoning=f"Insufficient evidence: {total_evidence} items provided, minimum {self.min_evidence} required",
                risk_factors=["insufficient_evidence"],
                suggested_split_pct=50.0,
                analysis_hash="",
            )
        
        if total_evidence > self.max_evidence * 2:
            sender_evidence = sender_evidence[:self.max_evidence]
            receiver_evidence = receiver_evidence[:self.max_evidence]

        sender_score_data = self._score_evidence_set(sender_evidence)
        receiver_score_data = self._score_evidence_set(receiver_evidence)

        confidence = self._compute_confidence(sender_score_data, receiver_score_data)
        risk_factors = self._detect_risk_factors(sender_evidence, receiver_evidence, escrow_amount)

        sender_score = sender_score_data["score"]
        receiver_score = receiver_score_data["score"]

        if confidence < 0.3:
            recommendation = "escalate"
            split_pct = 50.0
            reasoning = f"Low confidence ({confidence:.2f}): manual review required. Sender score: {sender_score:.2f}, Receiver score: {receiver_score:.2f}"
        elif abs(sender_score - receiver_score) < 0.15:
            recommendation = "split"
            split_pct = 50.0
            reasoning = f"Scores too close to determine winner. Sender: {sender_score:.2f}, Receiver: {receiver_score:.2f}"
        elif sender_score > receiver_score:
            recommendation = "favor_sender"
            score_diff = sender_score - receiver_score
            split_pct = min(100.0, 50.0 + score_diff * 50.0)
            reasoning = f"Sender evidence stronger by {score_diff:.2f}. Factors: {sender_score_data['factors']}"
        else:
            recommendation = "favor_receiver"
            score_diff = receiver_score - sender_score
            split_pct = max(0.0, 50.0 - score_diff * 50.0)
            reasoning = f"Receiver evidence stronger by {score_diff:.2f}. Factors: {receiver_score_data['factors']}"

        analysis_content = (
            f"{dispute_id}:{recommendation}:{confidence:.4f}:"
            f"{sender_score:.4f}:{receiver_score:.4f}:"
            f"{escrow_amount}:{','.join(sorted(risk_factors))}"
        )
        analysis_hash = hashlib.sha256(analysis_content.encode()).hexdigest()

        result = ArbitrationRecommendation(
            dispute_id=dispute_id,
            recommendation=recommendation,
            confidence=confidence,
            reasoning=reasoning,
            risk_factors=risk_factors,
            suggested_split_pct=round(split_pct, 2),
            analysis_hash=analysis_hash,
        )

        self._history.append(result)
        for ev in sender_evidence:
            self._agent_disputes[ev.claimant].append(dispute_id)
        for ev in receiver_evidence:
            self._agent_disputes[ev.claimant].append(dispute_id)

        return result

    def compute_slashing(self, escrow_amount: int, loser_stake: int, confidence: float) -> int:
        if escrow_amount < 0 or loser_stake < 0:
            raise ValueError("amounts must be non-negative")
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        
        base_slash = int(loser_stake * self.slashing_rate)
        confidence_multiplier = 0.5 + (confidence * 0.5)
        adjusted_slash = int(base_slash * confidence_multiplier)
        
        max_slash = min(escrow_amount, loser_stake)
        return min(adjusted_slash, max_slash)

    def _score_evidence_set(self, evidence: list[DisputeEvidence]) -> dict[str, Any]:
        if not evidence:
            return {"score": 0.0, "factors": ["no_evidence"]}

        now = int(time.time())
        max_age = 90 * 86400

        scores: list[float] = []
        types_seen: set[str] = set()
        hashes_seen: set[str] = set()
        consistency_issues = 0

        for ev in evidence:
            item_score = 1.0

            age = now - ev.timestamp
            if age < 0:
                age = 0
            if age > max_age:
                recency_factor = 0.3
            else:
                recency_factor = 1.0 - (age / max_age) * 0.7
            item_score *= recency_factor

            if ev.evidence_type == "transaction":
                item_score *= 1.3
            elif ev.evidence_type == "hash":
                item_score *= 1.2
            elif ev.evidence_type == "screenshot":
                item_score *= 1.0
            else:
                item_score *= 0.9

            if ev.content_hash in hashes_seen:
                consistency_issues += 1
                item_score *= 0.5
            hashes_seen.add(ev.content_hash)

            types_seen.add(ev.evidence_type)
            scores.append(item_score)

        count_bonus = min(len(evidence) * 0.1, 0.5)
        diversity_bonus = len(types_seen) * 0.1

        consistency_penalty = consistency_issues * 0.3

        total_score = sum(scores) / len(scores) if scores else 0.0
        total_score = total_score * (1.0 + count_bonus + diversity_bonus - consistency_penalty)
        total_score = max(0.0, min(1.0, total_score))

        factors = []
        if len(evidence) >= 5:
            factors.append("high_volume")
        if len(types_seen) >= 3:
            factors.append("high_diversity")
        if consistency_issues > 0:
            factors.append(f"consistency_issues:{consistency_issues}")
        else:
            factors.append("consistent")

        return {"score": total_score, "factors": factors}

    def _compute_confidence(self, sender_score: dict, receiver_score: dict) -> float:
        sender_val = sender_score["score"]
        receiver_val = receiver_score["score"]

        if sender_val == 0.0 and receiver_val == 0.0:
            return 0.0

        total = sender_val + receiver_val
        if total == 0.0:
            return 0.0

        max_score = max(sender_val, receiver_val)
        dominance = max_score / total if total > 0 else 0.0

        evidence_quality = (sender_val + receiver_val) / 2.0

        raw_confidence = dominance * 0.6 + evidence_quality * 0.4
        return round(min(1.0, max(0.0, raw_confidence)), 4)

    def _detect_risk_factors(
        self,
        sender_evidence: list[DisputeEvidence],
        receiver_evidence: list[DisputeEvidence],
        escrow_amount: int,
    ) -> list[str]:
        risks: list[str] = []

        all_evidence = sender_evidence + receiver_evidence
        if not all_evidence:
            return ["no_evidence_submitted"]

        claimants: set[str] = set()
        for ev in all_evidence:
            claimants.add(ev.claimant)

        for claimant in claimants:
            dispute_count = len(self._agent_disputes.get(claimant, []))
            if dispute_count >= 3:
                risks.append(f"repeat_disputes:{claimant}:{dispute_count}")
            if dispute_count >= 5:
                risks.append(f"high_volume_disputant:{claimant}")

        if escrow_amount > 1_000_000:
            risks.append("high_value_escrow")
        elif escrow_amount > 100_000:
            risks.append("elevated_value_escrow")

        sender_types = {e.evidence_type for e in sender_evidence}
        receiver_types = {e.evidence_type for e in receiver_evidence}
        if sender_types and receiver_types and not sender_types.intersection(receiver_types):
            risks.append("divergent_evidence_types")

        now = int(time.time())
        stale_count = sum(1 for e in all_evidence if now - e.timestamp > 180 * 86400)
        if stale_count > len(all_evidence) // 2:
            risks.append("majority_stale_evidence")

        if len(sender_evidence) == 0 or len(receiver_evidence) == 0:
            risks.append("unilateral_evidence")

        unique_escrows = {e.escrow_id for e in all_evidence}
        if len(unique_escrows) > 1:
            risks.append("multi_escrow_evidence")

        return risks if risks else ["standard_risk_profile"]


class ArbitrationHistory:
    def __init__(self) -> None:
        self._records: list[ArbitrationRecommendation] = []
        self._agent_records: dict[str, list[ArbitrationRecommendation]] = defaultdict(list)

    def record(self, recommendation: ArbitrationRecommendation) -> None:
        self._records.append(recommendation)

    def get_agent_disputes(self, agent: str) -> list[ArbitrationRecommendation]:
        return [r for r in self._records if r.dispute_id.startswith(agent) or any(
            agent in rf for rf in r.risk_factors
        )]

    def get_repeat_offenders(self, threshold: int = 3) -> list[str]:
        from collections import Counter

        claimant_counts: Counter[str] = Counter()
        for rec in self._records:
            for factor in rec.risk_factors:
                if factor.startswith("repeat_disputes:"):
                    parts = factor.split(":")
                    if len(parts) >= 3:
                        claimant = parts[1]
                        count = int(parts[2])
                        claimant_counts[claimant] = max(claimant_counts[claimant], count)

        return [claimant for claimant, count in claimant_counts.items() if count >= threshold]
