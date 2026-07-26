"""
Adaptive arbiter panel sizing (A).

Above the 10-CSPR cap, arbiter panels get bigger. Below the cap, a
3-arbiter panel is plenty. This module returns the panel size for a
given escrow amount using a simple monotonic step function, easy to
reason about and cheap to prove.

  amount             panel size (arbiters, must be odd)
  ─────────────────────────────────────────────────────
  < 1 CSPR                                     3
  1 – 10 CSPR                                  5
  10 – 100 CSPR                                7
  ≥ 100 CSPR                                   9

Odd panel sizes → no ties → simple majority is well-defined without
the AI arbiter tiebreak layer.

Related:
- server/arbiter_crypto.py (quorum threshold uses this)
- server/insurance.py      (above-cap claims require the bigger panel)
"""

from __future__ import annotations

from dataclasses import dataclass

# CSPR in motes.
_ONE_CSPR = 1_000_000_000
_CAP_10_CSPR = 10 * _ONE_CSPR
_CAP_100_CSPR = 100 * _ONE_CSPR


@dataclass(frozen=True)
class PanelSize:
    arbiters: int
    quorum: int  # simple majority: floor(n/2) + 1
    tier: str


def panel_size_for_amount(amount_motes: int) -> PanelSize:
    if amount_motes <= 0:
        raise ValueError("amount_motes must be positive")

    if amount_motes < _ONE_CSPR:
        n, tier = 3, "small"
    elif amount_motes < _CAP_10_CSPR:
        n, tier = 5, "medium"
    elif amount_motes < _CAP_100_CSPR:
        n, tier = 7, "large"
    else:
        n, tier = 9, "jumbo"

    quorum = n // 2 + 1
    return PanelSize(arbiters=n, quorum=quorum, tier=tier)


def is_odd_panel_size(size: int) -> bool:
    """Panel sizes MUST be odd — no ties."""
    return size >= 3 and size % 2 == 1
