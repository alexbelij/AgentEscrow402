"""Compliance framework for regulated jurisdictions (T3.6/T3.7).

Pure, deterministic policy engine — no I/O, no chain calls, no wall-clock
side effects beyond the timestamp the caller supplies. Mirrors the
`server/batch_guard.py` and `server/risk_scoring.py` shape: given a typed
request, return a typed, fully-explained decision with stable rejection
codes a client can switch on.

Scope and honesty up front, same as every other Tier 3 module in this repo:
this is a **reference policy engine**, not legal advice and not a
regulator-certified compliance product. It models three things that show
up in every serious jurisdiction analysis for agent-to-agent crypto
payments, without pretending to cover licensing, tax, or securities law:

1. **Jurisdiction classification** — a small static table of regimes
   (`unrestricted`, `restricted`, `prohibited`) keyed by ISO 3166-1 alpha-2
   country code, mirroring the shape of a real sanctions/travel-rule
   jurisdiction list (OFAC-style) without shipping a live sanctions feed.
   `prohibited` always blocks; `restricted` requires a minimum KYC/
   verification tier plus per-jurisdiction transaction/day-volume caps.
2. **KYC/verification tiering** — reuses `identity_registry.VerificationLevel`
   (UNVERIFIED/BASIC/ENHANCED/FULL) as the KYC tier so this module has a
   single source of truth with the reputation registry instead of a
   second, drifting notion of "how verified is this agent". Each
   jurisdiction regime declares a `min_verification` requirement.
3. **Reporting thresholds** — a travel-rule-style rule: any single
   transaction (or the caller-supplied rolling counterparty total) at or
   above a configurable threshold requires a structured compliance record
   (`requires_reporting=True` + a stable `report_reason`), independent of
   whether the transaction is otherwise permitted.

None of the three regimes below are a real regulatory determination for
any real jurisdiction — they are illustrative defaults a deployer
replaces with their own counsel-reviewed table before going live. That
replaceability is the point: `ComplianceEngine` takes the table as a
constructor argument, so the default table below is a fixture, not a
hardcoded assumption baked into the logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from server.identity_registry import VerificationLevel

_LEVEL_ORDER: dict[VerificationLevel, int] = {
    VerificationLevel.UNVERIFIED: 0,
    VerificationLevel.BASIC: 1,
    VerificationLevel.ENHANCED: 2,
    VerificationLevel.FULL: 3,
}


class JurisdictionRegime(str, Enum):
    """Coarse regulatory posture for a jurisdiction.

    UNRESTRICTED — no jurisdiction-specific gating beyond the global
      reporting threshold.
    RESTRICTED — permitted, but gated on a minimum KYC/verification tier
      and a per-jurisdiction transaction/day-volume cap.
    PROHIBITED — always blocked, no override. Modeled on sanctioned/
      embargoed jurisdiction lists; a real deployment wires this to an
      actual sanctions data feed instead of the static default table.
    """

    UNRESTRICTED = "UNRESTRICTED"
    RESTRICTED = "RESTRICTED"
    PROHIBITED = "PROHIBITED"


class ComplianceRejection(str, Enum):
    """Stable, switchable rejection codes — same convention as
    `server/batch_guard.py`'s `BatchRejection`."""

    UNKNOWN_JURISDICTION = "unknown_jurisdiction"
    JURISDICTION_PROHIBITED = "jurisdiction_prohibited"
    INSUFFICIENT_VERIFICATION = "insufficient_verification"
    DAILY_VOLUME_CAP_EXCEEDED = "daily_volume_cap_exceeded"
    TRANSACTION_CAP_EXCEEDED = "transaction_cap_exceeded"


class ReportReason(str, Enum):
    """Why a transaction was flagged for a compliance record. A
    transaction can be *permitted* and still `requires_reporting` —
    reporting and permission are independent axes, matching how travel-rule
    / large-transaction-reporting regimes actually work."""

    LARGE_TRANSACTION = "large_transaction"
    RESTRICTED_JURISDICTION = "restricted_jurisdiction"
    ROLLING_VOLUME_THRESHOLD = "rolling_volume_threshold"


