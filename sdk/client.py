"""AgentEscrow402 Python SDK.

Provides an async client for the x402-compatible escrow API.

Two authentication modes, matching what the real backend actually accepts
(``server/app.py::_extract_sender`` / ``server/middleware.py``):

1. **Sandbox mode** (``sandbox=True``, the default) — the hosted API's own
   ``SANDBOX_MODE=true`` config path accepts a plain ``?sender=`` query
   param with no signature. Fine for quick local testing against a
   ``sandbox`` instance, but the *live* production deployment
   (``sandbox=False`` server-side) rejects this with 401
   ``sender identity required``.

2. **Signed mode** (``sandbox=False``) — builds and Ed25519-signs a real
   ``X-Payment: x402-v1;<escrow_hash>;<amount>;<sender>;<timestamp>;<nonce>;<signature>``
   header exactly as ``server/middleware.py`` verifies it (canonical
   payload bound to version, escrow_hash, amount, sender, timestamp,
   nonce, HTTP method, and path). This is required for any request against
   a real (non-sandbox) AgentEscrow402 deployment, and is what a genuinely
   autonomous on-chain agent must do — there is no unsigned path in
   production.

Usage (sandbox, quick local testing):
    from sdk.client import EscrowClient

    client = EscrowClient("http://localhost:8000", sender="agent-001")
    escrow = await client.create_escrow(receiver="ab" * 32, amount=5000)
    await client.release(escrow["service_hash"])

Usage (signed, works against a real/live deployment too):
    from sdk.client import EscrowClient

    client = EscrowClient.generate("https://agentescrow402-api.onrender.com")
    print("agent identity:", client.sender)  # the derived 64-hex public key
    escrow = await client.create_escrow(receiver="ab" * 32, amount=5000)
    await client.release(escrow["service_hash"])
"""

from __future__ import annotations

import hashlib
import secrets
import time
import uuid
from typing import Any

import httpx
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

X402_VERSION = "x402-v1"


def _canonical_payload(
    version: str, escrow_hash: str, amount: int, sender: str, timestamp: int,
    nonce: str, method: str, path: str,
) -> bytes:
    """Must match ``server/middleware.py::_build_signing_payload`` exactly."""
    payload = (
        f"{version};{escrow_hash};{amount};{sender};{timestamp};{nonce};"
        f"{method};{path}"
    )
    return payload.encode("utf-8")


