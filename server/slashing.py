"""
Slashing hooks (A) — economic accountability for arbiter misbehaviour.

The slashing module is a pure decision function: it converts an
`Offence` (with a canonical evidence bundle) into a `SlashingDecision`
containing:

  - `offence_kind` — one of {equivocation, reveal_mismatch, no_show,
                             collusion_signal, above_cap_signing}
  - `bond_burn_fraction`     — bps of the arbiter bond to burn
  - `panel_ban_days`         — how long they are barred from the panel
  - `flags`                  — audit tags for the incident report

The actual chain-level bond transfer happens in
`contracts/challenge_arbiter/`. Python side does the math and the
book-keeping so the WASM contract can stay small.

Offence catalogue
-----------------

  equivocation
    Signed *two* different verdicts on the same escrow. Hard slash:
    burn 100% bond, permanent panel ban.

  reveal_mismatch
    Reveal did not match the previously-posted commit. Medium slash:
    burn 50% bond, 30d panel ban.

  no_show
    Committed but never revealed within the reveal window. Soft
    slash: burn 10% bond, 7d panel ban.

  collusion_signal
    Statistical detector (server/arbiter_analytics.py) flagged
    ≥ 3 identical-verdict clusters in the last N cases. Soft
    slash: burn 5%, 14d panel ban. Advisory pending panel review.

  above_cap_signing
    Signed off on an escrow above the 10-CSPR cap without the
    required quorum. Medium slash: burn 30% bond, 21d panel ban.

Related:
- server/arbiter_commit_reveal.py  (reveal_mismatch feeds this)
- server/arbiter_crypto.py         (equivocation detection)
- docs/AGENTIC_SAFETY.md
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

OffenceKind = Literal[
    "equivocation",
    "reveal_mismatch",
    "no_show",
    "collusion_signal",
    "above_cap_signing",
]


@dataclass(frozen=True)
class Offence:
    kind: OffenceKind
    arbiter_pubkey_hex: str
    escrow_hash: str
    evidence: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class SlashingDecision:
    offence_kind: OffenceKind
    bond_burn_bps: int  # 10000 = 100%
    panel_ban_days: int
    flags: list[str] = field(default_factory=list)


# The catalogue above, expressed as data. Kept in one place so tests
# assert the exact numbers.
_CATALOGUE: dict[OffenceKind, tuple[int, int, list[str]]] = {
    "equivocation": (10_000, 3650, ["hard_slash", "permanent_ban"]),
    "reveal_mismatch": (5_000, 30, ["medium_slash"]),
    "no_show": (1_000, 7, ["soft_slash"]),
    "collusion_signal": (500, 14, ["soft_slash", "advisory"]),
    "above_cap_signing": (3_000, 21, ["medium_slash"]),
}


def decide(offence: Offence) -> SlashingDecision:
    """Return the deterministic slashing decision for `offence`.

    Pure function. No I/O, no clock, no randomness. Property-tested
    for symmetry across offence kinds.
    """
    if offence.kind not in _CATALOGUE:
        raise ValueError(f"unknown offence kind {offence.kind!r}")
    burn_bps, ban_days, flags = _CATALOGUE[offence.kind]
    return SlashingDecision(
        offence_kind=offence.kind,
        bond_burn_bps=burn_bps,
        panel_ban_days=ban_days,
        flags=list(flags),  # copy so callers can't mutate the catalogue
    )
