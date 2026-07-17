"""AI arbitration for AgentEscrow402.

Fallback chain (cheapest/fastest first):
  1. Groq          (llama-3.1-8b-instant, free tier)
  2. NVIDIA NIM    (meta/llama-3.1-8b-instruct, free tier)
  3. OpenRouter    (free-tier model)
  4. Heuristic     (deterministic scoring, always works)
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from typing import Any
from collections import defaultdict

import httpx
from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

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
    recommendation: str = Field(..., pattern="^(favor_sender|favor_receiver|split|escalate|abstain)$")
    confidence: float = Field(..., ge=0.0, le=1.0)
    reasoning: str
    risk_factors: list[str]
    suggested_split_pct: float = Field(..., ge=0.0, le=100.0)
    analysis_hash: str
    provider: str = "heuristic"  # which provider answered


# ---------------------------------------------------------------------------
# LLM provider implementations (all async, all OpenAI-compatible)
# ---------------------------------------------------------------------------

ARBITRATION_SYSTEM_PROMPT = """You are an impartial AI arbitration judge for AgentEscrow402 — \
an on-chain escrow system for AI agent service payments on Casper blockchain.

Your task: analyze dispute evidence and return a JSON verdict. No markdown, no explanation outside JSON.

Valid recommendations:
- "favor_sender"   — refund sender (service not delivered / fraud)
- "favor_receiver" — release funds to receiver (service delivered)
- "split"          — split funds proportionally
- "escalate"       — insufficient evidence, needs human review
- "abstain"        — arbiter has a conflict of interest or cannot judge fairly

