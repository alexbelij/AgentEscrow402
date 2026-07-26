"""FastAPI router for gaming-reward escrow (T3.2).

End-to-end flow served by these endpoints:

  1. POST /gaming/commit          — operator commits a reward sheet.
     Returns the root the caller pins onto the escrow record. The
     sheet stays with the operator; the API also caches it in-memory
     (`_SHEETS`) so subsequent `prove` calls can build inclusion
     proofs without the operator re-uploading it.

  2. GET  /gaming/proof/{root}/{player_id} — an individual winner
     requests their inclusion proof for a locked round. Anyone can
     verify a proof against the root client-side; this endpoint is a
     convenience for demos.

  3. POST /gaming/lock            — locks a prize pool against a
     previously committed root. The escrow is opened with pool
     `prize_pool_motes`; releases go through /gaming/claim.

  4. POST /gaming/claim           — a winner claims their reward by
     submitting an inclusion proof. Escrow is decremented atomically
     inside a lock; double-claim and over-pool are rejected via
     `evaluate_claim`.

  5. GET  /gaming/escrow/{escrow_id} — inspect an escrow's current
     state (remaining pool, claimed players, sheet metadata).

Storage: in-memory (`_SHEETS`, `_ESCROWS`). Persistence to the main
db.py layer is intentionally out of scope for this demo module; the
math and the API contract are the deliverable. Moving to Postgres is
a mechanical follow-up (mirror the two dicts with tables + a
transaction around the claim decrement).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from server.gaming_reward import (
    ClaimResult,
    ProofStep,
    RewardCommitment,
    RewardInclusionProof,
    RewardLeaf,
    build_claim_proof,
    commit_results,
    evaluate_claim,
)

router = APIRouter(prefix="/gaming", tags=["gaming"])

# ---------------------------------------------------------------------------
# Pydantic wire types (thin wrappers over the dataclasses)
# ---------------------------------------------------------------------------


class RewardLeafDTO(BaseModel):
    player_id: str = Field(..., min_length=1, max_length=128)
    reward_amount: int = Field(..., ge=1, description="Reward in the escrow's unit (motes for Casper)")
    rank: int = Field(..., ge=1, description="Leaderboard position (1 = winner)")


class ProofStepDTO(BaseModel):
    hash: str = Field(..., min_length=64, max_length=64)
    position: str = Field(..., pattern=r"^(left|right)$")


class RewardInclusionProofDTO(BaseModel):
    player_id: str
    reward_amount: int
    rank: int
    siblings: list[ProofStepDTO]


class CommitRequest(BaseModel):
    round_id: str = Field(..., min_length=1, max_length=64, description="Operator-chosen round identifier")
    leaves: list[RewardLeafDTO] = Field(..., description="Full reward sheet (kept private on the operator side)")


class CommitResponse(BaseModel):
    root: str
    total_committed: int
    winners_count: int
    round_id: str


class LockRequest(BaseModel):
    round_id: str
    prize_pool_motes: int = Field(..., ge=1)


class LockResponse(BaseModel):
    escrow_id: str
    root: str
    prize_pool_motes: int
    winners_count: int


class ClaimRequest(BaseModel):
    escrow_id: str
    proof: RewardInclusionProofDTO


class ClaimResponse(BaseModel):
    ok: bool
    amount_released: int
    reason: str
    remaining_pool: int


class EscrowStateResponse(BaseModel):
    escrow_id: str
    root: str
    round_id: str
    prize_pool_motes: int
    remaining_pool: int
    winners_count: int
    claimed_players: list[str]


# ---------------------------------------------------------------------------
# In-memory storage
# ---------------------------------------------------------------------------


@dataclass
class _StoredSheet:
    round_id: str
    leaves: list[RewardLeaf]
    commitment: RewardCommitment


@dataclass
class _EscrowState:
    escrow_id: str
    round_id: str
    root: str
    prize_pool_motes: int
    remaining_pool: int
    winners_count: int
    claimed: set[str] = field(default_factory=set)


# key: root (unique per sheet)
_SHEETS: dict[str, _StoredSheet] = {}
# key: escrow_id
_ESCROWS: dict[str, _EscrowState] = {}
# per-escrow lock to make claim decrement atomic
_ESCROW_LOCKS: dict[str, asyncio.Lock] = {}


def _reset_state_for_tests() -> None:
    """Test hook — wipe in-memory state between tests."""
    _SHEETS.clear()
    _ESCROWS.clear()
    _ESCROW_LOCKS.clear()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/commit", response_model=CommitResponse)
def commit_sheet(req: CommitRequest) -> CommitResponse:
    """Commit a reward sheet.

    The operator uploads the full sheet; the server hashes it into a
    Merkle root and caches the sheet so winners can later fetch their
    proofs. The response's `root` is what the operator pins onto the
    escrow (via `/gaming/lock`) — this is the only piece of data that
    needs to be public.
    """
    if not req.leaves:
        raise HTTPException(status_code=400, detail="reward sheet must be non-empty")

    seen: set[str] = set()
    for lf in req.leaves:
        if lf.player_id in seen:
            raise HTTPException(status_code=400, detail=f"duplicate player_id on sheet: {lf.player_id}")
        seen.add(lf.player_id)

    leaves = [RewardLeaf(lf.player_id, lf.reward_amount, lf.rank) for lf in req.leaves]
    commitment = commit_results(leaves)
    _SHEETS[commitment.root] = _StoredSheet(round_id=req.round_id, leaves=leaves, commitment=commitment)
    return CommitResponse(
        root=commitment.root,
        total_committed=commitment.total_committed,
        winners_count=commitment.winners_count,
        round_id=req.round_id,
    )


@router.get("/proof/{root}/{player_id}", response_model=RewardInclusionProofDTO)
def get_claim_proof(root: str, player_id: str) -> RewardInclusionProofDTO:
    """Build the inclusion proof a specific winner will submit."""
    sheet = _SHEETS.get(root)
    if sheet is None:
        raise HTTPException(status_code=404, detail="unknown reward root — commit the sheet first")

    proof = build_claim_proof(sheet.leaves, player_id)
    if proof is None:
        raise HTTPException(status_code=404, detail=f"player {player_id} is not on this reward sheet")

    return RewardInclusionProofDTO(
        player_id=proof.player_id,
        reward_amount=proof.reward_amount,
        rank=proof.rank,
        siblings=[ProofStepDTO(hash=s.hash, position=s.position) for s in proof.siblings],
    )


@router.post("/lock", response_model=LockResponse)
def lock_prize_pool(req: LockRequest) -> LockResponse:
    """Lock the prize pool against a previously committed reward sheet.

    Refuses to lock if the sheet's `total_committed` exceeds
    `prize_pool_motes` — a solvency guard.
    """
    # Find the sheet by round_id (a round has exactly one committed sheet).
    matching = [s for s in _SHEETS.values() if s.round_id == req.round_id]
    if not matching:
        raise HTTPException(status_code=404, detail=f"no committed sheet found for round_id={req.round_id}")
    if len(matching) > 1:
        raise HTTPException(status_code=409, detail=f"round_id={req.round_id} has multiple commitments — ambiguous")
    sheet = matching[0]

    if sheet.commitment.total_committed > req.prize_pool_motes:
        raise HTTPException(
            status_code=400,
            detail=(
                f"insolvent commitment: total_committed={sheet.commitment.total_committed} "
                f"exceeds prize_pool_motes={req.prize_pool_motes}"
            ),
        )

    escrow_id = f"gaming_{sheet.commitment.root[:16]}"
    if escrow_id in _ESCROWS:
        raise HTTPException(status_code=409, detail=f"escrow already locked for this round: {escrow_id}")

    _ESCROWS[escrow_id] = _EscrowState(
        escrow_id=escrow_id,
        round_id=req.round_id,
        root=sheet.commitment.root,
        prize_pool_motes=req.prize_pool_motes,
        remaining_pool=req.prize_pool_motes,
        winners_count=sheet.commitment.winners_count,
    )
    _ESCROW_LOCKS[escrow_id] = asyncio.Lock()
    return LockResponse(
        escrow_id=escrow_id,
        root=sheet.commitment.root,
        prize_pool_motes=req.prize_pool_motes,
        winners_count=sheet.commitment.winners_count,
    )


@router.post("/claim", response_model=ClaimResponse)
async def claim_reward(req: ClaimRequest) -> ClaimResponse:
    """A winner claims their reward by submitting an inclusion proof."""
    escrow = _ESCROWS.get(req.escrow_id)
    if escrow is None:
        raise HTTPException(status_code=404, detail=f"escrow not found: {req.escrow_id}")

    proof = RewardInclusionProof(
        player_id=req.proof.player_id,
        reward_amount=req.proof.reward_amount,
        rank=req.proof.rank,
        siblings=[ProofStep(hash=s.hash, position=s.position) for s in req.proof.siblings],
    )

    lock = _ESCROW_LOCKS[req.escrow_id]
    async with lock:
        result: ClaimResult = evaluate_claim(
            proof=proof,
            locked_root=escrow.root,
            already_claimed=escrow.claimed,
            prize_pool_remaining=escrow.remaining_pool,
        )
        if result.ok:
            escrow.remaining_pool -= result.amount_to_release
            escrow.claimed.add(proof.player_id)

        return ClaimResponse(
            ok=result.ok,
            amount_released=result.amount_to_release,
            reason=result.reason,
            remaining_pool=escrow.remaining_pool,
        )


@router.get("/escrow/{escrow_id}", response_model=EscrowStateResponse)
def get_escrow_state(escrow_id: str) -> EscrowStateResponse:
    """Read-only view of an escrow's claim state."""
    escrow = _ESCROWS.get(escrow_id)
    if escrow is None:
        raise HTTPException(status_code=404, detail=f"escrow not found: {escrow_id}")
    return EscrowStateResponse(
        escrow_id=escrow.escrow_id,
        root=escrow.root,
        round_id=escrow.round_id,
        prize_pool_motes=escrow.prize_pool_motes,
        remaining_pool=escrow.remaining_pool,
        winners_count=escrow.winners_count,
        claimed_players=sorted(escrow.claimed),
    )
