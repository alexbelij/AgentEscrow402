"""AgentEscrow402 client SDK."""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

import httpx


class EscrowClient:
    """Python client for the AgentEscrow402 API."""

    def __init__(self, base_url: str = "http://localhost:8000", sender: str = "") -> None:
        self._base = base_url.rstrip("/")
        self._sender = sender
        self._http = httpx.AsyncClient(timeout=30.0)

    async def create_escrow(
        self,
        receiver: str,
        amount: int,
        ttl: int = 300,
        nonce: str | None = None,
    ) -> dict[str, Any]:
        """Create a new escrow, locking funds until service delivery."""
        if nonce is None:
            nonce = uuid.uuid4().hex
        service_hash = self._compute_hash(self._sender, receiver, amount, nonce)
        resp = await self._http.post(
            f"{self._base}/escrow",
            json={
                "receiver": receiver,
                "amount": amount,
                "service_hash": service_hash,
                "ttl": ttl,
            },
            params={"sender": self._sender},
        )
        resp.raise_for_status()
        return resp.json()

    async def release(self, service_hash: str) -> dict[str, Any]:
        """Release escrowed funds to the receiver."""
        resp = await self._http.post(
            f"{self._base}/release",
            json={"service_hash": service_hash},
            params={"sender": self._sender},
        )
        resp.raise_for_status()
        return resp.json()

    async def refund(self, service_hash: str) -> dict[str, Any]:
        """Request refund of escrowed funds."""
        resp = await self._http.post(
            f"{self._base}/refund",
            json={"service_hash": service_hash},
            params={"sender": self._sender},
        )
        resp.raise_for_status()
        return resp.json()

    async def get_escrow(self, service_hash: str) -> dict[str, Any]:
        resp = await self._http.get(f"{self._base}/escrow/{service_hash}")
        resp.raise_for_status()
        return resp.json()

    async def get_reputation(self, agent: str) -> dict[str, Any]:
        resp = await self._http.get(f"{self._base}/reputation/{agent}")
        resp.raise_for_status()
        return resp.json()

    async def close(self) -> None:
        await self._http.aclose()

    @staticmethod
    def _compute_hash(sender: str, receiver: str, amount: int, nonce: str) -> str:
        payload = f"{sender}:{receiver}:{amount}:{nonce}"
        return hashlib.sha256(payload.encode()).hexdigest()
