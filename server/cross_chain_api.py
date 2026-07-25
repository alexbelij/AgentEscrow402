"""FastAPI router for cross-chain escrows (W.3).

Exposes the cross-chain escrow lifecycle:
  POST /crosschain/escrow        create pending cross-chain escrow
  POST /crosschain/settle        attempt to settle by verifying trigger event
  POST /crosschain/cancel        cancel a PENDING escrow (sender only)
  GET  /crosschain/escrow/{id}   fetch a single escrow
  GET  /crosschain/escrows       list all escrows
  POST /crosschain/mock/event    inject a mock EVM event (demo only)
  POST /crosschain/mock/advance  advance mock block height (demo only)
  GET  /crosschain/chains        list supported foreign chains

Demo/audit surface — plain single-chain escrows remain the production path.
The `/mock/*` endpoints only work against the built-in `MockEVMAdapter`
and are guarded by a "sandbox" check (they're always no-op enabled in
this demo build; a real deployment would gate them behind admin auth).
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from server import cross_chain as cc

router = APIRouter(prefix="/crosschain", tags=["cross-chain"])


# ---------------------------------------------------------------------------
# Request/response models
# ---------------------------------------------------------------------------

class CreateCrossChainRequest(BaseModel):
    sender: str = Field(..., min_length=1, max_length=140)
    receiver: str = Field(..., min_length=1, max_length=140)
    amount_motes: int = Field(..., gt=0, lt=1 << 64)
    service_hash: str = Field(..., min_length=64, max_length=64, pattern=r"^[0-9a-fA-F]{64}$")
    trigger_chain: cc.ChainId
    trigger_tx_hash: str = Field(..., min_length=2, max_length=68)
    trigger_topic: str = Field(default="", max_length=68)
    min_confirmations: int = Field(default=12, ge=1, le=100)


class SettleRequest(BaseModel):
    escrow_id: str = Field(..., min_length=1, max_length=64)


class CancelRequest(BaseModel):
    escrow_id: str = Field(..., min_length=1, max_length=64)
    caller: str = Field(..., min_length=1, max_length=140)


class MockEventRequest(BaseModel):
    chain: cc.ChainId
    tx_hash: str = Field(..., min_length=2, max_length=68)
    topics: List[str] = Field(default_factory=list, max_length=16)
    data: str = Field(default="", max_length=1024)
    block_offset: int = Field(default=0, ge=0, le=100_000)


class AdvanceBlocksRequest(BaseModel):
    chain: cc.ChainId
    blocks: int = Field(..., ge=1, le=100_000)


class EscrowResponse(BaseModel):
    escrow: dict


class EscrowListResponse(BaseModel):
    escrows: List[dict]
    count: int


class SupportedChainsResponse(BaseModel):
    evm: List[str]
    casper: List[str]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/escrow", response_model=EscrowResponse, status_code=status.HTTP_201_CREATED)
def create_escrow(req: CreateCrossChainRequest) -> EscrowResponse:
    """Open a cross-chain escrow bound to a trigger event on a foreign chain."""
    reg = cc.get_registry()
    try:
        escrow = reg.create_cross_chain_escrow(
            sender=req.sender,
            receiver=req.receiver,
            amount_motes=req.amount_motes,
            service_hash=req.service_hash,
            trigger_chain=req.trigger_chain,
            trigger_tx_hash=req.trigger_tx_hash,
            trigger_topic=req.trigger_topic,
            min_confirmations=req.min_confirmations,
        )
    except cc.CrossChainError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return EscrowResponse(escrow=escrow.to_dict())


@router.post("/settle", response_model=EscrowResponse)
def settle(req: SettleRequest) -> EscrowResponse:
    """Attempt to settle the escrow by verifying its trigger event."""
    reg = cc.get_registry()
    try:
        escrow = reg.settle_on_evm_event(req.escrow_id)
    except cc.CrossChainError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return EscrowResponse(escrow=escrow.to_dict())


@router.post("/cancel", response_model=EscrowResponse)
def cancel(req: CancelRequest) -> EscrowResponse:
    """Cancel a PENDING escrow (sender only)."""
    reg = cc.get_registry()
    try:
        escrow = reg.cancel(req.escrow_id, req.caller)
    except cc.CrossChainError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return EscrowResponse(escrow=escrow.to_dict())


@router.get("/escrow/{escrow_id}", response_model=EscrowResponse)
def get_escrow(escrow_id: str) -> EscrowResponse:
    reg = cc.get_registry()
    escrow = reg.get(escrow_id)
    if escrow is None:
        raise HTTPException(status_code=404, detail=f"unknown escrow: {escrow_id}")
    return EscrowResponse(escrow=escrow.to_dict())


@router.get("/escrows", response_model=EscrowListResponse)
def list_escrows() -> EscrowListResponse:
    reg = cc.get_registry()
    escrows = [e.to_dict() for e in reg.list_all()]
    return EscrowListResponse(escrows=escrows, count=len(escrows))


@router.get("/chains", response_model=SupportedChainsResponse)
def supported_chains() -> SupportedChainsResponse:
    reg = cc.get_registry()
    return SupportedChainsResponse(
        evm=[c.value for c in reg.evm.supported_chains()],
        casper=[c.value for c in reg.casper.supported_chains()],
    )


@router.post("/mock/event", response_model=EscrowResponse)
def mock_event(req: MockEventRequest) -> EscrowResponse:
    """Demo helper: inject a mock EVM event into the mock adapter."""
    reg = cc.get_registry()
    try:
        result = reg.evm.record_event(
            chain_id=req.chain,
            tx_hash=req.tx_hash,
            topics=req.topics,
            data=req.data,
            block_offset=req.block_offset,
        )
    except cc.CrossChainError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return EscrowResponse(escrow={"event": result.to_dict()})


@router.post("/mock/advance", response_model=EscrowResponse)
def mock_advance(req: AdvanceBlocksRequest) -> EscrowResponse:
    """Demo helper: advance the mock block height."""
    reg = cc.get_registry()
    try:
        new_height = reg.evm.advance_blocks(req.chain, req.blocks)
    except cc.CrossChainError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return EscrowResponse(escrow={"chain": req.chain.value, "new_height": new_height})
