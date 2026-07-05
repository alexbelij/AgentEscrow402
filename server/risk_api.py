"""Risk scoring API for AgentEscrow402.

Wires the IsolationForest (risk_scoring.py) to real on-chain tx data,
exposes GET /risk-score/{agent} and a dashboard summary endpoint.
Trains on-the-fly from testnet transaction history.
"""

from __future__ import annotations

import asyncio
import logging
import math
import random
import re
import secrets
import time as _time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from server.risk_scoring import (
    IsolationForest,
    RiskEngine,
    RiskScore,
    TransactionFeatures,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/risk", tags=["risk"])

# Singleton risk engine (trained lazily on first request)
_risk_engine: RiskEngine | None = None
_last_trained: float = 0.0
_TRAIN_TTL = 300  # retrain every 5 minutes


def get_casper():
    try:
        from server.app import get_casper as _gc
        return _gc()
    except Exception:
        return None


def _load_escrow_records() -> list[dict[str, Any]]:
    """Load escrow records from Neon or the running in-memory demo store."""
    try:
        from server import db as pgdb
        records = pgdb.load_escrows()
        if records:
            return records
    except Exception as exc:
        logger.debug("Neon escrow load failed for risk API: %s", exc)
    try:
        from server.app import get_sandbox
        store = get_sandbox()
        return list(store._escrows.values())
    except Exception as exc:
        logger.debug("Sandbox escrow load failed for risk API: %s", exc)
    return []


async def _get_or_train_engine(casper, db=None) -> RiskEngine:
    global _risk_engine, _last_trained

    now = _time.time()
    if _risk_engine is not None and (now - _last_trained) < _TRAIN_TTL:
        return _risk_engine

    # Gather training data from in-memory DB (real escrow records)
    training_samples: list[TransactionFeatures] = []

    for e in _load_escrow_records()[:500]:
        try:
            amount = int(e.get("amount", 0))
            created_at = int(e.get("created_at", 0))
            ttl = int(e.get("ttl", 86400))
            status = str(e.get("status", "pending"))
            disputed = 1 if status in ("disputed", "resolved") else 0

            training_samples.append(TransactionFeatures(
                amount=amount,
                frequency=1.0,
                counterparty_count=1,
                avg_ttl=float(ttl),
                dispute_rate=float(disputed),
                time_since_first=max(0, int(now) - created_at),
                total_volume=amount,
                max_single=amount,
                stddev_amount=0.0,
                hour_of_day=_time.gmtime(created_at).tm_hour,
            ))
        except Exception as exc:
            logger.debug("Skipping malformed escrow record: %s", exc)

    # If we have too few real samples, seed with synthetic normal distribution
    if len(training_samples) < 20:
        rng = random.Random(secrets.randbits(64))  # non-deterministic synthetic seed
        for i in range(50):
            amount = int(rng.gauss(500_000_000_000, 200_000_000_000))  # ~500 CSPR
            training_samples.append(TransactionFeatures(
                amount=max(1_000_000_000, amount),
                frequency=rng.uniform(0.1, 5.0),
                counterparty_count=rng.randint(1, 10),
                avg_ttl=rng.uniform(3600, 604800),
                dispute_rate=rng.uniform(0.0, 0.1),
                time_since_first=rng.randint(0, 30 * 86400),
                total_volume=max(1_000_000_000, amount),
                max_single=max(1_000_000_000, amount),
                stddev_amount=rng.uniform(0, amount * 0.3),
                hour_of_day=rng.randint(0, 23),
            ))

    engine = RiskEngine(threshold=0.65)
    engine.model.fit(training_samples)
    _risk_engine = engine
    _last_trained = now
    logger.info("Risk engine trained on %d samples", len(training_samples))
    return engine


# ── Response models ────────────────────────────────────────────────────────

class AgentRiskResponse(BaseModel):
    agent: str
    risk_score: int
    anomaly_flag: bool
    explanation: str
    model_version: str
    scored_at: int
    escrow_count: int
    total_volume_motes: int
    dispute_rate: float


class RiskDashboard(BaseModel):
    total_agents: int
    high_risk_count: int
    avg_risk_score: float
    agents: list[AgentRiskResponse]
    model_trained_at: float
    training_samples: int


# ── Endpoints ──────────────────────────────────────────────────────────────

_AGENT_PATTERN = re.compile(r"^[a-fA-F0-9]{64}$|^account-hash-[a-fA-F0-9]{64}$|^[a-zA-Z0-9_\-]{1,128}$")


@router.get("/score/{agent}", response_model=AgentRiskResponse)
async def get_agent_risk_score(agent: str) -> AgentRiskResponse:
    """Get the IsolationForest risk score for a specific agent address."""
    # Input validation — reject oversized or suspicious agent identifiers
    if len(agent) > 200 or not _AGENT_PATTERN.match(agent):
        raise HTTPException(status_code=422, detail="Invalid agent identifier format")
    casper = get_casper()
    engine = await _get_or_train_engine(casper)

    # Gather agent-specific metrics from DB
    escrow_count = 0
    total_volume = 0
    dispute_count = 0
    ttls: list[float] = []
    amounts: list[int] = []

    for e in _load_escrow_records()[:500]:
        sender = e.get("sender", "")
        receiver = e.get("receiver", "")
        if agent not in (sender, receiver):
            continue
        escrow_count += 1
        amt = int(e.get("amount", 0))
        total_volume += amt
        amounts.append(amt)
        ttls.append(float(e.get("ttl", 86400)))
        if e.get("status") in ("disputed", "resolved"):
            dispute_count += 1

    # Build feature vector
    stddev = 0.0
    if len(amounts) > 1:
        mean = total_volume / len(amounts)
        stddev = math.sqrt(sum((a - mean) ** 2 for a in amounts) / len(amounts))

    features = TransactionFeatures(
        amount=total_volume // max(1, escrow_count),
        frequency=escrow_count / max(1, 30),  # per 30 days
        counterparty_count=escrow_count,
        avg_ttl=sum(ttls) / max(1, len(ttls)),
        dispute_rate=dispute_count / max(1, escrow_count),
        time_since_first=0,
        total_volume=total_volume,
        max_single=max(amounts, default=0),
        stddev_amount=stddev,
        hour_of_day=_time.gmtime().tm_hour,
    )

    risk_score = await engine.assess(agent, features)

    return AgentRiskResponse(
        agent=agent,
        risk_score=risk_score.score,
        anomaly_flag=risk_score.anomaly_flag,
        explanation=risk_score.explanation,
        model_version=risk_score.model_version,
        scored_at=risk_score.scored_at,
        escrow_count=escrow_count,
        total_volume_motes=total_volume,
        dispute_rate=dispute_count / max(1, escrow_count),
    )


@router.get("/dashboard", response_model=RiskDashboard)
async def get_risk_dashboard() -> RiskDashboard:
    """Return aggregated risk scores for all known agents."""
    casper = get_casper()
    engine = await _get_or_train_engine(casper)

    # Collect all unique agents
    agents: dict[str, dict[str, Any]] = {}
    for e in _load_escrow_records()[:500]:
        for role in ("sender", "receiver"):
            ag = e.get(role, "")
            if not ag:
                continue
            if ag not in agents:
                agents[ag] = {"amounts": [], "disputes": 0, "ttls": []}
            agents[ag]["amounts"].append(int(e.get("amount", 0)))
            agents[ag]["ttls"].append(float(e.get("ttl", 86400)))
            if e.get("status") in ("disputed", "resolved"):
                agents[ag]["disputes"] += 1

    # If no real agents, show empty dashboard
    if not agents:
        return RiskDashboard(
            total_agents=0,
            high_risk_count=0,
            avg_risk_score=0.0,
            agents=[],
            model_trained_at=_last_trained,
            training_samples=len(engine.model.trees),
        )

    # Score each agent
    scored: list[AgentRiskResponse] = []
    for ag, data in agents.items():
        amounts = data["amounts"]
        ttls_list = data["ttls"]
        total = sum(amounts)
        cnt = len(amounts)
        disputes = data["disputes"]
        mean = total / max(1, cnt)
        stddev = math.sqrt(sum((a - mean) ** 2 for a in amounts) / max(1, cnt))

        features = TransactionFeatures(
            amount=int(mean),
            frequency=cnt / 30.0,
            counterparty_count=cnt,
            avg_ttl=sum(ttls_list) / max(1, len(ttls_list)),
            dispute_rate=disputes / max(1, cnt),
            time_since_first=0,
            total_volume=total,
            max_single=max(amounts, default=0),
            stddev_amount=stddev,
            hour_of_day=_time.gmtime().tm_hour,
        )
        rs = await engine.assess(ag, features)
        scored.append(AgentRiskResponse(
            agent=ag,
            risk_score=rs.score,
            anomaly_flag=rs.anomaly_flag,
            explanation=rs.explanation,
            model_version=rs.model_version,
            scored_at=rs.scored_at,
            escrow_count=cnt,
            total_volume_motes=total,
            dispute_rate=disputes / max(1, cnt),
        ))

    scored.sort(key=lambda x: x.risk_score, reverse=True)
    high_risk = sum(1 for s in scored if s.anomaly_flag)
    avg = sum(s.risk_score for s in scored) / max(1, len(scored))

    return RiskDashboard(
        total_agents=len(scored),
        high_risk_count=high_risk,
        avg_risk_score=round(avg, 1),
        agents=scored,
        model_trained_at=_last_trained,
        training_samples=len(engine.model.trees),
    )
