"""Data models for AgentEscrow402."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class EscrowStatus(str, Enum):
    PENDING = "pending"
    RELEASED = "released"
    REFUNDED = "refunded"
    EXPIRED = "expired"
    DISPUTED = "disputed"
    RESOLVED = "resolved"
    # Backward-compatible aliases used by older batch tests / integrations.
    COMPLETED = "released"
    FAILED = "refunded"


class EscrowRequest(BaseModel):
    """Request to create a new escrow."""

    receiver: str = Field(
        ...,
        pattern=r"^(account-hash-)?[0-9a-fA-F]{64}$",
        description="Casper account hash of the receiver (raw 64-hex or account-hash- prefixed)",
    )
    amount: int = Field(..., gt=0, description="Amount in motes")
    service_hash: str = Field(..., min_length=64, max_length=64, pattern=r"^[0-9a-fA-F]{64}$")
    ttl: int = Field(default=300, ge=60, le=86400, description="Time-to-live in seconds")


class EscrowRecord(BaseModel):
    """On-chain escrow record.

    Optional ML-KEM fields are returned by create_escrow so the console can
    prove that post-quantum metadata encryption actually ran for the demo.
    """

    sender: str
    receiver: str
    amount: int
    service_hash: str
    status: EscrowStatus
    created_at: int
    ttl: int
    deploy_hash: str | None = None
    mlkem_ciphertext: str | None = None
    mlkem_decap_key: str | None = None
    mlkem_algorithm: str | None = None


class ReleaseRequest(BaseModel):
    service_hash: str = Field(..., min_length=64, max_length=64)
    # Set when the wallet-connected caller already built, signed (via their
    # own Casper Wallet/Ledger/MetaMask through CSPR.click) and submitted the
    # on-chain transaction directly. In that case the backend does not sign
    # or submit anything itself — it only polls contract state and confirms
    # the entry point actually executed before updating hosted records.
    wallet_tx_hash: str | None = Field(default=None, min_length=1, max_length=128)


class RefundRequest(BaseModel):
    service_hash: str = Field(..., min_length=64, max_length=64)
    wallet_tx_hash: str | None = Field(default=None, min_length=1, max_length=128)


class DisputeRequest(BaseModel):
    service_hash: str = Field(..., min_length=64, max_length=64)
    reason_hash: str = Field(..., min_length=64, max_length=64)
    wallet_tx_hash: str | None = Field(default=None, min_length=1, max_length=128)


class ResolveRequest(BaseModel):
    service_hash: str = Field(..., min_length=64, max_length=64)
    in_favor_of: str = Field(..., pattern="^(sender|receiver)$")
    # Each arbiter casts their vote as a real Ed25519 signature (hex,
    # AsymmetricType tag-prefixed) over "resolve:{service_hash}:{in_favor_of}",
    # verified on-chain in the resolve() entry point -- not just a claimed
    # account-hash. arbiter_pubkeys[i] must correspond to arbiter_signatures[i].
    arbiter_pubkeys: list[str]
    arbiter_signatures: list[str]


class ReputationRecord(BaseModel):
    agent: str
    completed: int = 0
    disputed: int = 0
    slashed: int = 0
    last_active: int = 0
    score: int = 50


class PaymentHeader(BaseModel):
    """x402 payment header parsed from Authorization."""

    version: str = "x402-v1"
    escrow_hash: str
    amount: int
    sender: str
    signature: str
    timestamp: int = 0
    nonce: str = ""


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "0.2.0"
    sandbox: bool = True
    chain: str = ""
    contract_hash: str = ""
    db: str = "disconnected"
    uptime: int = 0
