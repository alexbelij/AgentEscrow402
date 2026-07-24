"""AgentEscrow402 API server."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from server import arbiter_crypto, strict
from server import db as pgdb
from server.admin_api import router as admin_router
from server.agent_identity import router as identity_router
from server.ai_arbitration import ArbitrationAgent, ArbitrationRecommendation, DisputeEvidence
from server.casper_client import CasperClient
from server.config import Config
from server.escrow_fsm import InvalidTransitionError
from server.event_monitor import EventMonitor
from server.identity_registry_api import _registry as _id_registry
from server.identity_registry_api import router as identity_registry_router
from server.insurance import router as insurance_router
from server.macaroon_api import router as macaroon_router
from server.middleware import (
    _build_signing_payload,
    _check_replay,
    _verify_signature,
    compute_service_hash,
    parse_x402_header,
)
from server.models import (
    BatchEscrowRequest,
    BatchEscrowResponse,
    DisputeRequest,
    EscrowRecord,
    EscrowRequest,
    HealthResponse,
    RefundRequest,
    ReleaseRequest,
    ReputationRecord,
    ResolveRequest,
)
from server.multi_asset import router as multi_asset_router
from server.risk_api import router as risk_router
from server.sandbox import SandboxStore
from server.telegram_api import (
    fanout_event as _telegram_fanout,
)
from server.telegram_api import (
    init_bridge as _telegram_init_bridge,
)
from server.telegram_api import (
    router as telegram_router,
)
from server.telegram_api import (
    shutdown_bridge as _telegram_shutdown,
)
from server.vrf_election import router as vrf_router

try:
    from server.mlkem_crypto import encrypt_metadata, generate_keypair

    _MLKEM_AVAILABLE = True
except Exception:
    _MLKEM_AVAILABLE = False

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
_started_at = time.time()


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
    _broadcast_event({"type": "dispute_opened", "service_hash": sh, "ts": int(time.time())})


def _raise_fsm_or_generic(exc: ValueError) -> None:
    """AE-14: turn a chained :class:`InvalidTransitionError` into HTTP 409.

    ``server.sandbox`` and other stores wrap the FSM error in a
    ``ValueError`` for backwards-compatible tests, but preserve the
    original as ``__cause__``. When we see one, surface the structured
    payload as a 409 so clients can drive UX off ``allowed_actions``.
    Anything else stays a 400 with plain-string detail.
    """
    cause = exc.__cause__
    if isinstance(cause, InvalidTransitionError):
        raise HTTPException(status_code=409, detail=cause.to_payload())
    raise HTTPException(status_code=400, detail=str(exc))


def _broadcast_event(event: dict[str, Any]) -> None:
    """Push event to all SSE subscribers."""
    for q in _event_subscribers:
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            pass
    # Optional fan-out to Telegram subscribers. The helper is a no-op when
    # the Telegram bridge is not configured (default). Errors inside the
    # helper are logged, never raised, so the SSE stream is unaffected.
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # Called from sync context — skip; tests exercise the fan-out
        # directly via ``await telegram_api.fanout_event``.
        return
    loop.create_task(_telegram_fanout(event))


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(application: FastAPI):
    global _casper, _monitor, _monitor_task
    cfg = get_config()

    # Fail-loud precondition check. Under AE402_STRICT=1, refuse to start
    # if any of the three well-known preconditions are missing (empty
    # CASPER_NODE_URL, empty ESCROW_CONTRACT_HASH, or SANDBOX=true). This
    # is the first thing that runs so an operator gets an immediate crash
    # -- not a running-but-broken app -- when strict-mode is misconfigured.
    # See server/strict.py.
    from server.strict import ensure_strict

    ensure_strict(cfg)

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

    # Initialise the Telegram bridge once the app is up. When
    # TELEGRAM_BOT_TOKEN is not set the call returns None and every
    # ``/telegram/*`` mutation endpoint fails-closed with 503.
    _telegram_init_bridge()

    yield

    # Shutdown
    if _monitor:
        await _monitor.stop()
    if _monitor_task and not _monitor_task.done():
        _monitor_task.cancel()
    if _casper:
        await _casper.close()
    await _telegram_shutdown()


async def _sync_identity_registry(account_hash: str, completed: int = 0, disputed: int = 0) -> None:
    """Bridge escrow reputation events into the DID Identity Registry.

    If the agent has a registered identity (did:casper:…), update its
    reputation score there too.  Silently no-ops when the account has no
    registered DID — this is expected for most demo escrows.
    """
    try:
        identity = await _id_registry.get_by_account(account_hash)
        if identity:
            await _id_registry.update_reputation(identity.did, completed=completed, disputed=disputed)
    except Exception:
        pass  # non-critical — DB reputation is the canonical store


app = FastAPI(
    title="AgentEscrow402",
    version="0.3.0",
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
# Strict-mode exception handler
#
# Any request-time code path that hits `strict.guard(cfg, path, reason)`
# under AE402_STRICT=1 raises StrictModeError. Render it as a 503 with a
# structured body so UI / CLI callers can distinguish it from a generic
# 500. See server/strict.py.
# ---------------------------------------------------------------------------
from server.strict import StrictModeError as _StrictModeError  # noqa: E402


@app.exception_handler(_StrictModeError)
async def _strict_mode_exception_handler(request: Request, exc: _StrictModeError):
    return JSONResponse(
        status_code=503,
        content={
            "error": "strict_mode_violation",
            "path": exc.path,
            "reason": exc.reason,
            "detail": (
                "AE402_STRICT=1 is set and a silent-fallback code path was "
                "about to trigger. The request has been rejected to avoid "
                "returning a synthesised / mock response. Fix the underlying "
                "configuration (see reason) or unset AE402_STRICT."
            ),
        },
    )


# ---------------------------------------------------------------------------
# Rate limiting (60 req/min per IP)
# ---------------------------------------------------------------------------
_rate_limits: dict[str, dict] = {}


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    """Attach a unique request ID to every response for tracing."""
    import uuid

    rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
    response = await call_next(request)
    response.headers["X-Request-ID"] = rid
    return response


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
            return JSONResponse(status_code=429, content={"error": "rate_limited", "detail": "Too many requests"})
    # Bound the in-memory limiter so attacker-controlled IP churn cannot grow it forever.
    if len(_rate_limits) > 5000:
        cutoff = now - 120
        for key in [k for k, v in _rate_limits.items() if v.get("reset", 0) < cutoff]:
            _rate_limits.pop(key, None)
    return await call_next(request)


# Register sub-routers
app.include_router(multi_asset_router)
app.include_router(insurance_router)
app.include_router(vrf_router)
app.include_router(identity_router)
app.include_router(risk_router)
app.include_router(identity_registry_router)
app.include_router(macaroon_router)
app.include_router(admin_router)
app.include_router(telegram_router)


# ---------------------------------------------------------------------------
# Insurance fee helper
# ---------------------------------------------------------------------------


def _apply_insurance_fee(amount: int, fee_bps: int) -> tuple[int, int]:
    """Split amount into net + insurance fee.

    Amounts are integer atomic units (e.g. motes, where 1 CSPR = 1e9 motes).
    Uses pure integer floor division so `net + fee == amount` always holds
    exactly, with no floating-point precision loss for large amounts and no
    rounding drift. Fees below one atomic unit floor to 0.
    """
    fee = (amount * fee_bps) // 10_000
    return amount - fee, fee


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/", include_in_schema=False)
@app.head("/", include_in_schema=False)
async def root():
    """Render health-check probe hits / with HEAD — redirect to /health."""
    from starlette.responses import RedirectResponse

    return RedirectResponse(url="/health", status_code=307)


@app.get("/health", response_model=HealthResponse)
async def health(cfg: Config = Depends(get_config)):
    contract_hash = cfg.contract_hash or ""
    connected = pgdb.is_connected()
    return HealthResponse(
        sandbox=cfg.sandbox,
        chain=cfg.casper_chain_name,
        contract_hash=contract_hash,
        db="connected" if connected else "disconnected",
        uptime=int(time.time() - _started_at),
        mode="sandbox" if cfg.sandbox else "live",
        strict_mode=cfg.strict_mode_capabilities(),
    )


@app.get("/contracts")
async def contracts(cfg: Config = Depends(get_config)):
    """Backend-configured deployed contract addresses.

    Previously the 3 non-escrow contract hashes were hardcoded directly in
    the frontend (frontend/src/components/console/Contracts.tsx) with no
    env/config wiring — a redeploy of any of them required a frontend code
    change. All 4 are now sourced from Config (env-overridable) and served
    here so the frontend can fetch them at runtime instead.
    """
    return {
        "contracts": [
            {
                "name": "Core Escrow",
                "hash": cfg.contract_hash,
                "role": (
                    "Full escrow lifecycle: create → release / refund / dispute → 3-of-5 "
                    "arbiter resolve, with release-cap guard and emergency freeze."
                ),
                "category": "core",
            },
            {
                "name": "Escrow Manager",
                "hash": cfg.manager_contract_hash,
                "role": "Batch escrow orchestration: create, release and cancel multiple escrows in a single deploy.",
                "category": "core",
            },
            {
                "name": "Insurance Pool",
                "hash": cfg.insurance_contract_hash,
                "role": "Collects insurance premiums on escrow creation, manages claim payouts for disputed escrows.",
                "category": "core",
            },
            {
                "name": "VRF Arbiter",
                "hash": cfg.vrf_contract_hash,
                "role": (
                    "On-chain verifiable random arbiter election with staked purses; "
                    "API falls back to local CSPRNG when unavailable."
                ),
                "category": "core",
            },
            {
                "name": "Agent Identity Registry",
                "hash": cfg.agent_identity_contract_hash,
                "role": (
                    "DID-style agent registration with on-chain staking, reputation tracking and capability delegation."
                ),
                "category": "identity",
            },
            {
                "name": "MultiAssetEscrow",
                "hash": cfg.multi_asset_escrow_contract_hash,
                "role": (
                    "Contract-custody escrow for CEP-18 fungible tokens: approve → "
                    "create → release/refund/dispute/resolve, all on-chain."
                ),
                "category": "multi-asset",
            },
            {
                "name": "AEMAT (test token)",
                "hash": cfg.test_token_contract_hash,
                "role": (
                    "CEP-18 fungible test token for multi-asset escrow demos "
                    "(custody-compatible, uses get_immediate_caller)."
                ),
                "category": "token",
            },
            {
                "name": "AETUSD (test token)",
                "hash": cfg.cep18_aetusd_contract_hash,
                "role": (
                    "CEP-18 fungible test token used to prefill the contract-hash field "
                    "for CEP-18 escrow/permit demos."
                ),
                "category": "token",
            },
            {
                "name": "AETNFT (test NFT)",
                "hash": cfg.aetnft_contract_hash,
                "role": (
                    "CEP-78 enhanced NFT collection for multi-asset escrow NFT demos "
                    "(Transferable, Public minting, Ordinal IDs)."
                ),
                "category": "token",
            },
        ]
    }


@app.get("/stats")
async def stats(store: SandboxStore = Depends(get_sandbox)):
    """Aggregate statistics for the console.

    Neon is optional on the hosted demo. When it is disconnected or empty,
    the console must still reflect the in-memory testnet/demo escrows loaded at
    startup and created during the current process.
    """
    cfg = get_config()
    db_stats = pgdb.get_stats()
    records = pgdb.load_escrows()
    data_source = "neon" if records else "hosted_demo_fallback"

    if not records:
        records = list(store._escrows.values())

    if records:
        total = len(records)
        pending = sum(1 for r in records if str(r.get("status")) == "pending")
        released = sum(1 for r in records if str(r.get("status")) == "released")
        disputed = sum(1 for r in records if str(r.get("status")) == "disputed")
        total_volume = sum(int(r.get("amount", 0) or 0) for r in records)
        active_agents = len(
            {r.get("sender") for r in records if r.get("sender")}
            | {r.get("receiver") for r in records if r.get("receiver")}
        )
        total_transactions = (
            total + released + disputed + sum(1 for r in records if str(r.get("status")) in {"refunded", "expired"})
        )
        s = {
            "total": total,
            "pending": pending,
            "released": released,
            "disputed": disputed,
            "volume": total_volume,
            "active_agents": active_agents,
            "total_transactions": total_transactions,
            "db": db_stats.get("db", "disconnected"),
            "data_source": data_source,
        }
    else:
        s = dict(db_stats)
        s.setdefault("volume", 0)
        s.setdefault("pending", 0)
        s.setdefault("released", 0)
        s.setdefault("disputed", 0)
        s.setdefault("active_agents", 0)
        s.setdefault("total_transactions", s.get("total", 0))
        s["data_source"] = "neon" if s.get("db") == "connected" else "unavailable"

    s["total_escrows"] = s.get("total", 0)
    s["pending_escrows"] = s.get("pending", 0)
    s["disputed_escrows"] = s.get("disputed", 0)
    s["released_escrows"] = s.get("released", 0)
    s["total_volume"] = s.get("volume", 0)
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


@app.get("/wasm/escrow_funder")
async def wasm_escrow_funder():
    """Serve the session-wasm module used to fund an escrow's on-chain
    deposit directly from a caller's own main purse (see
    `sendCreateEscrowTx` in frontend/src/lib/liveTx.ts). Session code
    executed under the signer's own account context is the only way the
    Casper execution engine grants legitimate elevated purse access — a
    plain stored-contract call cannot (see wallet_frontend_gotchas skill
    notes on `Mint error: 4` / InvalidAccessRights). This is the exact same
    compiled artifact the backend's own hosted-key flow already runs
    (`server/casper_tx/escrow_funder.wasm`); serving it lets the connected
    wallet sign+submit it itself instead.
    """
    wasm_path = Path(__file__).resolve().parent / "casper_tx" / "escrow_funder.wasm"
    if not wasm_path.exists():
        raise HTTPException(status_code=500, detail="escrow_funder.wasm not found on server")
    return StreamingResponse(
        iter([wasm_path.read_bytes()]),
        media_type="application/wasm",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@app.post("/escrow", response_model=EscrowRecord)
async def create_escrow(
    req: EscrowRequest,
    request: Request,
    cfg: Config = Depends(get_config),
    store: SandboxStore = Depends(get_sandbox),
    casper: CasperClient | None = Depends(get_casper),
):
    if req.wallet_tx_hash:
        if not req.sender_public_key_hex:
            raise HTTPException(
                status_code=422,
                detail="sender_public_key_hex is required when wallet_tx_hash is set",
            )
        sender = req.sender_public_key_hex
    else:
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
            if not pgdb.save_escrow(record):
                strict.guard(
                    cfg,
                    "app.create_escrow.sandbox_db_write_failed",
                    "pgdb.save_escrow returned False (DB disconnected), escrow only persisted in memory",
                )
            if fee > 0:
                pgdb.record_insurance_fee(req.service_hash, fee)
            # ML-KEM: encrypt service metadata for post-quantum confidentiality
            result_dict = record.model_dump()
            if _MLKEM_AVAILABLE:
                try:
                    encap_key, decap_key = generate_keypair()
                    plaintext = f"service_hash={req.service_hash}&sender={sender}&receiver={req.receiver}"
                    enc_meta = encrypt_metadata(plaintext, encap_key)
                    # NOTE: decap_key is the private decryption key — never
                    # return it in the API response.  In production the sender
                    # would derive it via their own KEM decapsulation.
                    result_dict["mlkem_ciphertext"] = enc_meta.kem_ciphertext_b64
                    result_dict["mlkem_algorithm"] = "ML-KEM-768"
                    logger.info("ML-KEM encryption applied to escrow %s", req.service_hash[:16])
                except Exception as mlkem_exc:
                    logger.warning("ML-KEM encryption failed (non-fatal): %s", mlkem_exc)
            return result_dict
        except ValueError as exc:
            logger.warning("create_escrow validation failed: %s", exc)
            raise HTTPException(status_code=409, detail="Escrow creation conflict")

    # Live mode — deploy to Casper
    if req.wallet_tx_hash:
        confirmed, revert_reason = await casper.confirm_wallet_created_escrow(
            req.service_hash, deploy_hash=req.wallet_tx_hash
        )
        if not confirmed:
            detail = (
                f"On-chain create-escrow transaction reverted: {revert_reason}"
                if revert_reason
                else "Wallet transaction not yet confirmed on-chain; local state unchanged"
            )
            raise HTTPException(status_code=502, detail=detail)
        deploy_hash = req.wallet_tx_hash
    else:
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
    if not pgdb.save_escrow(record):
        strict.guard(
            cfg,
            "app.create_escrow.live_db_write_failed",
            "pgdb.save_escrow returned False (DB disconnected) after a real on-chain write; "
            "the escrow exists on testnet but would not be recorded in Postgres",
        )
    if fee > 0:
        pgdb.record_insurance_fee(req.service_hash, fee)
    _broadcast_event(
        {"type": "escrow_created", "service_hash": req.service_hash, "deploy_hash": deploy_hash, "ts": now}
    )
    # ML-KEM: post-quantum encrypt escrow metadata
    result_dict = record.model_dump()
    if _MLKEM_AVAILABLE:
        try:
            encap_key, decap_key = generate_keypair()
            plaintext = f"service_hash={req.service_hash}&sender={sender}&receiver={req.receiver}"
            enc_meta = encrypt_metadata(plaintext, encap_key)
            result_dict["mlkem_ciphertext"] = enc_meta.kem_ciphertext_b64
            result_dict["mlkem_algorithm"] = "ML-KEM-768"
            logger.info("ML-KEM encryption applied to live escrow %s", req.service_hash[:16])
        except Exception as mlkem_exc:
            logger.warning("ML-KEM encryption failed (non-fatal): %s", mlkem_exc)
    return result_dict


@app.post("/escrows/batch", response_model=BatchEscrowResponse)
async def create_escrow_batch(
    req: BatchEscrowRequest,
    request: Request,
    cfg: Config = Depends(get_config),
    store: SandboxStore = Depends(get_sandbox),
    casper: CasperClient | None = Depends(get_casper),
):
    """Create up to 50 escrows in ONE on-chain deploy via
    escrow-manager.create_batch() (contracts/escrow-manager/src/main.rs).

    Unlike /escrow (one escrow per deploy, hosted-key path funded from the
    backend's own purse), this batches N escrow creations behind a single
    session-wasm transaction (contracts/batch-funder), trading per-escrow
    dispute/insurance/ML-KEM features for deploy-count efficiency — intended
    for bulk/demo provisioning, not the interactive per-agent flow.
    """
    sender = _extract_sender(request)
    now = int(time.time())

    service_hashes = [item.service_hash for item in req.escrows]
    if len(set(service_hashes)) != len(service_hashes):
        raise HTTPException(status_code=422, detail="Duplicate service_hash in batch request")
    for sh in service_hashes:
        if sh in store._escrows:
            raise HTTPException(status_code=409, detail=f"Escrow {sh} already exists")

    if cfg.sandbox or casper is None:
        records = [
            store.create_escrow(
                sender=sender,
                receiver=item.receiver,
                amount=item.amount,
                service_hash=item.service_hash,
                ttl=item.ttl,
            )
            for item in req.escrows
        ]
        for rec in records:
            if not pgdb.save_escrow(rec):
                strict.guard(
                    cfg,
                    "app.create_escrow_batch.sandbox_db_write_failed",
                    "pgdb.save_escrow returned False (DB disconnected), escrow only persisted in memory",
                )
        return BatchEscrowResponse(deploy_hash=None, created=len(records), records=records)

    # Live mode — one real deploy covering the whole batch.
    deploy_hash = await casper.create_batch(
        receivers=[item.receiver for item in req.escrows],
        amounts=[item.amount for item in req.escrows],
        service_hashes=service_hashes,
        ttls=[item.ttl for item in req.escrows],
    )

    records: list[EscrowRecord] = []
    for item in req.escrows:
        record = EscrowRecord(
            sender=sender,
            receiver=item.receiver,
            amount=item.amount,
            service_hash=item.service_hash,
            status="pending",
            created_at=now,
            ttl=item.ttl,
            deploy_hash=deploy_hash,
        )
        store._escrows[item.service_hash] = {
            "sender": sender,
            "receiver": item.receiver,
            "amount": item.amount,
            "service_hash": item.service_hash,
            "status": "pending",
            "created_at": now,
            "ttl": item.ttl,
            "deploy_hash": deploy_hash,
        }
        if not pgdb.save_escrow(record):
            strict.guard(
                cfg,
                "app.create_escrow_batch.live_db_write_failed",
                "pgdb.save_escrow returned False (DB disconnected) after a real on-chain write; "
                "the escrow exists on testnet but would not be recorded in Postgres",
            )
        records.append(record)

    _broadcast_event({"type": "escrow_batch_created", "count": len(records), "deploy_hash": deploy_hash, "ts": now})
    return BatchEscrowResponse(deploy_hash=deploy_hash, created=len(records), records=records)


# ── Batch lifecycle (release / cancel) ─────────────────────────────────
# Python-side cap/quorum guard fills the gap the on-chain escrow-manager
# lacks: every escrow in the batch is individually validated before the
# single deploy is submitted. If ANY escrow fails the check, the entire
# request is rejected (atomic all-or-nothing).


class BatchLifecycleRequest(BaseModel):
    """Request to batch-release or batch-cancel escrows."""

    service_hashes: list[str]
    # Required only for release when any escrow exceeds release_cap
    arbiter_pubkeys: list[str] = []
    arbiter_signatures: list[str] = []


class BatchLifecycleResponse(BaseModel):
    deploy_hash: str | None
    processed: int


@app.post("/escrows/batch-release", response_model=BatchLifecycleResponse)
async def batch_release_escrows(
    req: BatchLifecycleRequest,
    cfg: Config = Depends(get_config),
    store: SandboxStore = Depends(get_sandbox),
    casper: CasperClient | None = Depends(get_casper),
):
    """Release multiple batch-created escrows in one deploy.

    Server-side enforcement: every escrow is checked against the release cap.
    If any escrow exceeds the cap, a valid arbiter quorum (via
    arbiter_pubkeys/arbiter_signatures) is required for the ENTIRE batch —
    same threshold as single-escrow release.
    """
    if not req.service_hashes:
        raise HTTPException(status_code=422, detail="service_hashes must be non-empty")
    if len(req.service_hashes) > 50:
        raise HTTPException(status_code=422, detail="batch size exceeds MAX_BATCH_SIZE (50)")
    if len(req.arbiter_pubkeys) != len(req.arbiter_signatures):
        raise HTTPException(
            status_code=422,
            detail="arbiter_pubkeys and arbiter_signatures must have the same length",
        )

    # Pre-validate every escrow: must exist, must be pending, cap/quorum check
    needs_quorum = False
    for sh in req.service_hashes:
        existing = store.get_escrow(sh)
        if existing is None:
            raise HTTPException(status_code=404, detail=f"Escrow {sh[:16]}… not found")
        if existing.status != "pending":
            raise HTTPException(status_code=422, detail=f"Escrow {sh[:16]}… is {existing.status}, not pending")
        if existing.amount > cfg.release_cap_motes:
            needs_quorum = True

    if needs_quorum and cfg.arbiter_pubkeys:
        # Validate arbiter quorum against ALL above-cap escrows
        for sh in req.service_hashes:
            existing = store.get_escrow(sh)
            if existing and existing.amount > cfg.release_cap_motes:
                valid_votes = arbiter_crypto.count_valid_cap_approval_votes(
                    req.arbiter_pubkeys,
                    req.arbiter_signatures,
                    cfg.arbiter_pubkeys,
                    "release",
                    sh,
                )
                if valid_votes < cfg.arbiter_threshold:
                    raise HTTPException(
                        status_code=422,
                        detail=(
                            f"Escrow {sh[:16]}… exceeds release_cap "
                            f"({cfg.release_cap_motes} motes); only {valid_votes} "
                            f"valid arbiter signature(s), need >= {cfg.arbiter_threshold}"
                        ),
                    )

    deploy_hash = ""
    if not cfg.sandbox and casper is not None:
        try:
            deploy_hash = await casper.batch_release(req.service_hashes)
        except Exception as exc:
            logger.error("Casper batch_release failed: %s", exc)
            raise HTTPException(
                status_code=502,
                detail="On-chain batch_release failed; local state unchanged",
            )

    # Update local state — release_escrow needs a caller (sender); for the
    # batch path the backend's own deployer key IS the sender, so we pass
    # the escrow's sender from the record to satisfy the permission check.
    for sh in req.service_hashes:
        try:
            existing = store.get_escrow(sh)
            if existing:
                store.release_escrow(sh, existing.sender, deploy_hash)
                pgdb.update_escrow_status(sh, "released", deploy_hash)
                pgdb.bump_reputation(existing.receiver, completed=1)
                await _sync_identity_registry(existing.receiver, completed=1)
        except Exception as exc:
            logger.warning("batch_release local update for %s failed: %s", sh[:16], exc)

    _broadcast_event(
        {
            "type": "escrow_batch_released",
            "count": len(req.service_hashes),
            "deploy_hash": deploy_hash,
            "ts": int(time.time()),
        }
    )
    return BatchLifecycleResponse(deploy_hash=deploy_hash or None, processed=len(req.service_hashes))


@app.post("/escrows/batch-cancel", response_model=BatchLifecycleResponse)
async def batch_cancel_escrows(
    req: BatchLifecycleRequest,
    cfg: Config = Depends(get_config),
    store: SandboxStore = Depends(get_sandbox),
    casper: CasperClient | None = Depends(get_casper),
):
    """Cancel multiple batch-created escrows in one deploy.

    Full refund to sender. Only pending escrows can be cancelled.
    """
    if not req.service_hashes:
        raise HTTPException(status_code=422, detail="service_hashes must be non-empty")
    if len(req.service_hashes) > 50:
        raise HTTPException(status_code=422, detail="batch size exceeds MAX_BATCH_SIZE (50)")

    for sh in req.service_hashes:
        existing = store.get_escrow(sh)
        if existing is None:
            raise HTTPException(status_code=404, detail=f"Escrow {sh[:16]}… not found")
        if existing.status != "pending":
            raise HTTPException(status_code=422, detail=f"Escrow {sh[:16]}… is {existing.status}, not pending")

    deploy_hash = ""
    if not cfg.sandbox and casper is not None:
        try:
            deploy_hash = await casper.batch_cancel(req.service_hashes)
        except Exception as exc:
            logger.error("Casper batch_cancel failed: %s", exc)
            raise HTTPException(
                status_code=502,
                detail="On-chain batch_cancel failed; local state unchanged",
            )

    for sh in req.service_hashes:
        try:
            existing = store.get_escrow(sh)
            if existing:
                store.refund_escrow(sh, existing.sender, deploy_hash)
                pgdb.update_escrow_status(sh, "cancelled", deploy_hash)
        except Exception as exc:
            logger.warning("batch_cancel local update for %s failed: %s", sh[:16], exc)

    _broadcast_event(
        {
            "type": "escrow_batch_cancelled",
            "count": len(req.service_hashes),
            "deploy_hash": deploy_hash,
            "ts": int(time.time()),
        }
    )
    return BatchLifecycleResponse(deploy_hash=deploy_hash or None, processed=len(req.service_hashes))


@app.post("/release", response_model=EscrowRecord)
async def release_escrow(
    req: ReleaseRequest,
    request: Request,
    cfg: Config = Depends(get_config),
    store: SandboxStore = Depends(get_sandbox),
    casper: CasperClient | None = Depends(get_casper),
):
    """Release escrowed funds to the receiver.

    A1 hardening: if this escrow's amount exceeds the contract's
    `release_cap`, `arbiter_pubkeys`/`arbiter_signatures` must carry a
    quorum of registered-arbiter signatures over
    "release:{service_hash}:cap_approval" (see arbiter_crypto.
    build_cap_approval_message) — same fast-fail-then-on-chain-enforced
    pattern as /resolve. Below cap, empty lists are fine.
    """
    existing = store.get_escrow(req.service_hash)
    if existing is None:
        raise HTTPException(status_code=404, detail="Escrow not found")

    if len(req.arbiter_pubkeys) != len(req.arbiter_signatures):
        raise HTTPException(
            status_code=422,
            detail="arbiter_pubkeys and arbiter_signatures must have the same length",
        )

    if existing.amount > cfg.release_cap_motes and cfg.arbiter_pubkeys:
        valid_votes = arbiter_crypto.count_valid_cap_approval_votes(
            req.arbiter_pubkeys,
            req.arbiter_signatures,
            cfg.arbiter_pubkeys,
            "release",
            req.service_hash,
        )
        if valid_votes < cfg.arbiter_threshold:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Escrow amount exceeds release_cap ({cfg.release_cap_motes} motes); "
                    f"only {valid_votes} valid arbiter cap-approval signature(s), "
                    f"need >= {cfg.arbiter_threshold}"
                ),
            )

    deploy_hash = ""

    if not cfg.sandbox and casper is not None:
        if req.wallet_tx_hash:
            confirmed, revert_reason = await casper.confirm_wallet_lifecycle_tx(
                req.service_hash, "released", deploy_hash=req.wallet_tx_hash
            )
            if not confirmed:
                detail = (
                    f"On-chain release transaction reverted: {revert_reason}"
                    if revert_reason
                    else "Wallet transaction not yet confirmed on-chain as 'released'; local state unchanged"
                )
                raise HTTPException(status_code=502, detail=detail)
            deploy_hash = req.wallet_tx_hash
        else:
            try:
                deploy_hash = await casper.release(req.service_hash, req.arbiter_pubkeys, req.arbiter_signatures)
            except Exception as exc:
                logger.error("Casper release failed: %s", exc)
                raise HTTPException(
                    status_code=502,
                    detail="On-chain release transaction failed; local state unchanged",
                )

    caller = _extract_release_refund_caller(request, req.wallet_tx_hash, existing.sender)

    try:
        record = store.release_escrow(req.service_hash, caller, deploy_hash)
        pgdb.update_escrow_status(req.service_hash, "released", deploy_hash)
        pgdb.bump_reputation(record.receiver, completed=1)
        await _sync_identity_registry(record.receiver, completed=1)
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
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        _raise_fsm_or_generic(exc)


@app.post("/refund", response_model=EscrowRecord)
async def refund_escrow(
    req: RefundRequest,
    request: Request,
    cfg: Config = Depends(get_config),
    store: SandboxStore = Depends(get_sandbox),
    casper: CasperClient | None = Depends(get_casper),
):
    deploy_hash = ""

    if not cfg.sandbox and casper is not None:
        if req.wallet_tx_hash:
            # A wallet-submitted refund lands on-chain as "refunded" (before
            # TTL) or "expired" (after TTL) depending on chain time at the
            # moment the contract call executes -- either is a genuine
            # success from the caller's perspective.
            confirmed, revert_reason = await casper.confirm_wallet_lifecycle_tx(
                req.service_hash, ("refunded", "expired"), deploy_hash=req.wallet_tx_hash
            )
            if not confirmed:
                detail = (
                    f"On-chain refund transaction reverted: {revert_reason}"
                    if revert_reason
                    else "Wallet transaction not yet confirmed on-chain as 'refunded'; local state unchanged"
                )
                raise HTTPException(status_code=502, detail=detail)
            deploy_hash = req.wallet_tx_hash
        else:
            try:
                deploy_hash = await casper.refund(req.service_hash)
            except Exception as exc:
                logger.error("Casper refund failed: %s", exc)
                raise HTTPException(
                    status_code=502,
                    detail="On-chain refund transaction failed; local state unchanged",
                )

    existing = store.get_escrow(req.service_hash)
    if existing is None:
        raise HTTPException(status_code=404, detail="Escrow not found")
    caller = _extract_release_refund_caller(request, req.wallet_tx_hash, existing.sender)

    try:
        record = store.refund_escrow(req.service_hash, caller, deploy_hash)
        pgdb.update_escrow_status(req.service_hash, record.status, deploy_hash)
        _broadcast_event({"type": "escrow_refunded", "service_hash": req.service_hash, "ts": int(time.time())})
        return record
    except KeyError:
        raise HTTPException(status_code=404, detail="Escrow not found")
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        _raise_fsm_or_generic(exc)


@app.post("/dispute", response_model=EscrowRecord)
async def dispute_escrow(
    req: DisputeRequest,
    request: Request,
    cfg: Config = Depends(get_config),
    store: SandboxStore = Depends(get_sandbox),
    casper: CasperClient | None = Depends(get_casper),
):
    escrow = store.get_escrow(req.service_hash)
    if escrow is None:
        raise HTTPException(status_code=404, detail="Escrow not found")

    deploy_hash = ""

    if not cfg.sandbox and casper is not None:
        if req.wallet_tx_hash:
            # Authorization for the live-wallet path comes from on-chain
            # confirmation below: the contract itself only allows the true
            # sender or receiver to call `dispute`, so a confirmed status
            # change is strictly stronger proof than an x402 header check.
            confirmed, revert_reason = await casper.confirm_wallet_lifecycle_tx(
                req.service_hash, "disputed", deploy_hash=req.wallet_tx_hash
            )
            if not confirmed:
                detail = (
                    f"On-chain dispute transaction reverted: {revert_reason}"
                    if revert_reason
                    else "Wallet transaction not yet confirmed on-chain as 'disputed'; local state unchanged"
                )
                raise HTTPException(status_code=502, detail=detail)
            deploy_hash = req.wallet_tx_hash
        else:
            # Authorization: only escrow sender or receiver may dispute
            caller = _extract_sender(request)
            if caller not in (escrow.sender, escrow.receiver):
                raise HTTPException(
                    status_code=403,
                    detail="Only escrow sender or receiver may dispute",
                )
            try:
                deploy_hash = await casper.dispute(req.service_hash)
            except Exception as exc:
                logger.error("Casper dispute failed: %s", exc)
                raise HTTPException(
                    status_code=502,
                    detail="On-chain dispute transaction failed; local state unchanged",
                )
    else:
        # Sandbox mode (no real chain) — still enforce the same x402-based check.
        caller = _extract_sender(request)
        if caller not in (escrow.sender, escrow.receiver):
            raise HTTPException(
                status_code=403,
                detail="Only escrow sender or receiver may dispute",
            )

    try:
        record = store.dispute_escrow(req.service_hash, deploy_hash)
        pgdb.update_escrow_status(req.service_hash, "disputed", deploy_hash)
        pgdb.bump_reputation(record.sender, disputed=1)
        await _sync_identity_registry(record.sender, disputed=1)
        _broadcast_event({"type": "escrow_disputed", "service_hash": req.service_hash, "ts": int(time.time())})
        # Spec alias — mirror as `dispute_opened` so notification listeners
        # that follow AE402_AGENT_SPEC.md (batch-2 A5) fire on the same event
        # without breaking existing consumers of `escrow_disputed`.
        _broadcast_event({"type": "dispute_opened", "service_hash": req.service_hash, "ts": int(time.time())})
        return record
    except KeyError:
        raise HTTPException(status_code=404, detail="Escrow not found")
    except ValueError as exc:
        _raise_fsm_or_generic(exc)


@app.post("/resolve", response_model=EscrowRecord)
async def resolve_escrow(
    req: ResolveRequest,
    cfg: Config = Depends(get_config),
    store: SandboxStore = Depends(get_sandbox),
    casper: CasperClient | None = Depends(get_casper),
):
    """Resolve a disputed escrow via 3-of-5 arbiter multisig.

    Unlike release/refund/dispute, this is *not* gated on the escrow
    sender/receiver identity: authorization comes from the contract's own
    check that each submitted (pubkey, signature) pair is (a) a member of
    the on-chain registered `arbiter_list` and (b) a real Ed25519 signature
    over the canonical vote message `"resolve:{service_hash}:{in_favor_of}"`,
    verified on-chain via `casper_types::crypto::verify`. Any caller may
    submit this once they have collected enough signed arbiter votes
    off-chain -- a claimed account-hash alone is never sufficient.
    """
    escrow = store.get_escrow(req.service_hash)
    if escrow is None:
        raise HTTPException(status_code=404, detail="Escrow not found")

    if len(req.arbiter_pubkeys) != len(req.arbiter_signatures):
        raise HTTPException(
            status_code=422,
            detail="arbiter_pubkeys and arbiter_signatures must have the same length",
        )

    # Fast local check with the same crypto guarantee the contract enforces
    # on-chain: real signatures, from registered arbiters, over this exact
    # escrow+verdict. In sandbox mode this is the *only* enforcement (no
    # chain call happens); in live mode it's a fast-fail before submitting
    # a transaction the contract would otherwise revert.
    if cfg.arbiter_pubkeys:
        valid_votes = arbiter_crypto.count_valid_votes(
            req.arbiter_pubkeys,
            req.arbiter_signatures,
            cfg.arbiter_pubkeys,
            req.service_hash,
            req.in_favor_of,
        )
        if valid_votes < cfg.arbiter_threshold:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Only {valid_votes} valid arbiter signature(s) for this escrow/verdict, "
                    f"need >= {cfg.arbiter_threshold}"
                ),
            )

    deploy_hash = ""

    if not cfg.sandbox and casper is not None:
        # Casper does not guarantee execution order between two deploys from
        # the same account submitted moments apart -- if `dispute()` and
        # `resolve()` land in the *same* block, `resolve()` can execute
        # first and see status still "pending", reverting with the
        # contract's "wrong status" error even though our own `/dispute`
        # call already returned success. Require a fresh, direct on-chain
        # read (not the local cache) showing "disputed" before submitting,
        # and retry submission once if the contract still reverts for that
        # reason (waiting long enough for the next block).
        for _ in range(6):
            onchain = await casper.get_escrow(req.service_hash)
            if onchain is not None and onchain.status.value == "disputed":
                break
            await asyncio.sleep(1.5)
        else:
            raise HTTPException(
                status_code=409,
                detail="Escrow not yet confirmed as 'disputed' on-chain; retry shortly",
            )

        last_error: str | None = None
        for attempt in range(2):
            try:
                deploy_hash = await casper.resolve(
                    req.service_hash, req.in_favor_of, req.arbiter_pubkeys, req.arbiter_signatures
                )
            except Exception as exc:
                logger.error("Casper resolve submission failed: %s", exc)
                raise HTTPException(
                    status_code=502,
                    detail="On-chain resolve transaction failed to submit; local state unchanged",
                )

            # Give the deploy a moment to land, then check whether the
            # contract reverted it (e.g. the same-block race described
            # above) before trusting the tx hash.
            await asyncio.sleep(4.0)
            last_error = await casper.get_deploy_error(deploy_hash)
            if last_error is None:
                break
            logger.warning("resolve() deploy %s reverted (%s), attempt %d/2", deploy_hash, last_error, attempt + 1)
            await asyncio.sleep(6.0)  # let the next block pass before retrying

        if last_error is not None:
            raise HTTPException(
                status_code=502,
                detail=f"On-chain resolve transaction reverted: {last_error}",
            )

        confirmed, revert_reason = await casper.confirm_wallet_lifecycle_tx(
            req.service_hash, "resolved", deploy_hash=deploy_hash
        )
        if not confirmed:
            raise HTTPException(
                status_code=502,
                detail=(
                    f"On-chain resolve transaction reverted: {revert_reason}"
                    if revert_reason
                    else "Resolve transaction submitted but not yet confirmed on-chain as 'resolved'"
                ),
            )

    try:
        record = store.resolve_escrow(req.service_hash, req.in_favor_of, deploy_hash)
        pgdb.update_escrow_status(req.service_hash, "resolved", deploy_hash)
        winner = record.sender if req.in_favor_of == "sender" else record.receiver
        pgdb.bump_reputation(winner, completed=1)
        await _sync_identity_registry(winner, completed=1)
        _broadcast_event({"type": "escrow_resolved", "service_hash": req.service_hash, "ts": int(time.time())})
        # Spec alias — mirror as `arbitration_complete` (see AE402_AGENT_SPEC.md
        # batch-2 A5). Kept as an additional broadcast so any consumer still
        # subscribed to the older `escrow_resolved` name keeps working.
        _broadcast_event({"type": "arbitration_complete", "service_hash": req.service_hash, "ts": int(time.time())})
        return record
    except KeyError:
        raise HTTPException(status_code=404, detail="Escrow not found")
    except ValueError as exc:
        _raise_fsm_or_generic(exc)


# ---------------------------------------------------------------------------
# POST /arbitration/analyze — LLM-powered dispute analysis
# ---------------------------------------------------------------------------


class ArbitrateRequest(BaseModel):
    dispute_id: str
    sender_evidence: list[DisputeEvidence]
    receiver_evidence: list[DisputeEvidence]
    escrow_amount: int
    # AE-A1.4: optional dispute-party account hashes. When present, an
    # abstain / low-confidence-escalate verdict auto-triggers VRF panel
    # election (excluding these two accounts). Format: lowercase hex
    # Casper account hash without 'account-hash-' prefix (see
    # vrf_election.ElectArbiterRequest).
    sender_account: str | None = None
    receiver_account: str | None = None
    # Verifiable random seed for panel election. When omitted, we hash
    # the dispute_id + verdict.analysis_hash — deterministic but bound
    # to a state the arbiter has already committed to.
    election_seed_hash: str | None = None


# Confidence gate for escalate-with-low-confidence → panel. Above this
# threshold, an 'escalate' verdict is left as-is (the arbiter is
# confident that a human should look, not that a panel should re-vote).
_ESCALATION_CONFIDENCE_MAX = 0.3


def _should_escalate(verdict: ArbitrationRecommendation) -> bool:
    """AE-A1.4 escalation policy.

    'abstain'  → always escalate (LLM refused to judge).
    'escalate' → escalate only when confidence < _ESCALATION_CONFIDENCE_MAX
                 (below this, LLM had no signal; above, a human review
                 is the intended path, not a panel re-vote).
    Anything else → no escalation.
    """
    if verdict.recommendation == "abstain":
        return True
    if verdict.recommendation == "escalate" and verdict.confidence < _ESCALATION_CONFIDENCE_MAX:
        return True
    return False


async def _try_escalate_to_panel(
    verdict: ArbitrationRecommendation,
    req: ArbitrateRequest,
) -> None:
    """Populate verdict.escalated_to_panel / .panel_election / .escalation_reason
    in place. Never raises — escalation failures are recorded as
    escalation_reason and the flat verdict is still returned.
    """
    if not req.sender_account or not req.receiver_account:
        verdict.escalation_reason = (
            "missing_party_accounts: abstain/low-conf-escalate verdict "
            "needs sender_account + receiver_account for VRF panel election"
        )
        return

    # Deterministic seed: dispute + analysis_hash. Caller-supplied seed
    # (e.g. a recent block hash) wins.
    seed_hash = (
        req.election_seed_hash
        or hashlib.sha256(f"{req.dispute_id}:{verdict.analysis_hash}".encode("utf-8")).hexdigest()
    )

    try:
        from server.vrf_election import (
            ElectArbiterRequest,
            _election_results,
            elect_arbiter,
        )

        election_req = ElectArbiterRequest(
            dispute_id=req.dispute_id,
            sender=req.sender_account,
            receiver=req.receiver_account,
            seed_hash=seed_hash,
        )
        election = await elect_arbiter(
            request=election_req,
            casper=None,  # forces local CSPRNG unless on-chain VRF configured
            cfg=get_config(),
        )
        verdict.escalated_to_panel = True
        verdict.panel_election = election.model_dump()
        verdict.escalation_reason = (
            "abstain_verdict"
            if verdict.recommendation == "abstain"
            else f"low_confidence_escalate:{verdict.confidence:.2f}"
        )
        logger.info(
            "Arbitration escalated: dispute=%s rec=%s conf=%.2f → panel=%s method=%s",
            req.dispute_id[:16],
            verdict.recommendation,
            verdict.confidence,
            election.elected_arbiter.arbiter_id,
            election.method,
        )
    except HTTPException as he:
        # 409 = already elected earlier for this dispute; look it up.
        if he.status_code == status.HTTP_409_CONFLICT:
            from server.vrf_election import _election_results

            prior = _election_results.get(req.dispute_id)
            if prior:
                verdict.escalated_to_panel = True
                verdict.panel_election = prior
                verdict.escalation_reason = "prior_election_reused"
                return
        logger.warning("VRF panel escalation returned %s: %s", he.status_code, he.detail)
        verdict.escalation_reason = f"panel_election_failed_http_{he.status_code}"
    except Exception as exc:
        logger.warning("VRF panel escalation raised: %s", exc)
        verdict.escalation_reason = f"panel_election_failed:{type(exc).__name__}"


@app.post("/arbitration/analyze", response_model=ArbitrationRecommendation, tags=["arbitration"])
async def arbitrate_dispute(req: ArbitrateRequest):
    """Run LLM arbitration on dispute evidence.

    Tries Groq → NVIDIA NIM → OpenRouter → heuristic fallback. Returns
    recommendation: favor_sender | favor_receiver | split | escalate |
    abstain.

    AE-A1.4 auto-escalation (flat fields on the response):
      * verdict.recommendation == 'abstain'  → always route to VRF panel
      * verdict.recommendation == 'escalate' AND confidence <
        _ESCALATION_CONFIDENCE_MAX → route to VRF panel
      * escalation needs sender_account + receiver_account in the
        request (they must be excluded from the panel); when missing,
        the verdict is returned with escalated_to_panel=false and
        escalation_reason set so the caller knows what to add.
    """
    if req.escrow_amount < 0:
        raise HTTPException(status_code=400, detail="escrow_amount must be non-negative")
    try:
        verdict = await _arbitration_agent.analyze_dispute(
            dispute_id=req.dispute_id,
            sender_evidence=req.sender_evidence,
            receiver_evidence=req.receiver_evidence,
            escrow_amount=req.escrow_amount,
        )
        logger.info(
            "Arbitration complete: dispute=%s provider=%s rec=%s conf=%.2f",
            req.dispute_id[:16],
            verdict.provider,
            verdict.recommendation,
            verdict.confidence,
        )

        if _should_escalate(verdict):
            await _try_escalate_to_panel(verdict, req)

        return verdict
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Arbitration error: %s", exc)
        raise HTTPException(status_code=500, detail=f"Arbitration failed: {exc}")


@app.get("/arbitration/history", response_model=list[ArbitrationRecommendation], tags=["arbitration"])
async def arbitration_history(limit: int = 20):
    """Most recent LLM arbitration analyses (process-lifetime in-memory history),
    newest first. Powers the console's Arbitration verdict-history view."""
    if limit < 1 or limit > 200:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 200")
    return list(reversed(_arbitration_agent._history[-limit:]))


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
@app.get("/api/v1/events/stream")
async def event_stream():
    """Server-Sent Events stream for real-time escrow updates.

    Exposed on two paths:
    - ``/events`` (canonical, historical)
    - ``/api/v1/events/stream`` (AE402 Agent Spec alias)
    """
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


DEMO_CONSOLE_SENDER = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
# Second labelled demo identity ("the other party"), needed for two-sided demo
# flows where a sender and a receiver must each act (e.g. atomic-swap
# commit-by-sender / reveal-by-receiver). Matches frontend's DEMO_AGENT_RECEIVER.
# Still just a fixed, publicly-known placeholder key — no real key material,
# same trust model as DEMO_CONSOLE_SENDER, just a second named counterparty.
DEMO_CONSOLE_RECEIVER = "fedcba9876543210fedcba9876543210fedcba9876543210fedcba9876543210"
DEMO_CONSOLE_SIGNATURE = "a" * 128
DEMO_CONSOLE_IDENTITIES = {DEMO_CONSOLE_SENDER, DEMO_CONSOLE_RECEIVER}


def _extract_sender(request: Request) -> str:
    """Extract sender identity from x402 header or sandbox mode.

    Production x402 headers are Ed25519-verified and replay-checked. The hosted
    console has explicit, labelled demo bypasses so non-wallet visitors can run
    the testnet UI; it is limited to the known demo sender/signature markers.
    """
    cfg = get_config()
    if hasattr(request.state, "payment") and request.state.payment:
        return request.state.payment.sender
    payment_header = request.headers.get("X-Payment")
    if payment_header:
        parsed = parse_x402_header(payment_header)
        if parsed:
            is_demo_console = request.headers.get("X-AE402-Demo-Identity") == "hosted-console"
            if is_demo_console:
                if not cfg.allow_hosted_demo_identity:
                    raise HTTPException(status_code=401, detail="hosted demo x402 identity disabled")
                if parsed.sender in DEMO_CONSOLE_IDENTITIES and parsed.signature == DEMO_CONSOLE_SIGNATURE:
                    return parsed.sender
                raise HTTPException(status_code=401, detail="invalid demo x402 identity")

            replay_err = _check_replay(parsed.nonce, parsed.timestamp)
            if replay_err:
                raise HTTPException(status_code=401, detail=replay_err)
            msg = _build_signing_payload(parsed, method=request.method, path=request.url.path)
            if not _verify_signature(parsed.sender, msg, parsed.signature):
                raise HTTPException(status_code=401, detail="invalid x402 signature")
            return parsed.sender
    if cfg.sandbox:
        return request.query_params.get("sender", "sandbox-agent-001")
    raise HTTPException(status_code=401, detail="sender identity required")


def _extract_release_refund_caller(request: Request, wallet_tx_hash: str | None, escrow_sender: str) -> str:
    """Resolve the acting caller for release/refund.

    Normal path: verified x402 header (hosted demo signer or a real signed
    payment intent). Live-wallet path: the x402 header is intentionally not
    required here — on-chain contract state (already confirmed via
    `CasperClient.confirm_wallet_lifecycle_tx` before this is called) is
    strictly stronger proof of authorization than an x402 signature could
    ever add, since the contract itself only lets the true escrow sender
    execute release/refund. The caller is simply the escrow's own recorded
    sender, which is exactly what the on-chain check already verified.
    """
    if wallet_tx_hash:
        return escrow_sender
    return _extract_sender(request)
