"""x402 payment middleware for FastAPI."""

from __future__ import annotations

import hashlib
import logging
import time
from typing import Any, Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse

from server.models import PaymentHeader

logger = logging.getLogger(__name__)

X402_HEADER = "X-Payment"
X402_VERSION = "x402-v1"

# Replay window: signatures older than this are rejected.
REPLAY_WINDOW_SEC = 300  # 5 minutes

# Simple in-memory nonce cache to prevent replay within the window.
# Production: replace with Redis/DB-backed set.
_used_nonces: dict[str, float] = {}


def _verify_ed25519(public_hex: str, message: bytes, sig_hex: str) -> bool:
    """Verify ed25519 signature. Returns False on any error."""
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PublicKey,
        )

        pub_bytes = bytes.fromhex(public_hex)
        sig_bytes = bytes.fromhex(sig_hex)
        key = Ed25519PublicKey.from_public_bytes(pub_bytes)
        key.verify(sig_bytes, message)
        return True
    except Exception:
        logger.debug("ed25519 verification failed for sender=%s", public_hex[:16])
        return False


def _check_replay(nonce: str, ts: int) -> str | None:
    """Check for replay attacks. Returns error message or None."""
    now = int(time.time())
    if abs(now - ts) > REPLAY_WINDOW_SEC:
        return "timestamp_expired"

    # Evict old entries
    cutoff = now - REPLAY_WINDOW_SEC
    stale = [k for k, v in _used_nonces.items() if v < cutoff]
    for k in stale:
        del _used_nonces[k]

    if nonce in _used_nonces:
        return "nonce_reused"

    _used_nonces[nonce] = now
    return None


def parse_x402_header(raw: str) -> PaymentHeader | None:
    """Parse x402 payment header string into structured data.

    Format: x402-v1;<escrow_hash>;<amount>;<sender>;<timestamp>;<nonce>;<signature>
    """
    parts = raw.split(";")
    if len(parts) != 7:
        return None
    version, escrow_hash, amount_str, sender, ts_str, nonce, signature = parts
    if version != X402_VERSION:
        return None
    try:
        amount = int(amount_str)
        timestamp = int(ts_str)
    except ValueError:
        return None
    if not all(c in "0123456789abcdef" for c in escrow_hash.lower()):
        return None
    return PaymentHeader(
        version=version,
        escrow_hash=escrow_hash,
        amount=amount,
        sender=sender,
        signature=signature,
        timestamp=timestamp,
        nonce=nonce,
    )


def _build_signing_payload(
    payment: PaymentHeader, method: str = "", path: str = ""
) -> bytes:
    """Canonical bytes that the sender must sign.

    Binds the signature to: version, escrow_hash, amount, sender,
    timestamp, nonce, HTTP method, and request path.
    """
    payload = (
        f"{payment.version};{payment.escrow_hash};{payment.amount};"
        f"{payment.sender};{payment.timestamp};{payment.nonce};"
        f"{method};{path}"
    )
    return payload.encode("utf-8")


def require_payment(min_amount: int = 0, verify_sig: bool = True):
    """Decorator factory: require x402 payment header on a route.

    When verify_sig=True (default), the sender's ed25519 signature is
    checked against the canonical payload (bound to method+path).
    Replay protection via timestamp + nonce.
    Disable verify_sig for sandbox/testing.
    """

    def decorator(func: Callable) -> Callable:
        async def wrapper(request: Request, *args: Any, **kwargs: Any) -> Response:
            header_val = request.headers.get(X402_HEADER)
            if not header_val:
                return JSONResponse(
                    status_code=402,
                    content={
                        "error": "payment_required",
                        "message": "Missing X-Payment header",
                        "accepts": X402_VERSION,
                        "price": min_amount,
                    },
                    headers={"X-Payment-Required": str(min_amount)},
                )

            payment = parse_x402_header(header_val)
            if payment is None:
                return JSONResponse(
                    status_code=400,
                    content={"error": "invalid_payment_header"},
                )

            if payment.amount < min_amount:
                return JSONResponse(
                    status_code=402,
                    content={
                        "error": "insufficient_payment",
                        "required": min_amount,
                        "provided": payment.amount,
                    },
                )

            if verify_sig:
                # Replay protection
                replay_err = _check_replay(payment.nonce, payment.timestamp)
                if replay_err:
                    return JSONResponse(
                        status_code=401,
                        content={"error": replay_err},
                    )

                # Signature bound to HTTP method + path
                msg = _build_signing_payload(
                    payment,
                    method=request.method,
                    path=request.url.path,
                )
                if not _verify_ed25519(payment.sender, msg, payment.signature):
                    return JSONResponse(
                        status_code=401,
                        content={"error": "invalid_signature"},
                    )

            request.state.payment = payment
            return await func(request, *args, **kwargs)

        wrapper.__name__ = func.__name__
        wrapper.__doc__ = func.__doc__
        return wrapper

    return decorator


def compute_service_hash(sender: str, receiver: str, amount: int, nonce: str) -> str:
    """Compute deterministic service hash for escrow lookup."""
    payload = f"{sender}:{receiver}:{amount}:{nonce}"
    return hashlib.sha256(payload.encode()).hexdigest()
