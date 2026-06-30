"""AgentEscrow402 API server."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from functools import lru_cache

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from server.casper_client import CasperClient
from server.config import Config
from server.middleware import compute_service_hash, parse_x402_header
from server.models import (
    DisputeRequest,
    EscrowRecord,
    EscrowRequest,
    HealthResponse,
    RefundRequest,
    ReleaseRequest,
    ReputationRecord,
)
from server.sandbox import SandboxStore

logger = logging.getLogger(__name__)


@lru_cache
def get_config() -> Config:
    return Config.from_env()


_casper: CasperClient | None = None
_sandbox = SandboxStore()


def get_sandbox() -> SandboxStore:
    return _sandbox


def get_casper() -> CasperClient | None:
    return _casper


@asynccontextmanager
async def lifespan(application: FastAPI):
    global _casper
    cfg = get_config()
    if not cfg.sandbox and cfg.casper_node_url:
        _casper = CasperClient(cfg)
        logger.info("Connected to Casper node: %s", cfg.casper_node_url)
    else:
        logger.info("Running in sandbox mode")
    yield
    if _casper:
        await _casper.close()


app = FastAPI(
    title="AgentEscrow402",
    version="0.1.0",
    description="x402-compatible payment middleware for AI agents on Casper",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", response_model=HealthResponse)
async def health(cfg: Config = Depends(get_config)):
    return HealthResponse(sandbox=cfg.sandbox, chain=cfg.casper_chain_name)


@app.post("/escrow", response_model=EscrowRecord)
async def create_escrow(
    req: EscrowRequest,
    request: Request,
    cfg: Config = Depends(get_config),
    store: SandboxStore = Depends(get_sandbox),
    casper: CasperClient | None = Depends(get_casper),
):
    sender = _extract_sender(request)
    if cfg.sandbox:
        try:
            return store.create_escrow(
                sender=sender,
                receiver=req.receiver,
                amount=req.amount,
                service_hash=req.service_hash,
                ttl=req.ttl,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc))

    if casper is None:
        raise HTTPException(status_code=503, detail="Casper client not configured")
    await casper.create_escrow(
        sender=sender,
        receiver=req.receiver,
        amount=req.amount,
        service_hash=req.service_hash,
        ttl=req.ttl,
    )
    return EscrowRecord(
        sender=sender,
        receiver=req.receiver,
        amount=req.amount,
        service_hash=req.service_hash,
        status="pending",
        created_at=0,
        ttl=req.ttl,
    )


@app.post("/release", response_model=EscrowRecord)
async def release_escrow(
    req: ReleaseRequest,
    request: Request,
    cfg: Config = Depends(get_config),
    store: SandboxStore = Depends(get_sandbox),
    casper: CasperClient | None = Depends(get_casper),
):
    caller = _extract_sender(request)
    if cfg.sandbox:
        try:
            return store.release_escrow(req.service_hash, caller)
        except KeyError:
            raise HTTPException(status_code=404, detail="Escrow not found")
        except (ValueError, PermissionError) as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    if casper is None:
        raise HTTPException(status_code=503, detail="Casper client not configured")
    await casper.release(req.service_hash)
    record = await casper.get_escrow(req.service_hash)
    if record is None:
        raise HTTPException(status_code=404, detail="Escrow not found")
    return record


@app.post("/refund", response_model=EscrowRecord)
async def refund_escrow(
    req: RefundRequest,
    request: Request,
    cfg: Config = Depends(get_config),
    store: SandboxStore = Depends(get_sandbox),
    casper: CasperClient | None = Depends(get_casper),
):
    caller = _extract_sender(request)
    if cfg.sandbox:
        try:
            return store.refund_escrow(req.service_hash, caller)
        except KeyError:
            raise HTTPException(status_code=404, detail="Escrow not found")
        except (ValueError, PermissionError) as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    if casper is None:
        raise HTTPException(status_code=503, detail="Casper client not configured")
    await casper.refund(req.service_hash)
    record = await casper.get_escrow(req.service_hash)
    if record is None:
        raise HTTPException(status_code=404, detail="Escrow not found")
    return record


@app.post("/dispute", response_model=EscrowRecord)
async def dispute_escrow(
    req: DisputeRequest,
    cfg: Config = Depends(get_config),
    store: SandboxStore = Depends(get_sandbox),
    casper: CasperClient | None = Depends(get_casper),
):
    if cfg.sandbox:
        try:
            return store.dispute_escrow(req.service_hash)
        except KeyError:
            raise HTTPException(status_code=404, detail="Escrow not found")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    if casper is None:
        raise HTTPException(status_code=503, detail="Casper client not configured")
    await casper.dispute(req.service_hash)
    record = await casper.get_escrow(req.service_hash)
    if record is None:
        raise HTTPException(status_code=404, detail="Escrow not found")
    return record


@app.get("/escrow/{service_hash}", response_model=EscrowRecord)
async def get_escrow(
    service_hash: str,
    cfg: Config = Depends(get_config),
    store: SandboxStore = Depends(get_sandbox),
    casper: CasperClient | None = Depends(get_casper),
):
    if cfg.sandbox:
        record = store.get_escrow(service_hash)
        if record is None:
            raise HTTPException(status_code=404, detail="Escrow not found")
        return record
    if casper:
        record = await casper.get_escrow(service_hash)
        if record is None:
            raise HTTPException(status_code=404, detail="Escrow not found")
        return record
    raise HTTPException(status_code=503, detail="Casper client not configured")


@app.get("/reputation/{agent}", response_model=ReputationRecord)
async def get_reputation(
    agent: str,
    cfg: Config = Depends(get_config),
    store: SandboxStore = Depends(get_sandbox),
    casper: CasperClient | None = Depends(get_casper),
):
    if cfg.sandbox:
        return store.get_reputation(agent)
    if casper:
        return await casper.get_reputation(agent)
    raise HTTPException(status_code=503, detail="Casper client not configured")


@app.post("/compute-hash")
async def compute_hash(sender: str, receiver: str, amount: int, nonce: str):
    """Utility endpoint to compute a service hash."""
    return {"service_hash": compute_service_hash(sender, receiver, amount, nonce)}


def _extract_sender(request: Request) -> str:
    """Extract sender identity from x402 header or sandbox mode.

    In production (non-sandbox), the sender MUST come from the verified
    payment header. Query-param fallback is sandbox-only.
    """
    # Check verified payment from middleware first
    if hasattr(request.state, "payment") and request.state.payment:
        return request.state.payment.sender
    # Fallback: parse from raw header
    payment_header = request.headers.get("X-Payment")
    if payment_header:
        parsed = parse_x402_header(payment_header)
        if parsed:
            return parsed.sender
    # Sandbox-only fallback — in production this should never be reached
    cfg = get_config()
    if cfg.sandbox:
        return request.query_params.get("sender", "sandbox-agent-001")
    raise HTTPException(status_code=401, detail="sender identity required")
