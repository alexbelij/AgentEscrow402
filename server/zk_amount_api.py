"""FastAPI router exposing ZK amount primitives (W.2).

This is an **opt-in demo/audit surface** — real escrows still use the plain
`amount_motes` wire field. These endpoints let a UI or an auditor:

  * Prove and verify a hidden-amount commitment.
  * Aggregate commitments to check batch-cap conservation without seeing
    individual amounts.

The server does **not** store commitments in the primary escrow table (that
would need a schema migration). Instead, this router is stateless: it
computes and returns. A caller who wants persistence can pass the returned
`commitment` + `range_proof` alongside their normal escrow payload; the
server-side arbiter/audit path can verify without ever seeing the amount.

Design choice — no auth on prove/verify: these endpoints are cryptographic
utilities, not privileged operations. They don't touch the DB, they don't
sign anything, they don't move value. Rate-limiting from `server/app.py`
still applies (60 req/min per IP).
"""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from server import zk_amount

router = APIRouter(prefix="/zk", tags=["zk-amount"])


# ---------------------------------------------------------------------------
# Request/response models
# ---------------------------------------------------------------------------


class ProveRequest(BaseModel):
    amount: int = Field(..., ge=0, lt=1 << zk_amount.AMOUNT_BITS)
    transcript: str = Field(default="", max_length=256, description="Binding context (hex or utf8)")
    bits: int = Field(default=zk_amount.AMOUNT_BITS, ge=1, le=64)


class ProveResponse(BaseModel):
    commitment: str
    range_proof: dict
    blinding: str  # 64-char hex — caller MUST persist privately
    bits: int
    prove_ms: float


class VerifyRequest(BaseModel):
    commitment: str
    range_proof: dict
    transcript: str = Field(default="", max_length=256)


class VerifyResponse(BaseModel):
    valid: bool
    verify_ms: float
    bits: int


class CommitmentRef(BaseModel):
    commitment: str


class AggregateRequest(BaseModel):
    commitments: List[CommitmentRef] = Field(..., min_length=1, max_length=1000)


class AggregateResponse(BaseModel):
    aggregate: str
    count: int


class OpenRequest(BaseModel):
    commitment: str
    amount: int = Field(..., ge=0, lt=1 << zk_amount.AMOUNT_BITS)
    blinding: str  # 64-char hex


class OpenResponse(BaseModel):
    valid: bool


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


def _decode_transcript(t: str) -> bytes:
    """Accept either hex (`0x...` or pure hex string) or UTF-8 text."""
    if not t:
        return b""
    if t.startswith("0x"):
        try:
            return bytes.fromhex(t[2:])
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"invalid hex transcript: {exc}")
    # Try hex first (all-hex string), fall back to utf-8.
    if len(t) % 2 == 0 and all(c in "0123456789abcdefABCDEF" for c in t):
        try:
            return bytes.fromhex(t)
        except ValueError:
            pass
    return t.encode("utf-8")


@router.post("/prove", response_model=ProveResponse)
def prove(req: ProveRequest) -> ProveResponse:
    """Generate a Pedersen commitment + range proof for `amount`.

    Returns the commitment, the range proof (JSON), the blinding factor (the
    caller must persist this privately — losing it means the escrow cannot
    be opened later), and prove timing.
    """
    import time

    transcript = _decode_transcript(req.transcript)
    t0 = time.perf_counter()
    try:
        _, blinding = zk_amount.commit(req.amount)
        C, proof = zk_amount.prove_range(req.amount, blinding, transcript=transcript, bits=req.bits)
    except zk_amount.ZKError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    dt_ms = (time.perf_counter() - t0) * 1000
    return ProveResponse(
        commitment=C.C,
        range_proof=proof.to_dict(),
        blinding=zk_amount._encode_scalar(blinding).hex(),
        bits=req.bits,
        prove_ms=round(dt_ms, 2),
    )


@router.post("/verify", response_model=VerifyResponse)
def verify(req: VerifyRequest) -> VerifyResponse:
    """Verify a range proof against a commitment."""
    import time

    transcript = _decode_transcript(req.transcript)
    try:
        commitment = zk_amount.Commitment(C=req.commitment)
        proof = zk_amount.RangeProof.from_dict(req.range_proof)
    except zk_amount.ZKError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    t0 = time.perf_counter()
    ok = zk_amount.verify_range(commitment, proof, transcript=transcript)
    dt_ms = (time.perf_counter() - t0) * 1000
    return VerifyResponse(valid=ok, verify_ms=round(dt_ms, 2), bits=proof.bits())


@router.post("/aggregate", response_model=AggregateResponse)
def aggregate(req: AggregateRequest) -> AggregateResponse:
    """Homomorphic sum: aggregate commitment = Σ C_i.

    Useful for batch-cap conservation checks: sum all commitments in a batch
    and verify the aggregate against the batch cap (which the auditor knows).
    """
    try:
        comms = [zk_amount.Commitment(C=c.commitment) for c in req.commitments]
        agg = zk_amount.sum_commitments(comms)
    except zk_amount.ZKError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return AggregateResponse(aggregate=agg.C, count=len(comms))


@router.post("/open", response_model=OpenResponse)
def open_commitment(req: OpenRequest) -> OpenResponse:
    """Verify `commitment` opens to `(amount, blinding)`.

    Used by an auditor or receiver who is authorized to see the amount:
    given the sender's disclosure of `(amount, blinding)`, this endpoint
    confirms they match the public commitment. No secrets are logged.
    """
    try:
        commitment = zk_amount.Commitment(C=req.commitment)
        blinding_bytes = bytes.fromhex(req.blinding)
        blinding = zk_amount._decode_scalar(blinding_bytes)
    except (zk_amount.ZKError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"invalid input: {exc}")
    ok = zk_amount.verify_open(commitment, req.amount, blinding)
    return OpenResponse(valid=ok)


@router.get("/generators")
def generators() -> dict:
    """Return the two group generators G, H (SEC-1 compressed, hex).

    Deterministic — same output on every server. Useful for a client that
    wants to independently verify the generators the server is using.
    """
    return {
        "G": zk_amount.generator_G().hex(),
        "H": zk_amount.generator_H().hex(),
        "curve": "secp256k1",
        "amount_bits": zk_amount.AMOUNT_BITS,
        "commitment_scheme": "Pedersen",
        "range_proof_scheme": "Chaum-Pedersen OR per bit (Fiat-Shamir)",
    }
