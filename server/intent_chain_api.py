"""FastAPI router exposing `server/intent_chain.py`'s multi-hop A2A
choreography (AE-M1).

A choreography is a planned chain of escrow hops between agents
(``agent A -> agent B -> agent C -> ...``). Each hop is created and
released through the existing `/escrow` and `/release` endpoints
unchanged -- this router adds bookkeeping only:

1. `POST /intents` -- declare the planned agent path up front. Returns
   `intent_id` (server-issued, unless the caller supplies one) and the
   number of planned hops.
2. `POST /intents/{intent_id}/hops` -- register hop N's `service_hash`
   (the escrow's existing service_hash, created separately via
   `POST /escrow`) against the intent. Must be called in hop order.
3. `POST /intents/{intent_id}/hops/{hop_index}/attest` -- called after
   hop N's escrow has been released (via `POST /release`), to fold a
   `hop_attested` audit event into the intent's `chain_root_hash`.
4. `GET /intents/{intent_id}` -- full choreography state: hops, which
   are attested, and the current `chain_root_hash`. A judge/verifier
   can independently recompute the root from the returned
   `attestation_event_ids` via `audit_trace.compute_chain_root`.

Deliberately NOT wired into `/escrow` or `/release` bodies: those two
endpoints are the most security-sensitive, most-tested paths in the
whole service (release-cap arbiter quorum, FSM guards, wallet-tx
confirmation). Keeping choreography bookkeeping as separate calls means
zero risk of regressing that path -- a caller opts into chaining
explicitly, on top of the ordinary escrow lifecycle it would run anyway.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from server.intent_chain import IntentChainError, IntentChainStore

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/intents", tags=["intent-chain"])

# Single process-lifetime in-memory store, same pattern as
# server/identity_registry_api.py's module-level `_registry`.
_store = IntentChainStore()


class DeclareIntentRequest(BaseModel):
    intent_id: str | None = Field(
        default=None,
        max_length=128,
        description="Caller-supplied intent id. Omit to have the server "
        "generate one (uuid4 hex).",
    )
    agent_path: list[str] = Field(
        ...,
        min_length=2,
        max_length=17,
        description="Ordered agent identifiers, e.g. ['A', 'B', 'C'] for "
        "a 2-hop A->B->C choreography. len(agent_path) - 1 hops planned.",
    )


class ChainEscrowRequest(BaseModel):
    service_hash: str = Field(..., min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    hop_index: int = Field(..., ge=0)


class AttestHopRequest(BaseModel):
    service_hash: str = Field(..., min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")


class HopView(BaseModel):
    hop_index: int
    service_hash: str
    from_agent: str
    to_agent: str
    attested: bool


class IntentView(BaseModel):
    intent_id: str
    agent_path: list[str]
    planned_hop_count: int
    attested_hop_count: int
    is_complete: bool
    chain_root_hash: str
    attestation_event_ids: list[str]
    hops: list[HopView]


def _to_view(intent) -> IntentView:
    hops = [
        HopView(
            hop_index=h.hop_index,
            service_hash=h.service_hash,
            from_agent=h.from_agent,
            to_agent=h.to_agent,
            attested=h.attested,
        )
        for h in sorted(intent.hops.values(), key=lambda h: h.hop_index)
    ]
    return IntentView(
        intent_id=intent.intent_id,
        agent_path=intent.agent_path,
        planned_hop_count=intent.planned_hop_count,
        attested_hop_count=intent.attested_hop_count,
        is_complete=intent.is_complete,
        chain_root_hash=intent.chain_root_hash,
        attestation_event_ids=intent.ordered_attestation_event_ids(),
        hops=hops,
    )


@router.post("", response_model=IntentView)
async def declare_intent(req: DeclareIntentRequest):
    intent_id = req.intent_id or uuid.uuid4().hex
    try:
        intent = _store.declare_intent(intent_id, req.agent_path)
    except IntentChainError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return _to_view(intent)


@router.get("/{intent_id}", response_model=IntentView)
async def get_intent(intent_id: str):
    try:
        intent = _store.get_intent(intent_id)
    except IntentChainError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return _to_view(intent)


@router.post("/{intent_id}/hops", response_model=IntentView)
async def chain_escrow(intent_id: str, req: ChainEscrowRequest):
    try:
        _store.chain_escrow(intent_id, req.service_hash, req.hop_index)
        intent = _store.get_intent(intent_id)
    except IntentChainError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return _to_view(intent)


@router.post("/{intent_id}/hops/{hop_index}/attest", response_model=IntentView)
async def attest_hop(intent_id: str, hop_index: int, req: AttestHopRequest):
    try:
        _store.attest_hop(intent_id, req.service_hash, hop_index)
        intent = _store.get_intent(intent_id)
    except IntentChainError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return _to_view(intent)

