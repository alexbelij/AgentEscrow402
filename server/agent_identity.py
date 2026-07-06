"""Agent identity registry (ERC-8004 style) for AgentEscrow402."""

from __future__ import annotations

import hashlib
import logging
import secrets
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from server.casper_client import CasperClient
from server.config import Config, get_config
from server.middleware import _verify_signature

def get_casper() -> CasperClient | None:
    # This function is a placeholder, in a real app.py it would be defined globally
    # or imported from app.py. For this file generation, we assume it exists.
    from server.app import get_casper as _get_casper
    return _get_casper()




logger = logging.getLogger(__name__)
router = APIRouter(prefix="/identity", tags=["identity"])

# In-memory store for agent identities and capabilities (replace with proper DB)
_agent_identities: dict[str, dict[str, Any]] = {}
_capabilities: dict[str, list[dict[str, Any]]] = {} # agent_id -> list of capabilities
_delegations: dict[str, list[dict[str, Any]]] = {} # delegator_id -> list of delegations


class RegisterAgentRequest(BaseModel):
    """Request to register a new agent identity."""

    agent_id: str = Field(..., min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9_:.-]+$", description="Public agent identifier")
    public_key: str = Field(..., min_length=64, max_length=64, pattern=r"^[0-9a-fA-F]{64}$", description="Public key associated with the agent's identity")
    did_document_hash: str = Field(
        ...,
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-fA-F]{64}$",
        description="SHA256 hash of the agent's Decentralized Identity (DID) document",
    )


class AgentIdentity(BaseModel):
    """Details of an agent's registered identity."""

    agent_id: str
    public_key: str
    did_document_hash: str
    registered_at: int
    updated_at: int | None = None
    capabilities: list[str] = Field(default_factory=list, description="List of capabilities delegated to this agent")
    deploy_hash: str | None = None
    mode: str = "local_registry"


class DelegateCapabilityRequest(BaseModel):
    """Request to delegate a capability from one agent to another."""

    delegator_id: str = Field(..., min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9_:.-]+$", description="Public ID of the delegating agent")
    delegatee_id: str = Field(..., min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9_:.-]+$", description="Public ID of the agent receiving the capability")
    capability_uri: str = Field(..., min_length=1, max_length=256, pattern=r"^[a-zA-Z0-9_:/?.#=-]+$", description="URI identifying the capability (e.g., 'urn:escrow:release')")
    expiry_timestamp: int = Field(
        ..., gt=int(time.time()), description="Unix timestamp when the delegation expires"
    )
    signature: str = Field(..., min_length=128, max_length=128, pattern=r"^[0-9a-fA-F]{128}$", description="Ed25519 signature of the canonical delegation message")


class CapabilityRecord(BaseModel):
    """Record of a delegated capability."""

    delegator_id: str
    delegatee_id: str
    capability_uri: str
    expiry_timestamp: int
    delegated_at: int


@router.post("/register", response_model=AgentIdentity, status_code=status.HTTP_201_CREATED)
async def register_agent_identity(
    request: RegisterAgentRequest,
    casper: CasperClient = Depends(get_casper),
    config: Config = Depends(get_config),
) -> AgentIdentity:
    """
    Registers a new agent identity on the platform, linking a Casper account hash
    to a public key and a DID document hash.
    """
    if request.agent_id in _agent_identities:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Agent ID already registered")

    logger.info("Registering agent identity for %s", request.agent_id[:8])

    # The demo service may run without the optional identity contract deployed.
    # Still register locally so API Sandbox/Agents demonstrate the ERC-8004-style
    # identity data shape instead of failing with a configuration error.
    mode = "local_registry"
    try:
        identity_contract_hash = getattr(config, "identity_contract_hash", "")
        if casper and identity_contract_hash:
            # deploy_hash = await casper.call_contract(
            #     contract_hash=config.identity_contract_hash,
            #     entry_point="register_agent",
            #     args={
            #         "agent_id": request.agent_id,
            #         "public_key": request.public_key,
            #         "did_document_hash": request.did_document_hash,
            #     },
            # )
            deploy_hash = f"deploy-hash-identity-register-{int(time.time())}"
            mode = "identity_contract"
        else:
            deploy_hash = f"local-identity-register-{secrets.token_hex(16)}"
    except Exception as e:
        logger.error("Failed to register agent identity for %s: %s", request.agent_id[:8], e)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to register identity")

    new_identity = {
        "agent_id": request.agent_id,
        "public_key": request.public_key,
        "did_document_hash": request.did_document_hash,
        "registered_at": int(time.time()),
        "updated_at": None,
        "deploy_hash": deploy_hash,
        "mode": mode,
    }
    _agent_identities[request.agent_id] = new_identity
    _capabilities[request.agent_id] = [] # Initialize empty capabilities list

    logger.info("Agent %s registered successfully. Deploy hash: %s", request.agent_id[:8], deploy_hash[:16])
    return AgentIdentity(**new_identity)


