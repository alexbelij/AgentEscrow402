"""Multi-hop A2A choreography (AE-M1).

An *intent* is a planned chain of escrow hops between agents:
``agent A -> agent B -> agent C -> ...``. Each hop is an ordinary escrow
(created and released through the existing `/escrow` + `/release` API —
this module never talks to the chain directly and never introduces a new
on-chain entry point). What's new is the bookkeeping that *links* the hops
together into one auditable choreography:

- `parent_intent_id` — declared once, up front, for the whole chain.
- `chain_escrow(intent, service_hash, hop_index)` — registers one hop's
  escrow under the intent, in order.
- `attest_hop(intent, service_hash, hop_index)` — called after a hop's
  escrow is released; emits a redacted `hop_attested` audit event
  (server.audit_trace.emit_event) and folds its event_id into a running
  `chain_root_hash`.

Chain root math is delegated to `audit_trace.compute_chain_root`, a linear
hash chain over the ordered attestation event_ids:

    chain_root_hash = fold(sha256, [genesis, event_id_0, event_id_1, ...])

Anyone holding the ordered list of event_ids (returned by `get_intent`) can
independently recompute `chain_root_hash` and confirm no hop was skipped,
reordered, or substituted — without needing anything on-chain to change.

This module is intentionally pure/in-memory (mirrors `batch_guard.py`'s
role: "the gap the on-chain contract doesn't fill"). Persistence is the
caller's job; `IntentChainStore` below is the sandbox/demo implementation,
analogous to `SandboxStore` for escrows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from server import audit_trace


class IntentChainError(ValueError):
    """Raised for any invalid intent/hop operation. Callers map this to a
    4xx at the API layer -- never a 500, these are all caller mistakes."""


@dataclass
class Hop:
    hop_index: int
    service_hash: str
    from_agent: str
    to_agent: str
    attested: bool = False
    attestation_event_id: Optional[str] = None
    # On-chain evidence: the tx hash of the `escrow-manager.link_escrows`
    # call that anchored (parent.service_hash -> self.service_hash) with
    # this intent's chain_root_hash. Set by IntentChainStore.record_on_chain_link
    # after the API layer submits the tx. `None` = never anchored on-chain
    # (either hop_index == 0 which has no parent, or the anchoring call was
    # skipped/failed -- read `chain_root_hash` off-chain in that case, and
    # KNOWN_LIMITATIONS.md documents that IntentChainStore is a cache, not
    # the source of truth).
    on_chain_link_tx_hash: Optional[str] = None


@dataclass
class Intent:
    """One multi-hop choreography, e.g. agent A -> B -> C."""

    intent_id: str
    agent_path: list[str]  # e.g. ["A", "B", "C"] -- len(path) - 1 hops planned
    hops: dict[int, Hop] = field(default_factory=dict)
    declared_event_id: Optional[str] = None

    @property
    def planned_hop_count(self) -> int:
        return max(len(self.agent_path) - 1, 0)

    @property
    def attested_hop_count(self) -> int:
        return sum(1 for h in self.hops.values() if h.attested)

    @property
    def is_complete(self) -> bool:
        return self.planned_hop_count > 0 and self.attested_hop_count == self.planned_hop_count

    def ordered_attestation_event_ids(self) -> list[str]:
        """Attestation event_ids in hop order. A gap (a hop not yet
        attested) truncates the list -- chain_root_hash only ever covers
        a *contiguous prefix* of attested hops, so a skipped hop can never
        be silently backfilled out of order."""
        ids: list[str] = []
        for i in range(self.planned_hop_count):
            hop = self.hops.get(i)
            if hop is None or not hop.attested or hop.attestation_event_id is None:
                break
            ids.append(hop.attestation_event_id)
        return ids

    @property
    def chain_root_hash(self) -> str:
        return audit_trace.compute_chain_root(self.ordered_attestation_event_ids())


class IntentChainStore:
    """In-memory store for intents/hops -- sandbox/demo analogue of
    `SandboxStore`. Not thread-safe beyond what FastAPI's single-worker
    sandbox mode already assumes elsewhere in this codebase."""

    def __init__(self) -> None:
        self._intents: dict[str, Intent] = {}

    # -- intent lifecycle -------------------------------------------------

    def declare_intent(self, intent_id: str, agent_path: list[str]) -> Intent:
        if not intent_id:
            raise IntentChainError("intent_id must be non-empty")
        if intent_id in self._intents:
            raise IntentChainError(f"intent {intent_id!r} already declared")
        if len(agent_path) < 2:
            raise IntentChainError("agent_path must have at least 2 agents (>=1 hop), " f"got {agent_path!r}")
        if len(set(agent_path)) != len(agent_path):
            raise IntentChainError(f"agent_path must not repeat an agent: {agent_path!r}")

        event = audit_trace.emit_event(
            event_type="intent_declared",
            subject_id=intent_id,
            attributes={"hop_count": len(agent_path) - 1},
        )
        intent = Intent(
            intent_id=intent_id,
            agent_path=list(agent_path),
            declared_event_id=event.event_id,
        )
        self._intents[intent_id] = intent
        return intent

    def get_intent(self, intent_id: str) -> Intent:
        intent = self._intents.get(intent_id)
        if intent is None:
            raise IntentChainError(f"intent {intent_id!r} not found")
        return intent

    # -- hop registration ---------------------------------------------------

    def chain_escrow(self, intent_id: str, service_hash: str, hop_index: int) -> Hop:
        """Register `service_hash`'s escrow as hop `hop_index` of `intent_id`.

        Must be called with hops in order (0, 1, 2, ...) -- a hop can only
        be registered once its predecessor has been registered (not
        necessarily attested yet). This is what makes `parent_intent_id` +
        `hop_index` on the escrow request enough to reconstruct the whole
        choreography even before any hop is released.
        """
        intent = self.get_intent(intent_id)
        if hop_index < 0 or hop_index >= intent.planned_hop_count:
            raise IntentChainError(
                f"hop_index {hop_index} out of range for intent "
                f"{intent_id!r} (planned {intent.planned_hop_count} hops)"
            )
        if hop_index in intent.hops:
            raise IntentChainError(f"hop {hop_index} already chained for intent {intent_id!r}")
        if hop_index > 0 and (hop_index - 1) not in intent.hops:
            raise IntentChainError(
                f"hop {hop_index} chained out of order for intent "
                f"{intent_id!r} -- hop {hop_index - 1} must be chained first"
            )
        for existing in intent.hops.values():
            if existing.service_hash == service_hash:
                raise IntentChainError(
                    f"service_hash {service_hash!r} already chained to intent "
                    f"{intent_id!r} at hop {existing.hop_index}"
                )

        hop = Hop(
            hop_index=hop_index,
            service_hash=service_hash,
            from_agent=intent.agent_path[hop_index],
            to_agent=intent.agent_path[hop_index + 1],
        )
        intent.hops[hop_index] = hop
        return hop

    # -- attestation ---------------------------------------------------------

    def attest_hop(self, intent_id: str, service_hash: str, hop_index: int) -> Hop:
        """Record that hop `hop_index`'s escrow has been released, and fold
        a new `hop_attested` audit event into the intent's chain root.

        Idempotent guard: attesting an already-attested hop raises rather
        than silently re-emitting (a second attestation would change
        chain_root_hash for a hop that already has a fixed position in the
        chain -- that's a caller bug, not something to paper over).
        """
        intent = self.get_intent(intent_id)
        hop = intent.hops.get(hop_index)
        if hop is None:
            raise IntentChainError(
                f"hop {hop_index} not chained yet for intent {intent_id!r} " "-- call chain_escrow first"
            )
        if hop.service_hash != service_hash:
            raise IntentChainError(
                f"service_hash mismatch for hop {hop_index} of intent "
                f"{intent_id!r}: chained={hop.service_hash!r} "
                f"attested={service_hash!r}"
            )
        if hop.attested:
            raise IntentChainError(f"hop {hop_index} of intent {intent_id!r} already attested")

        event = audit_trace.emit_event(
            event_type="hop_attested",
            actor_id=intent_id,
            subject_id=service_hash,
            attributes={
                "hop_index": hop_index,
                "hop_count": intent.planned_hop_count,
            },
        )
        hop.attested = True
        hop.attestation_event_id = event.event_id
        return hop

    def record_on_chain_link(self, intent_id: str, hop_index: int, tx_hash: str) -> Hop:
        """Record the tx hash of the `escrow-manager.link_escrows` call
        that anchored hop `hop_index` on-chain. Called by the API layer
        *after* the on-chain tx is submitted (see intent_chain_api.py).

        Idempotent guard: overwriting an already-recorded tx_hash raises,
        because a hop can only be anchored once on-chain (the manager
        contract itself enforces `ERROR_LINK_ALREADY_EXISTS` on duplicate
        link_escrows calls -- a second tx would revert, so recording it
        here would be a lie).
        """
        if not tx_hash:
            raise IntentChainError("tx_hash must be non-empty")
        intent = self.get_intent(intent_id)
        hop = intent.hops.get(hop_index)
        if hop is None:
            raise IntentChainError(f"hop {hop_index} not chained for intent {intent_id!r}")
        if hop_index == 0:
            raise IntentChainError("hop 0 has no parent; on-chain link_escrows is only defined " "for hop_index >= 1")
        if hop.on_chain_link_tx_hash is not None:
            raise IntentChainError(
                f"hop {hop_index} of intent {intent_id!r} already anchored "
                f"on-chain (tx {hop.on_chain_link_tx_hash!r})"
            )
        hop.on_chain_link_tx_hash = tx_hash
        return hop
