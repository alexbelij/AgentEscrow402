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


class EscrowRequest(BaseModel):
    """Request to create a new escrow."""

    receiver: str = Field(..., description="Casper account hash of the receiver")
    amount: int = Field(..., gt=0, description="Amount in motes")
    service_hash: str = Field(..., min_length=64, max_length=64)
    ttl: int = Field(
        default=300, ge=60, le=86400, description="Time-to-live in seconds"
    )


class EscrowRecord(BaseModel):
    """On-chain escrow record."""

    sender: str
    receiver: str
    amount: int
    service_hash: str
    status: EscrowStatus
    created_at: int
    ttl: int
    deploy_hash: str | None = None


class ReleaseRequest(BaseModel):
    service_hash: str = Field(..., min_length=64, max_length=64)


class RefundRequest(BaseModel):
    service_hash: str = Field(..., min_length=64, max_length=64)


class DisputeRequest(BaseModel):
    service_hash: str = Field(..., min_length=64, max_length=64)
    reason_hash: str = Field(..., min_length=64, max_length=64)


class ResolveRequest(BaseModel):
    service_hash: str = Field(..., min_length=64, max_length=64)
    in_favor_of: str = Field(..., pattern="^(sender|receiver)$")
    arbiter_accounts: list[str]


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
