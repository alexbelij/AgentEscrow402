"""Tests for the slashing decision function."""

from __future__ import annotations

import pytest

from server.slashing import Offence, decide


def _offence(kind: str, **kw) -> Offence:
    return Offence(
        kind=kind,  # type: ignore[arg-type]
        arbiter_pubkey_hex=kw.get("arbiter", "aa" * 33),
        escrow_hash=kw.get("escrow", "bb" * 32),
        evidence=kw.get("evidence", {}),
    )


# --- Determinism -------------------------------------------------------- #


def test_deterministic() -> None:
    o = _offence("reveal_mismatch")
    d1 = decide(o)
    d2 = decide(o)
    assert d1 == d2


def test_evidence_does_not_change_outcome() -> None:
    """Same kind, different evidence → same slashing decision.

    Evidence is audit metadata; the decision function is a pure map
    from `kind` → numbers so the on-chain contract can mirror it.
    """
    a = decide(_offence("reveal_mismatch", evidence={"foo": "bar"}))
    b = decide(_offence("reveal_mismatch", evidence={"baz": "qux"}))
    assert a.bond_burn_bps == b.bond_burn_bps
    assert a.panel_ban_days == b.panel_ban_days


# --- Catalogue exact numbers -------------------------------------------- #


def test_equivocation_is_permanent() -> None:
    d = decide(_offence("equivocation"))
    assert d.bond_burn_bps == 10_000  # 100%
    assert d.panel_ban_days >= 365 * 5
    assert "hard_slash" in d.flags
    assert "permanent_ban" in d.flags


def test_reveal_mismatch_medium() -> None:
    d = decide(_offence("reveal_mismatch"))
    assert d.bond_burn_bps == 5_000  # 50%
    assert d.panel_ban_days == 30
    assert "medium_slash" in d.flags


def test_no_show_soft() -> None:
    d = decide(_offence("no_show"))
    assert d.bond_burn_bps == 1_000
    assert d.panel_ban_days == 7
    assert "soft_slash" in d.flags


def test_collusion_signal_soft_advisory() -> None:
    d = decide(_offence("collusion_signal"))
    assert d.bond_burn_bps == 500
    assert "advisory" in d.flags


def test_above_cap_signing_medium() -> None:
    d = decide(_offence("above_cap_signing"))
    assert d.bond_burn_bps == 3_000
    assert d.panel_ban_days == 21


# --- Rejects garbage ---------------------------------------------------- #


def test_unknown_kind_raises() -> None:
    with pytest.raises(ValueError, match="unknown offence kind"):
        decide(_offence("selling_state_secrets"))


# --- Monotonicity ------------------------------------------------------- #


def test_equivocation_is_worst() -> None:
    """Equivocation slashes more than any other offence — by design."""
    equiv = decide(_offence("equivocation"))
    for kind in ["reveal_mismatch", "no_show", "collusion_signal", "above_cap_signing"]:
        other = decide(_offence(kind))
        assert equiv.bond_burn_bps >= other.bond_burn_bps
        assert equiv.panel_ban_days >= other.panel_ban_days


def test_flags_are_defensive_copies() -> None:
    """Mutating the returned flags MUST NOT poison the catalogue."""
    d1 = decide(_offence("no_show"))
    d1.flags.append("injected")
    d2 = decide(_offence("no_show"))
    assert "injected" not in d2.flags
