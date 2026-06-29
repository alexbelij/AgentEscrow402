"""AgentEscrow402 Python SDK.

Provides sync and async clients for the x402-compatible escrow API.

Usage:
    from sdk.client import EscrowClient

    client = EscrowClient("http://localhost:8000", sender="agent-001")
    escrow = await client.create_escrow(receiver="svc-007", amount=5000)
    await client.release(escrow["service_hash"])
"""

from __future__ import annotations

import hashlib
import time
import uuid
from typing import Any

import httpx


class EscrowClient:
    """Async client for AgentEscrow402 API."""

    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        sender: str = "",
        timeout: float = 30.0,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._sender = sender
        self._http = httpx.AsyncClient(timeout=timeout)

    # -- Escrow lifecycle -------------------------------------------------

    async def create_escrow(
        self,
        receiver: str,
        amount: int,
        ttl: int = 300,
        nonce: str | None = None,
    ) -> dict[str, Any]:
        """Lock funds in escrow until service is delivered."""
        if nonce is None:
            nonce = uuid.uuid4().hex
        service_hash = self.compute_hash(self._sender, receiver, amount, nonce)
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

    async def get_escrow(self, service_hash: str) -> dict[str, Any]:
        """Fetch escrow status by service hash."""
        resp = await self._http.get(f"{self._base}/escrow/{service_hash}")
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
        """Request refund of escrowed funds back to sender."""
        resp = await self._http.post(
            f"{self._base}/refund",
            json={"service_hash": service_hash},
            params={"sender": self._sender},
        )
        resp.raise_for_status()
        return resp.json()

    async def dispute(self, service_hash: str, reason_hash: str) -> dict[str, Any]:
        """Open a dispute on an active escrow."""
        resp = await self._http.post(
            f"{self._base}/dispute",
            json={"service_hash": service_hash, "reason_hash": reason_hash},
            params={"sender": self._sender},
        )
        resp.raise_for_status()
        return resp.json()

    # -- Reputation -------------------------------------------------------

    async def get_reputation(self, agent: str) -> dict[str, Any]:
        """Get reputation score for an agent."""
        resp = await self._http.get(f"{self._base}/reputation/{agent}")
        resp.raise_for_status()
        return resp.json()

    # -- x402 header helpers ----------------------------------------------

    def build_x402_header(
        self,
        receiver: str,
        amount: int,
        nonce: str | None = None,
    ) -> str:
        """Build an x402 payment header string.

        Format: ``x402;1;<amount>;<service_hash>;<timestamp>;<nonce>``
        """
        if nonce is None:
            nonce = uuid.uuid4().hex
        service_hash = self.compute_hash(self._sender, receiver, amount, nonce)
        ts = int(time.time())
        return f"x402;1;{amount};{service_hash};{ts};{nonce}"

    # -- Utilities --------------------------------------------------------

    @staticmethod
    def compute_hash(sender: str, receiver: str, amount: int, nonce: str) -> str:
        """Deterministic SHA-256 of ``sender:receiver:amount:nonce``."""
        payload = f"{sender}:{receiver}:{amount}:{nonce}"
        return hashlib.sha256(payload.encode()).hexdigest()

    async def health(self) -> dict[str, Any]:
        resp = await self._http.get(f"{self._base}/health")
        resp.raise_for_status()
        return resp.json()

    async def close(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> "EscrowClient":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()