class EscrowClient:
    """Async client for the AgentEscrow402 API.

    Set ``sandbox=False`` (or use :meth:`generate`/pass a ``private_key``)
    to sign every request with a real Ed25519 keypair, so the client also
    works against a live (non-sandbox) deployment.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        sender: str = "",
        timeout: float = 30.0,
        private_key: Ed25519PrivateKey | None = None,
        sandbox: bool = True,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._http = httpx.AsyncClient(timeout=timeout)
        self._private_key = private_key
        self._sandbox = sandbox and private_key is None

        if private_key is not None:
            pub = private_key.public_key().public_bytes_raw()
            self._sender = pub.hex()
        else:
            self._sender = sender

    @classmethod
    def generate(cls, base_url: str = "http://localhost:8000", timeout: float = 30.0) -> "EscrowClient":
        """Create a client with a freshly generated Ed25519 identity, ready
        to sign requests for a real (non-sandbox) deployment.

        The agent's on-chain-facing identity (``client.sender``) is the
        64-hex Ed25519 public key — this is what appears as
        ``escrow.sender`` in every escrow this client creates.
        """
        key = Ed25519PrivateKey.generate()
        return cls(base_url=base_url, timeout=timeout, private_key=key, sandbox=False)

    @property
    def sender(self) -> str:
        return self._sender

    def _sign(self, escrow_hash: str, amount: int, method: str, path: str) -> str:
        """Build a real, Ed25519-signed X-Payment header value."""
        if self._private_key is None:
            raise RuntimeError(
                "EscrowClient has no signing key — construct with "
                "EscrowClient.generate(...) or private_key=... to sign requests"
            )
        ts = int(time.time())
        nonce = secrets.token_hex(16)  # 32 hex chars, within the 8-128 bound
        msg = _canonical_payload(X402_VERSION, escrow_hash, amount, self._sender, ts, nonce, method, path)
        signature = self._private_key.sign(msg).hex()
        return f"{X402_VERSION};{escrow_hash};{amount};{self._sender};{ts};{nonce};{signature}"

    async def _request(
        self, method: str, path: str, *, escrow_hash: str, amount: int,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        headers = {}
        params = None
        if self._private_key is not None:
            headers["X-Payment"] = self._sign(escrow_hash, amount, method, path)
        elif self._sandbox:
            params = {"sender": self._sender}
        resp = await self._http.request(
            method, f"{self._base}{path}", json=json_body, params=params, headers=headers,
        )
        resp.raise_for_status()
        return resp.json()

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
        return await self._request(
            "POST", "/escrow", escrow_hash=service_hash, amount=amount,
            json_body={
                "receiver": receiver,
                "amount": amount,
                "service_hash": service_hash,
                "ttl": ttl,
            },
        )

    async def get_escrow(self, service_hash: str) -> dict[str, Any]:
        """Fetch escrow status by service hash."""
        resp = await self._http.get(f"{self._base}/escrow/{service_hash}")
        resp.raise_for_status()
        return resp.json()

    async def release(self, service_hash: str, amount: int = 0) -> dict[str, Any]:
        """Release escrowed funds to the receiver."""
        return await self._request(
            "POST", "/release", escrow_hash=service_hash, amount=amount,
            json_body={"service_hash": service_hash},
        )

    async def refund(self, service_hash: str, amount: int = 0) -> dict[str, Any]:
        """Request refund of escrowed funds back to sender."""
        return await self._request(
            "POST", "/refund", escrow_hash=service_hash, amount=amount,
            json_body={"service_hash": service_hash},
        )

    async def dispute(self, service_hash: str, reason_hash: str, amount: int = 0) -> dict[str, Any]:
        """Open a dispute on an active escrow."""
        return await self._request(
            "POST", "/dispute", escrow_hash=service_hash, amount=amount,
            json_body={"service_hash": service_hash, "reason_hash": reason_hash},
        )

    async def resolve(
        self,
        service_hash: str,
        in_favor_of: str,
        arbiter_pubkeys: list[str],
        arbiter_signatures: list[str],
    ) -> dict[str, Any]:
        """Settle a disputed escrow via 3-of-5 arbiter multisig.

        Unlike release/refund/dispute this is not gated on the escrow
        sender/receiver's own signature -- the contract instead verifies,
        on-chain, that each (pubkey, signature) pair is a registered
        arbiter's real Ed25519 signature (>= threshold) over the canonical
        message `"resolve:{service_hash}:{in_favor_of}"`. Use
        `sign_arbiter_vote()` (see `sdk/arbiter_signing.py`) to produce each
        arbiter's vote signature from their private key. No X-Payment
        header is required.
        """
        resp = await self._http.post(
            f"{self._base}/resolve",
            json={
                "service_hash": service_hash,
                "in_favor_of": in_favor_of,
                "arbiter_pubkeys": arbiter_pubkeys,
                "arbiter_signatures": arbiter_signatures,
            },
        )
        resp.raise_for_status()
        return resp.json()

    # -- Reputation -------------------------------------------------------

    async def get_reputation(self, agent: str) -> dict[str, Any]:
        """Get reputation score for an agent."""
        resp = await self._http.get(f"{self._base}/reputation/{agent}")
        resp.raise_for_status()
        return resp.json()

    # -- Arbitration --------------------------------------------------------

    async def arbitrate(
        self,
        dispute_id: str,
        sender_evidence: list[dict[str, Any]],
        receiver_evidence: list[dict[str, Any]],
        escrow_amount: int,
    ) -> dict[str, Any]:
        """Ask the real (Groq/NVIDIA/heuristic-fallback) arbitration engine
        to analyze a dispute and recommend a resolution."""
        resp = await self._http.post(
            f"{self._base}/arbitration/analyze",
            json={
                "dispute_id": dispute_id,
                "sender_evidence": sender_evidence,
                "receiver_evidence": receiver_evidence,
                "escrow_amount": escrow_amount,
            },
        )
        resp.raise_for_status()
        return resp.json()

    # -- x402 header helpers (legacy/manual use) ---------------------------

    def build_x402_header(
        self,
        receiver: str,
        amount: int,
        nonce: str | None = None,
    ) -> str:
        """Build an (unsigned) x402 payment header string for manual/legacy
        use. Prefer ``EscrowClient.generate(...)`` for real signed requests
        — this helper does not sign anything and will be rejected by a
        real (non-sandbox) deployment.

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
