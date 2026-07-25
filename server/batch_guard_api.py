"""FastAPI wiring for the deterministic batch cap/quorum guard (T3.3).

Exposes a single `POST /escrows/batch-preview` route that returns the
`BatchDecision` without mutating any state or hitting Casper. Useful for:

* SDK clients running a client-side pre-flight before spending gas.
* Judges reproducing the exact admit/reject decision the pod would make
  for a given batch, using nothing but the store.
* Regression fixtures for the future WASM guard: capture Decision JSON
  for a fixed input and diff the Rust output against it.

The existing `/escrows/batch-release` route is refactored in `app.py` to
call `batch_guard.evaluate_batch` internally so the two paths cannot
drift.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from . import batch_guard as bg
from .config import Config, get_config
from .sandbox import SandboxStore

router = APIRouter(prefix="/escrows", tags=["batch-guard"])


class BatchPreviewRequest(BaseModel):
    action: str = Field(default="release", description='Either "release" or "cancel".')
    service_hashes: list[str]
    arbiter_pubkeys: list[str] = Field(default_factory=list)
    arbiter_signatures: list[str] = Field(default_factory=list)


class BatchRejectionResponse(BaseModel):
    code: str
    message: str
    service_hash: str | None = None
    detail: dict = Field(default_factory=dict)


class BatchPreviewResponse(BaseModel):
    admit: bool
    action: str
    needs_quorum: bool
    valid_arbiter_votes: int
    required_quorum: int
    above_cap_hashes: list[str]
    rejections: list[BatchRejectionResponse]
    max_batch_size: int


def _load_snapshots(store: SandboxStore, hashes: list[str]) -> dict[str, bg.EscrowSnapshot]:
    """Load the snapshots the guard needs from the sandbox store.

    Deduplicates by service_hash; the guard flags dupes separately so the
    caller sees the reason instead of a silent merge.
    """
    snaps: dict[str, bg.EscrowSnapshot] = {}
    for sh in set(hashes):
        record = store.get_escrow(sh)
        if record is None:
            continue
        snaps[sh] = bg.EscrowSnapshot(
            service_hash=sh,
            status=_normalize_status(record.status),
            amount_motes=int(record.amount),
        )
    return snaps


def _normalize_status(raw) -> str:
    """Coerce an EscrowStatus enum (or a plain string) to its bare value.

    `SandboxStore.get_escrow` returns `EscrowStatus` enum members whose
    `str()` is `"EscrowStatus.PENDING"`; the guard compares against plain
    lowercase `"pending"`. Use `.value` when available, and fall back to
    a suffix split for defensiveness.
    """
    if hasattr(raw, "value"):
        return str(raw.value).lower()
    text = str(raw)
    if "." in text:
        text = text.rsplit(".", 1)[-1]
    return text.lower()


def _get_sandbox_dep():
    # Late import to avoid circular dependency between app.py and this router.
    from .app import get_sandbox

    return get_sandbox


@router.post("/batch-preview", response_model=BatchPreviewResponse)
async def preview_batch(
    req: BatchPreviewRequest,
    cfg: Config = Depends(get_config),
    store: SandboxStore = Depends(_get_sandbox_dep()),
) -> BatchPreviewResponse:
    """Dry-run the batch cap/quorum guard.

    Returns the exact `BatchDecision` the mutating route would compute,
    without hitting Casper or updating any local state. Never returns
    non-200 for a policy rejection: the rejection is in the body's
    `admit=false` + `rejections[]`. Only structural bugs (e.g. empty
    service_hashes list — which is itself a rejection code, not a raise)
    would fail the request.
    """
    if not isinstance(req.service_hashes, list):
        raise HTTPException(status_code=422, detail="service_hashes must be an array")

    snapshots = _load_snapshots(store, req.service_hashes)

    decision = bg.evaluate_batch(
        action=req.action,
        service_hashes=req.service_hashes,
        snapshots=snapshots,
        release_cap_motes=cfg.release_cap_motes,
        arbiter_registered=cfg.arbiter_pubkeys,
        arbiter_threshold=cfg.arbiter_threshold,
        arbiter_pubkeys=req.arbiter_pubkeys,
        arbiter_signatures=req.arbiter_signatures,
    )

    return BatchPreviewResponse(
        admit=decision.admit,
        action=decision.action,
        needs_quorum=decision.needs_quorum,
        valid_arbiter_votes=decision.valid_arbiter_votes,
        required_quorum=decision.required_quorum,
        above_cap_hashes=list(decision.above_cap_hashes),
        rejections=[
            BatchRejectionResponse(
                code=r.code,
                message=r.message,
                service_hash=r.service_hash,
                detail=r.detail,
            )
            for r in decision.rejections
        ],
        max_batch_size=bg.MAX_BATCH_SIZE,
    )


__all__ = [
    "router",
    "BatchPreviewRequest",
    "BatchPreviewResponse",
    "BatchRejectionResponse",
]
