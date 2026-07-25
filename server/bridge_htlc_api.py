"""FastAPI wiring for the deterministic HTLC atomic-swap bridge (T3.4-A).

Exposes CRUD-ish endpoints over `bridge_htlc.HTLCRegistry`:

    POST   /bridge/htlc/initiate           # create both legs
    POST   /bridge/htlc/legs/{leg_id}/lock
    POST   /bridge/htlc/legs/{leg_id}/claim
    POST   /bridge/htlc/legs/{leg_id}/refund
    GET    /bridge/htlc/legs/{leg_id}
    GET    /bridge/htlc/swaps/{swap_id}
    GET    /bridge/htlc/swaps/{swap_id}/summary   # atomic outcome / safety flag
    GET    /bridge/htlc/swaps                     # list all
    POST   /bridge/htlc/preimage/new              # helper: generate (preimage, hashlock)

All state is in-memory (module registry). No Casper / EVM RPC calls —
this is the deterministic bridge-mock; the real Sepolia adapter is
T3.4-B (separate ticket).
"""

from __future__ import annotations

import time
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import bridge_htlc as htlc

router = APIRouter(prefix="/bridge/htlc", tags=["bridge-htlc"])


# ── Request / response models ────────────────────────────────────────


class InitiateSwapRequest(BaseModel):
    hashlock_hex: str = Field(..., description="lowercase sha256(preimage) hex, 64 chars")
    casper_initiator: str
    casper_counterparty: str
    casper_amount: int = Field(..., gt=0)
    casper_timelock_ms: int = Field(..., description="absolute deadline in ms (must be > evm_timelock_ms)")
    evm_initiator: str
    evm_counterparty: str
    evm_amount: int = Field(..., gt=0)
    evm_timelock_ms: int = Field(..., description="absolute deadline in ms (must be < casper_timelock_ms)")
    now_ms: Optional[int] = Field(default=None, description="test override; defaults to wall clock")


class ClaimRequest(BaseModel):
    preimage_hex: str = Field(..., description="the 32-byte secret in hex")
    now_ms: Optional[int] = None


class TimeOnlyRequest(BaseModel):
    now_ms: Optional[int] = None


class LegResponse(BaseModel):
    leg_id: str
    side: str
    initiator: str
    counterparty: str
    amount: int
    hashlock_hex: str
    timelock_ms: int
    status: str
    preimage_hex: Optional[str] = None
    locked_at_ms: Optional[int] = None
    claimed_at_ms: Optional[int] = None
    refunded_at_ms: Optional[int] = None
    lock_tx_hash: Optional[str] = None
    claim_tx_hash: Optional[str] = None
    refund_tx_hash: Optional[str] = None


class SwapResponse(BaseModel):
    swap_id: str
    hashlock_hex: str
    created_at_ms: int
    casper_leg: Optional[LegResponse] = None
    evm_leg: Optional[LegResponse] = None


class SwapSummaryResponse(BaseModel):
    swap_id: str
    hashlock_hex: str
    casper_status: Optional[str]
    evm_status: Optional[str]
    revealed_preimage_hex: Optional[str]
    atomic_outcome: str  # completed | aborted | in_progress
    safety_violation: bool


class PreimageResponse(BaseModel):
    preimage_hex: str
    hashlock_hex: str


# ── Helpers ──────────────────────────────────────────────────────────


def _now_ms() -> int:
    return int(time.time() * 1000)


def _wrap_leg(leg: htlc.HTLCLeg) -> LegResponse:
    return LegResponse(**leg.to_dict())


def _wrap_swap(swap: htlc.HTLCSwap) -> SwapResponse:
    return SwapResponse(
        swap_id=swap.swap_id,
        hashlock_hex=swap.hashlock_hex,
        created_at_ms=swap.created_at_ms,
        casper_leg=_wrap_leg(swap.casper_leg) if swap.casper_leg else None,
        evm_leg=_wrap_leg(swap.evm_leg) if swap.evm_leg else None,
    )


def _htlc_error_to_http(e: htlc.HTLCError) -> HTTPException:
    """Map typed rejection codes to conventional HTTP statuses."""
    # 404 for unknown ids
    if e.code == htlc.RejectCode.UNKNOWN_LEG:
        return HTTPException(status_code=404, detail={"code": e.code.value, "message": e.detail})
    # 409 for state conflicts / already-terminal / not-locked etc.
    conflict = {
        htlc.RejectCode.ALREADY_CLAIMED,
        htlc.RejectCode.ALREADY_REFUNDED,
        htlc.RejectCode.NOT_LOCKED,
        htlc.RejectCode.NOT_PROPOSED,
        htlc.RejectCode.LEG_ALREADY_EXISTS,
        htlc.RejectCode.TIMELOCK_EXPIRED,
        htlc.RejectCode.TIMELOCK_NOT_EXPIRED,
    }
    if e.code in conflict:
        return HTTPException(status_code=409, detail={"code": e.code.value, "message": e.detail})
    # 400 for validation / preimage mismatch (client-supplied bad input)
    return HTTPException(status_code=400, detail={"code": e.code.value, "message": e.detail})


