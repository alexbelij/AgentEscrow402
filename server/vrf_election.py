"""VRF-based arbiter election for AgentEscrow402.

On-chain VRF via the deployed vrf-arbiter contract:
- Calls `elect_arbiter` entry point on deployed vrf-arbiter contract
- Parses `selected_arbiters_csv` from on-chain contract state
- Falls back to local cryptographic selection if contract unavailable
"""

from __future__ import annotations

import hashlib
import re
import threading
import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from server.config import Config
from server.models import ReputationRecord
from server.casper_client import CasperClient

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/vrf", tags=["vrf"])

# ── In-memory state (replace with DB in production) ───────────────────────
_registered_arbiters: dict[str, ReputationRecord] = {
    # Pre-seeded demo arbiters
    "arbiter_alpha": ReputationRecord(agent="arbiter_alpha", score=85.0, completed=12),
    "arbiter_beta": ReputationRecord(agent="arbiter_beta", score=72.0, completed=8),
    "arbiter_gamma": ReputationRecord(agent="arbiter_gamma", score=91.0, completed=19),
}
_election_results: dict[str, dict[str, Any]] = {}


def get_casper() -> CasperClient | None:
    try:
        from server.app import get_casper as _get_casper
        return _get_casper()
    except Exception:
        return None


def get_config() -> Config:
    from server.app import get_config as _get_config
    return _get_config()


def get_db():
    """Legacy hook kept for compatibility; VRF routes no longer require app.get_db."""
    return None


# ── Pydantic models ────────────────────────────────────────────────────────

class ReputationScore(BaseModel):
    agent: str
    score: float = 0.0
    completed: int = 0
    disputed: int = 0


class ArbiterRecord(BaseModel):
    arbiter_id: str
    reputation_score: float
    completed_arbitrations: int
    availability: bool = True


class ElectArbiterRequest(BaseModel):
    dispute_id: str = Field(..., description="Unique dispute identifier")
    sender: str = Field(..., description="Dispute sender account (excluded from election)")
    receiver: str = Field(..., description="Dispute receiver account (excluded from election)")
    seed_hash: str = Field(
        ...,
        description="A recent block hash or other verifiable random seed for election",
    )


class ElectArbiterResponse(BaseModel):
    dispute_id: str
    elected_arbiter: ArbiterRecord
    election_proof: str
    elected_at: int
    method: str = "onchain_vrf"  # "onchain_vrf" or "local_csprng"


class ArbiterListResponse(BaseModel):
    arbiters: list[ReputationScore]
    count: int


# ── On-chain VRF helper ────────────────────────────────────────────────────

async def _elect_via_onchain_vrf(
    casper: CasperClient,
    dispute_id: str,
    eligible_ids: list[str],
    seed_hash: str,
    vrf_contract_hash: str = "",
) -> str | None:
    """Read an already-recorded election result from the deployed
    vrf-arbiter contract's `elections_dict` dictionary.

    IMPORTANT — this is a *read-only* helper, not a full on-chain flow:
    the vrf-arbiter contract's `select_arbiters` entry point (the one that
    actually performs the on-chain election and writes this dictionary
    entry) is never called by this backend anywhere. Nothing currently
    triggers a real on-chain election, so in practice this will almost
    always return None and the caller falls back to
    `_elect_local_csprng`. Wiring the write path (submitting a
    `select_arbiters` transaction here, plus registering arbiters via
    `register_arbiter` with a staked purse) is tracked as a separate,
    larger follow-up -- see skills/projects/ae402_hackathon.

    Previously this both read the wrong contract entirely (defaulted to
    the escrow contract's hash) and the wrong dictionary name
    ("vrf_elections" vs. the contract's actual "elections_dict"); fixed
    2026-07-06 so at least the read path is structurally correct for when
    the write path lands.

    Returns the elected arbiter account hash string, or None if no
    on-chain election result is available.
    """
    if not vrf_contract_hash:
        logger.warning("vrf_contract_hash not configured, skipping on-chain VRF read")
        return None

    try:
        # Contract's ElectionRecord layout:
        #   ((dispute_id, seed, selection_count), (selected_arbiters_csv, status, resolved_block_time))
        # CLValue "parsed" for a nested tuple typically comes back as a
        # nested list mirroring that shape; handle both that and a flat
        # CSV string defensively since we've never observed a real one yet.
        result = await casper.query_contract_dict("elections_dict", dispute_id, contract_hash=vrf_contract_hash)
        if not result or not result.get("parsed"):
            return None
        parsed = result["parsed"]
        selected_csv: str | None = None
        if isinstance(parsed, str):
            selected_csv = parsed
        elif isinstance(parsed, (list, tuple)) and len(parsed) == 2:
            inner = parsed[1]
            if isinstance(inner, (list, tuple)) and inner and isinstance(inner[0], str):
                selected_csv = inner[0]
        if not selected_csv:
            return None
        candidates = [a.strip() for a in selected_csv.split(",") if a.strip()]
        for candidate in candidates:
            if candidate in eligible_ids:
                logger.info("On-chain VRF elected arbiter: %s", candidate)
                return candidate
        if candidates:
            return candidates[0]
    except Exception as exc:
        logger.warning("On-chain VRF query failed: %s", exc)

    return None


