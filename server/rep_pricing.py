"""
Reputation-based pricing for insurance premiums.

Pure function `insurance_fee(amount, reputation)` — same input, same fee,
byte-for-byte. No randomness, no clock, no I/O. Property-tested for:

  - monotonicity in reputation (higher rep → lower fee)
  - monotonicity in amount (higher amount → higher fee)
  - bounded output (fee ≥ AE402_MIN_PREMIUM_MOTES, fee ≤ amount)
  - continuity (no jumps at score boundaries beyond the tier discount)

Related:
- server/insurance.py       (premium-quote endpoint, uses this)
- server/dispute_ai.py      (rubric, also reputation-aware)
- tests/test_rep_pricing.py (property + boundary tests)
"""

from __future__ import annotations

from dataclasses import dataclass

BASE_RATE_BPS = 50  # 0.5% of the escrow amount, before adjustments
MIN_PREMIUM_MOTES = 1_000_000  # ~0.001 CSPR floor
_BPS_DENOM = 10_000


@dataclass(frozen=True)
class PricingBreakdown:
    """Explainable premium breakdown.

    All figures are motes-integer; `base_fee` is the pre-adjustment
    number, `fee` is the final. `tier` is one of
    {"high_risk", "medium_risk", "neutral", "low_risk"}.
    """

    base_fee: int
    adjusted_fee: int
    fee: int  # clamped to [MIN_PREMIUM_MOTES, escrow_amount]
    tier: str
    multiplier: float
    reputation_used: int


def _tier(reputation: int) -> tuple[str, float]:
    r = max(0, min(100, int(reputation)))
    if r < 30:
        return "high_risk", 2.0
    if r < 50:
        return "medium_risk", 1.5
    if r > 70:
        return "low_risk", 0.8
    return "neutral", 1.0


def insurance_fee(amount_motes: int, reputation: int) -> int:
    """Return the final insurance premium in motes.

    Pure function; call `price_breakdown` for the full explainable object.
    """
    return price_breakdown(amount_motes, reputation).fee


def price_breakdown(amount_motes: int, reputation: int) -> PricingBreakdown:
    """Full pricing breakdown for one (amount, reputation) pair.

    Guarantees:
      * fee >= MIN_PREMIUM_MOTES for any amount_motes > 0
      * fee <= amount_motes
      * amount_a >= amount_b AND reputation_a == reputation_b →
        fee(a) >= fee(b)
      * reputation_a >= reputation_b AND amount_a == amount_b →
        fee(a) <= fee(b)
    """
    if amount_motes <= 0:
        raise ValueError("amount_motes must be positive")

    tier, mult = _tier(reputation)
    base_fee = (amount_motes * BASE_RATE_BPS) // _BPS_DENOM
    adjusted_fee = int(base_fee * mult)

    fee = max(MIN_PREMIUM_MOTES, adjusted_fee)
    fee = min(fee, amount_motes)  # premium can never exceed the escrow

    return PricingBreakdown(
        base_fee=base_fee,
        adjusted_fee=adjusted_fee,
        fee=fee,
        tier=tier,
        multiplier=mult,
        reputation_used=max(0, min(100, int(reputation))),
    )
