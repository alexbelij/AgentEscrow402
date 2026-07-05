"""Multi-asset escrow support (CEP-18/CEP-78 tokens) for AgentEscrow402."""

from __future__ import annotations

import abc
import asyncio
import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from server.casper_client import CasperClient
from server.config import Config, get_config
from server.sandbox import SandboxStore
from server.models import EscrowRecord, EscrowStatus, PaymentHeader
from server.middleware import (
    parse_x402_header,
    _build_signing_payload,
    _check_replay,
    _verify_ed25519,
)

def get_casper() -> CasperClient | None:
    # This function is a placeholder, in a real app.py it would be defined globally
    # or imported from app.py. For this file generation, we assume it exists.
    from server.app import get_casper as _get_casper
    return _get_casper()


def get_sandbox_store() -> "SandboxStore":
    """Shared SandboxStore instance, same one the main /escrow lifecycle uses.

    Previously these endpoints depended on `InMemoryDB` (server.db's generic
    scratch key-value store: only get_collection/insert/find) and called
    db.create_escrow()/db.get_escrow()/db.update_escrow_status() on it - none
    of those methods exist on InMemoryDB (nor does server/db.py define a
    module-level get_escrow function). Every one of these calls would have
    raised AttributeError at runtime the moment a request got this far -
    confirmed by exercising these endpoints directly. Using the same
    SandboxStore as /escrow, /release, /refund also lets atomic-swap commit
    and reveal act on an escrow created through the regular escrow-creation
    endpoint, not just one created via /escrow/multi-asset.
    """
    from server.app import get_sandbox as _get_sandbox
    return _get_sandbox()


async def get_x402_payment(request: Request, config: Config = Depends(get_config)) -> PaymentHeader:
    """FastAPI dependency that extracts and authorizes the X-Payment header.

    `Depends(parse_x402_header)` (the previous implementation of this
    dependency) was broken: `parse_x402_header(raw: str)` takes a plain
    positional string, so FastAPI resolved `raw` as a *required query
    parameter* instead of reading the `X-Payment` header, and every request
    to these endpoints therefore 422'd unconditionally regardless of what
    was sent (confirmed: /escrow/multi-asset, /escrow/stream and both
    /escrow/atomic-swap/* endpoints have never worked end-to-end). This
    mirrors the working `_extract_sender`/header-parsing pattern already
    used by the main /escrow, /release, /refund routes in server/app.py.
    """
    from server.app import DEMO_CONSOLE_IDENTITIES, DEMO_CONSOLE_SIGNATURE

    raw = request.headers.get("X-Payment")
    if not raw:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="X-Payment header required")
    parsed = parse_x402_header(raw)
    if not parsed:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid X-Payment header")

    is_demo_console = request.headers.get("X-AE402-Demo-Identity") == "hosted-console"
    if is_demo_console:
        if not config.allow_hosted_demo_identity:
            raise HTTPException(status_code=401, detail="hosted demo x402 identity disabled")
        if parsed.sender in DEMO_CONSOLE_IDENTITIES and parsed.signature == DEMO_CONSOLE_SIGNATURE:
            return parsed
        raise HTTPException(status_code=401, detail="invalid demo x402 identity")

    replay_err = _check_replay(parsed.nonce, parsed.timestamp)
    if replay_err:
        raise HTTPException(status_code=401, detail=replay_err)
    msg = _build_signing_payload(parsed, method=request.method, path=request.url.path)
    if not _verify_ed25519(parsed.sender, msg, parsed.signature):
        raise HTTPException(status_code=401, detail="invalid x402 signature")
    return parsed




logger = logging.getLogger(__name__)
router = APIRouter(prefix="/escrow", tags=["multi-asset", "streaming"])

# In-memory store for multi-asset and streaming escrows (replace with proper DB)
_multi_asset_escrows: dict[str, EscrowRecord] = {}
_streaming_escrows: dict[str, dict[str, Any]] = {}
_commit_reveals: dict[str, dict[str, Any]] = {}
_store_lock = asyncio.Lock()


class TokenIdentifier(BaseModel):
    """Identifies a token type (CSPR, CEP-18, CEP-78)."""

    token_type: str = Field(..., pattern="^(cspr|cep18|cep78)$", description="Type of token: 'cspr', 'cep18', or 'cep78'")
    contract_hash: str | None = Field(
        None, min_length=64, max_length=64, description="Contract hash for CEP-18/CEP-78 tokens"
    )

    def __hash__(self) -> int:
        return hash((self.token_type, self.contract_hash))

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, TokenIdentifier):
            return NotImplemented
        return self.token_type == other.token_type and self.contract_hash == other.contract_hash


