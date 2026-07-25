"""Deterministic batch cap/quorum guard (T3.3).

Extracts the ad-hoc server-side batch-release validation currently inlined
in `server/app.py::batch_release_escrows` into a *pure*, deterministic
validator with a stable typed result. This is the exact same policy that
must eventually be enforced inside the escrow-manager WASM contract so a
malicious relayer cannot bypass it by talking to Casper directly.

Design goals
------------
1. **Deterministic.** No I/O, no side effects, no time-of-day. Given the
   same inputs it always produces the same output — so a jury can replay
   the check byte-for-byte, and the same logic can be transliterated to
   Rust for the on-chain guard without behavioural drift.
2. **Typed rejections.** Every failure carries a machine-readable
   `code` from a fixed enum. FastAPI wraps them into HTTP 422 with the
   code intact; the SDK maps them 1:1 to typed exceptions.
3. **On-chain parity.** The canonical message an arbiter signs
   (`{action}:{service_hash}:cap_approval`) already matches the Rust
   contract's `build_cap_approval_message`. The vote-counting and
   threshold logic here mirrors what the WASM will do, so the migration
   is a straight transliteration.
4. **Zero new deps.** Uses only `arbiter_crypto` (already in the tree)
   and stdlib.

Not in scope for T3.3
---------------------
- Actually rewriting the escrow-manager WASM. The spec is written and the
  Python reference is the oracle; the Rust follow-up is tracked in
  `docs/tier3/T3.3-batch-cap-quorum-guard.md` under "WASM migration".
- Signing arbiter votes on the client. That helper already lives in
  `arbiter_crypto.py` on the verifier side; producing votes is by design
  outside the backend's trust boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from . import arbiter_crypto

# Same MAX_BATCH_SIZE enforced by the existing batch-release route.
MAX_BATCH_SIZE = 50

BATCH_ACTIONS = frozenset({"release", "cancel"})


@dataclass(frozen=True)
class EscrowSnapshot:
    """Minimal escrow projection the guard needs.

    Kept intentionally narrow so callers can build it from any store
    (SandboxStore, Postgres row, RPC response) without leaking a full
    ORM object into the pure validator.
    """

    service_hash: str
    status: str  # "pending" | "released" | "cancelled" | "disputed"
    amount_motes: int


@dataclass(frozen=True)
class BatchRejection:
    """One typed reason the batch was rejected.

    `code` is stable and safe to switch on client-side. `service_hash`
    identifies the offending escrow when the failure is per-escrow;
    global failures (empty batch, oversize, quorum shortfall) leave it
    `None`.
    """

    code: str
    message: str
    service_hash: str | None = None
    detail: dict = field(default_factory=dict)


@dataclass(frozen=True)
class BatchDecision:
    """Result of `evaluate_batch`. `admit=True` iff `rejections` is empty."""

    admit: bool
    action: str
    needs_quorum: bool
    valid_arbiter_votes: int
    required_quorum: int
    above_cap_hashes: tuple[str, ...]
    rejections: tuple[BatchRejection, ...]

    @property
    def first_reason(self) -> str | None:
        return self.rejections[0].code if self.rejections else None


# ── Rejection codes ────────────────────────────────────────────────────

CODE_EMPTY_BATCH = "empty_batch"
CODE_BATCH_TOO_LARGE = "batch_too_large"
CODE_UNKNOWN_ACTION = "unknown_action"
CODE_ARBITER_LIST_MISMATCH = "arbiter_list_length_mismatch"
CODE_DUPLICATE_SERVICE_HASH = "duplicate_service_hash"
CODE_ESCROW_NOT_FOUND = "escrow_not_found"
CODE_ESCROW_NOT_PENDING = "escrow_not_pending"
CODE_QUORUM_SHORTFALL = "quorum_shortfall"


def evaluate_batch(
    *,
    action: str,
    service_hashes: Iterable[str],
    snapshots: dict[str, EscrowSnapshot],
    release_cap_motes: int,
    arbiter_registered: tuple[str, ...],
    arbiter_threshold: int,
    arbiter_pubkeys: list[str] | None = None,
    arbiter_signatures: list[str] | None = None,
    max_batch_size: int = MAX_BATCH_SIZE,
) -> BatchDecision:
    """Pure, deterministic evaluation of a batch lifecycle request.

    Parameters mirror the shape of an on-chain contract call so this can
    be transliterated to Rust:

    * `snapshots` — the caller has already loaded every referenced escrow
      from its store. The guard does NOT do I/O.
    * `arbiter_registered` — the current registered arbiter set (from
      config or on-chain named key).
    * `arbiter_pubkeys` / `arbiter_signatures` — the client-supplied
      cap-approval votes; only checked if the batch actually needs them.

    Returns a `BatchDecision`. Callers should inspect `admit`; if
    `False`, `rejections` gives the full ordered list of failures.
    """
    action = action.lower()
    hashes = list(service_hashes)
    rejections: list[BatchRejection] = []

    # ── Structural checks (fail fast) ──────────────────────────────────
    if action not in BATCH_ACTIONS:
        rejections.append(
            BatchRejection(
                code=CODE_UNKNOWN_ACTION,
                message=f"action must be one of {sorted(BATCH_ACTIONS)}, got {action!r}",
            )
        )
        return BatchDecision(
            admit=False,
            action=action,
            needs_quorum=False,
            valid_arbiter_votes=0,
            required_quorum=arbiter_threshold,
            above_cap_hashes=(),
            rejections=tuple(rejections),
        )

    if not hashes:
        rejections.append(BatchRejection(code=CODE_EMPTY_BATCH, message="service_hashes must be non-empty"))
    if len(hashes) > max_batch_size:
        rejections.append(
            BatchRejection(
                code=CODE_BATCH_TOO_LARGE,
                message=f"batch size {len(hashes)} exceeds MAX_BATCH_SIZE ({max_batch_size})",
            )
        )

    pubkeys = list(arbiter_pubkeys or [])
    signatures = list(arbiter_signatures or [])
    if len(pubkeys) != len(signatures):
        rejections.append(
            BatchRejection(
                code=CODE_ARBITER_LIST_MISMATCH,
                message=(
                    f"arbiter_pubkeys ({len(pubkeys)}) and arbiter_signatures "
                    f"({len(signatures)}) must have the same length"
                ),
            )
        )

    # Duplicate service_hash inside one batch is disallowed — otherwise a
    # relayer could budget the same escrow's cap-approval quorum against
    # itself multiple times.
    seen: set[str] = set()
    dupes: list[str] = []
    for sh in hashes:
        if sh in seen:
            dupes.append(sh)
        else:
            seen.add(sh)
    for sh in dupes:
        rejections.append(
            BatchRejection(
                code=CODE_DUPLICATE_SERVICE_HASH,
                message=f"escrow {sh[:16]}… appears more than once in batch",
                service_hash=sh,
            )
        )

    # ── Per-escrow checks + cap detection ──────────────────────────────
    above_cap: list[str] = []
    for sh in hashes:
        snap = snapshots.get(sh)
        if snap is None:
            rejections.append(
                BatchRejection(
                    code=CODE_ESCROW_NOT_FOUND,
                    message=f"escrow {sh[:16]}… not found",
                    service_hash=sh,
                )
            )
            continue
        if snap.status != "pending":
            rejections.append(
                BatchRejection(
                    code=CODE_ESCROW_NOT_PENDING,
                    message=f"escrow {sh[:16]}… is {snap.status}, not pending",
                    service_hash=sh,
                    detail={"actual_status": snap.status},
                )
            )
            continue
        if action == "release" and snap.amount_motes > release_cap_motes:
            above_cap.append(sh)

    # Cancel never requires a cap-approval quorum: refund path is
    # unconditional up to the caller-authorization check enforced on-chain.
    needs_quorum = bool(above_cap) and action == "release" and bool(arbiter_registered)
    valid_votes = 0

    if needs_quorum:
        # A single cap-approval message is bound to ONE service_hash, so
        # a caller must submit enough votes for EACH above-cap escrow. We
        # take the MIN of per-escrow valid-vote counts as the effective
        # batch-wide quorum: the batch is only admissible if every
        # above-cap escrow independently meets the threshold, and the
        # decision reports the tightest bottleneck.
        min_valid = None
        for sh in above_cap:
            n = arbiter_crypto.count_valid_cap_approval_votes(
                pubkeys,
                signatures,
                arbiter_registered,
                "release",
                sh,
            )
            if min_valid is None or n < min_valid:
                min_valid = n
            if n < arbiter_threshold:
                rejections.append(
                    BatchRejection(
                        code=CODE_QUORUM_SHORTFALL,
                        message=(
                            f"escrow {sh[:16]}… exceeds release_cap "
                            f"({release_cap_motes} motes); only {n} valid arbiter "
                            f"signature(s), need >= {arbiter_threshold}"
                        ),
                        service_hash=sh,
                        detail={
                            "valid_votes": n,
                            "required": arbiter_threshold,
                            "amount_motes": snapshots[sh].amount_motes,
                            "release_cap_motes": release_cap_motes,
                        },
                    )
                )
        valid_votes = int(min_valid) if min_valid is not None else 0

    return BatchDecision(
        admit=not rejections,
        action=action,
        needs_quorum=needs_quorum,
        valid_arbiter_votes=valid_votes,
        required_quorum=arbiter_threshold,
        above_cap_hashes=tuple(above_cap),
        rejections=tuple(rejections),
    )


__all__ = [
    "EscrowSnapshot",
    "BatchRejection",
    "BatchDecision",
    "evaluate_batch",
    "MAX_BATCH_SIZE",
    "BATCH_ACTIONS",
    "CODE_EMPTY_BATCH",
    "CODE_BATCH_TOO_LARGE",
    "CODE_UNKNOWN_ACTION",
    "CODE_ARBITER_LIST_MISMATCH",
    "CODE_DUPLICATE_SERVICE_HASH",
    "CODE_ESCROW_NOT_FOUND",
    "CODE_ESCROW_NOT_PENDING",
    "CODE_QUORUM_SHORTFALL",
]
