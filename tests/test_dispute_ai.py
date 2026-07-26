"""Tests for the deterministic dispute rubric + advisory narrative.

Verifies:
- Determinism: same input → same score, byte-for-byte.
- Monotonicity in the four intuitive axes.
- Score is always clamped to [-100, +100].
- Replay-flag always escalates to the arbiter panel.
- Above-cap escrows always escalate to the arbiter panel.
- Narrator is a pure string producer with no LLM by default.
"""

from __future__ import annotations

import pytest

from server.dispute_ai import RubricInput, RubricVerdict, narrate_verdict, score_dispute


def _base_input(**overrides) -> RubricInput:
    defaults = dict(
        escrow_amount_motes=500_000_000,
        time_to_dispute_seconds=3600,
        claimant_reputation=50,
        respondent_reputation=50,
        claimant_evidence_count=0,
        respondent_evidence_count=0,
        claimant_prior_disputes=0,
        respondent_prior_disputes=0,
        evidence_provenance_verified=False,
        x402_replay_flagged=False,
    )
    defaults.update(overrides)
    return RubricInput(**defaults)


# --- Determinism ---------------------------------------------------------- #


def test_score_dispute_is_deterministic() -> None:
    """Same input → same verdict, byte-for-byte (frozen dataclasses)."""
    inp = _base_input(
        claimant_reputation=80,
        respondent_reputation=30,
        claimant_evidence_count=3,
    )
    v1 = score_dispute(inp)
    v2 = score_dispute(inp)
    assert v1 == v2
    assert v1.score == v2.score
    assert v1.reasons == v2.reasons


def test_score_symmetric_neutral_case() -> None:
    """Perfectly symmetric case (all deltas zero) → score 0, insufficient."""
    v = score_dispute(_base_input())
    assert v.score == 0
    assert v.label == "insufficient"
    assert v.needs_arbiter_panel is True


# --- Monotonicity in the four axes ---------------------------------------- #


def test_reputation_delta_favours_higher_side() -> None:
    """Claimant with higher rep gets positive score."""
    v = score_dispute(_base_input(claimant_reputation=90, respondent_reputation=20))
    assert v.score > 0
    # Reason must be listed
    assert any(name == "reputation_delta" for name, _, _ in v.reasons)


def test_evidence_count_favours_more_evidence() -> None:
    v = score_dispute(_base_input(claimant_evidence_count=5, respondent_evidence_count=1))
    assert v.score > 0
    assert any(name == "evidence_count" for name, _, _ in v.reasons)


def test_prior_disputes_penalise_respondent() -> None:
    """More prior disputes on the respondent → claimant wins that signal."""
    v = score_dispute(_base_input(claimant_prior_disputes=0, respondent_prior_disputes=5))
    assert v.score > 0


def test_prior_disputes_penalise_claimant() -> None:
    """More prior disputes on the claimant → respondent wins that signal."""
    v = score_dispute(_base_input(claimant_prior_disputes=5, respondent_prior_disputes=0))
    assert v.score < 0


def test_provenance_verified_gives_big_boost() -> None:
    """Verified Merkle provenance is a strong claimant signal."""
    v = score_dispute(_base_input(claimant_evidence_count=1, evidence_provenance_verified=True))
    assert v.score >= 20
    assert any(name == "provenance_verified" for name, _, _ in v.reasons)


def test_provenance_needs_evidence_to_fire() -> None:
    """No evidence + provenance=True → provenance signal does not fire."""
    v = score_dispute(_base_input(evidence_provenance_verified=True))
    assert not any(name == "provenance_verified" for name, _, _ in v.reasons)


# --- Timeline sanity ------------------------------------------------------ #


def test_ultra_fast_dispute_is_penalised() -> None:
    """Dispute in <60s reads as noise, not signal."""
    v = score_dispute(_base_input(time_to_dispute_seconds=10))
    assert any(name == "timeline" and delta < 0 for name, delta, _ in v.reasons)


def test_ultra_late_dispute_is_penalised() -> None:
    """Dispute >30 days after escrow reads as shopping."""
    v = score_dispute(_base_input(time_to_dispute_seconds=60 * 24 * 3600))
    assert any(name == "timeline" and delta < 0 for name, delta, _ in v.reasons)


def test_sweet_spot_timeline_no_penalty() -> None:
    """Dispute at ~1h → no timeline penalty."""
    v = score_dispute(_base_input(time_to_dispute_seconds=3600))
    assert not any(name == "timeline" for name, _, _ in v.reasons)


# --- Safety properties ---------------------------------------------------- #