class MultiAssetEscrowRequest(BaseModel):
    """Request to create a new multi-asset escrow."""

    receiver: str = Field(..., description="Casper account hash of the receiver")
    amount: int = Field(..., gt=0, description="Amount in motes or token units")
    token: TokenIdentifier = Field(..., description="Details of the token being escrowed")
    service_hash: str = Field(..., min_length=64, max_length=64)
    ttl: int = Field(default=300, ge=60, le=86400, description="Time-to-live in seconds")


class StreamEscrowRequest(BaseModel):
    """Request to create a new streaming escrow."""

    receiver: str = Field(..., description="Casper account hash of the receiver")
    amount: int = Field(..., gt=0, description="Total amount in motes or token units")
    token: TokenIdentifier = Field(..., description="Details of the token being streamed")
    service_hash: str = Field(..., min_length=64, max_length=64)
    start_time: int = Field(..., description="Unix timestamp when streaming starts")
    end_time: int = Field(..., description="Unix timestamp when streaming ends")

    @property
    def duration(self) -> int:
        return self.end_time - self.start_time

    def __init__(self, **data: Any):
        super().__init__(**data)
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be strictly after start_time")
    # Optional: interval_amount or duration for more granular control, for simplicity we derive from total/duration
    # interval_seconds: int = Field(..., gt=0, description="Interval in seconds for payment chunks")

    class Config:
        extra = "forbid"
        json_schema_extra = {
            "example": {
                "receiver": "account-hash-...",
                "amount": 1000000000,
                "token": {"token_type": "cspr"},
                "service_hash": "a" * 64,
                "start_time": int(time.time()),
                "end_time": int(time.time()) + 3600,
            }
        }


class StreamStatusResponse(BaseModel):
    """Current status of a streaming escrow."""

    service_hash: str
    total_amount: int
    token: TokenIdentifier
    receiver: str
    sender: str
    start_time: int
    end_time: int
    streamed_amount: int
    remaining_amount: int
    status: EscrowStatus
    last_payout_time: int | None = None


class CommitRequest(BaseModel):
    """Request to commit a hash for an atomic swap."""

    service_hash: str = Field(..., min_length=64, max_length=64)
    commit_hash: str = Field(..., min_length=64, max_length=64, description="SHA256 hash of the secret preimage")


class RevealRequest(BaseModel):
    """Request to reveal the preimage for an atomic swap."""

    service_hash: str = Field(..., min_length=64, max_length=64)
    preimage: str = Field(..., min_length=1, description="The secret preimage to reveal")


class TokenAdapter(abc.ABC):
    """Abstract base class for interacting with different token types."""

    def __init__(self, casper_client: CasperClient, config: Config) -> None:
        self._casper = casper_client
        self._config = config

    @abc.abstractmethod
    async def transfer_to_escrow(self, sender: str, receiver: str, amount: int, token_id: TokenIdentifier) -> str:
        """Transfers tokens to the escrow contract."""
        raise NotImplementedError

    @abc.abstractmethod
    async def get_balance(self, account_hash: str, token_id: TokenIdentifier) -> int:
        """Gets the balance of an account for a specific token."""
        raise NotImplementedError

    @abc.abstractmethod
    async def get_token_info(self, token_id: TokenIdentifier) -> dict[str, Any]:
        """Gets information about the token (e.g., symbol, decimals)."""
        raise NotImplementedError


class CsprAdapter(TokenAdapter):
    """Adapter for Casper native token (CSPR)."""

    async def transfer_to_escrow(self, sender: str, receiver: str, amount: int, token_id: TokenIdentifier) -> str:
        logger.info("Simulating CSPR transfer from %s to escrow for %s motes", sender, amount)
        # In a real scenario, this would involve a Casper deploy to transfer CSPR
        # to the escrow contract, potentially calling an entry point.
        # For now, we simulate success.
        return "deploy-hash-cspr-" + str(int(time.time()))

    async def get_balance(self, account_hash: str, token_id: TokenIdentifier) -> int:
        logger.info("Simulating CSPR balance query for %s", account_hash)
        # In a real scenario, query Casper state for account balance
        return 1_000_000_000_000  # Example balance

    async def get_token_info(self, token_id: TokenIdentifier) -> dict[str, Any]:
        return {"symbol": "CSPR", "decimals": 9, "name": "Casper"}


