"""x402 payment middleware for FastAPI."""

from __future__ import annotations

import hashlib
import logging
from typing import Any, Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse

from server.models import PaymentHeader

logger = logging.getLogger(__name__)

X402_HEADER = "X-Payment"
X402_VERSION = "x402-v1"


def parse_x402_header(raw: str) -> PaymentHeader | None:
    """Parse x402 payment header string into structured data.

    Expected format: x402-v1;<escrow_hash>;<amount>;<sender>;<signature>
    """
    parts = raw.split(";")
    if len(parts) != 5:
        return None
    version, escrow_hash, amount_str, sender, signature = parts
    if version != X402_VERSION:
        return None
    try:
        amount = int(amount_str)
    except ValueError:
        return None
    return PaymentHeader(
        version=version,
        escrow_hash=escrow_hash,
        amount=amount,
        sender=sender,
        signature=signature,
    )


def require_payment(min_amount: int = 0):
    """Decorator factory: require x402 payment header on a route."""

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
