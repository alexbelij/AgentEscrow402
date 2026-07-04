"""FastAPI router exposing `server/identity_registry.py`'s DID-based agent
identity/reputation system.

This module (staking-aware reputation, score decay, slashing, capability
search) previously existed as pure business logic with a full unit test
suite (`tests/test_identity_registry.py`) but was never wired to a single
HTTP endpoint - CHANGELOG 1.1.0 documented an "Identity Registry" console
tab that was never actually built. This router + `console/IdentityRegistry.tsx`
close that gap.

Distinct from `server/agent_identity.py` (mounted at `/identity`), which is a
simpler public-key + delegated-capability registry already surfaced in
`Agents.tsx`. This module is a separate reputation/staking system (DIDs,
verification levels, stake slashing, reputation decay) mounted at
`/identity-registry` to avoid colliding with the existing `/identity` prefix.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from server.identity_registry import (
    AgentCapability,
    AgentIdentity,
    IdentityRegistry,
    VerificationLevel,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/identity-registry", tags=["identity-registry"])

# Single process-lifetime in-memory registry (matches the rest of this
# sandbox's demo backend - see SandboxStore / _registered_arbiters / etc).
_registry = IdentityRegistry()


class RegisterIdentityRequest(BaseModel):
    account_hash: str = Field(..., min_length=1, max_length=128)
    display_name: str = Field(..., max_length=256)
    capabilities: list[AgentCapability] = Field(default_factory=list)


class UpdateReputationRequest(BaseModel):
    completed: int = Field(0, ge=0)
    disputed: int = Field(0, ge=0)


class SlashRequest(BaseModel):
    amount: int = Field(..., gt=0)
    reason: str = Field(..., min_length=1, max_length=256)


class VerifyRequest(BaseModel):
    level: VerificationLevel


class AddCapabilityRequest(BaseModel):
    capability: AgentCapability


def _get_or_404(did: str) -> None:
    return None


@router.post("/register", response_model=AgentIdentity, status_code=status.HTTP_201_CREATED)
async def register_identity(req: RegisterIdentityRequest) -> AgentIdentity:
    try:
        return await _registry.register(req.account_hash, req.display_name, req.capabilities)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("/{did}", response_model=AgentIdentity)
async def get_identity(did: str) -> AgentIdentity:
    identity = await _registry.get(did)
    if not identity:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Identity not found")
    return identity


@router.get("/by-account/{account_hash}", response_model=AgentIdentity)
async def get_identity_by_account(account_hash: str) -> AgentIdentity:
    identity = await _registry.get_by_account(account_hash)
    if not identity:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Identity not found")
    return identity


@router.post("/{did}/reputation", response_model=AgentIdentity)
async def update_reputation(did: str, req: UpdateReputationRequest) -> AgentIdentity:
    try:
        return await _registry.update_reputation(did, completed=req.completed, disputed=req.disputed)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/{did}/decay", response_model=AgentIdentity)
async def apply_decay(did: str) -> AgentIdentity:
    try:
        return await _registry.apply_decay(did)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/{did}/slash", response_model=AgentIdentity)
async def slash_identity(did: str, req: SlashRequest) -> AgentIdentity:
    try:
        return await _registry.slash(did, req.amount, req.reason)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/{did}/verify", response_model=AgentIdentity)
async def verify_identity(did: str, req: VerifyRequest) -> AgentIdentity:
    try:
        return await _registry.verify(did, req.level)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/{did}/capabilities", response_model=AgentIdentity)
async def add_capability(did: str, req: AddCapabilityRequest) -> AgentIdentity:
    try:
        return await _registry.add_capability(did, req.capability)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/search/agents", response_model=list[AgentIdentity])
async def search_identities(
    capability: str | None = Query(default=None),
    min_reputation: int = Query(default=0, ge=0, le=100),
    min_verification: VerificationLevel = Query(default=VerificationLevel.UNVERIFIED),
) -> list[AgentIdentity]:
    return await _registry.search(
        capability_name=capability,
        min_reputation=min_reputation,
        min_verification=min_verification,
    )


@router.get("/stats/summary")
async def registry_statistics() -> dict:
    return await _registry.get_statistics()
