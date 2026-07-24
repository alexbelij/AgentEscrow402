"""HTTP surface for Macaroon-style capability tokens.

Routes:

- `POST /macaroons/mint`        — mint a root macaroon (server-signed).
- `POST /macaroons/attenuate`   — append first-party caveats to an existing token.
- `POST /macaroons/verify`      — verify a token against a verifier context.
- `POST /macaroons/discharge`   — mint a discharge macaroon for a third-party caveat.
- `GET  /macaroons/policy`      — describe accepted caveat predicates (docs surface).

The root secret is loaded from `Config.macaroon_root_secret` (env
`MACAROON_ROOT_SECRET`). When unset the service refuses to mint or verify
macaroons — the AE402 API surface is *additive*: no default-open behaviour
that could grant unauthenticated authority.
"""

from __future__ import annotations

import base64
import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from sdk.macaroons import (
    MacaroonError,
    MacaroonVerifyError,
    VerifierContext,
    add_third_party_caveat,
    attenuate,
    decode,
    derive_third_party_key,
    encode,
    mint_discharge,
    mint_root,
)
from server.config import Config, get_config

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/macaroons", tags=["macaroons"])


def _load_root_secret(config: Config) -> bytes:
    raw = getattr(config, "macaroon_root_secret", "") or ""
    if not raw:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="macaroon_root_secret not configured",
        )
    # Accept base64url or hex or raw ASCII. We *require* at least 24 bytes
    # of entropy — HMAC-SHA256 with a short secret is still a hash of the
    # secret but a 12-char password would be too easy to brute-force in
    # offline verifier scenarios.
    candidates: list[bytes] = []
    try:
        padded = raw + "=" * (-len(raw) % 4)
        candidates.append(base64.urlsafe_b64decode(padded.encode("ascii")))
    except Exception:
        pass
    try:
        candidates.append(bytes.fromhex(raw))
    except Exception:
        pass
    candidates.append(raw.encode("utf-8"))
    for cand in candidates:
        if len(cand) >= 24:
            return cand
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="macaroon_root_secret must decode to >=24 bytes",
    )


class MintRequest(BaseModel):
    caveats: list[str] = Field(default_factory=list, max_length=32)
    ttl_seconds: int = Field(default=3600, ge=1, le=30 * 24 * 3600)
    identifier: str | None = Field(default=None, min_length=1, max_length=128)


class MintResponse(BaseModel):
    token: str
    identifier: str
    caveats: list[str]
    expires_at: int


@router.post("/mint", response_model=MintResponse)
async def mint(request: MintRequest, config: Config = Depends(get_config)) -> MintResponse:
    # SECURITY (reviewed 2026-07-24, not yet fixed -- tracked follow-up):
    # this endpoint has no caller-identity check today. A macaroon's caveats
    # are exactly what the caller asks for (`capability=release`,
    # `amount<=...`, etc.), so anyone who can reach this endpoint can mint a
    # token that *claims* any capability string they like. That is
    # currently safe because nothing in the codebase yet trusts a verified
    # macaroon to authorize a real escrow/insurance action -- see
    # docs/MACAROONS.md "Known limitation". Before any endpoint is wired to
    # accept a macaroon as proof of authority, mint() must first check the
    # caller already holds that authority through an existing auth path
    # (e.g. agent-identity-registry delegation or a session token) and only
    # allow attenuation, never grant of capabilities the caller doesn't
    # already have from elsewhere.
    root = _load_root_secret(config)
    try:
        macaroon = mint_root(root, identifier=request.identifier) if request.identifier else mint_root(root)
    except MacaroonError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    expires_at = int(time.time()) + request.ttl_seconds
    try:
        macaroon = attenuate(macaroon, f"expires<{expires_at}")
        for cav in request.caveats:
            macaroon = attenuate(macaroon, cav)
    except MacaroonError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    logger.info("Minted macaroon %s with %d caveats", macaroon.identifier[:8], len(macaroon.caveats))
    return MintResponse(
        token=encode(macaroon),
        identifier=macaroon.identifier,
        caveats=[c.cid for c in macaroon.caveats],
        expires_at=expires_at,
    )


class AttenuateRequest(BaseModel):
    token: str = Field(..., min_length=1)
    caveats: list[str] = Field(..., min_length=1, max_length=32)


class AttenuateResponse(BaseModel):
    token: str
    caveats: list[str]


@router.post("/attenuate", response_model=AttenuateResponse)
async def attenuate_endpoint(request: AttenuateRequest) -> AttenuateResponse:
    """Attenuate a macaroon without touching the server root secret.

    Attenuation is a pure client-side operation — every bearer can do it.
    Exposing it as an endpoint is a convenience for clients that would
    rather not implement the HMAC chain themselves; the endpoint does not
    grant any additional authority.
    """
    try:
        macaroon = decode(request.token)
        for cav in request.caveats:
            macaroon = attenuate(macaroon, cav)
    except MacaroonError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return AttenuateResponse(
        token=encode(macaroon),
        caveats=[c.cid for c in macaroon.caveats],
    )


