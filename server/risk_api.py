"""Risk scoring API for AgentEscrow402.

Wires the IsolationForest (risk_scoring.py) to real on-chain tx data,
exposes GET /risk-score/{agent} and a dashboard summary endpoint.
Trains on-the-fly from testnet transaction history.
"""

from __future__ import annotations

import logging
import math
import random
import re
import secrets
import time as _time
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from server.regime_shift import (
    RegimeShiftBenchmark,
    benchmark_stream,
    cusum_stream,
    page_hinkley_stream,
)
from server.risk_premium import (
    RiskPremiumRequest,
    RiskPremiumResponse,
    compute_premium,
)
from server.risk_scoring import (
    RiskEngine,
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

            training_samples.append(
                TransactionFeatures(
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
                )
            )
        except Exception as exc:
            logger.debug("Skipping malformed escrow record: %s", exc)

    # If we have too few real samples, seed with synthetic normal distribution
    if len(training_samples) < 20:
        rng = random.Random(secrets.randbits(64))  # non-deterministic synthetic seed
        for i in range(50):
            amount = int(rng.gauss(500_000_000_000, 200_000_000_000))  # ~500 CSPR
            training_samples.append(
                TransactionFeatures(
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
                )
            )

    engine = RiskEngine(threshold=0.65)
    engine.model.fit(training_samples)
    _risk_engine = engine
    _last_trained = now
    logger.info("Risk engine trained on %d samples", len(training_samples))
    return engine


# ── Response models ────────────────────────────────────────────────────────


class AgentRiskResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

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
    model_config = ConfigDict(protected_namespaces=())

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
        scored.append(
            AgentRiskResponse(
                agent=ag,
                risk_score=rs.score,
                anomaly_flag=rs.anomaly_flag,
                explanation=rs.explanation,
                model_version=rs.model_version,
                scored_at=rs.scored_at,
                escrow_count=cnt,
                total_volume_motes=total,
                dispute_rate=disputes / max(1, cnt),
            )
        )

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


# ---------------------------------------------------------------------------
# Regime-shift detectors (CUSUM & Page-Hinkley)
# ---------------------------------------------------------------------------


class RegimeShiftRequest(BaseModel):
    """Input for /risk/regime-shift/* endpoints.

    ``values`` — the stream to analyse (e.g. per-hour dispute rate,
    counterparty volume, oracle latency). Typically 100-1000 samples.
    ``mu0``, ``sigma`` — assumed baseline mean/std (CUSUM only).
    ``cusum_k``, ``cusum_h`` — CUSUM slack and alarm threshold.
    ``ph_delta``, ``ph_threshold``, ``ph_alpha`` — Page-Hinkley knobs.
    """

    model_config = ConfigDict(extra="forbid")

    values: list[float]
    mu0: float = 0.0
    sigma: float = 1.0
    cusum_k: float = 0.5
    cusum_h: float = 5.0
    ph_delta: float = 0.005
    ph_threshold: float = 50.0
    ph_alpha: float = 1.0


class RegimeShiftBenchmarkResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    n_samples: int
    first_cusum_alarm_idx: int | None
    first_page_hinkley_alarm_idx: int | None
    agreement_ratio: float  # fraction of samples where both detectors agree
    trajectory: list[RegimeShiftBenchmark]


@router.post("/regime-shift/cusum")
async def regime_shift_cusum(req: RegimeShiftRequest) -> dict[str, Any]:
    """Run CUSUM over the supplied stream. Returns per-step results and the
    index of the first alarm (if any)."""
    if len(req.values) > 10000:
        raise HTTPException(status_code=413, detail="stream too long (max 10000 samples)")
    if len(req.values) == 0:
        raise HTTPException(status_code=400, detail="empty stream")
    try:
        results = cusum_stream(req.values, mu0=req.mu0, sigma=req.sigma, k=req.cusum_k, h=req.cusum_h)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    first_alarm = next((i for i, r in enumerate(results) if r.alarm_upper or r.alarm_lower), None)
    return {
        "n_samples": len(results),
        "first_alarm_idx": first_alarm,
        "first_alarm_direction": (results[first_alarm].direction if first_alarm is not None else None),
        "results": results,
    }


@router.post("/regime-shift/page-hinkley")
async def regime_shift_page_hinkley(req: RegimeShiftRequest) -> dict[str, Any]:
    """Run Page-Hinkley over the supplied stream."""
    if len(req.values) > 10000:
        raise HTTPException(status_code=413, detail="stream too long (max 10000 samples)")
    if len(req.values) == 0:
        raise HTTPException(status_code=400, detail="empty stream")
    try:
        results = page_hinkley_stream(
            req.values,
            delta=req.ph_delta,
            threshold=req.ph_threshold,
            alpha=req.ph_alpha,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    first_alarm = next((i for i, r in enumerate(results) if r.alarm), None)
    return {
        "n_samples": len(results),
        "first_alarm_idx": first_alarm,
        "results": results,
    }


@router.post("/regime-shift/benchmark", response_model=RegimeShiftBenchmarkResponse)
async def regime_shift_benchmark(req: RegimeShiftRequest) -> RegimeShiftBenchmarkResponse:
    """Side-by-side CUSUM vs Page-Hinkley on the same stream.

    Useful for operator dashboards — shows which detector fired first,
    how often they agree, and lets ops pick the right knob for the
    signal at hand.
    """
    if len(req.values) > 10000:
        raise HTTPException(status_code=413, detail="stream too long (max 10000 samples)")
    if len(req.values) == 0:
        raise HTTPException(status_code=400, detail="empty stream")
    try:
        trajectory = benchmark_stream(
            req.values,
            mu0=req.mu0,
            sigma=req.sigma,
            cusum_k=req.cusum_k,
            cusum_h=req.cusum_h,
            ph_delta=req.ph_delta,
            ph_threshold=req.ph_threshold,
            ph_alpha=req.ph_alpha,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    first_c = next(
        (i for i, r in enumerate(trajectory) if r.cusum.alarm_upper or r.cusum.alarm_lower),
        None,
    )
    first_p = next((i for i, r in enumerate(trajectory) if r.page_hinkley.alarm), None)
    agree = sum(1 for r in trajectory if r.detectors_agree) / len(trajectory)
    return RegimeShiftBenchmarkResponse(
        n_samples=len(trajectory),
        first_cusum_alarm_idx=first_c,
        first_page_hinkley_alarm_idx=first_p,
        agreement_ratio=round(agree, 4),
        trajectory=trajectory,
    )


# ---------------------------------------------------------------------------
# Beta-Binomial risk premium
# ---------------------------------------------------------------------------


@router.post("/premium", response_model=RiskPremiumResponse)
async def risk_premium(req: RiskPremiumRequest) -> RiskPremiumResponse:
    """Compute the Beta-Binomial risk premium for an agent given their
    observed (successes, disputes) history.

    Returns posterior parameters, credible interval on the dispute
    probability, and the recommended premium in basis points (UCB-driven,
    capped at 25%). A ``should_refuse: true`` result means the escrow
    should decline the counterparty entirely — the UCB implies the raw
    premium would exceed the safety ceiling.
    """
    try:
        return compute_premium(
            successes=req.successes,
            disputes=req.disputes,
            alpha0=req.alpha0,
            beta0=req.beta0,
            ci_level=req.ci_level,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


class PremiumBatchRequest(BaseModel):
    items: list[RiskPremiumRequest]


@router.post("/premium/batch")
async def risk_premium_batch(req: PremiumBatchRequest) -> list[RiskPremiumResponse]:
    """Batch variant — computes premium for a list of counterparties in one call."""
    if len(req.items) > 500:
        raise HTTPException(status_code=413, detail="batch too large (max 500)")
    return [
        compute_premium(
            successes=r.successes,
            disputes=r.disputes,
            alpha0=r.alpha0,
            beta0=r.beta0,
            ci_level=r.ci_level,
        )
        for r in req.items
    ]
