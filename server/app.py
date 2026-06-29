"""AgentEscrow402 API server."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

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
    ResolveRequest,
)
from server.sandbox import SandboxStore

logger = logging.getLogger(__name__)
cfg = Config.from_env()

sandbox_store = SandboxStore()
casper_client: CasperClient | None = None


@asynccontextmanager
async def lifespan(application: FastAPI):
    global casper_client
    if not cfg.sandbox and cfg.casper_node_url:
        casper_client = CasperClient(cfg)
        logger.info("Connected to Casper node: %s", cfg.casper_node_url)
    else:
        logger.info("Running in sandbox mode")
    yield
    if casper_client:
        await casper_client.close()


app = FastAPI(
    title="AgentEscrow402",
    version="0.1.0",
    description="x402-compatible payment middleware for AI agents on Casper",
    lifespan=lifespan,
)


@app.get("/health", response_model=HealthResponse)
async def health():
    return HealthResponse(
        sandbox=cfg.sandbox,
        chain=cfg.casper_chain_name,
    )


@app.post("/escrow", response_model=EscrowRecord)
async def create_escrow(req: EscrowRequest, request: Request):
    sender = _extract_sender(request)
    if cfg.sandbox:
        try:
            return sandbox_store.create_escrow(
                sender=sender,
                receiver=req.receiver,
                amount=req.amount,
                service_hash=req.service_hash,
                ttl=req.ttl,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
    raise HTTPException(status_code=501, detail="On-chain escrow not yet implemented")


@app.post("/release", response_model=EscrowRecord)
async def release_escrow(req: ReleaseRequest, request: Request):
    caller = _extract_sender(request)
    if cfg.sandbox:
        try:
            return sandbox_store.release_escrow(req.service_hash, caller)
        except KeyError:
            raise HTTPException(status_code=404, detail="Escrow not found")
        except (ValueError, PermissionError) as exc:
            raise HTTPException(status_code=400, detail=str(exc))
    raise HTTPException(status_code=501, detail="Not implemented")


@app.post("/refund", response_model=EscrowRecord)
async def refund_escrow(req: RefundRequest, request: Request):
    caller = _extract_sender(request)
    if cfg.sandbox:
        try:
            return sandbox_store.refund_escrow(req.service_hash, caller)
        except KeyError:
            raise HTTPException(status_code=404, detail="Escrow not found")
        except (ValueError, PermissionError) as exc:
            raise HTTPException(status_code=400, detail=str(exc))
    raise HTTPException(status_code=501, detail="Not implemented")


@app.post("/dispute", response_model=EscrowRecord)
async def dispute_escrow(req: DisputeRequest):
    if cfg.sandbox:
        try:
            return sandbox_store.dispute_escrow(req.service_hash)
        except KeyError:
            raise HTTPException(status_code=404, detail="Escrow not found")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
    raise HTTPException(status_code=501, detail="Not implemented")


@app.get("/escrow/{service_hash}", response_model=EscrowRecord)
async def get_escrow(service_hash: str):
    if cfg.sandbox:
        record = sandbox_store.get_escrow(service_hash)
        if record is None:
            raise HTTPException(status_code=404, detail="Escrow not found")
        return record
    if casper_client:
        record = await casper_client.get_escrow(service_hash)
        if record is None:
            raise HTTPException(status_code=404, detail="Escrow not found")
        return record
    raise HTTPException(status_code=501, detail="Not implemented")


@app.get("/reputation/{agent}", response_model=ReputationRecord)
async def get_reputation(agent: str):
    if cfg.sandbox:
        return sandbox_store.get_reputation(agent)
    if casper_client:
        return await casper_client.get_reputation(agent)
    raise HTTPException(status_code=501, detail="Not implemented")


@app.post("/compute-hash")
async def compute_hash(sender: str, receiver: str, amount: int, nonce: str):
    """Utility endpoint to compute a service hash."""
    return {"service_hash": compute_service_hash(sender, receiver, amount, nonce)}


def _extract_sender(request: Request) -> str:
    """Extract sender identity from x402 header or fallback to query param."""
    payment_header = request.headers.get("X-Payment")
    if payment_header:
        parsed = parse_x402_header(payment_header)
        if parsed:
            return parsed.sender
    sender = request.query_params.get("sender", "sandbox-agent-001")
    return sender