class Cep18Adapter(TokenAdapter):
    """Adapter for CEP-18 tokens.

    Backed by a real deployed CEP-18 contract on casper-test (see
    server/casper_tx/cep18_transfer.mjs + CasperClient.cep18_transfer/
    get_cep18_balance/get_cep18_token_info). Custodial-demo model: the
    on-chain `transfer` call is signed by the client's configured operator
    key (same account that deployed the escrow/insurance-pool/VRF-arbiter
    contracts and the token itself), same as CsprAdapter's escrow funding.
    """

    async def transfer_to_escrow(self, sender: str, receiver: str, amount: int, token_id: TokenIdentifier) -> str:
        if not token_id.contract_hash:
            raise ValueError("CEP-18 token requires contract_hash")
        logger.info(
            "CEP-18 transfer of %s units from %s to escrow for contract %s",
            amount,
            sender,
            token_id.contract_hash[:16],
        )
        return await self._casper.cep18_transfer(token_id.contract_hash, receiver, amount)

    async def get_balance(self, account_hash: str, token_id: TokenIdentifier) -> int:
        if not token_id.contract_hash:
            raise ValueError("CEP-18 token requires contract_hash")
        return await self._casper.get_cep18_balance(token_id.contract_hash, account_hash)

    async def get_token_info(self, token_id: TokenIdentifier) -> dict[str, Any]:
        if not token_id.contract_hash:
            raise ValueError("CEP-18 token requires contract_hash")
        info = await self._casper.get_cep18_token_info(token_id.contract_hash)
        return {
            "symbol": info.get("symbol") or "CEP18",
            "decimals": info.get("decimals") if info.get("decimals") is not None else 9,
            "name": info.get("name") or "CEP-18 Token",
        }


class Cep78Adapter(TokenAdapter):
    """Adapter for CEP-78 NFTs.

    Backed by a real deployed CEP-78 (Ordinal identifier mode) contract on
    casper-test (see server/casper_tx/cep78_mint.mjs, cep78_transfer.mjs +
    CasperClient.cep78_transfer/get_cep78_balance/get_cep78_owner/
    get_cep78_token_info). Custodial-demo model, same as Cep18Adapter/
    CsprAdapter: the on-chain `transfer` call is signed by the client's
    configured operator key. `amount` is reused as the NFT's ordinal
    `token_id` (there is no fungible quantity for an NFT transfer).
    """

    async def transfer_to_escrow(self, sender: str, receiver: str, amount: int, token_id: TokenIdentifier) -> str:
        if not token_id.contract_hash:
            raise ValueError("CEP-78 token requires contract_hash")
        # For NFTs, `amount` carries the ordinal token_id (e.g., NFT #3).
        logger.info(
            "CEP-78 NFT transfer of token_id %s from %s to escrow for contract %s",
            amount,
            sender,
            token_id.contract_hash[:16],
        )
        return await self._casper.cep78_transfer(token_id.contract_hash, amount, sender, receiver)

    async def get_balance(self, account_hash: str, token_id: TokenIdentifier) -> int:
        if not token_id.contract_hash:
            raise ValueError("CEP-78 token requires contract_hash")
        return await self._casper.get_cep78_balance(token_id.contract_hash, account_hash)

    async def get_token_info(self, token_id: TokenIdentifier) -> dict[str, Any]:
        if not token_id.contract_hash:
            raise ValueError("CEP-78 token requires contract_hash")
        info = await self._casper.get_cep78_token_info(token_id.contract_hash)
        return {
            "symbol": info.get("collection_symbol") or "NFT",
            "decimals": 0,
            "name": info.get("collection_name") or "CEP-78 NFT",
        }


def _build_token_adapter(
    token_id: TokenIdentifier, casper: CasperClient | None, config: Config
) -> TokenAdapter:
    """Plain helper (not a FastAPI dependency) that picks the right token adapter.

    Previously this was declared as `Depends(get_token_adapter)` with
    `token_id: TokenIdentifier` as an un-annotated parameter. FastAPI then
    treated `token_id` as its own required top-level request-body field
    (sibling to the endpoint's own `request` body model), so every call
    that only sent the documented `{receiver, amount, token, ...}` body
    422'd with "field required: token_id" (and, confusingly, "field
    required: request" too, since FastAPI no longer treated the single
    Pydantic model as the whole body once a second body field existed).
    Now called directly inside each endpoint with the token identifier
    read from the already-parsed request body.
    """
    if not casper:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Casper client not initialized")

    if token_id.token_type == "cspr":
        return CsprAdapter(casper, config)
    elif token_id.token_type == "cep18":
        return Cep18Adapter(casper, config)
    elif token_id.token_type == "cep78":
        return Cep78Adapter(casper, config)
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unsupported token type: {token_id.token_type}")


