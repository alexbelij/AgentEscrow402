"""VRF-based arbiter election for AgentEscrow402."""

from __future__ import annotations

import hashlib
import logging
import random
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from server.casper_client import CasperClient
from server.config import Config, get_config
from server.db import get_db, InMemoryDB
from server.models import ReputationRecord, PaymentHeader
from server.middleware import parse_x402_header

def get_casper() -> CasperClient | None:
    # This function is a placeholder, in a real app.py it would be defined globally
    # or imported from app.py. For this file generation, we assume it exists.
    from server.app import get_casper as _get_casper
    return _get_casper()




logger = logging.getLogger(__name__)
router = APIRouter(prefix="/arbitration", tags=["arbitration"])

# In-memory store for registered arbiters and election results (replace with proper DB)
_registered_arbiters: dict[str, ReputationRecord] = {
    "account-hash-arbiter1": ReputationRecord(agent="account-hash-arbiter1", score=80, completed=10),
    "account-hash-arbiter2": ReputationRecord(agent="account-hash-arbiter2", score=65, completed=5),
    "account-hash-arbiter3": ReputationRecord(agent="account-hash-arbiter3", score=90, completed=15),
    "account-hash-arbiter4": ReputationRecord(agent="account-hash-arbiter4", score=40, completed=2, disputed=1),
}
_election_results: dict[str, dict[str, Any]] = {}


class ElectArbiterRequest(BaseModel):
    """Request to elect an arbiter for a dispute."""

    dispute_id: str = Field(..., description="Unique identifier for the dispute (e.g., escrow service_hash)")
    sender: str = Field(..., description="Casper account hash of the sender in the dispute")
    receiver: str = Field(..., description="Casper account hash of the receiver in the dispute")
    seed_hash: str = Field(
        ...,
        min_length=64,
        max_length=64,
        description="A recent block hash or other verifiable random seed for election",
    )


class ArbiterRecord(BaseModel):
    """Details of an arbiter."""

    arbiter_id: str = Field(..., description="Casper account hash of the arbiter")
    reputation_score: int = Field(..., ge=0, le=100)
    completed_arbitrations: int = Field(default=0, ge=0)
    availability: bool = Field(default=True, description="Whether the arbiter is currently available")


class ElectArbiterResponse(BaseModel):
    """Response containing the elected arbiter."""

    dispute_id: str
    elected_arbiter: ArbiterRecord
    election_proof: str = Field(..., description="Proof of the election process (e.g., seed used, weighted selection details)")
    elected_at: int


class ArbiterListResponse(BaseModel):
    """List of available arbiters."""

    arbiters: list[ArbiterRecord]


@router.post("/elect", response_model=ElectArbiterResponse, status_code=status.HTTP_201_CREATED)
async def elect_arbiter(
    request: ElectArbiterRequest,
    casper: CasperClient = Depends(get_casper),
    config: Config = Depends(get_config),
    db: InMemoryDB = Depends(get_db),
) -> ElectArbiterResponse:
    """
    Elects an arbiter for a given dispute using a VRF-like, reputation-weighted selection process.
    Ensures the elected arbiter is not one of the dispute parties.
    """
    if request.dispute_id in _election_results:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Arbiter already elected for this dispute ID")

    if not casper:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Casper client not initialized")

    logger.info(
        "Initiating arbiter election for dispute %s between %s and %s with seed %s",
        request.dispute_id[:16],
        request.sender[:8],
        request.receiver[:8],
        request.seed_hash[:16],
    )

    # 1. Get available arbiters and filter out dispute parties
    eligible_arbiters: list[ReputationRecord] = []
    for arbiter_id, rep_record in _registered_arbiters.items():
        if arbiter_id not in [request.sender, request.receiver]:
            eligible_arbiters.append(rep_record)

    if not eligible_arbiters:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="No eligible arbiters available")

    # 2. Reputation-weighted selection
    # Use the seed_hash to make the selection deterministic and verifiable (if the seed is public)
    # For a true VRF, the contract would generate and reveal the randomness.
    # Here, we simulate a weighted choice based on reputation and a pseudo-random seed.
    seed_int = int(request.seed_hash, 16)
    random.seed(seed_int)  # Seed the random generator for deterministic selection

    weights = []
    for arbiter in eligible_arbiters:
        # A simple weighting: higher score means higher weight
        # Add a minimum weight to ensure even low-score arbiters have a chance
        weight = max(1, arbiter.score)
        weights.append(weight)

    elected_arbiter_record = random.choices(eligible_arbiters, weights=weights, k=1)[0]

    elected_arbiter_details = ArbiterRecord(
        arbiter_id=elected_arbiter_record.agent,
        reputation_score=elected_arbiter_record.score,
        completed_arbitrations=elected_arbiter_record.completed,
        availability=True, # Assume available for now
    )

    election_proof = f"Seed: {request.seed_hash}, Weights: {weights}, Elected: {elected_arbiter_record.agent}"

    _election_results[request.dispute_id] = {
        "elected_arbiter": elected_arbiter_details.model_dump(),
        "election_proof": election_proof,
        "elected_at": int(time.time()),
    }

    logger.info(
        "Arbiter %s elected for dispute %s. Score: %s",
        elected_arbiter_details.arbiter_id[:8],
        request.dispute_id[:16],
        elected_arbiter_details.reputation_score,
    )

    return ElectArbiterResponse(
        dispute_id=request.dispute_id,
        elected_arbiter=elected_arbiter_details,
        election_proof=election_proof,
        elected_at=int(time.time()),
    )


@router.get("/election/{dispute_id}", response_model=ElectArbiterResponse)
async def get_election_result(dispute_id: str) -> ElectArbiterResponse:
    """
    Retrieves the result of an arbiter election for a specific dispute.
    """
    election_data = _election_results.get(dispute_id)
    if not election_data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Election result not found for this dispute ID")

    logger.debug("Retrieving election result for dispute %s", dispute_id[:16])
    return ElectArbiterResponse(
        dispute_id=dispute_id,
        elected_arbiter=ArbiterRecord(**election_data["elected_arbiter"]),
        election_proof=election_data["election_proof"],
        elected_at=election_data["elected_at"],
    )


@router.get("/arbiters", response_model=ArbiterListResponse)
async def get_registered_arbiters() -> ArbiterListResponse:
    """
    Lists all currently registered arbiters and their reputation scores.
    """
    arbiters_list = []
    for arbiter_id, rep_record in _registered_arbiters.items():
        arbiters_list.append(
            ArbiterRecord(
                arbiter_id=arbiter_id,
                reputation_score=rep_record.score,
                completed_arbitrations=rep_record.completed,
                availability=True,  # Placeholder
            )
        )
    logger.debug("Listing %d registered arbiters.", len(arbiters_list))
    return ArbiterListResponse(arbiters=arbiters_list)
