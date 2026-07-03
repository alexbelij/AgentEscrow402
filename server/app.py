"""AgentEscrow402 API server."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager
from functools import lru_cache
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from server import db as pgdb
from server.casper_client import CasperClient
from server.config import Config
from server.event_monitor import EventMonitor
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
from server.multi_asset import router as multi_asset_router
from server.insurance import router as insurance_router
from server.vrf_election import router as vrf_router
from server.agent_identity import router as identity_router
from server.ai_arbitration import ArbitrationAgent, DisputeEvidence, ArbitrationRecommendation

# Singleton arbitration agent (stateful — keeps history)
_arbitration_agent = ArbitrationAgent()

logger = logging.getLogger(__name__)


@lru_cache
def get_config() -> Config:
    return Config.from_env()


_casper: CasperClient | None = None
_sandbox = SandboxStore()
_monitor: EventMonitor | None = None
_monitor_task: asyncio.Task | None = None
_event_subscribers: list[asyncio.Queue] = []


def get_sandbox() -> SandboxStore:
    return _sandbox


def get_casper() -> CasperClient | None:
    return _casper


# ---------------------------------------------------------------------------
# Event handlers — called by EventMonitor when on-chain events arrive
# ---------------------------------------------------------------------------


async def _on_escrow_created(event: dict[str, Any]) -> None:
    """Handle on-chain escrow_created event."""
    sh = event.get("service_hash", "")
    logger.info("On-chain event: escrow_created %s", sh[:16])
    _broadcast_event({"type": "escrow_created", "service_hash": sh, "ts": int(time.time())})


async def _on_escrow_released(event: dict[str, Any]) -> None:
    sh = event.get("service_hash", "")
    pgdb.update_escrow_status(sh, "released")
    if sh in _sandbox._escrows:
        _sandbox._escrows[sh]["status"] = "released"
    logger.info("On-chain event: escrow_released %s", sh[:16])
    _broadcast_event({"type": "escrow_released", "service_hash": sh, "ts": int(time.time())})


async def _on_escrow_disputed(event: dict[str, Any]) -> None:
    sh = event.get("service_hash", "")
    pgdb.update_escrow_status(sh, "disputed")
    if sh in _sandbox._escrows:
        _sandbox._escrows[sh]["status"] = "disputed"
    logger.info("On-chain event: escrow_disputed %s", sh[:16])
    _broadcast_event({"type": "escrow_disputed", "service_hash": sh, "ts": int(time.time())})


def _broadcast_event(event: dict[str, Any]) -> None:
    """Push event to all SSE subscribers."""
    for q in _event_subscribers:
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            pass


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(application: FastAPI):
    global _casper, _monitor, _monitor_task
    cfg = get_config()

    # Initialize Casper client
    if not cfg.sandbox and cfg.casper_node_url and cfg.casper_private_key_path:
        _casper = CasperClient(cfg)
        logger.info("Casper client initialized: node=%s chain=%s", cfg.casper_node_url, cfg.casper_chain_name)

        # Wire up EventMonitor
        if cfg.contract_hash:
            _monitor = EventMonitor(
                node_url=cfg.casper_node_url,
                contract_hash=cfg.contract_hash,
                poll_interval=10.0,
            )
            _monitor.on("escrow_created", _on_escrow_created)
            _monitor.on("escrow_released", _on_escrow_released)
            _monitor.on("escrow_disputed", _on_escrow_disputed)
            _monitor_task = asyncio.create_task(_monitor.start())
            logger.info("EventMonitor started for contract %s", cfg.contract_hash[:16])
    else:
        logger.info("Running in sandbox mode (sandbox=%s, node=%s)", cfg.sandbox, bool(cfg.casper_node_url))

    # Load from DB or seed
    db_records = pgdb.load_escrows()
    if db_records:
        for rec in db_records:
            _sandbox._escrows[rec["service_hash"]] = rec
        logger.info("Loaded %d escrows from database", len(db_records))
    else:
        from server.seed import generate_seed_escrows

        seeds = generate_seed_escrows()
        for s in seeds:
            _sandbox._escrows[s["service_hash"]] = s
            pgdb.save_escrow(EscrowRecord(**s))
        logger.info("Seeded %d demo escrows", len(seeds))

    yield

    # Shutdown
    if _monitor:
        await _monitor.stop()
    if _monitor_task and not _monitor_task.done():
        _monitor_task.cancel()
    if _casper:
        await _casper.close()


app = FastAPI(
    title="AgentEscrow402",
    version="0.2.0",
    description="x402-compatible payment middleware for AI agents on Casper",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Rate limiting (60 req/min per IP)
# ---------------------------------------------------------------------------
_rate_limits: dict[str, dict] = {}


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    ip = request.client.host if request.client else "unknown"
    now = time.time()
    entry = _rate_limits.get(ip)
    if not entry or now > entry["reset"]:
        _rate_limits[ip] = {"count": 1, "reset": now + 60}
    else:
        entry["count"] += 1
        if entry["count"] > 60:
            raise HTTPException(status_code=429, detail="Too many requests")
    return await call_next(request)


# Register sub-routers
app.include_router(multi_asset_router)
app.include_router(insurance_router)
app.include_router(vrf_router)
app.include_router(identity_router)


# ---------------------------------------------------------------------------
# Insurance fee helper
# ---------------------------------------------------------------------------


def _apply_insurance_fee(amount: int, fee_bps: int) -> tuple[int, int]:
    """Split amount into net + insurance fee.

    Returns (net_amount, fee_amount).
    """
    fee = (amount * fee_bps) // 10_000
    return amount - fee, fee


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/health", response_model=HealthResponse)
async def health(cfg: Config = Depends(get_config)):
    contract_hash = cfg.contract_hash or ""
    connected = pgdb.is_connected()
    return HealthResponse(
        sandbox=cfg.sandbox,
        chain=cfg.casper_chain_name,
        contract_hash=contract_hash,
        db="connected" if connected else "disconnected",
    )


@app.get("/stats")
async def stats():
    """Aggregate statistics for the console."""
    s = pgdb.get_stats()
    cfg = get_config()
    s["contract_hash"] = cfg.contract_hash or ""
    s["sandbox"] = cfg.sandbox
    s["insurance_fee_bps"] = cfg.insurance_fee_bps
    return s


@app.get("/escrows")
async def list_escrows(
    status: str | None = None,
    sender: str | None = None,
    page: int = 1,
    limit: int = 20,  # capped at 100 below
    offset: int | None = None,
    store: SandboxStore = Depends(get_sandbox),
):
    """List escrows with optional filters and pagination."""
    limit = min(limit, 100)  # hard cap to prevent excessive queries
    all_records = pgdb.load_escrows()
    if not all_records:
        all_records = [
            {
                "service_hash": k,
                "sender": v["sender"],
                "receiver": v["receiver"],
                "amount": v["amount"],
                "status": v["status"],
                "ttl": v["ttl"],
                "created_at": v["created_at"],
                "deploy_hash": v.get("deploy_hash"),
            }
            for k, v in store._escrows.items()
        ]
    if status:
        all_records = [r for r in all_records if r["status"] == status]
    if sender:
        all_records = [r for r in all_records if r["sender"] == sender]
    total = len(all_records)
    if offset is not None:
        start = offset
    else:
        start = (page - 1) * limit
    page_records = all_records[start : start + limit]
    return {"escrows": page_records, "total": total, "page": page, "limit": limit}


@app.post("/escrow", response_model=EscrowRecord)
async def create_escrow(
    req: EscrowRequest,
    request: Request,
    cfg: Config = Depends(get_config),
    store: SandboxStore = Depends(get_sandbox),
    casper: CasperClient | None = Depends(get_casper),
):
    sender = _extract_sender(request)

    # Apply insurance fee
    net_amount, fee = _apply_insurance_fee(req.amount, cfg.insurance_fee_bps)
    logger.info(
        "Escrow create: gross=%d net=%d fee=%d (%d bps)",
        req.amount,
        net_amount,
        fee,
        cfg.insurance_fee_bps,
    )

    if cfg.sandbox or casper is None:
        try:
            record = store.create_escrow(
                sender=sender,
                receiver=req.receiver,
                amount=net_amount,
                service_hash=req.service_hash,
                ttl=req.ttl,
            )
            pgdb.save_escrow(record)
            if fee > 0:
                pgdb.record_insurance_fee(req.service_hash, fee)
            return record
        except ValueError as exc:
            logger.warning("create_escrow validation failed: %s", exc)
            raise HTTPException(status_code=409, detail="Escrow creation conflict")

    # Live mode — deploy to Casper
    deploy_hash = await casper.create_escrow(
        sender=sender,
        receiver=req.receiver,
        amount=net_amount,
        service_hash=req.service_hash,
        ttl=req.ttl,
    )
    now = int(time.time())
    record = EscrowRecord(
        sender=sender,
        receiver=req.receiver,
        amount=net_amount,
        service_hash=req.service_hash,
        status="pending",
        created_at=now,
        ttl=req.ttl,
        deploy_hash=deploy_hash,
    )
    # Persist locally too
    store._escrows[req.service_hash] = {
        "sender": sender,
        "receiver": req.receiver,
        "amount": net_amount,
        "service_hash": req.service_hash,
        "status": "pending",
        "created_at": now,
        "ttl": req.ttl,
        "deploy_hash": deploy_hash,
    }
    pgdb.save_escrow(record)
    if fee > 0:
        pgdb.record_insurance_fee(req.service_hash, fee)
    _broadcast_event(
        {"type": "escrow_created", "service_hash": req.service_hash, "deploy_hash": deploy_hash, "ts": now}
    )
    return record


@app.post("/release", response_model=EscrowRecord)
async def release_escrow(
    req: ReleaseRequest,
    request: Request,
    cfg: Config = Depends(get_config),
    store: SandboxStore = Depends(get_sandbox),
    casper: CasperClient | None = Depends(get_casper),
):
    caller = _extract_sender(request)
    deploy_hash = ""

    if not cfg.sandbox and casper is not None:
        try:
            deploy_hash = await casper.release(req.service_hash)
        except Exception as exc:
            logger.error("Casper release failed: %s", exc)
            raise HTTPException(
                status_code=502,
                detail="On-chain release transaction failed; local state unchanged",
            )

    try:
        record = store.release_escrow(req.service_hash, caller)
        pgdb.update_escrow_status(req.service_hash, "released", deploy_hash)
        pgdb.bump_reputation(record.receiver, completed=1)
        _broadcast_event(
            {
                "type": "escrow_released",
                "service_hash": req.service_hash,
                "deploy_hash": deploy_hash,
                "ts": int(time.time()),
            }
        )
        return record
    except KeyError:
        raise HTTPException(status_code=404, detail="Escrow not found")
    except (ValueError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/refund", response_model=EscrowRecord)
async def refund_escrow(
    req: RefundRequest,
    request: Request,
    cfg: Config = Depends(get_config),
    store: SandboxStore = Depends(get_sandbox),
    casper: CasperClient | None = Depends(get_casper),
):
    caller = _extract_sender(request)
    deploy_hash = ""

    if not cfg.sandbox and casper is not None:
        try:
            deploy_hash = await casper.refund(req.service_hash)
        except Exception as exc:
            logger.error("Casper refund failed: %s", exc)
            raise HTTPException(
                status_code=502,
                detail="On-chain refund transaction failed; local state unchanged",
            )

    try:
        record = store.refund_escrow(req.service_hash, caller)
        pgdb.update_escrow_status(req.service_hash, record.status, deploy_hash)
        _broadcast_event({"type": "escrow_refunded", "service_hash": req.service_hash, "ts": int(time.time())})
        return record
    except KeyError:
        raise HTTPException(status_code=404, detail="Escrow not found")
    except (ValueError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/dispute", response_model=EscrowRecord)
async def dispute_escrow(
    req: DisputeRequest,
    request: Request,
    cfg: Config = Depends(get_config),
    store: SandboxStore = Depends(get_sandbox),
    casper: CasperClient | None = Depends(get_casper),
):
    # Authorization: only escrow sender or receiver may dispute
    caller = _extract_sender(request)
    try:
        escrow = store.get_escrow(req.service_hash)
        if caller not in (escrow.sender, escrow.receiver):
            raise HTTPException(
                status_code=403,
                detail="Only escrow sender or receiver may dispute",
            )
    except KeyError:
        raise HTTPException(status_code=404, detail="Escrow not found")

    deploy_hash = ""

    if not cfg.sandbox and casper is not None:
        try:
            deploy_hash = await casper.dispute(req.service_hash)
        except Exception as exc:
            logger.error("Casper dispute failed: %s", exc)
            raise HTTPException(
                status_code=502,
                detail="On-chain dispute transaction failed; local state unchanged",
            )

    try:
        record = store.dispute_escrow(req.service_hash)
        pgdb.update_escrow_status(req.service_hash, "disputed", deploy_hash)
        pgdb.bump_reputation(record.sender, disputed=1)
        _broadcast_event({"type": "escrow_disputed", "service_hash": req.service_hash, "ts": int(time.time())})
        return record
    except KeyError:
        raise HTTPException(status_code=404, detail="Escrow not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ---------------------------------------------------------------------------
# POST /arbitration/analyze — LLM-powered dispute analysis
# ---------------------------------------------------------------------------

class ArbitrateRequest(BaseModel):
    dispute_id: str
    sender_evidence: list[DisputeEvidence]
    receiver_evidence: list[DisputeEvidence]
    escrow_amount: int


@app.post("/arbitration/analyze", response_model=ArbitrationRecommendation, tags=["arbitration"])
async def arbitrate_dispute(req: ArbitrateRequest):
    """Run LLM arbitration on dispute evidence.

    Tries Groq → NVIDIA NIM → heuristic fallback.
    Returns recommendation: favor_sender | favor_receiver | split | escalate.
    """
    if req.escrow_amount < 0:
        raise HTTPException(status_code=400, detail="escrow_amount must be non-negative")
    try:
        result = await _arbitration_agent.analyze_dispute(
            dispute_id=req.dispute_id,
            sender_evidence=req.sender_evidence,
            receiver_evidence=req.receiver_evidence,
            escrow_amount=req.escrow_amount,
        )
        logger.info(
            "Arbitration complete: dispute=%s provider=%s rec=%s conf=%.2f",
            req.dispute_id[:16], result.provider, result.recommendation, result.confidence,
        )
        return result
    except Exception as exc:
        logger.exception("Arbitration error: %s", exc)
        raise HTTPException(status_code=500, detail=f"Arbitration failed: {exc}")


@app.get("/escrow/{service_hash}", response_model=EscrowRecord)
async def get_escrow(
    service_hash: str,
    cfg: Config = Depends(get_config),
    store: SandboxStore = Depends(get_sandbox),
    casper: CasperClient | None = Depends(get_casper),
):
    record = store.get_escrow(service_hash)
    if record is not None:
        return record
    if casper:
        record = await casper.get_escrow(service_hash)
        if record:
            return record
    raise HTTPException(status_code=404, detail="Escrow not found")


@app.get("/reputation/{agent}", response_model=ReputationRecord)
async def get_reputation(
    agent: str,
    cfg: Config = Depends(get_config),
    store: SandboxStore = Depends(get_sandbox),
    casper: CasperClient | None = Depends(get_casper),
):
    # Try DB first
    db_rep = pgdb.get_reputation_db(agent)
    if db_rep:
        return ReputationRecord(agent=agent, **db_rep)
    if cfg.sandbox:
        return store.get_reputation(agent)
    if casper:
        try:
            return await asyncio.wait_for(casper.get_reputation(agent), timeout=5.0)
        except Exception:
            logger.warning("On-chain reputation lookup failed for %s, using default", agent)
    return ReputationRecord(agent=agent)


@app.get("/agents")
async def list_agents(store: SandboxStore = Depends(get_sandbox)):
    """List known agents with their reputation scores."""
    seen: dict[str, dict[str, Any]] = {}
    for rec in store._escrows.values():
        for role in ("sender", "receiver"):
            name = rec[role]
            if name not in seen:
                rep = store.get_reputation(name)
                seen[name] = {
                    "agent": name,
                    "score": rep.score,
                    "completed": rep.completed,
                    "disputed": rep.disputed,
                    "role": role,
                }
    agents = sorted(seen.values(), key=lambda x: x["score"], reverse=True)
    return {"agents": agents, "total": len(agents)}


@app.get("/escrow/{service_hash}/history")
async def escrow_history(service_hash: str, store: SandboxStore = Depends(get_sandbox)):
    """Transaction timeline for a specific escrow."""
    rec = store._escrows.get(service_hash)
    if rec is None:
        raise HTTPException(status_code=404, detail="Escrow not found")

    events = [
        {"action": "created", "ts": rec["created_at"], "by": rec["sender"], "amount": rec["amount"]},
    ]
    status = rec["status"]
    if status == "released":
        events.append({"action": "released", "ts": rec["created_at"] + 60, "by": rec["sender"]})
    elif status == "disputed":
        events.append({"action": "disputed", "ts": rec["created_at"] + 30, "by": "system"})
    elif status in ("refunded", "expired"):
        events.append({"action": status, "ts": rec["created_at"] + rec["ttl"], "by": "system"})

    return {"service_hash": service_hash, "events": events}


@app.get("/estimate")
async def fee_estimate(amount: int, cfg: Config = Depends(get_config)):
    """Calculate insurance fee for a given amount."""
    net, fee = _apply_insurance_fee(amount, cfg.insurance_fee_bps)
    return {
        "gross_amount": amount,
        "net_amount": net,
        "insurance_fee": fee,
        "fee_bps": cfg.insurance_fee_bps,
        "fee_pct": f"{cfg.insurance_fee_bps / 100:.1f}%",
    }


@app.get("/events")
async def event_stream():
    """Server-Sent Events stream for real-time escrow updates."""
    queue: asyncio.Queue = asyncio.Queue(maxsize=50)
    _event_subscribers.append(queue)

    async def generate():
        try:
            # Send heartbeat first
            yield f"data: {json.dumps({'type': 'connected', 'ts': int(time.time())})}\n\n"
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield f"data: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    # Send keepalive
                    yield f": keepalive {int(time.time())}\n\n"
        finally:
            _event_subscribers.remove(queue)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/compute-hash")
async def compute_hash(sender: str, receiver: str, amount: int, nonce: str):
    """Utility endpoint to compute a service hash."""
    return {"service_hash": compute_service_hash(sender, receiver, amount, nonce)}


def _extract_sender(request: Request) -> str:
    """Extract sender identity from x402 header or sandbox mode."""
    if hasattr(request.state, "payment") and request.state.payment:
        return request.state.payment.sender
    payment_header = request.headers.get("X-Payment")
    if payment_header:
        parsed = parse_x402_header(payment_header)
        if parsed:
            return parsed.sender
    cfg = get_config()
    if cfg.sandbox:
        return request.query_params.get("sender", "sandbox-agent-001")
    raise HTTPException(status_code=401, detail="sender identity required")