Required JSON format (EXACTLY, no extra keys):
{
  "recommendation": "<favor_sender|favor_receiver|split|escalate|abstain>",
  "confidence": <0.0-1.0>,
  "reasoning": "<concise explanation, max 200 chars>",
  "risk_factors": ["<factor1>", "<factor2>"],
  "suggested_split_pct": <0.0-100.0>
}
suggested_split_pct = percentage that goes to RECEIVER (0 = full refund, 100 = full payment).
"""


def _build_arbitration_prompt(
    dispute_id: str,
    sender_evidence: list[DisputeEvidence],
    receiver_evidence: list[DisputeEvidence],
    escrow_amount: int,
) -> str:
    def _fmt(evs: list[DisputeEvidence]) -> str:
        if not evs:
            return "  (none)"
        lines = []
        for i, e in enumerate(evs[:5]):  # cap at 5 items for token efficiency
            lines.append(
                f"  [{i+1}] type={e.evidence_type} claimant={e.claimant[:12]}... "
                f"description={e.description[:80]}"
            )
        if len(evs) > 5:
            lines.append(f"  ... and {len(evs)-5} more items")
        return "\n".join(lines)

    cspr = escrow_amount / 1_000_000_000
    return (
        f"Dispute ID: {dispute_id}\n"
        f"Escrow Amount: {cspr:.4f} CSPR ({escrow_amount} motes)\n\n"
        f"SENDER evidence ({len(sender_evidence)} items):\n{_fmt(sender_evidence)}\n\n"
        f"RECEIVER evidence ({len(receiver_evidence)} items):\n{_fmt(receiver_evidence)}\n\n"
        "Respond with JSON verdict only."
    )


def _parse_llm_json(raw: str) -> dict[str, Any] | None:
    """Extract and validate JSON from LLM response (handles markdown code blocks)."""
    # Strip markdown code fences
    raw = re.sub(r"```(?:json)?", "", raw).strip()
    # Find first { ... }
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        return None
    try:
        d = json.loads(m.group())
    except json.JSONDecodeError:
        return None

    required = {"recommendation", "confidence", "reasoning", "risk_factors", "suggested_split_pct"}
    if not required.issubset(d.keys()):
        return None
    if d["recommendation"] not in ("favor_sender", "favor_receiver", "split", "escalate", "abstain"):
        return None
    try:
        d["confidence"] = float(d["confidence"])
        d["suggested_split_pct"] = float(d["suggested_split_pct"])
        d["risk_factors"] = list(d["risk_factors"])
    except (TypeError, ValueError):
        return None
    d["confidence"] = max(0.0, min(1.0, d["confidence"]))
    d["suggested_split_pct"] = max(0.0, min(100.0, d["suggested_split_pct"]))
    return d


async def _call_openai_compat(
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict],
    timeout: float = 20.0,
) -> str:
    """Generic OpenAI-compatible chat completions call."""
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": messages,
                "max_tokens": 300,
                "temperature": 0.1,
            },
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


async def _try_groq(prompt: str) -> dict[str, Any] | None:
    api_key = os.getenv("GROQ_API_KEY", "")
    if not api_key:
        return None
    try:
        raw = await _call_openai_compat(
            "https://api.groq.com/openai/v1",
            api_key,
            "llama-3.1-8b-instant",
            [
                {"role": "system", "content": ARBITRATION_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        )
        parsed = _parse_llm_json(raw)
        if parsed:
            parsed["_provider"] = "groq/llama-3.1-8b-instant"
        return parsed
    except Exception as exc:
        logger.warning("Groq arbitration failed: %s", exc)
        return None


async def _try_nvidia(prompt: str) -> dict[str, Any] | None:
    api_key = os.getenv("NVIDIA_API_KEY", "")
    if not api_key:
        return None
    try:
        raw = await _call_openai_compat(
            "https://integrate.api.nvidia.com/v1",
            api_key,
            "meta/llama-3.1-8b-instruct",
            [
                {"role": "system", "content": ARBITRATION_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        )
        parsed = _parse_llm_json(raw)
        if parsed:
            parsed["_provider"] = "nvidia/llama-3.1-8b-instruct"
        return parsed
    except Exception as exc:
        logger.warning("NVIDIA arbitration failed: %s", exc)
        return None


async def _try_zai(prompt: str) -> dict[str, Any] | None:
    """z.ai (Zhipu GLM) — free tier with glm-4.5-air if account has balance."""
    api_key = os.getenv("ZAI_API_KEY", "")
    if not api_key:
        return None
    try:
        raw = await _call_openai_compat(
            "https://api.z.ai/api/paas/v4",
            api_key,
            "glm-4.5-air",
            [
                {"role": "system", "content": ARBITRATION_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            timeout=20.0,
        )
        parsed = _parse_llm_json(raw)
        if parsed:
            parsed["_provider"] = "zai/glm-4.5-air"
        return parsed
    except Exception as exc:
        logger.warning("z.ai arbitration failed: %s", exc)
        return None


async def _try_openrouter(prompt: str) -> dict[str, Any] | None:
    api_key = os.getenv("OPENROUTER_API_KEY", "")
    if not api_key:
        return None
    # Use nemotron-ultra (free, large context)
    try:
        raw = await _call_openai_compat(
            "https://openrouter.ai/api/v1",
            api_key,
            "nvidia/nemotron-3-ultra-550b-a55b:free",
            [
                {"role": "system", "content": ARBITRATION_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            timeout=30.0,
        )
        parsed = _parse_llm_json(raw)
        if parsed:
            parsed["_provider"] = "openrouter/nemotron-ultra"
        return parsed
    except Exception as exc:
        logger.warning("OpenRouter arbitration failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Heuristic fallback (kept from original, always works)
# ---------------------------------------------------------------------------

class _HeuristicArbitrator:
    """Pure scoring-based arbitration, no external calls."""

    def analyze(
        self,
        dispute_id: str,
        sender_evidence: list[DisputeEvidence],
        receiver_evidence: list[DisputeEvidence],
        escrow_amount: int,
        min_evidence: int = 1,
        max_evidence: int = 20,
        agent_disputes: dict[str, list[str]] | None = None,
    ) -> dict[str, Any]:
        agent_disputes = agent_disputes or {}
        total_evidence = len(sender_evidence) + len(receiver_evidence)
        if total_evidence < min_evidence:
            return {
                "recommendation": "escalate",
                "confidence": 0.0,
                "reasoning": f"Insufficient evidence: {total_evidence} items, min {min_evidence}",
                "risk_factors": ["insufficient_evidence"],
                "suggested_split_pct": 50.0,
                "_provider": "heuristic",
            }
        if total_evidence > max_evidence * 2:
            sender_evidence = sender_evidence[:max_evidence]
            receiver_evidence = receiver_evidence[:max_evidence]

        sender_sd = self._score(sender_evidence)
        receiver_sd = self._score(receiver_evidence)
        confidence = self._confidence(sender_sd, receiver_sd)
        risk_factors = self._risks(sender_evidence, receiver_evidence, escrow_amount, agent_disputes)

        s = sender_sd["score"]
        r = receiver_sd["score"]
        if confidence < 0.3:
            rec, split, reasoning = "escalate", 50.0, f"Low confidence ({confidence:.2f}): manual review needed"
        elif abs(s - r) < 0.15:
            rec, split, reasoning = "split", 50.0, f"Evidence too close. Sender={s:.2f} Receiver={r:.2f}"
        elif s > r:
            diff = s - r
            split = min(100.0, 50.0 + diff * 50.0)
            rec, reasoning = "favor_sender", f"Sender evidence stronger by {diff:.2f}"
        else:
            diff = r - s
            split = max(0.0, 50.0 - diff * 50.0)
            rec, reasoning = "favor_receiver", f"Receiver evidence stronger by {diff:.2f}"

        return {
            "recommendation": rec,
            "confidence": confidence,
            "reasoning": reasoning,
            "risk_factors": risk_factors,
            "suggested_split_pct": round(split, 2),
            "_provider": "heuristic",
        }

    def _score(self, evidence: list[DisputeEvidence]) -> dict[str, Any]:
        if not evidence:
            return {"score": 0.0, "factors": ["no_evidence"]}
        now = int(time.time())
        max_age = 90 * 86400
        scores: list[float] = []
        types_seen: set[str] = set()
        hashes_seen: set[str] = set()
        dup_count = 0
        for ev in evidence:
            item = 1.0
            age = max(0, now - ev.timestamp)
            item *= (1.0 - (age / max_age) * 0.7) if age <= max_age else 0.3
            item *= {"transaction": 1.3, "hash": 1.2, "screenshot": 1.0}.get(ev.evidence_type, 0.9)
            if ev.content_hash in hashes_seen:
                dup_count += 1
                item *= 0.5
            hashes_seen.add(ev.content_hash)
            types_seen.add(ev.evidence_type)
            scores.append(item)
        total = sum(scores) / len(scores) if scores else 0.0
        total *= (1.0 + min(len(evidence) * 0.1, 0.5) + len(types_seen) * 0.1 - dup_count * 0.3)
        return {"score": max(0.0, min(1.0, total)), "factors": list(types_seen)}

    def _confidence(self, s: dict, r: dict) -> float:
        sv, rv = s["score"], r["score"]
        total = sv + rv
        if total == 0:
            return 0.0
        dominance = max(sv, rv) / total
        quality = (sv + rv) / 2.0
        return round(min(1.0, max(0.0, dominance * 0.6 + quality * 0.4)), 4)

    def _risks(
        self,
        sender: list[DisputeEvidence],
        receiver: list[DisputeEvidence],
        amount: int,
        agent_disputes: dict[str, list[str]],
    ) -> list[str]:
        risks: list[str] = []
        all_ev = sender + receiver
        if not all_ev:
            return ["no_evidence_submitted"]
        for cl in {e.claimant for e in all_ev}:
            cnt = len(agent_disputes.get(cl, []))
            if cnt >= 3:
                risks.append(f"repeat_disputes:{cl[:12]}:{cnt}")
        if amount > 1_000_000:
            risks.append("high_value_escrow")
        if not sender or not receiver:
            risks.append("unilateral_evidence")
        now = int(time.time())
        stale = sum(1 for e in all_ev if now - e.timestamp > 180 * 86400)
        if stale > len(all_ev) // 2:
            risks.append("majority_stale_evidence")
        return risks or ["standard_risk_profile"]


_heuristic = _HeuristicArbitrator()


# ---------------------------------------------------------------------------
# Main ArbitrationAgent
# ---------------------------------------------------------------------------

class ArbitrationAgent:
    MAX_HISTORY = 10_000

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

        prompt = _build_arbitration_prompt(
            dispute_id, sender_evidence, receiver_evidence, escrow_amount
        )

        # Try LLM providers in order: Groq → NVIDIA → OpenRouter → heuristic
        verdict: dict[str, Any] | None = None
        for provider_fn in (_try_groq, _try_nvidia, _try_zai, _try_openrouter):
            verdict = await provider_fn(prompt)
            if verdict:
                logger.info("Arbitration via %s for dispute %s", verdict.get("_provider"), dispute_id[:16])
                break

        if not verdict:
            logger.warning("All LLM providers failed; using heuristic for %s", dispute_id[:16])
            verdict = _heuristic.analyze(
                dispute_id, sender_evidence, receiver_evidence, escrow_amount,
                self.min_evidence, self.max_evidence, dict(self._agent_disputes),
            )

        provider = verdict.pop("_provider", "heuristic")

        # Build analysis_hash
        content = (
            f"{dispute_id}:{verdict['recommendation']}:{verdict['confidence']:.4f}:"
            f"{escrow_amount}:{','.join(sorted(verdict['risk_factors']))}"
        )
        analysis_hash = hashlib.sha256(content.encode()).hexdigest()

        result = ArbitrationRecommendation(
            dispute_id=dispute_id,
            recommendation=verdict["recommendation"],
            confidence=verdict["confidence"],
            reasoning=str(verdict["reasoning"])[:300],
            risk_factors=verdict["risk_factors"],
            suggested_split_pct=round(float(verdict["suggested_split_pct"]), 2),
            analysis_hash=analysis_hash,
            provider=provider,
        )

        self._history.append(result)
        if len(self._history) > self.MAX_HISTORY:
            self._history = self._history[-self.MAX_HISTORY:]
        for ev in sender_evidence + receiver_evidence:
            self._agent_disputes[ev.claimant].append(dispute_id)
            if len(self._agent_disputes[ev.claimant]) > self.MAX_HISTORY:
                self._agent_disputes[ev.claimant] = self._agent_disputes[ev.claimant][-self.MAX_HISTORY:]

        return result

    def compute_slashing(self, escrow_amount: int, loser_stake: int, confidence: float) -> int:
        if escrow_amount < 0 or loser_stake < 0:
            raise ValueError("amounts must be non-negative")
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        base_slash = int(loser_stake * self.slashing_rate)
        adjusted = int(base_slash * (0.5 + confidence * 0.5))
        return min(adjusted, min(escrow_amount, loser_stake))


class ArbitrationHistory:
    def __init__(self) -> None:
        self._records: list[ArbitrationRecommendation] = []

    def record(self, recommendation: ArbitrationRecommendation) -> None:
        self._records.append(recommendation)

    def get_agent_disputes(self, agent: str) -> list[ArbitrationRecommendation]:
        return [r for r in self._records if any(agent in rf for rf in r.risk_factors)]

    def get_repeat_offenders(self, threshold: int = 3) -> list[str]:
        from collections import Counter
        counts: Counter[str] = Counter()
        for rec in self._records:
            for rf in rec.risk_factors:
                if rf.startswith("repeat_disputes:"):
                    parts = rf.split(":")
                    if len(parts) >= 3:
                        counts[parts[1]] = max(counts[parts[1]], int(parts[2]))
        return [c for c, n in counts.items() if n >= threshold]
