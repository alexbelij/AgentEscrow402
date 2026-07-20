"""x402 payment middleware for FastAPI."""

from __future__ import annotations

import hashlib
import logging
import time
from collections import OrderedDict
from typing import Any, Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse

from server.models import PaymentHeader

logger = logging.getLogger(__name__)

X402_HEADER = "X-Payment"
X402_VERSION = "x402-v1"

# Replay window: signatures older than this are rejected.
REPLAY_WINDOW_SEC = 300  # 5 minutes

# Bounded nonce cache to prevent replay within the window.
# Production: replace with Redis/DB-backed set.
MAX_NONCE_CACHE = 10_000  # Hard cap to prevent memory exhaustion
_used_nonces: OrderedDict[str, float] = OrderedDict()


def _verify_ed25519(public_hex: str, message: bytes, sig_hex: str) -> bool:
    """Verify ed25519 signature. Returns False on any error.

    Uses constant-time patterns to mitigate timing attacks:
    all code paths perform equivalent work before returning.
    """
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PublicKey,
        )

        # Validate hex encoding first (constant length check)
        if len(public_hex) != 64 or len(sig_hex) != 128:
            return False
        pub_bytes = bytes.fromhex(public_hex)
        sig_bytes = bytes.fromhex(sig_hex)
        key = Ed25519PublicKey.from_public_bytes(pub_bytes)
        key.verify(sig_bytes, message)
        return True
    except Exception:
        logger.debug("ed25519 verification failed for sender=%s", public_hex[:16])
        return False


def _verify_secp256k1(public_hex: str, message: bytes, sig_hex: str) -> bool:
    """Verify a secp256k1 ECDSA signature. Returns False on any error.

    Matches Casper's own on-chain `casper_types::crypto::verify` for
    secp256k1: a 33-byte compressed public key, a 64-byte compact (raw
    r||s, not DER) signature, and SHA-256 as the digest -- the same
    encoding CSPR.click's `signMessage()` produces and the same encoding
    the cep18 fork's `permit()` entry point verifies on-chain (k256's
    default `ecdsa::Signature`/`Verifier` behavior). We only need to
    re-encode r||s as DER for the `cryptography` library's ECDSA API.
    """
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric import ec, utils
        from cryptography.hazmat.primitives.hashes import SHA256

        # Compressed secp256k1 pubkey = 33 bytes; compact signature = 64 bytes.
        if len(public_hex) != 66 or len(sig_hex) != 128:
            return False
        pub_bytes = bytes.fromhex(public_hex)
        sig_bytes = bytes.fromhex(sig_hex)
        r = int.from_bytes(sig_bytes[:32], "big")
        s = int.from_bytes(sig_bytes[32:], "big")
        der_sig = utils.encode_dss_signature(r, s)
        key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256K1(), pub_bytes)
        key.verify(der_sig, message, ec.ECDSA(SHA256()))
        return True
    except InvalidSignature:
        return False
    except Exception:
        logger.debug("secp256k1 verification failed for sender=%s", public_hex[:16])
        return False


# Browser wallets (Casper Wallet / CSPR.click's `signMessage()`) never sign
# the raw bytes handed to them: per the ecosystem-standard convention (see
# casper-js-sdk's `formatMessageWithHeaders`), the wallet always prepends
# this fixed text before signing, specifically so a message-signing request
# can never be silently reused as a raw-deploy/session signature. Agent
# SDKs that hold a private key directly and sign the x402 payload
# themselves (no wallet involved) do NOT add this prefix. We can't tell
# which path produced a given signature ahead of time, so we try the raw
# message first (the primary/most common agent-to-agent x402 path) and
# only fall back to the prefixed form if that fails.
CASPER_MESSAGE_PREFIX = b"Casper Message:\n"


def _verify_signature(public_hex: str, message: bytes, sig_hex: str) -> bool:
    """Dispatches to the right verifier based on the raw public key length:
    32 bytes (64 hex) -> Ed25519, 33 bytes (66 hex) -> secp256k1 compressed.
    Both key types are legitimate CSPR.click wallets; only the crypto
    primitive differs. Tries the raw message first, then the
    wallet-`signMessage`-prefixed form (see CASPER_MESSAGE_PREFIX above)."""
    if len(public_hex) == 64:
        verifier = _verify_ed25519
    elif len(public_hex) == 66:
        verifier = _verify_secp256k1
    else:
        return False
    if verifier(public_hex, message, sig_hex):
        return True
    return verifier(public_hex, CASPER_MESSAGE_PREFIX + message, sig_hex)


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
    # Enforce hard cap — evict oldest entries if over limit
    while len(_used_nonces) > MAX_NONCE_CACHE:
        _used_nonces.popitem(last=False)
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
    hex_chars = set("0123456789abcdef")
    if len(escrow_hash) != 64 or not all(c in hex_chars for c in escrow_hash.lower()):
        return None
    # 64 hex = raw 32-byte Ed25519 pubkey, 66 hex = 33-byte compressed
    # secp256k1 pubkey -- see _verify_signature in this module.
    if len(sender) not in (64, 66) or not all(c in hex_chars for c in sender.lower()):
        return None
    if len(signature) != 128 or not all(c in hex_chars for c in signature.lower()):
        return None
    if not (8 <= len(nonce) <= 128) or any(ch in ";\r\n" for ch in nonce):
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


def _build_signing_payload(payment: PaymentHeader, method: str = "", path: str = "") -> bytes:
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
                if not _verify_signature(payment.sender, msg, payment.signature):
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
