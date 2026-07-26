"""FastAPI router for threshold-secret escrow release (T3.1).

Endpoints:
  POST /threshold/split      — build a threshold-gated release bundle
  POST /threshold/reconstruct — collect shares and decrypt payload
  GET  /threshold/config      — describe supported n-of-m ranges
"""

from __future__ import annotations

import base64

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from server.threshold_secret import (
    ThresholdReleaseBundle,
    build_threshold_release,
)

router = APIRouter(prefix="/threshold", tags=["threshold"])

MIN_THRESHOLD = 2
MAX_TOTAL_SHARES = 255


class SplitRequest(BaseModel):
    payload_b64: str = Field(..., description="Base64-encoded release payload to protect")
    threshold: int = Field(..., ge=MIN_THRESHOLD, description="Shares required to reconstruct (n)")
    total_shares: int = Field(..., le=MAX_TOTAL_SHARES, description="Total shares to generate (m)")


class SplitResponse(BaseModel):
    encrypted_payload_b64: str
    shares_hex: list[str]
    threshold: int
    total: int
    warning: str = (
        "Distribute shares over independent channels to independent holders. "
        "Store the encrypted_payload; deliver each share separately. "
        "AE402 does NOT retain shares."
    )


class ReconstructRequest(BaseModel):
    encrypted_payload_b64: str
    shares_hex: list[str]
    threshold: int


class ReconstructResponse(BaseModel):
    payload_b64: str
    shares_used: int


class ThresholdConfig(BaseModel):
    min_threshold: int
    max_total_shares: int
    algorithm: str = "Shamir Secret Sharing over secp256k1 group order"
    aead: str = "HKDF-SHA256 + HMAC-SHA256-CTR + HMAC-SHA256 authentication"
    note: str = "Threshold gate for escrow release-secret. See docs/wow/T3.1-threshold-mpc.md"


@router.get("/config", response_model=ThresholdConfig)
def get_config() -> ThresholdConfig:
    return ThresholdConfig(
        min_threshold=MIN_THRESHOLD,
        max_total_shares=MAX_TOTAL_SHARES,
    )


@router.post("/split", response_model=SplitResponse)
def split_release(req: SplitRequest) -> SplitResponse:
    try:
        payload = base64.b64decode(req.payload_b64)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"invalid base64 payload: {e}")
    if req.total_shares < req.threshold:
        raise HTTPException(status_code=400, detail="total_shares must be >= threshold")
    try:
        bundle = build_threshold_release(payload, threshold=req.threshold, total=req.total_shares)
    except (ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    return SplitResponse(
        encrypted_payload_b64=base64.b64encode(bundle.encrypted_payload).decode("ascii"),
        shares_hex=bundle.shares_hex,
        threshold=bundle.threshold,
        total=bundle.total,
    )


@router.post("/reconstruct", response_model=ReconstructResponse)
def reconstruct_release(req: ReconstructRequest) -> ReconstructResponse:
    try:
        encrypted = base64.b64decode(req.encrypted_payload_b64)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"invalid base64 payload: {e}")
    if len(req.shares_hex) < req.threshold:
        raise HTTPException(
            status_code=400,
            detail=f"need {req.threshold} shares, got {len(req.shares_hex)}",
        )
    bundle = ThresholdReleaseBundle(
        encrypted_payload=encrypted,
        shares_hex=req.shares_hex,
        threshold=req.threshold,
        total=len(req.shares_hex),
    )
    try:
        payload = bundle.collect_and_decrypt(req.shares_hex[: req.threshold])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return ReconstructResponse(
        payload_b64=base64.b64encode(payload).decode("ascii"),
        shares_used=req.threshold,
    )
