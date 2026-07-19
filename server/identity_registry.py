"""DID-based agent identity registry (ERC-8004 style) for AgentEscrow402.

In-memory reputation/staking store: registration, verification levels,
cumulative reputation from completed/disputed deals, time-based reputation
decay, stake slashing, and capability search. Exposed over HTTP via
server/identity_registry_api.py.
"""

from __future__ import annotations

import asyncio
import hashlib
import json as _json
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class AgentCapability(BaseModel):
    name: str
    version: str
    description: str
    verified: bool = False


class VerificationLevel(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    BASIC = "BASIC"
    ENHANCED = "ENHANCED"
    FULL = "FULL"


class AgentIdentity(BaseModel):
    did: str
    account_hash: str
    display_name: str
    capabilities: list[AgentCapability]
    verification_level: VerificationLevel
    reputation_score: int = Field(ge=0, le=100)
    total_deals: int
    dispute_rate: float
    registered_at: int
    last_active: int
    metadata_hash: str
    risk_score: int = Field(ge=0, le=100)
    slashed_count: int
    stake: int = Field(default=0, ge=0)

    @field_validator("did")
    @classmethod
    def validate_did(cls, v: str) -> str:
        if not v.startswith("did:casper:"):
            raise ValueError("DID must start with 'did:casper:'")
        return v


class IdentityRegistry:
    def __init__(self, decay_interval: int = 86400, decay_rate: float = 0.01):
        self._identities: dict[str, AgentIdentity] = {}
        self._account_to_did: dict[str, str] = {}
        self._lock = asyncio.Lock()
        self._decay_interval = decay_interval
        self._decay_rate = decay_rate

    async def register(
        self, account_hash: str, display_name: str, capabilities: list[AgentCapability] = None
    ) -> AgentIdentity:
        async with self._lock:
            if account_hash in self._account_to_did:
                raise ValueError("Account already registered")

            did = f"did:casper:{account_hash}"
            now = int(datetime.utcnow().timestamp())

            # Defensive copy to prevent shared mutable reference
            identity = AgentIdentity(
                did=did,
                account_hash=account_hash,
                display_name=display_name[:256],
                capabilities=list(capabilities) if capabilities else [],
                verification_level=VerificationLevel.UNVERIFIED,
                reputation_score=50,
                total_deals=0,
                dispute_rate=0.0,
                registered_at=now,
                last_active=now,
                metadata_hash="",
                risk_score=50,
                slashed_count=0,
                stake=0,
            )
            identity.metadata_hash = self._compute_metadata_hash(identity)

            self._identities[did] = identity
            self._account_to_did[account_hash] = did

            return identity

    async def get(self, did: str) -> Optional[AgentIdentity]:
        async with self._lock:
            return self._identities.get(did)

    async def get_by_account(self, account_hash: str) -> Optional[AgentIdentity]:
        async with self._lock:
            did = self._account_to_did.get(account_hash)
            return self._identities.get(did) if did else None

    async def update_reputation(self, did: str, completed: int = 0, disputed: int = 0) -> AgentIdentity:
        async with self._lock:
            identity = self._identities.get(did)
            if not identity:
                raise ValueError("Identity not found")

            new_deals = completed + disputed
            if new_deals > 0:
                total = identity.total_deals + new_deals
                new_dispute_rate = (identity.dispute_rate * identity.total_deals + disputed) / total
                identity.dispute_rate = new_dispute_rate
                identity.total_deals = total
                success_rate = (completed / total) * 100
                identity.reputation_score = min(100, max(0, round(success_rate)))

            # No new deals this call: nothing to recompute, leave the score
            # as-is (a bare "touch" call must not reset reputation to 0).
            identity.last_active = int(datetime.utcnow().timestamp())
            identity.metadata_hash = self._compute_metadata_hash(identity)

            return identity

    async def apply_decay(self, did: str) -> AgentIdentity:
        async with self._lock:
            identity = self._identities.get(did)
            if not identity:
                raise ValueError("Identity not found")

            now = int(datetime.utcnow().timestamp())
            periods = (now - identity.last_active) // self._decay_interval

            if periods > 0:
                decay_factor = (1 - self._decay_rate) ** periods
                identity.reputation_score = int(identity.reputation_score * decay_factor)
                identity.last_active = now
                identity.metadata_hash = self._compute_metadata_hash(identity)

            return identity

    async def slash(self, did: str, amount: int, reason: str) -> AgentIdentity:
        async with self._lock:
            identity = self._identities.get(did)
            if not identity:
                raise ValueError("Identity not found")

            identity.slashed_count += 1
            identity.stake = max(0, identity.stake - amount)
            identity.risk_score = min(100, identity.risk_score + 10)
            identity.reputation_score = max(0, identity.reputation_score - amount)
            identity.last_active = int(datetime.utcnow().timestamp())
            identity.metadata_hash = self._compute_metadata_hash(identity)

            return identity

    async def verify(self, did: str, level: VerificationLevel) -> AgentIdentity:
        async with self._lock:
            identity = self._identities.get(did)
            if not identity:
                raise ValueError("Identity not found")

            identity.verification_level = level
            identity.last_active = int(datetime.utcnow().timestamp())
            identity.metadata_hash = self._compute_metadata_hash(identity)

            return identity

    async def add_capability(self, did: str, capability: AgentCapability) -> AgentIdentity:
        async with self._lock:
            identity = self._identities.get(did)
            if not identity:
                raise ValueError("Identity not found")

            identity.capabilities.append(capability)
            identity.last_active = int(datetime.utcnow().timestamp())
            identity.metadata_hash = self._compute_metadata_hash(identity)

            return identity

    async def search(
        self,
        capability_name: str = None,
        min_reputation: int = 0,
        min_verification: VerificationLevel = VerificationLevel.UNVERIFIED,
    ) -> list[AgentIdentity]:
        async with self._lock:
            result = []
            level_order = list(VerificationLevel)
            min_level_idx = level_order.index(min_verification)

            for identity in self._identities.values():
                level_idx = level_order.index(identity.verification_level)
                if level_idx < min_level_idx:
                    continue
                if identity.reputation_score < min_reputation:
                    continue

                if capability_name:
                    caps = [c for c in identity.capabilities if c.name == capability_name]
                    if not caps:
                        continue

                result.append(identity)

            return result

    async def get_statistics(self) -> dict:
        async with self._lock:
            total = len(self._identities)
            if total == 0:
                return {
                    "total_agents": 0,
                    "avg_reputation": 0.0,
                    "distribution_by_level": {},
                }

            avg_rep = sum(i.reputation_score for i in self._identities.values()) / total
            distribution: dict[str, int] = {}
            for level in VerificationLevel:
                distribution[level.value] = 0
            for identity in self._identities.values():
                distribution[identity.verification_level.value] += 1

            return {
                "total_agents": total,
                "avg_reputation": avg_rep,
                "distribution_by_level": distribution,
            }

    def _compute_metadata_hash(self, identity: AgentIdentity) -> str:
        # Use structured JSON to avoid delimiter-based hash collisions
        data = _json.dumps(
            {
                "did": identity.did,
                "account_hash": identity.account_hash,
                "display_name": identity.display_name,
                "verification_level": identity.verification_level.value,
                "reputation_score": identity.reputation_score,
                "last_active": identity.last_active,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(data.encode()).hexdigest()


class DIDResolver:
    def __init__(self, registry: IdentityRegistry):
        self._registry = registry

    async def resolve(self, did: str) -> Optional[AgentIdentity]:
        return await self._registry.get(did)

    @staticmethod
    def parse_did(did: str) -> tuple[str, str, str]:
        parts = did.split(":")
        if len(parts) != 3:
            raise ValueError("Invalid DID format")
        return parts[0], parts[1], parts[2]

    @staticmethod
    def is_valid_did(did: str) -> bool:
        try:
            method, network, account_hash = DIDResolver.parse_did(did)
            return method == "did" and network == "casper" and len(account_hash) > 0
        except ValueError:
            return False
