"""Dynamic insurance pool for AgentEscrow402."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from server.casper_client import CasperClient
from server.config import Config, get_config
from server.db import get_db, InMemoryDB, get_reputation_db
from server.models import EscrowRecord, EscrowStatus, ReputationRecord, PaymentHeader
from server.middleware import parse_x402_header, _build_signing_payload, _check_replay, _verify_signature

DEMO_CONSOLE_SENDER = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
DEMO_CONSOLE_SIGNATURE = "a" * 128


def _extract_payment_from_request(http_request: Request):
    x402 = parse_x402_header(http_request.headers.get("X-Payment", ""))
    if x402 is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="X-Payment header required")
    is_demo_console = http_request.headers.get("X-AE402-Demo-Identity") == "hosted-console"
    if is_demo_console:
        if x402.sender == DEMO_CONSOLE_SENDER and x402.signature == DEMO_CONSOLE_SIGNATURE:
            return x402
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid demo x402 identity")
    replay_err = _check_replay(x402.nonce, x402.timestamp)
    if replay_err:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=replay_err)
    msg = _build_signing_payload(x402, method=http_request.method, path=http_request.url.path)
    if not _verify_signature(x402.sender, msg, x402.signature):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid x402 signature")
    return x402

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
    # Live-wallet path (see sendInsuranceClaimTx in frontend/src/lib/liveTx.ts):
    # when set, the connected wallet itself already built+signed+submitted a
    # real `claim()` call to the insurance-pool contract (which pays out to
    # `runtime::get_caller()` directly on-chain) -- the backend only confirms
    # the resulting on-chain state instead of ever holding the payout key.
    wallet_tx_hash: str | None = Field(default=None, description="Transaction hash of a wallet-submitted on-chain claim() call")
    sender_public_key_hex: str | None = Field(
        default=None,
        description="Connected wallet's public key hex, matched against the escrow's recorded sender/receiver (required when wallet_tx_hash is set)",
    )
    claimant_account_hash: str | None = Field(
        default=None,
        description="account-hash-{hex} of the connected wallet, used to poll the on-chain claims dict (required when wallet_tx_hash is set)",
    )


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
    http_request: Request,
    casper: CasperClient = Depends(get_casper),
    config: Config = Depends(get_config),
) -> dict[str, str]:
    """
    Allows an agent to deposit funds into the shared insurance pool.
    These funds contribute to the pool's solvency and can be used to cover claims.
    """
    x402 = _extract_payment_from_request(http_request)
    depositor = x402.sender
    if x402.amount != request.amount:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="X402 amount must match deposit request amount.",
        )

    # Pool accounting remains available even if the optional insurance contract
    # client is unavailable in the hosted demo.

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
    http_request: Request,
    casper: CasperClient = Depends(get_casper),
    config: Config = Depends(get_config),
    db: InMemoryDB = Depends(get_db),
) -> dict[str, str]:
    """
    Allows an agent to file a claim against the insurance pool for a disputed or failed escrow.
    Includes basic fraud detection.
    """
    if request.wallet_tx_hash:
        # Live-wallet path (see sendInsuranceClaimTx in liveTx.ts): the
        # connected wallet already built+signed+submitted the real claim()
        # call itself, so there's no x402 header to verify identity from --
        # the wallet's own public key hex (matched against the escrow's
        # recorded sender/receiver below) is the claimant, and on-chain
        # confirmation (after eligibility checks) is the actual proof of
        # payout, not this endpoint.
        if not request.sender_public_key_hex or not request.claimant_account_hash:
            raise HTTPException(
                status_code=422,
                detail="sender_public_key_hex and claimant_account_hash are required when wallet_tx_hash is set",
            )
        claimant = request.sender_public_key_hex
    else:
        x402 = _extract_payment_from_request(http_request)
        claimant = x402.sender

    escrow = None
    if hasattr(db, "get_escrow"):
        escrow = db.get_escrow(request.escrow_hash)
    if escrow is None and hasattr(db, "find"):
        found = db.find("escrows", service_hash=request.escrow_hash) or db.find("escrows", hash=request.escrow_hash)
        escrow = found[0] if found else None
    if escrow is None:
        try:
            from server.app import get_sandbox
            escrow = get_sandbox().get_escrow(request.escrow_hash)
        except Exception:
            escrow = None
    if not escrow:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Escrow not found")

    escrow_sender = escrow.get("sender") if isinstance(escrow, dict) else escrow.sender
    escrow_receiver = escrow.get("receiver") if isinstance(escrow, dict) else escrow.receiver
    escrow_status = escrow.get("status") if isinstance(escrow, dict) else escrow.status
    escrow_amount = int(escrow.get("amount", 0) if isinstance(escrow, dict) else escrow.amount)

    # Only sender or receiver of the escrow can file a claim related to it
    if claimant not in [escrow_sender, escrow_receiver]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only escrow parties can file a claim")

    # Basic fraud detection:
    # 1. Escrow must be in a disputable or failed state
    eligible_statuses = {EscrowStatus.DISPUTED, EscrowStatus.EXPIRED, "disputed", "expired"}
    if escrow_status not in eligible_statuses:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Escrow status '{escrow_status}' is not eligible for claim")

    # 2. Check claimant's reputation (simplified)
    reputation = None
    if hasattr(db, "get_reputation"):
        reputation = db.get_reputation(claimant)
    else:
        try:
            from server.app import get_sandbox
            reputation = get_sandbox().get_reputation(claimant)
        except Exception:
            reputation = None
    slashed = (reputation.get("slashed", 0) if isinstance(reputation, dict) else getattr(reputation, "slashed", 0)) if reputation else 0
    if slashed > 2:  # Example: too many previous slashes
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Claimant has a poor reputation history")

    # 3. Prevent duplicate claims
    if request.escrow_hash in _claims:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Claim already filed for this escrow")

    logger.info("Agent %s filing claim for escrow %s. Reason: %s", claimant[:8], request.escrow_hash[:16], request.reason[:50])

    if request.wallet_tx_hash:
        # Live-wallet path: the wallet already submitted a real `claim()`
        # call to the insurance-pool contract (pays out to its own
        # get_caller() on-chain) -- confirm it actually landed instead of
        # trusting the request. Casper's own claim() enforces cooldown /
        # max-coverage-of-pool-balance itself; if this dict entry updated
        # with our escrow_id, the payout genuinely happened.
        if casper is None:
            raise HTTPException(status_code=502, detail="Casper client unavailable to confirm on-chain claim")
        confirmed, revert_reason = await casper.confirm_wallet_insurance_claim(
            request.claimant_account_hash, request.escrow_hash, deploy_hash=request.wallet_tx_hash
        )
        if not confirmed:
            detail = (
                f"On-chain claim transaction reverted: {revert_reason}"
                if revert_reason
                else "Wallet transaction not yet confirmed on-chain; local state unchanged"
            )
            raise HTTPException(status_code=502, detail=detail)
        deploy_hash = request.wallet_tx_hash
        _insurance_pool["total_claims_filed"] += 1
        _claims[request.escrow_hash] = {
            "claimant": claimant,
            "escrow_hash": request.escrow_hash,
            "amount": escrow_amount,
            "reason": request.reason,
            "status": "paid",
            "filed_at": int(time.time()),
            "deploy_hash": deploy_hash,
        }
        # Real on-chain payout already happened via the contract's own
        # purse -- this is just the local dashboard/accounting mirror.
        _insurance_pool["total_claims_paid"] += escrow_amount
        _insurance_pool["total_assets"] -= escrow_amount
    else:
        # Simulated/demo path (no real on-chain insurance-pool contract call
        # yet) -- kept as-is for the hosted-console demo identity flow.
        try:
            deploy_hash = f"deploy-hash-insurance-claim-{int(time.time())}"
            _insurance_pool["total_claims_filed"] += 1
            _claims[request.escrow_hash] = {
                "claimant": claimant,
                "escrow_hash": request.escrow_hash,
                "amount": escrow_amount,
                "reason": request.reason,
                "status": "pending",
                "filed_at": int(time.time()),
                "deploy_hash": deploy_hash,
            }
            # For simplicity, immediately approve and pay out if no complex arbitration
            _insurance_pool["total_claims_paid"] += escrow_amount
            _insurance_pool["total_assets"] -= escrow_amount
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