class VerifyRequest(BaseModel):
    token: str = Field(..., min_length=1)
    facts: dict[str, Any] = Field(default_factory=dict)
    discharges: list[str] = Field(default_factory=list, max_length=8)
    now: int | None = Field(default=None)


class VerifyResponse(BaseModel):
    ok: bool
    identifier: str
    caveats: list[str]
    detail: str | None = None


@router.post("/verify", response_model=VerifyResponse)
async def verify_endpoint(request: VerifyRequest, config: Config = Depends(get_config)) -> VerifyResponse:
    root = _load_root_secret(config)
    try:
        macaroon = decode(request.token)
    except MacaroonError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    # Coerce facts values into str|int; anything else is coerced via str().
    facts: dict[str, str | int] = {}
    for k, v in request.facts.items():
        facts[str(k)] = v if isinstance(v, (str, int)) else str(v)

    ctx = VerifierContext(
        now=request.now if request.now is not None else int(time.time()),
        facts=facts,
    )
    for token in request.discharges:
        try:
            d = decode(token)
        except MacaroonError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"invalid discharge: {exc}") from exc
        ctx.discharges[d.identifier] = d

    try:
        from sdk.macaroons import verify as _verify

        _verify(macaroon, root, ctx)
    except MacaroonVerifyError as exc:
        return VerifyResponse(
            ok=False,
            identifier=macaroon.identifier,
            caveats=[c.cid for c in macaroon.caveats],
            detail=str(exc),
        )

    return VerifyResponse(ok=True, identifier=macaroon.identifier, caveats=[c.cid for c in macaroon.caveats])


class DischargeRequest(BaseModel):
    discharge_identifier: str = Field(..., min_length=1, max_length=128)
    location: str = Field(default="ae402", min_length=1, max_length=64)
    caveats: list[str] = Field(default_factory=list, max_length=16)
    ttl_seconds: int = Field(default=3600, ge=1, le=30 * 24 * 3600)


class DischargeResponse(BaseModel):
    token: str
    identifier: str


@router.post("/discharge", response_model=DischargeResponse)
async def discharge_endpoint(request: DischargeRequest, config: Config = Depends(get_config)) -> DischargeResponse:
    """Issue a discharge macaroon for a third-party caveat.

    In a hosted deployment this endpoint stands in for the third-party
    discharger (e.g. the arbiter pool). The discharger derives its
    per-caveat HMAC key from the shared `macaroon_root_secret` context —
    see `derive_third_party_key` docstring for why that is honest crypto
    without pulling in an asymmetric primitive.
    """

    root = _load_root_secret(config)
    key = derive_third_party_key(root, request.discharge_identifier)
    try:
        d = mint_discharge(key, identifier=request.discharge_identifier, location=request.location)
        d = attenuate(d, f"expires<{int(time.time()) + request.ttl_seconds}")
        for cav in request.caveats:
            d = attenuate(d, cav)
    except MacaroonError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return DischargeResponse(token=encode(d), identifier=d.identifier)


class AddThirdPartyRequest(BaseModel):
    token: str = Field(..., min_length=1)
    discharge_identifier: str = Field(..., min_length=1, max_length=128)
    location: str = Field(default="ae402", min_length=1, max_length=64)
    predicate_hint: str | None = Field(default=None, max_length=128)


class AddThirdPartyResponse(BaseModel):
    token: str
    caveats: list[str]


@router.post("/add-third-party", response_model=AddThirdPartyResponse)
async def add_third_party_endpoint(request: AddThirdPartyRequest) -> AddThirdPartyResponse:
    """Bind a third-party caveat onto an existing token (client-side operation)."""
    try:
        macaroon = decode(request.token)
        macaroon = add_third_party_caveat(
            macaroon,
            discharge_identifier=request.discharge_identifier,
            location=request.location,
            predicate_hint=request.predicate_hint,
        )
    except MacaroonError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return AddThirdPartyResponse(token=encode(macaroon), caveats=[c.cid for c in macaroon.caveats])


@router.get("/policy")
async def policy() -> dict[str, Any]:
    """Describe the caveat grammar accepted by the AE402 verifier."""
    return {
        "location": "ae402",
        "version": 1,
        "caveats": {
            "capability": {"operator": "=", "example": "capability=release"},
            "escrow_id": {"operator": "=", "example": "escrow_id=e123"},
            "amount": {"operators": ["<", "<=", "=", ">=", ">"], "example": "amount<=100"},
            "expires": {"operators": ["<", "<="], "example": "expires<1789200000"},
        },
        "third_party": {
            "identifier_format": "discharge:<opaque>[:<predicate_hint>]",
            "discharge_endpoint": "/macaroons/discharge",
        },
    }
