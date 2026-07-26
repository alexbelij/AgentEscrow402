"""FastAPI wiring for the compliance policy engine (T3.7).

Exposes the deterministic `server/compliance.py` `ComplianceEngine` over
HTTP: a dry-run evaluation endpoint (like `/escrows/batch-preview` in
T3.3 — never mutates state, never hits Casper), a read-only jurisdiction
table listing, and a lookup-by-agent convenience route that pulls the
caller's `verification_level` straight from the live identity registry
(T3.6/identity-registry) so a client does not have to look that up itself
and risk it drifting from what the registry actually has on file.

Mounted at `/compliance`, kept fully separate from `/identity-registry`
and `/risk` — this module answers "is this transaction permitted for this
jurisdiction/KYC tier, and does it need a compliance record", which is a
distinct question from "how good is this counterparty's track record"
(identity-registry) or "does this look anomalous" (risk).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from server.compliance import (
    ComplianceDecision,
    ComplianceEngine,
    JurisdictionPolicy,
    JurisdictionRegime,
)
from server.identity_registry import IdentityRegistry, VerificationLevel

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/compliance", tags=["compliance"])

# Single process-lifetime engine instance, same convention as
# identity_registry_api.py's module-level `_registry`.
_engine = ComplianceEngine()


def _get_identity_registry() -> IdentityRegistry:
    # Late import + late lookup to reuse the SAME registry instance the
    # /identity-registry router mutates, instead of a second, empty one.
    from server.identity_registry_api import _registry

    return _registry


class JurisdictionPolicyResponse(BaseModel):
    country_code: str
    regime: JurisdictionRegime
    min_verification: VerificationLevel
    max_single_tx_motes: int | None
    max_daily_volume_motes: int | None
    notes: str

    @classmethod
    def from_policy(cls, p: JurisdictionPolicy) -> "JurisdictionPolicyResponse":
        return cls(
            country_code=p.country_code,
            regime=p.regime,
            min_verification=p.min_verification,
            max_single_tx_motes=p.max_single_tx_motes,
            max_daily_volume_motes=p.max_daily_volume_motes,
            notes=p.notes,
        )


class EvaluateComplianceRequest(BaseModel):
    country_code: str = Field(..., min_length=2, max_length=2, description="ISO 3166-1 alpha-2 country code.")
    verification_level: VerificationLevel = Field(default=VerificationLevel.UNVERIFIED)
    amount_motes: int = Field(..., ge=0)
    prior_volume_today_motes: int = Field(default=0, ge=0)


class EvaluateComplianceByAgentRequest(BaseModel):
    country_code: str = Field(..., min_length=2, max_length=2)
    did: str = Field(..., description="DID of the agent in the identity registry — verification_level is read live.")
    amount_motes: int = Field(..., ge=0)
    prior_volume_today_motes: int = Field(default=0, ge=0)


class ComplianceDecisionResponse(BaseModel):
    permitted: bool
    country_code: str
    regime: JurisdictionRegime
    verification_level: VerificationLevel
    amount_motes: int
    requires_reporting: bool
    report_reasons: list[str]
    rejections: list[str]
    policy_notes: str

    @classmethod
    def from_decision(cls, d: ComplianceDecision) -> "ComplianceDecisionResponse":
        return cls(
            permitted=d.permitted,
            country_code=d.country_code,
            regime=d.regime,
            verification_level=d.verification_level,
            amount_motes=d.amount_motes,
            requires_reporting=d.requires_reporting,
            report_reasons=[r.value for r in d.report_reasons],
            rejections=[r.value for r in d.rejections],
            policy_notes=d.policy_notes,
        )


@router.get("/jurisdictions", response_model=list[JurisdictionPolicyResponse])
async def list_jurisdictions() -> list[JurisdictionPolicyResponse]:
    """Read-only listing of every configured jurisdiction policy, sorted
    by country code. Illustrative reference table — see the module
    docstring in `server/compliance.py`: not a real sanctions/licensing
    determination, replace before going live."""
    return [JurisdictionPolicyResponse.from_policy(p) for p in _engine.list_jurisdictions()]


@router.post("/evaluate", response_model=ComplianceDecisionResponse)
async def evaluate(req: EvaluateComplianceRequest) -> ComplianceDecisionResponse:
    """Dry-run compliance evaluation for an explicit `(country, KYC tier,
    amount)` triple. Never mutates state, never touches Casper or the
    identity registry — pure function of the request body. `permitted`
    is the enforceable verdict; `requires_reporting` is independent of it
    (a permitted transaction can still require a compliance record)."""
    decision = _engine.evaluate(
        country_code=req.country_code,
        verification_level=req.verification_level,
        amount_motes=req.amount_motes,
        prior_volume_today_motes=req.prior_volume_today_motes,
    )
    return ComplianceDecisionResponse.from_decision(decision)


@router.post("/evaluate-by-agent", response_model=ComplianceDecisionResponse)
async def evaluate_by_agent(req: EvaluateComplianceByAgentRequest) -> ComplianceDecisionResponse:
    """Same evaluation as `/evaluate`, but reads `verification_level` live
    from the identity registry for `did` instead of trusting a
    client-supplied value — closes the gap where a client could claim a
    higher KYC tier than the registry actually has on file for it."""
    registry = _get_identity_registry()
    identity = await registry.get(req.did)
    if identity is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Identity not found in registry")

    decision = _engine.evaluate(
        country_code=req.country_code,
        verification_level=identity.verification_level,
        amount_motes=req.amount_motes,
        prior_volume_today_motes=req.prior_volume_today_motes,
    )
    return ComplianceDecisionResponse.from_decision(decision)


__all__ = [
    "router",
    "JurisdictionPolicyResponse",
    "EvaluateComplianceRequest",
    "EvaluateComplianceByAgentRequest",
    "ComplianceDecisionResponse",
]
