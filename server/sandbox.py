"""Sandbox mode for demo payments without real chain interaction."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from server.escrow_fsm import EscrowAction, EscrowFSM, InvalidTransitionError
from server.models import EscrowRecord, EscrowStatus, ReputationRecord


class SandboxStore:
    """In-memory escrow store for sandbox/demo mode."""

    def __init__(self) -> None:
        self._escrows: dict[str, dict[str, Any]] = {}
        self._reputation: dict[str, dict[str, int]] = {}
        self._lock = asyncio.Lock()

    def create_escrow(self, sender: str, receiver: str, amount: int, service_hash: str, ttl: int) -> EscrowRecord:
        if service_hash in self._escrows:
            raise ValueError(f"Escrow {service_hash} already exists")
        now = int(time.time())
        record = {
            "sender": sender,
            "receiver": receiver,
            "amount": amount,
            "service_hash": service_hash,
            "status": "pending",
            "created_at": now,
            "ttl": ttl,
            # C13: threshold-arming stays optional; empty string = no gate.
            "threshold_commitment_hex": "",
            "threshold_n": 0,
            "threshold_m": 0,
        }
        self._escrows[service_hash] = record
        return EscrowRecord(**record)

    def release_escrow(self, service_hash: str, caller: str, deploy_hash: str = "") -> EscrowRecord:
        rec = self._get_or_raise(service_hash)
        # AE-14: deny-by-default FSM guards the state change before any
        # side effect (reputation bump, deploy-hash write) can happen.
        next_state = self._advance(rec, EscrowAction.RELEASE)
        if rec["sender"] != caller:
            raise PermissionError("Only sender can release")
        rec["status"] = next_state.value
        if deploy_hash:
            # Each lifecycle action is its own on-chain deploy -- the record
            # must reflect the *release* deploy, not the stale one from
            # `create_escrow`, or API/UI consumers would report the wrong
            # transaction hash for a released escrow.
            rec["deploy_hash"] = deploy_hash
        self._bump_reputation(rec["receiver"], completed=1)
        return EscrowRecord(**rec)

    def refund_escrow(self, service_hash: str, caller: str, deploy_hash: str = "") -> EscrowRecord:
        rec = self._get_or_raise(service_hash)
        now = int(time.time())
        expired = now > rec["created_at"] + rec["ttl"]
        if not expired and rec["sender"] != caller:
            raise PermissionError("Only sender can refund before TTL")
        # Two distinct FSM edges from PENDING: EXPIRE when TTL has passed,
        # REFUND otherwise. Both are validated by the same allow-matrix.
        action = EscrowAction.EXPIRE if expired else EscrowAction.REFUND
        next_state = self._advance(rec, action)
        rec["status"] = next_state.value
        if deploy_hash:
            rec["deploy_hash"] = deploy_hash
        return EscrowRecord(**rec)

    def dispute_escrow(self, service_hash: str, deploy_hash: str = "") -> EscrowRecord:
        rec = self._get_or_raise(service_hash)
        next_state = self._advance(rec, EscrowAction.DISPUTE)
        rec["status"] = next_state.value
        if deploy_hash:
            rec["deploy_hash"] = deploy_hash
        self._bump_reputation(rec["sender"], disputed=1)
        return EscrowRecord(**rec)

    def resolve_escrow(
        self,
        service_hash: str,
        in_favor_of: str,
        deploy_hash: str = "",
    ) -> EscrowRecord:
        """Resolve a disputed escrow via arbiter multisig decision.

        Mirrors the on-chain `resolve()` entry point: only valid on a
        `disputed` escrow; pays out to sender or receiver depending on
        `in_favor_of`, and marks the escrow `resolved`.
        """
        rec = self._get_or_raise(service_hash)
        if in_favor_of not in ("sender", "receiver"):
            raise ValueError(f"in_favor_of must be 'sender' or 'receiver', got: {in_favor_of!r}")
        action = EscrowAction.RESOLVE_SENDER if in_favor_of == "sender" else EscrowAction.RESOLVE_RECEIVER
        next_state = self._advance(rec, action)
        rec["status"] = next_state.value
        if deploy_hash:
            rec["deploy_hash"] = deploy_hash
        winner = rec["sender"] if in_favor_of == "sender" else rec["receiver"]
        self._bump_reputation(winner, completed=1)
        return EscrowRecord(**rec)

    def get_escrow(self, service_hash: str) -> EscrowRecord | None:
        rec = self._escrows.get(service_hash)
        if rec is None:
            return None
        return EscrowRecord(**rec)

    def get_reputation(self, agent: str) -> ReputationRecord:
        rep = self._reputation.get(agent, {})
        completed = rep.get("completed", 0)
        disputed = rep.get("disputed", 0)
        score = max(0, min(100, 50 + completed * 5 - disputed * 10))
        return ReputationRecord(
            agent=agent,
            completed=completed,
            disputed=disputed,
            slashed=rep.get("slashed", 0),
            last_active=rep.get("last_active", 0),
            score=score,
        )

    def _advance(self, rec: dict[str, Any], action: str) -> EscrowStatus:
        """Run ``rec['status']`` through :class:`EscrowFSM`.

        Preserves the historical ``ValueError`` surface — callers and
        FastAPI handlers already convert ``ValueError`` into HTTP 400 —
        while attaching the FSM's machine-readable payload for the
        newer 409-based error path.
        """
        current = EscrowStatus(rec["status"])
        try:
            return EscrowFSM.transition(current, action)
        except InvalidTransitionError as exc:
            # Chain the FSM error so surfaces that want the structured
            # payload can re-raise it (see server/app.py), while the
            # ValueError message keeps existing tests happy.
            raise ValueError(exc._message()) from exc

    def _get_or_raise(self, service_hash: str) -> dict[str, Any]:
        rec = self._escrows.get(service_hash)
        if rec is None:
            raise KeyError(f"Escrow {service_hash} not found")
        return rec

    def _bump_reputation(self, agent: str, completed: int = 0, disputed: int = 0) -> None:
        rep = self._reputation.setdefault(agent, {"completed": 0, "disputed": 0, "slashed": 0, "last_active": 0})
        rep["completed"] += completed
        rep["disputed"] += disputed
        rep["last_active"] = int(time.time())