@dataclass(frozen=True)
class JurisdictionPolicy:
    """Policy for one jurisdiction. `country_code` is ISO 3166-1 alpha-2,
    upper-cased, e.g. "US", "KP", "IR"."""

    country_code: str
    regime: JurisdictionRegime
    min_verification: VerificationLevel = VerificationLevel.UNVERIFIED
    max_single_tx_motes: int | None = None
    max_daily_volume_motes: int | None = None
    notes: str = ""


@dataclass(frozen=True)
class ComplianceDecision:
    """Full, explained verdict for one proposed transaction. Mirrors
    `BatchDecision`'s shape: a single boolean verdict plus every signal
    that fed it, so a UI/SDK never has to re-derive "why" from scratch."""

    permitted: bool
    country_code: str
    regime: JurisdictionRegime
    verification_level: VerificationLevel
    amount_motes: int
    requires_reporting: bool
    report_reasons: tuple[ReportReason, ...]
    rejections: tuple[ComplianceRejection, ...]
    policy_notes: str = ""


# ---------------------------------------------------------------------------
# Default illustrative jurisdiction table.
#
# NOT a real sanctions list. Three unrestricted majors, three restricted
# (KYC-gated + capped) as a stand-in for "jurisdictions with active but
# incomplete VASP licensing regimes", and two prohibited (OFAC-comprehensive-
# sanctions-style) as a stand-in for a real embargo list. A deployer
# replaces this table wholesale via `ComplianceEngine(policies=...)`.
# ---------------------------------------------------------------------------
DEFAULT_JURISDICTION_TABLE: dict[str, JurisdictionPolicy] = {
    p.country_code: p
    for p in [
        JurisdictionPolicy("US", JurisdictionRegime.UNRESTRICTED, notes="Illustrative default — not a real determination."),
        JurisdictionPolicy("GB", JurisdictionRegime.UNRESTRICTED),
        JurisdictionPolicy("SG", JurisdictionRegime.UNRESTRICTED),
        JurisdictionPolicy(
            "NG",
            JurisdictionRegime.RESTRICTED,
            min_verification=VerificationLevel.ENHANCED,
            max_single_tx_motes=5_000 * 10**9,
            max_daily_volume_motes=20_000 * 10**9,
            notes="Illustrative: evolving VASP licensing regime — ENHANCED KYC + caps.",
        ),
        JurisdictionPolicy(
            "TR",
            JurisdictionRegime.RESTRICTED,
            min_verification=VerificationLevel.BASIC,
            max_single_tx_motes=10_000 * 10**9,
            max_daily_volume_motes=50_000 * 10**9,
            notes="Illustrative: BASIC KYC + caps.",
        ),
        JurisdictionPolicy(
            "VE",
            JurisdictionRegime.RESTRICTED,
            min_verification=VerificationLevel.FULL,
            max_single_tx_motes=1_000 * 10**9,
            max_daily_volume_motes=5_000 * 10**9,
            notes="Illustrative: high-friction regime — FULL KYC + tight caps.",
        ),
        JurisdictionPolicy("KP", JurisdictionRegime.PROHIBITED, notes="Illustrative OFAC-comprehensive-sanctions stand-in."),
        JurisdictionPolicy("IR", JurisdictionRegime.PROHIBITED, notes="Illustrative OFAC-comprehensive-sanctions stand-in."),
    ]
}

# Any single transaction at/above this notional threshold requires a
# compliance record regardless of jurisdiction — a travel-rule-style
# large-transaction rule. 10,000 CSPR in motes (1 CSPR = 10^9 motes),
# chosen to echo the real-world $10k/€10k large-transaction-reporting
# convention used as a round-number illustrative default.
DEFAULT_LARGE_TRANSACTION_THRESHOLD_MOTES = 10_000 * 10**9


