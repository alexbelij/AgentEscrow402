"""Sandbox mode for demo payments without real chain interaction."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from server.models import EscrowRecord, ReputationRecord


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
        }
        self._escrows[service_hash] = record
        return EscrowRecord(**record)

    def release_escrow(self, service_hash: str, caller: str, deploy_hash: str = "") -> EscrowRecord:
        rec = self._get_or_raise(service_hash)
        if rec["status"] != "pending":
            raise ValueError(f"Cannot release escrow in status {rec['status']}")
        if rec["sender"] != caller:
            raise PermissionError("Only sender can release")
        rec["status"] = "released"
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
        if rec["status"] != "pending":
            raise ValueError(f"Cannot refund escrow in status {rec['status']}")
        now = int(time.time())
        expired = now > rec["created_at"] + rec["ttl"]
        if not expired and rec["sender"] != caller:
            raise PermissionError("Only sender can refund before TTL")
        rec["status"] = "expired" if expired else "refunded"
        if deploy_hash:
            rec["deploy_hash"] = deploy_hash
        return EscrowRecord(**rec)

    def dispute_escrow(self, service_hash: str, deploy_hash: str = "") -> EscrowRecord:
        rec = self._get_or_raise(service_hash)
        if rec["status"] != "pending":
            raise ValueError(f"Cannot dispute escrow in status {rec['status']}")
        rec["status"] = "disputed"
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
        if rec["status"] != "disputed":
            raise ValueError(f"Cannot resolve escrow in status {rec['status']} (must be disputed)")
        if in_favor_of not in ("sender", "receiver"):
            raise ValueError(f"in_favor_of must be 'sender' or 'receiver', got: {in_favor_of!r}")
        rec["status"] = "resolved"
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