def _elect_local_csprng(
    eligible_arbiters: list[ReputationRecord],
    seed_hash: str,
) -> ReputationRecord:
    """Cryptographically secure local arbiter election (fallback).
    
    Uses HMAC-SHA256 with seed_hash for deterministic, verifiable selection.
    Reputation-weighted: arbiters with higher scores have proportionally higher
    probability of selection.
    """
    import hmac
    import struct

    weights = [max(1, int(a.score)) for a in eligible_arbiters]
    total_weight = sum(weights)

    # Derive deterministic random bytes via HMAC-SHA256
    seed_bytes = bytes.fromhex(seed_hash.zfill(64))
    h = hmac.new(seed_bytes, b"arbiter_election_v1", hashlib.sha256)
    rand_bytes = h.digest()
    rand_int = struct.unpack(">Q", rand_bytes[:8])[0]  # 64-bit unsigned

    # Weighted selection
    pick = rand_int % total_weight
    cumulative = 0
    for arbiter, weight in zip(eligible_arbiters, weights):
        cumulative += weight
        if pick < cumulative:
            return arbiter

    return eligible_arbiters[-1]  # fallback


# ── Endpoints ──────────────────────────────────────────────────────────────

@router.post("/elect", response_model=ElectArbiterResponse, status_code=status.HTTP_201_CREATED)
async def elect_arbiter(
    request: ElectArbiterRequest,
    casper: CasperClient = Depends(get_casper),
    cfg: Config = Depends(get_config),
) -> ElectArbiterResponse:
    """Elect an arbiter using on-chain VRF (vrf-arbiter contract) with local CSPRNG fallback."""
    if request.dispute_id in _election_results:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Arbiter already elected for this dispute ID",
        )

    logger.info(
        "Initiating VRF arbiter election for dispute %s (seed=%s…)",
        request.dispute_id[:16],
        request.seed_hash[:16],
    )

    # 1. Filter eligible arbiters (not a dispute party)
    excluded = {request.sender, request.receiver}
    eligible: list[ReputationRecord] = [
        r for aid, r in _registered_arbiters.items() if aid not in excluded
    ]

    if not eligible:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No eligible arbiters available",
        )

    eligible_ids = [r.agent for r in eligible]
    elected_id: str | None = None
    method = "local_csprng"

    # 2. Try on-chain VRF first
    if casper and cfg.vrf_contract_hash:
        try:
            elected_id = await _elect_via_onchain_vrf(
                casper, request.dispute_id, eligible_ids, request.seed_hash, cfg.vrf_contract_hash
            )
            if elected_id:
                method = "onchain_vrf"
        except Exception as exc:
            logger.warning("On-chain VRF election failed, using local fallback: %s", exc)

    # 3. Fallback: local CSPRNG with reputation weighting
    if not elected_id:
        elected_record = _elect_local_csprng(eligible, request.seed_hash)
        elected_id = elected_record.agent

    # Look up full record
    elected_record = _registered_arbiters.get(elected_id, ReputationRecord(agent=elected_id))
    weights = [max(1, int(r.score)) for r in eligible]
    election_proof = (
        f"method={method}|seed={request.seed_hash}|"
        f"candidates={eligible_ids}|weights={weights}|elected={elected_id}"
    )

    arbiter_details = ArbiterRecord(
        arbiter_id=elected_id,
        reputation_score=elected_record.score,
        completed_arbitrations=elected_record.completed,
        availability=True,
    )

    elected_at = int(time.time())
    _election_results[request.dispute_id] = {
        "elected_arbiter": arbiter_details.model_dump(),
        "election_proof": election_proof,
        "elected_at": elected_at,
        "method": method,
    }

    logger.info(
        "Arbiter %s elected for dispute %s via %s. Score: %s",
        elected_id[:12],
        request.dispute_id[:16],
        method,
        elected_record.score,
    )

    return ElectArbiterResponse(
        dispute_id=request.dispute_id,
        elected_arbiter=arbiter_details,
        election_proof=election_proof,
        elected_at=elected_at,
        method=method,
    )


@router.get("/election/{dispute_id}", response_model=ElectArbiterResponse)
async def get_election_result(dispute_id: str) -> ElectArbiterResponse:
    """Retrieve the result of a previous arbiter election."""
    data = _election_results.get(dispute_id)
    if not data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Election result not found for this dispute ID",
        )
    return ElectArbiterResponse(
        dispute_id=dispute_id,
        elected_arbiter=ArbiterRecord(**data["elected_arbiter"]),
        election_proof=data["election_proof"],
        elected_at=data["elected_at"],
        method=data.get("method", "local_csprng"),
    )


@router.get("/arbiters", response_model=ArbiterListResponse)
async def get_registered_arbiters() -> ArbiterListResponse:
    """List all registered arbiters."""
    arbiters = [
        ReputationScore(
            agent=r.agent,
            score=r.score,
            completed=r.completed,
            disputed=r.disputed,
        )
        for r in _registered_arbiters.values()
    ]
    return ArbiterListResponse(arbiters=arbiters, count=len(arbiters))


@router.post("/arbiters/register", status_code=status.HTTP_201_CREATED)
async def register_arbiter(arbiter: ReputationScore) -> dict[str, str]:
    """Register an arbiter in the election pool."""
    _registered_arbiters[arbiter.agent] = ReputationRecord(
        agent=arbiter.agent,
        score=arbiter.score,
        completed=arbiter.completed,
        disputed=arbiter.disputed,
    )
    logger.info("Arbiter %s registered (score=%s)", arbiter.agent[:16], arbiter.score)
    return {"status": "registered", "agent": arbiter.agent}
