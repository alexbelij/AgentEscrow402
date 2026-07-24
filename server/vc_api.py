"""HTTP API for W3C VC 2.0 escrow receipts.

Endpoints
---------
GET  /vc/issuer              — returns the issuer DID + public key
POST /vc/receipts/issue      — mint a receipt for an escrow event
POST /vc/receipts/verify     — verify a receipt (portable, no DB check)

Configuration
-------------
- `VC_ISSUER_SEED` env: 32-byte Ed25519 seed, encoded as base64 / base64url /
  hex / 64-char ASCII. If unset or too short, endpoints return 503.
- `VC_AUTO_ISSUE_ON_RELEASE` env: "1" / "true" enables side-effect issuance
  in the escrow lifecycle (see `try_auto_issue`). Off by default.

Failure semantics
-----------------
- No secret configured → 503 Service Unavailable on issuance endpoints.
  `/vc/receipts/verify` remains available (verification only needs the
  credential; the pubkey is embedded in the issuer DID).
"""

from __future__ import annotations

import base64
import logging
import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from sdk.vc_receipts import (
    RECEIPT_TYPES,
    IssuerKey,
    ProofMissingError,
    SchemaError,
    SignatureInvalidError,
    VerificationError,
    issue_receipt,
    receipt_summary,
    verify_receipt,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/vc", tags=["vc-receipts"])


# ---------------------------------------------------------------------------
# Issuer resolution
# ---------------------------------------------------------------------------


def _decode_seed(raw: str) -> bytes | None:
    """Try to interpret an env-provided seed as bytes.

    Accepts (in order): base64url, base64, hex, raw 32-byte ASCII.
    Returns None if none of these produce 32 bytes.
    """
    if not raw:
        return None

    # base64 / base64url
    try:
        s = raw.replace("-", "+").replace("_", "/")
        pad = "=" * (-len(s) % 4)
        decoded = base64.b64decode(s + pad, validate=False)
        if len(decoded) == 32:
            return decoded
    except Exception:
        pass

    # hex
    try:
        if len(raw) == 64:
            decoded = bytes.fromhex(raw)
            if len(decoded) == 32:
                return decoded
    except ValueError:
        pass

    # raw ASCII
    b = raw.encode("utf-8")
    if len(b) == 32:
        return b

    return None


def get_issuer_key() -> IssuerKey:
    """Load the VC issuer key from env. Raises HTTPException(503) if unset."""
    raw = os.environ.get("VC_ISSUER_SEED", "").strip()
    seed = _decode_seed(raw)
    if seed is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "VC_ISSUER_SEED is not configured or not a 32-byte seed "
                "(accepted: base64/base64url/hex/raw ASCII)."
            ),
        )
    return IssuerKey.from_seed(seed)


def auto_issue_enabled() -> bool:
    return os.environ.get("VC_AUTO_ISSUE_ON_RELEASE", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


# ---------------------------------------------------------------------------
# Request/response schemas
# ---------------------------------------------------------------------------


class IssuerInfo(BaseModel):
    did: str
    public_key_hex: str
    proof_suite: str
    supported_events: list[str]


class IssueRequest(BaseModel):
    event: str = Field(..., description="release | refund | resolve")
    service_hash: str
    escrow_id: str | None = None
    payer: str
    receiver: str
    amount_motes: int = Field(..., ge=0)
    asset: str = "CSPR"
    issuance_ts: int | None = Field(
        None, description="Unix epoch seconds; defaults to now"
    )
    extra_claims: dict[str, Any] | None = None


class IssueResponse(BaseModel):
    credential: dict[str, Any]
    summary: dict[str, Any]


class VerifyRequest(BaseModel):
    credential: dict[str, Any]
    expected_issuer: str | None = Field(
        None, description="Optional did:key to enforce"
    )


class VerifyResponse(BaseModel):
    valid: bool
    error_type: str | None = None
    error_detail: str | None = None
    summary: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/issuer", response_model=IssuerInfo)
async def get_issuer(issuer: IssuerKey = Depends(get_issuer_key)) -> IssuerInfo:
    return IssuerInfo(
        did=issuer.did,
        public_key_hex=issuer.pubkey.hex(),
        proof_suite="Ed25519Signature2020",
        supported_events=sorted(RECEIPT_TYPES.keys()),
    )


@router.post("/receipts/issue", response_model=IssueResponse)
async def issue(
    req: IssueRequest,
    issuer: IssuerKey = Depends(get_issuer_key),
) -> IssueResponse:
    if req.event not in RECEIPT_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown event {req.event!r} — expected one of {sorted(RECEIPT_TYPES.keys())}",
        )

    try:
        vc = issue_receipt(
            issuer,
            event=req.event,  # type: ignore[arg-type]
            service_hash=req.service_hash,
            escrow_id=req.escrow_id or req.service_hash,
            payer=req.payer,
            receiver=req.receiver,
            amount_motes=req.amount_motes,
            asset=req.asset,
            issuance_ts=req.issuance_ts,
            extra_claims=req.extra_claims,
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return IssueResponse(credential=vc, summary=receipt_summary(vc))


@router.post("/receipts/verify", response_model=VerifyResponse)
async def verify(req: VerifyRequest) -> VerifyResponse:
    """Verify a receipt. Does NOT require issuer secret — verification only
    needs the credential (pubkey is embedded in the issuer DID)."""
    try:
        verify_receipt(req.credential, expected_issuer=req.expected_issuer)
    except SignatureInvalidError as exc:
        return VerifyResponse(
            valid=False, error_type="SignatureInvalid", error_detail=str(exc)
        )
    except ProofMissingError as exc:
        return VerifyResponse(
            valid=False, error_type="ProofMissing", error_detail=str(exc)
        )
    except SchemaError as exc:
        return VerifyResponse(
            valid=False, error_type="Schema", error_detail=str(exc)
        )
    except VerificationError as exc:
        return VerifyResponse(
            valid=False, error_type="Verification", error_detail=str(exc)
        )

    return VerifyResponse(
        valid=True, summary=receipt_summary(req.credential)
    )


# ---------------------------------------------------------------------------
# Optional lifecycle hook
# ---------------------------------------------------------------------------


def try_auto_issue(
    *,
    event: str,
    service_hash: str,
    payer: str,
    receiver: str,
    amount_motes: int,
    asset: str = "CSPR",
    extra_claims: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Best-effort auto-issuance hook for escrow FSM.

    - Returns None if `VC_AUTO_ISSUE_ON_RELEASE` is off or the issuer key
      isn't configured. Callers MUST NOT let a missing issuer key break
      the escrow event.
    - Returns the signed VC dict on success. Callers can attach it to
      the API response as `receipt`.
    """
    if not auto_issue_enabled():
        return None
    raw = os.environ.get("VC_ISSUER_SEED", "").strip()
    seed = _decode_seed(raw)
    if seed is None:
        logger.warning(
            "VC_AUTO_ISSUE_ON_RELEASE=1 but VC_ISSUER_SEED not configured; skipping receipt"
        )
        return None
    try:
        issuer = IssuerKey.from_seed(seed)
        return issue_receipt(
            issuer,
            event=event,  # type: ignore[arg-type]
            service_hash=service_hash,
            escrow_id=service_hash,
            payer=payer,
            receiver=receiver,
            amount_motes=amount_motes,
            asset=asset,
            extra_claims=extra_claims,
        )
    except Exception:  # pragma: no cover - defensive
        logger.exception("auto-issue of VC receipt failed for %s", service_hash)
        return None