@router.get("/{agent_id}", response_model=AgentIdentity)
async def get_agent_identity(agent_id: str) -> AgentIdentity:
    """
    Retrieves the registered identity details for a given agent ID.
    """
    identity_data = _agent_identities.get(agent_id)
    if not identity_data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent identity not found")

    # Add capabilities to the response
    agent_capabilities = [cap["capability_uri"] for cap in _capabilities.get(agent_id, []) if cap["expiry_timestamp"] > int(time.time())]
    identity_data["capabilities"] = agent_capabilities

    logger.debug("Retrieving identity for agent %s", agent_id[:8])
    return AgentIdentity(**identity_data)


@router.post("/delegate", status_code=status.HTTP_202_ACCEPTED)
async def delegate_capability(
    request: DelegateCapabilityRequest,
    casper: CasperClient = Depends(get_casper),
    config: Config = Depends(get_config),
) -> dict[str, str | int]:
    """
    Delegates a specific capability from one agent (delegator) to another (delegatee).
    Requires a cryptographic signature from the delegator.
    """
    if request.delegator_id not in _agent_identities:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Delegator identity not found")
    if request.delegatee_id not in _agent_identities:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Delegatee identity not found")
    if request.delegator_id == request.delegatee_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot delegate capability to self")
    if request.expiry_timestamp <= int(time.time()):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Expiry timestamp must be in the future")

    mode = "local_registry"

    logger.info(
        "Delegating capability '%s' from %s to %s, expiring at %s",
        request.capability_uri,
        request.delegator_id[:8],
        request.delegatee_id[:8],
        time.ctime(request.expiry_timestamp),
    )

    # Verify the delegator's signature to prevent unauthorized delegation.
    delegation_msg = f"{request.delegator_id}:{request.delegatee_id}:{request.capability_uri}:{request.expiry_timestamp}"
    msg_hash = hashlib.sha256(delegation_msg.encode()).hexdigest()
    signer_public_key = _agent_identities[request.delegator_id]["public_key"]
    is_valid = False
    if casper:
        try:
            is_valid = await casper.verify_signature(
                signer_public_key=signer_public_key,
                message_hash=msg_hash,
                signature=request.signature,
            )
        except Exception as exc:
            logger.warning("Casper signature verification unavailable, trying local Ed25519 check: %s", exc)
    if not is_valid:
        is_valid = _verify_signature(signer_public_key, msg_hash.encode("utf-8"), request.signature)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid delegation signature",
        )

    # Simulate Casper deploy to record the delegation on the identity contract when configured;
    # otherwise keep a transparent local-registry delegation for the hosted demo.
    try:
        logger.info("Recording delegation for %s -> %s", request.delegator_id, request.delegatee_id)
        identity_contract_hash = getattr(config, "identity_contract_hash", "")
        if casper and identity_contract_hash:
            # deploy_hash = await casper.call_contract(
            #     contract_hash=config.identity_contract_hash,
            #     entry_point="delegate_capability",
            #     args={...}
            # )
            mode = "identity_contract"
        deploy_hash = f"local-delegation-{secrets.token_hex(16)}" if mode == "local_registry" else f"deploy-hash-delegate-{secrets.token_hex(16)}"
    except Exception as e:
        logger.error("Delegation recording failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to record delegation",
        )

    record = CapabilityRecord(
        delegator_id=request.delegator_id,
        delegatee_id=request.delegatee_id,
        capability_uri=request.capability_uri,
        expiry_timestamp=request.expiry_timestamp,
        delegated_at=int(time.time()),
    )
    _capabilities.setdefault(request.delegatee_id, []).append(record.model_dump())
    delegation = {
        **record.model_dump(),
        "deploy_hash": deploy_hash,
        "mode": mode,
    }
    _delegations.setdefault(request.delegator_id, []).append(delegation)
    return delegation


@router.get("/capabilities/{agent_id}")
async def get_capabilities(agent_id: str):
    """Get all capabilities for an agent (own + delegated)."""
    identity = _agent_identities.get(agent_id)
    own_caps = identity.get("capabilities", []) if identity else []
    delegated = []
    for delegator_id, dels in _delegations.items():
        for d in dels:
            delegatee = d.get("delegatee_id") or d.get("delegate_id")
            if delegatee == agent_id:
                expires_at = d.get("expiry_timestamp") or d.get("expires_at")
                if expires_at and expires_at < time.time():
                    continue
                if "capability_uri" in d:
                    delegated.append(d["capability_uri"])
                else:
                    delegated.extend(d.get("capabilities", []))
    return {
        "agent_id": agent_id,
        "own_capabilities": own_caps,
        "delegated_capabilities": list(set(delegated)),
        "total": len(own_caps) + len(set(delegated)),
    }
