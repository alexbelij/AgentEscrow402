"""Dynamic insurance pool for AgentEscrow402."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from server.casper_client import CasperClient
from server.config import Config, get_config
from server.db import get_db, InMemoryDB, get_reputation_db
from server.models import EscrowRecord, EscrowStatus, ReputationRecord, PaymentHeader
from server.middleware import parse_x402_header

def get_casper() -> CasperClient | None:
    # This function is a placeholder, in a real app.py it would be defined globally
    # or imported from app.py. For this file generation, we assume it exists.
    from server.app import get_casper as _get_casper
    return _get_casper()




logger = logging.getLogger(__name__)
router = APIRouter(prefix="/insurance", tags=["insurance"])

# In-memory store for insurance pool and claims (replace with proper DB)
_insurance_pool: dict[str, Any] = {
    "total_assets": 100_000_000_000,  # Initial pool size in motes
    "total_premiums_collected": 0,
    "total_claims_paid": 0,
    "total_claims_filed": 0,
    "last_rebalance_time": int(time.time()),
}
_claims: dict[str, dict[str, Any]] = {}
_pool_lock = asyncio.Lock()


class InsuranceDepositRequest(BaseModel):
    """Request to deposit funds into the insurance pool."""

    amount: int = Field(..., gt=0, description="Amount in motes to deposit")


class InsuranceClaimRequest(BaseModel):
    """Request to file a claim against the insurance pool."""

    escrow_hash: str = Field(..., min_length=64, max_length=64, description="Service hash of the disputed escrow")
    reason: str = Field(..., min_length=10, description="Reason for the claim")


class PremiumQuoteRequest(BaseModel):
    """Request for an insurance premium quote."""

    agent_id: str = Field(..., description="Casper account hash of the agent requesting the quote")
    escrow_amount: int = Field(..., gt=0, description="Amount of the escrow to be insured")
    service_type: str = Field(default="general", description="Type of service (e.g., 'data_feed', 'computation')")


class PremiumQuoteResponse(BaseModel):
    """Response containing the calculated insurance premium."""

    premium_amount: int = Field(..., description="Calculated premium in motes")
    risk_multiplier: float = Field(..., description="Risk multiplier applied to the base rate")
    base_rate_bps: int = Field(..., description="Base premium rate in basis points")


class PoolStatsResponse(BaseModel):
    """Response containing current insurance pool statistics."""

    total_assets: int
    total_premiums_collected: int
    total_claims_paid: int
    total_claims_filed: int
    coverage_ratio: float = Field(..., description="Ratio of total assets to total potential liabilities (simplified)")
    last_rebalance_time: int


@router.post("/deposit", status_code=status.HTTP_202_ACCEPTED)
async def deposit_to_insurance_pool(
    request: InsuranceDepositRequest,
    x402: PaymentHeader = Depends(parse_x402_header),
    casper: CasperClient = Depends(get_casper),
    config: Config = Depends(get_config),
) -> dict[str, str]:
    """
    Allows an agent to deposit funds into the shared insurance pool.
    These funds contribute to the pool's solvency and can be used to cover claims.
    """
    depositor = x402.sender
    if x402.amount != request.amount:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="X402 amount must match deposit request amount.",
        )

    if not casper:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Casper client not initialized")
    if not config.insurance_contract_hash:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Insurance contract not configured")

    logger.info("Agent %s depositing %s motes into insurance pool.", depositor[:8], request.amount)

    # Simulate Casper deploy to transfer funds to the insurance contract
    # In a real scenario, this would be a contract call to `deposit`
    try:
        # deploy_hash = await casper.call_contract(
        #     contract_hash=config.insurance_contract_hash,
        #     entry_point="deposit",
        #     args={"amount": request.amount, "depositor": depositor},
        #     payment_amount=request.amount,
        # )
        deploy_hash = f"deploy-hash-insurance-deposit-{int(time.time())}"
        _insurance_pool["total_assets"] += request.amount
        _insurance_pool["total_premiums_collected"] += request.amount # Can be used for premiums or direct deposits
    except Exception as e:
        logger.error("Failed to process insurance deposit for %s: %s", depositor[:8], e)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to process deposit on-chain")

    logger.info("Deposit of %s motes by %s successful. Deploy hash: %s", request.amount, depositor[:8], deploy_hash[:16])
    return {"message": "Deposit successful", "deploy_hash": deploy_hash}


@router.post("/claim", status_code=status.HTTP_202_ACCEPTED)
async def file_insurance_claim(
    request: InsuranceClaimRequest,
    x402: PaymentHeader = Depends(parse_x402_header),
    casper: CasperClient = Depends(get_casper),
    config: Config = Depends(get_config),
    db: InMemoryDB = Depends(get_db),
) -> dict[str, str]:
    """
    Allows an agent to file a claim against the insurance pool for a disputed or failed escrow.
    Includes basic fraud detection.
    """
    claimant = x402.sender
    if not casper:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Casper client not initialized")
    if not config.insurance_contract_hash:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Insurance contract not configured")

    escrow = db.get_escrow(request.escrow_hash)
    if not escrow:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Escrow not found")

    # Only sender or receiver of the escrow can file a claim related to it
    if claimant not in [escrow.sender, escrow.receiver]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only escrow parties can file a claim")

    # Basic fraud detection:
    # 1. Escrow must be in a disputable or failed state
    if escrow.status not in [EscrowStatus.DISPUTED, EscrowStatus.EXPIRED]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Escrow status '{escrow.status}' is not eligible for claim")

    # 2. Check claimant's reputation (simplified)
    reputation = db.get_reputation(claimant)
    if reputation and reputation.slashed > 2:  # Example: too many previous slashes
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Claimant has a poor reputation history")

    # 3. Prevent duplicate claims
    if request.escrow_hash in _claims:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Claim already filed for this escrow")

    logger.info("Agent %s filing claim for escrow %s. Reason: %s", claimant[:8], request.escrow_hash[:16], request.reason[:50])

    # Simulate Casper deploy to record the claim on the insurance contract
    try:
        # deploy_hash = await casper.call_contract(
        #     contract_hash=config.insurance_contract_hash,
        #     entry_point="file_claim",
        #     args={"escrow_hash": request.escrow_hash, "claimant": claimant, "reason": request.reason},
        # )
        deploy_hash = f"deploy-hash-insurance-claim-{int(time.time())}"
        _insurance_pool["total_claims_filed"] += 1
        _claims[request.escrow_hash] = {
            "claimant": claimant,
            "escrow_hash": request.escrow_hash,
            "amount": escrow.amount,
            "reason": request.reason,
            "status": "pending",
            "filed_at": int(time.time()),
            "deploy_hash": deploy_hash,
        }
        # For simplicity, immediately approve and pay out if no complex arbitration
        _insurance_pool["total_claims_paid"] += escrow.amount
        _insurance_pool["total_assets"] -= escrow.amount
        _claims[request.escrow_hash]["status"] = "paid"

    except Exception as e:
        logger.error("Failed to process insurance claim for %s: %s", claimant[:8], e)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to process claim on-chain")

    logger.info("Claim for escrow %s by %s processed. Deploy hash: %s", request.escrow_hash[:16], claimant[:8], deploy_hash[:16])
    return {"message": "Claim filed and processed successfully", "deploy_hash": deploy_hash}


@router.get("/pool-stats", response_model=PoolStatsResponse)
async def get_insurance_pool_stats(
    casper: CasperClient = Depends(get_casper),
    config: Config = Depends(get_config),
) -> PoolStatsResponse:
    """
    Retrieves current statistics for the insurance pool.
    """
    # Pool stats are served from the in-memory store, so they must stay
    # available even when the Casper client or contract hash is missing.
    logger.debug("Fetching insurance pool statistics.")

    # In a real system, query the insurance contract for these stats
    # For now, use the in-memory store
    total_assets = _insurance_pool["total_assets"]
    total_premiums_collected = _insurance_pool["total_premiums_collected"]
    total_claims_paid = _insurance_pool["total_claims_paid"]
    total_claims_filed = _insurance_pool["total_claims_filed"]
    last_rebalance_time = _insurance_pool["last_rebalance_time"]

    # Simplified coverage ratio: total assets / (total claims filed * average claim amount)
    # Or simply total assets / (total potential liabilities from active escrows)
    # For simplicity, let's use a fixed value or a simple calculation.
    coverage_ratio = total_assets / max(1, total_claims_filed * 1_000_000_000) if total_claims_filed > 0 else 1.0
    coverage_ratio = min(coverage_ratio, 10.0) # Cap for display

    return PoolStatsResponse(
        total_assets=total_assets,
        total_premiums_collected=total_premiums_collected,
        total_claims_paid=total_claims_paid,
        total_claims_filed=total_claims_filed,
        coverage_ratio=round(coverage_ratio, 2),
        last_rebalance_time=last_rebalance_time,
    )


@router.get("/premium-quote", response_model=PremiumQuoteResponse)
async def get_premium_quote(
    request: PremiumQuoteRequest = Depends(),
) -> PremiumQuoteResponse:
    """
    Calculates a dynamic insurance premium quote based on agent reputation and escrow details.
    """
    base_rate_bps = 50  # 0.5% base rate in basis points
    risk_multiplier = 1.0

    # Look up the agent's reputation from the persistent store (if available).
    reputation = None
    try:
        reputation = get_reputation_db(request.agent_id)
    except Exception:  # never let a reputation lookup break the quote
        reputation = None
    if reputation:
        score = reputation.get("score", 50)
        # Adjust risk multiplier based on reputation score
        if score < 30:
            risk_multiplier *= 2.0  # High risk
        elif score < 50:
            risk_multiplier *= 1.5  # Medium risk
        elif score > 70:
            risk_multiplier *= 0.8  # Low risk

        # Further adjustments based on dispute/slashed history
        if reputation.get("disputed", 0) > 0:
            risk_multiplier *= 1.2
        if reputation.get("slashed", 0) > 0:
            risk_multiplier *= 1.5

    # Adjust based on service type (simplified)
    if request.service_type == "high_risk_data":
        risk_multiplier *= 1.3
    elif request.service_type == "low_value_task":
        risk_multiplier *= 0.9

    # Ensure multiplier is within reasonable bounds
    risk_multiplier = max(0.5, min(risk_multiplier, 5.0))

    premium_amount = int((request.escrow_amount * base_rate_bps / 10000) * risk_multiplier)
    premium_amount = max(premium_amount, 1000000) # Minimum premium of 1 CSPR mote

    logger.info(
        "Premium quote for agent %s, escrow %s: %s motes (risk_multiplier=%.2f)",
        request.agent_id[:8],
        request.escrow_amount,
        premium_amount,
        risk_multiplier,
    )

    return PremiumQuoteResponse(
        premium_amount=premium_amount,
        risk_multiplier=round(risk_multiplier, 2),
        base_rate_bps=base_rate_bps,
    )