@dataclass
class ComplianceEngine:
    """Deterministic policy engine. Stateless evaluation — `evaluate()`
    takes every input explicitly and returns a decision; no hidden clock,
    no hidden network call, no mutation. A caller wanting a rolling
    per-counterparty daily volume check supplies `prior_volume_today_motes`
    themselves (this module does not persist transaction history — that
    belongs to the caller/DB layer, same separation as `batch_guard.py`
    taking pre-fetched escrow snapshots instead of hitting the store
    itself)."""

    policies: dict[str, JurisdictionPolicy] = field(default_factory=lambda: dict(DEFAULT_JURISDICTION_TABLE))
    large_transaction_threshold_motes: int = DEFAULT_LARGE_TRANSACTION_THRESHOLD_MOTES

    def evaluate(
        self,
        country_code: str,
        verification_level: VerificationLevel,
        amount_motes: int,
        prior_volume_today_motes: int = 0,
    ) -> ComplianceDecision:
        cc = country_code.strip().upper()
        rejections: list[ComplianceRejection] = []
        report_reasons: list[ReportReason] = []

        policy = self.policies.get(cc)
        if policy is None:
            # Fail closed: an unrecognized jurisdiction is not silently
            # treated as unrestricted. Same "unknown is a rejection, not a
            # pass" posture as batch_guard's unknown_action code.
            return ComplianceDecision(
                permitted=False,
                country_code=cc,
                regime=JurisdictionRegime.PROHIBITED,
                verification_level=verification_level,
                amount_motes=amount_motes,
                requires_reporting=False,
                report_reasons=(),
                rejections=(ComplianceRejection.UNKNOWN_JURISDICTION,),
                policy_notes="No policy entry for this jurisdiction — fails closed.",
            )

        if policy.regime is JurisdictionRegime.PROHIBITED:
            rejections.append(ComplianceRejection.JURISDICTION_PROHIBITED)
            # A prohibited jurisdiction is reported too — the fact that a
            # blocked transaction was *attempted* is itself a compliance
            # signal a real deployment would want in its audit trail.
            report_reasons.append(ReportReason.RESTRICTED_JURISDICTION)

        elif policy.regime is JurisdictionRegime.RESTRICTED:
            if _LEVEL_ORDER[verification_level] < _LEVEL_ORDER[policy.min_verification]:
                rejections.append(ComplianceRejection.INSUFFICIENT_VERIFICATION)
            if policy.max_single_tx_motes is not None and amount_motes > policy.max_single_tx_motes:
                rejections.append(ComplianceRejection.TRANSACTION_CAP_EXCEEDED)
            if (
                policy.max_daily_volume_motes is not None
                and (prior_volume_today_motes + amount_motes) > policy.max_daily_volume_motes
            ):
                rejections.append(ComplianceRejection.DAILY_VOLUME_CAP_EXCEEDED)
            report_reasons.append(ReportReason.RESTRICTED_JURISDICTION)

        if amount_motes >= self.large_transaction_threshold_motes:
            report_reasons.append(ReportReason.LARGE_TRANSACTION)

        if (
            policy.max_daily_volume_motes is not None
            and prior_volume_today_motes > 0
            and (prior_volume_today_motes + amount_motes) >= policy.max_daily_volume_motes * 0.8
            and ReportReason.ROLLING_VOLUME_THRESHOLD not in report_reasons
        ):
            report_reasons.append(ReportReason.ROLLING_VOLUME_THRESHOLD)

        return ComplianceDecision(
            permitted=len(rejections) == 0,
            country_code=cc,
            regime=policy.regime,
            verification_level=verification_level,
            amount_motes=amount_motes,
            requires_reporting=len(report_reasons) > 0,
            report_reasons=tuple(report_reasons),
            rejections=tuple(rejections),
            policy_notes=policy.notes,
        )

    def list_jurisdictions(self) -> list[JurisdictionPolicy]:
        """Stable-ordered listing of every configured jurisdiction policy,
        for the API's `/compliance/jurisdictions` read-only listing route."""
        return [self.policies[cc] for cc in sorted(self.policies)]