def test_replay_flag_always_escalates() -> None:
    """A replay hit MUST escalate to the arbiter panel regardless of score."""
    v = score_dispute(
        _base_input(
            claimant_reputation=100,
            respondent_reputation=0,
            claimant_evidence_count=10,
            evidence_provenance_verified=True,
            x402_replay_flagged=True,
        )
    )
    assert v.needs_arbiter_panel is True
    assert any(name == "x402_replay_flagged" for name, _, _ in v.reasons)


def test_above_cap_always_escalates() -> None:
    """Escrow at or above the 10 CSPR cap always needs the panel."""
    v = score_dispute(
        _base_input(
            escrow_amount_motes=10_000_000_000,
            claimant_reputation=90,
            claimant_evidence_count=5,
            evidence_provenance_verified=True,
        )
    )
    assert v.needs_arbiter_panel is True


def test_score_is_clamped_to_range() -> None:
    """Extreme inputs still bound the score to [-100, +100]."""
    v_pos = score_dispute(
        _base_input(
            claimant_reputation=100,
            respondent_reputation=0,
            claimant_evidence_count=10,
            respondent_evidence_count=0,
            claimant_prior_disputes=0,
            respondent_prior_disputes=20,
            evidence_provenance_verified=True,
        )
    )
    assert -100 <= v_pos.score <= 100

    v_neg = score_dispute(
        _base_input(
            claimant_reputation=0,
            respondent_reputation=100,
            claimant_evidence_count=0,
            respondent_evidence_count=10,
            claimant_prior_disputes=20,
            respondent_prior_disputes=0,
            x402_replay_flagged=True,
        )
    )
    assert -100 <= v_neg.score <= 100


# --- Label boundaries ----------------------------------------------------- #


def test_label_claimant_at_threshold() -> None:
    v = score_dispute(
        _base_input(
            claimant_reputation=80,
            respondent_reputation=20,
            claimant_evidence_count=2,
            evidence_provenance_verified=True,
        )
    )
    assert v.label == "claimant"


def test_label_respondent_at_threshold() -> None:
    v = score_dispute(
        _base_input(
            claimant_reputation=10,
            respondent_reputation=90,
            respondent_evidence_count=5,
            claimant_prior_disputes=15,
            time_to_dispute_seconds=60 * 24 * 3600 + 1,  # late
        )
    )
    assert v.label == "respondent", f"score={v.score}, reasons={v.reasons}"


def test_label_insufficient_close_to_zero() -> None:
    v = score_dispute(
        _base_input(
            claimant_reputation=55,
            respondent_reputation=50,
        )
    )
    assert v.label == "insufficient"


# --- Narrator ------------------------------------------------------------- #


def test_narrator_is_pure_string() -> None:
    """Default narrator emits deterministic string, no LLM."""
    v = score_dispute(
        _base_input(
            claimant_reputation=90,
            respondent_reputation=20,
            claimant_evidence_count=3,
            evidence_provenance_verified=True,
        )
    )
    text1 = narrate_verdict(v)
    text2 = narrate_verdict(v)
    assert text1 == text2  # deterministic
    assert "CLAIMANT" in text1
    assert "score=" in text1
    assert "advisory" in text1.lower()


def test_narrator_llm_is_advisory_only() -> None:
    """LLM path never mutates the verdict object."""
    v = score_dispute(_base_input(claimant_reputation=90))

    class _FakeLLM:
        def narrate(self, s: str) -> str:
            return "LLM-generated commentary here."

    text = narrate_verdict(v, llm_client=_FakeLLM(), enable_llm=True)
    assert "LLM-generated commentary" in text
    # The verdict itself is frozen and unchanged.
    with pytest.raises(Exception):
        v.score = 999  # frozen dataclass raises


def test_narrator_llm_failure_is_swallowed() -> None:
    """A crashing LLM must not break the narrator."""
    v = score_dispute(_base_input())

    class _BrokenLLM:
        def narrate(self, s: str) -> str:
            raise RuntimeError("provider down")

    text = narrate_verdict(v, llm_client=_BrokenLLM(), enable_llm=True)
    # Base template still present
    assert "advisory" in text.lower()
    # No LLM tail
    assert "Advisory (LLM" not in text


# --- Verdict shape -------------------------------------------------------- #


def test_verdict_is_frozen_dataclass() -> None:
    """`RubricVerdict` cannot be mutated after construction."""
    v = RubricVerdict(score=42, label="claimant", reasons=[("a", 42, "b")])
    with pytest.raises(Exception):
        v.score = 0  # type: ignore[misc]