@router.post("/multi-asset", response_model=EscrowRecord, status_code=status.HTTP_201_CREATED)
async def create_multi_asset_escrow(
    request: MultiAssetEscrowRequest,
    x402: PaymentHeader = Depends(get_x402_payment),
    casper: CasperClient | None = Depends(get_casper),
    config: Config = Depends(get_config),
    store: SandboxStore = Depends(get_sandbox_store),
) -> EscrowRecord:
    """
    Creates a new multi-asset escrow.
    The sender (from X402 header) transfers the specified token amount to the escrow contract.
    """
    token_adapter = _build_token_adapter(request.token, casper, config)
    sender = x402.sender
    if x402.amount != request.amount:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="X402 amount must match escrow request amount.",
        )

    logger.info(
        "Creating multi-asset escrow for service_hash %s: sender=%s, receiver=%s, amount=%s %s",
        request.service_hash[:16],
        sender[:8],
        request.receiver[:8],
        request.amount,
        request.token.token_type,
    )

    # Simulate token transfer to the escrow contract
    try:
        deploy_hash = await token_adapter.transfer_to_escrow(sender, request.receiver, request.amount, request.token)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error("Failed to simulate token transfer: %s", e)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to initiate token transfer")

    try:
        escrow_record = store.create_escrow(
            sender=sender,
            receiver=request.receiver,
            amount=request.amount,
            service_hash=request.service_hash,
            ttl=request.ttl,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    escrow_record.deploy_hash = deploy_hash
    # Also kept in the local dict so other multi-asset-specific reads (token
    # type, etc.) stay available without extending the shared SandboxStore.
    _multi_asset_escrows[request.service_hash] = escrow_record
    logger.info("Multi-asset escrow %s created with deploy_hash %s", request.service_hash[:16], deploy_hash[:16])
    return escrow_record


@router.post("/stream", response_model=EscrowRecord, status_code=status.HTTP_201_CREATED)
async def create_streaming_escrow(
    request: StreamEscrowRequest,
    x402: PaymentHeader = Depends(get_x402_payment),
    casper: CasperClient | None = Depends(get_casper),
    config: Config = Depends(get_config),
    store: SandboxStore = Depends(get_sandbox_store),
) -> EscrowRecord:
    """
    Creates a new streaming escrow.
    The sender (from X402 header) deposits the total amount into a streaming contract,
    which then releases funds to the receiver over a specified time period.
    """
    token_adapter = _build_token_adapter(request.token, casper, config)
    sender = x402.sender
    if x402.amount != request.amount:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="X402 amount must match streaming escrow total amount.",
        )
    if request.start_time >= request.end_time:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Start time must be before end time.",
        )

    logger.info(
        "Creating streaming escrow for service_hash %s: sender=%s, receiver=%s, total_amount=%s %s, duration=%s",
        request.service_hash[:16],
        sender[:8],
        request.receiver[:8],
        request.amount,
        request.token.token_type,
        request.end_time - request.start_time,
    )

    # Simulate initial token transfer to the streaming escrow contract
    try:
        deploy_hash = await token_adapter.transfer_to_escrow(sender, request.receiver, request.amount, request.token)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error("Failed to simulate token transfer for streaming escrow: %s", e)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to initiate token transfer")

    try:
        escrow_record = store.create_escrow(
            sender=sender,
            receiver=request.receiver,
            amount=request.amount,
            service_hash=request.service_hash,
            ttl=request.end_time - int(time.time()) + 3600,  # TTL slightly longer than stream duration
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    escrow_record.deploy_hash = deploy_hash
    _streaming_escrows[request.service_hash] = {
        "escrow_record": escrow_record,
        "token": request.token,
        "start_time": request.start_time,
        "end_time": request.end_time,
        "streamed_amount": 0,
        "last_payout_time": None,
    }
    logger.info("Streaming escrow %s created with deploy_hash %s", request.service_hash[:16], deploy_hash[:16])
    return escrow_record


@router.get("/{service_hash}/stream-status", response_model=StreamStatusResponse)
async def get_stream_status(service_hash: str) -> StreamStatusResponse:
    """
    Retrieves the current status of a streaming escrow, including streamed and remaining amounts.
    """
    stream_data = _streaming_escrows.get(service_hash)
    if not stream_data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Streaming escrow not found")

    escrow_record = stream_data["escrow_record"]
    current_time = int(time.time())

    total_duration = stream_data["end_time"] - stream_data["start_time"]
    elapsed_time = max(0, min(current_time, stream_data["end_time"]) - stream_data["start_time"])

    if total_duration <= 0:  # Handle edge case where start_time == end_time
        streamed_amount = escrow_record.amount if current_time >= stream_data["end_time"] else 0
    else:
        streamed_amount = int((elapsed_time / total_duration) * escrow_record.amount)

    # Ensure streamed amount doesn't exceed total amount
    streamed_amount = min(streamed_amount, escrow_record.amount)

    remaining_amount = escrow_record.amount - streamed_amount
    status_val = EscrowStatus.RELEASED if streamed_amount == escrow_record.amount else EscrowStatus.PENDING
    if current_time > stream_data["end_time"] and streamed_amount < escrow_record.amount:
        status_val = EscrowStatus.EXPIRED # Or some other status for incomplete streams

    # Update local state (in a real system, this would be from on-chain query)
    stream_data["streamed_amount"] = streamed_amount
    stream_data["escrow_record"].status = status_val

    logger.debug(
        "Stream status for %s: streamed=%s, remaining=%s, status=%s",
        service_hash[:16],
        streamed_amount,
        remaining_amount,
        status_val,
    )

    return StreamStatusResponse(
        service_hash=service_hash,
        total_amount=escrow_record.amount,
        token=stream_data["token"],
        receiver=escrow_record.receiver,
        sender=escrow_record.sender,
        start_time=stream_data["start_time"],
        end_time=stream_data["end_time"],
        streamed_amount=streamed_amount,
        remaining_amount=remaining_amount,
        status=status_val,
        last_payout_time=stream_data["last_payout_time"],
    )


@router.post("/atomic-swap/commit", status_code=status.HTTP_202_ACCEPTED)
async def commit_atomic_swap(
    request: CommitRequest,
    x402: PaymentHeader = Depends(get_x402_payment),
    store: SandboxStore = Depends(get_sandbox_store),
) -> dict[str, str]:
    """
    Commits a SHA256 hash of a secret preimage for an atomic swap.
    This is the first step in a commit-reveal scheme.
    """
    # In a real scenario, this would involve a Casper deploy to store the commit_hash
    # on the escrow contract, linked to the service_hash.
    # The escrow itself would have been created earlier, potentially as a multi-asset escrow
    # or via the regular /escrow endpoint - both are backed by the same SandboxStore.

    escrow = store.get_escrow(request.service_hash)
    if not escrow:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Escrow not found for commit")
    if escrow.sender != x402.sender:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only sender can commit to this escrow")

    _commit_reveals[request.service_hash] = {
        "commit_hash": request.commit_hash,
        "committed_by": x402.sender,
        "timestamp": int(time.time()),
        "revealed": False,
        "preimage": None,
    }
    logger.info("Commit hash %s stored for service_hash %s by %s", request.commit_hash[:16], request.service_hash[:16], x402.sender[:8])
    return {"message": "Commit hash stored successfully. Awaiting reveal."}


@router.post("/atomic-swap/reveal", status_code=status.HTTP_200_OK)
async def reveal_atomic_swap(
    request: RevealRequest,
    x402: PaymentHeader = Depends(get_x402_payment),
    store: SandboxStore = Depends(get_sandbox_store),
) -> dict[str, str]:
    """
    Reveals the secret preimage for an atomic swap.
    The contract verifies the preimage against the previously committed hash.
    If valid, the escrow can be released.
    """
    import hashlib

    commit_data = _commit_reveals.get(request.service_hash)
    if not commit_data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No commit found for this service hash")
    if commit_data["revealed"]:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Preimage already revealed")

    escrow = store.get_escrow(request.service_hash)
    if not escrow:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Escrow not found for reveal")
    # Who can reveal? Typically the other party (receiver) or the committer.
    # For simplicity, let's say receiver can reveal to trigger release.
    if escrow.receiver != x402.sender:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only receiver can reveal for this escrow")

    # Verify preimage against committed hash
    computed_hash = hashlib.sha256(request.preimage.encode()).hexdigest()
    if computed_hash != commit_data["commit_hash"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid preimage: hash mismatch")

    # In a real scenario, this would trigger a Casper deploy to call the `reveal`
    # entry point on the escrow contract, which would then release funds.
    # release_escrow requires caller == escrow.sender (the party who committed
    # the hash-lock), which matches the commit-reveal model here.
    try:
        store.release_escrow(request.service_hash, caller=escrow.sender)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    _commit_reveals[request.service_hash]["revealed"] = True
    _commit_reveals[request.service_hash]["preimage"] = request.preimage
    logger.info("Preimage revealed for service_hash %s. Escrow released.", request.service_hash[:16])
    return {"message": "Preimage revealed successfully. Escrow released."}