def _registry() -> htlc.HTLCRegistry:
    return htlc.default_registry()


# ── Routes ───────────────────────────────────────────────────────────


@router.post("/preimage/new", response_model=PreimageResponse)
async def new_preimage_endpoint() -> PreimageResponse:
    """Convenience for demos/tests: generate a fresh secret + hashlock.

    In production the initiator generates the preimage client-side and
    ONLY publishes the hashlock. This endpoint is for local flows /
    tutorial scripts / judges reproducing a demo.
    """
    p = htlc.new_preimage()
    return PreimageResponse(preimage_hex=p.hex(), hashlock_hex=htlc.compute_hashlock(p))


@router.post("/initiate", response_model=SwapResponse, status_code=201)
async def initiate_swap(req: InitiateSwapRequest) -> SwapResponse:
    try:
        swap = _registry().initiate_swap(
            hashlock_hex=req.hashlock_hex,
            casper_initiator=req.casper_initiator,
            casper_counterparty=req.casper_counterparty,
            casper_amount=req.casper_amount,
            casper_timelock_ms=req.casper_timelock_ms,
            evm_initiator=req.evm_initiator,
            evm_counterparty=req.evm_counterparty,
            evm_amount=req.evm_amount,
            evm_timelock_ms=req.evm_timelock_ms,
            now_ms=req.now_ms if req.now_ms is not None else _now_ms(),
        )
    except htlc.HTLCError as e:
        raise _htlc_error_to_http(e)
    return _wrap_swap(swap)


@router.post("/legs/{leg_id}/lock", response_model=LegResponse)
async def lock_leg(leg_id: str, req: TimeOnlyRequest) -> LegResponse:
    try:
        leg = _registry().lock(
            leg_id,
            now_ms=req.now_ms if req.now_ms is not None else _now_ms(),
        )
    except htlc.HTLCError as e:
        raise _htlc_error_to_http(e)
    return _wrap_leg(leg)


@router.post("/legs/{leg_id}/claim", response_model=LegResponse)
async def claim_leg(leg_id: str, req: ClaimRequest) -> LegResponse:
    try:
        leg = _registry().claim(
            leg_id,
            preimage_hex=req.preimage_hex,
            now_ms=req.now_ms if req.now_ms is not None else _now_ms(),
        )
    except htlc.HTLCError as e:
        raise _htlc_error_to_http(e)
    return _wrap_leg(leg)


@router.post("/legs/{leg_id}/refund", response_model=LegResponse)
async def refund_leg(leg_id: str, req: TimeOnlyRequest) -> LegResponse:
    try:
        leg = _registry().refund(
            leg_id,
            now_ms=req.now_ms if req.now_ms is not None else _now_ms(),
        )
    except htlc.HTLCError as e:
        raise _htlc_error_to_http(e)
    return _wrap_leg(leg)


@router.get("/legs/{leg_id}", response_model=LegResponse)
async def get_leg(leg_id: str) -> LegResponse:
    leg = _registry().get_leg(leg_id)
    if leg is None:
        raise HTTPException(status_code=404, detail={"code": "unknown_leg", "message": leg_id})
    return _wrap_leg(leg)


@router.get("/swaps/{swap_id}", response_model=SwapResponse)
async def get_swap(swap_id: str) -> SwapResponse:
    swap = _registry().get_swap(swap_id)
    if swap is None:
        raise HTTPException(status_code=404, detail={"code": "unknown_swap", "message": swap_id})
    return _wrap_swap(swap)


@router.get("/swaps/{swap_id}/summary", response_model=SwapSummaryResponse)
async def get_swap_summary(swap_id: str) -> SwapSummaryResponse:
    summary = _registry().swap_state_summary(swap_id)
    if summary is None:
        raise HTTPException(status_code=404, detail={"code": "unknown_swap", "message": swap_id})
    return SwapSummaryResponse(**summary)


@router.get("/swaps", response_model=list[SwapResponse])
async def list_swaps() -> list[SwapResponse]:
    return [_wrap_swap(s) for s in _registry().list_swaps()]


__all__ = [
    "router",
    "InitiateSwapRequest",
    "ClaimRequest",
    "TimeOnlyRequest",
    "LegResponse",
    "SwapResponse",
    "SwapSummaryResponse",
    "PreimageResponse",
]
