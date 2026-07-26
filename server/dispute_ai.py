"""
Dispute AI — deterministic rubric + optional advisory narrative.

The rubric is a pure function of the dispute inputs. Its output is the
canonical `RubricVerdict` — arbiters and the on-chain contract only ever
consume this. No LLM, no randomness, no I/O — the same inputs always
produce the same verdict, byte-for-byte, so the score is auditable and
reproducible in CI.

An optional `narrative` is available under a strict advisory flag: a
short LLM-generated explanation to help the judge/operator read the
verdict. The narrative is NEVER treated as evidence and NEVER changes
the score — it is a human-readable veneer only. All safety filters from
`server/agentic_safety.py` apply to the narrative call.

Public surface
--------------
- `RubricInput`        — typed inputs (evidence hashes, timing, party claims)
- `RubricVerdict`      — score + label + reasons (deterministic)
- `score_dispute(inp)` — pure rubric scorer
- `narrate_verdict(v)` — optional LLM narrative (advisory-only)

Design notes
------------
The scoring function is intentionally arithmetic and boring. Every
signal contributes a bounded number of points in [−50, +50]; the sum
is clamped to [−100, +100]. Signals that require *judgement* (like
"was the counterparty's evidence more compelling") are deliberately
absent from the rubric — those go to the arbiter panel, not the rubric.

Related:
- server/arbiter_crypto.py    (arbiter quorum + signature verification)
- server/agentic_safety.py    (LLM safety filter)
- demo/prompt_injection_demo.py
- docs/AGENTIC_SAFETY.md
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# --- Public types ---------------------------------------------------------- #


@dataclass(frozen=True)
class RubricInput:
    """Inputs consumed by the deterministic rubric.

    All fields are numeric or short strings so the rubric is a pure
    function of a small, well-defined domain.
    """

    escrow_amount_motes: int
    time_to_dispute_seconds: int
    """Seconds between escrow creation and dispute opening."""
    claimant_reputation: int  # 0-100
    respondent_reputation: int  # 0-100
    claimant_evidence_count: int
    respondent_evidence_count: int
    claimant_prior_disputes: int
    respondent_prior_disputes: int
    evidence_provenance_verified: bool = False
    """True iff every evidence blob has a valid on-chain Merkle proof."""
    x402_replay_flagged: bool = False
    """True iff the replay-guard fired on any claim/counterclaim submission."""


@dataclass(frozen=True)
class RubricVerdict:
    """Deterministic verdict emitted by `score_dispute`.

    `score` is in [-100, +100]. Positive favours the claimant, negative
    favours the respondent, 0 = tie / insufficient signal.

    `label` is one of:
      - "claimant"    — score >= +30
      - "respondent"  — score <= -30
      - "insufficient" — |score| < 30 (needs arbiter panel)

    `reasons` is an ordered list of (signal, delta, note) tuples so the
    verdict is fully explainable. Sum of deltas == score before clamp.
    """

    score: int
    label: str
    reasons: list[tuple[str, int, str]] = field(default_factory=list)
    # A dispute the rubric refuses to auto-decide is escalated. This
    # flag is a *hint* to the caller; the arbiter panel decides.
    needs_arbiter_panel: bool = True


# --- Rubric scorer --------------------------------------------------------- #


# Signal weights (max absolute contribution each). Tuning these is a
# governance action, not a runtime choice.
_W_REP_DELTA = 25
_W_EVIDENCE = 20
_W_PRIOR_DISPUTES = 15
_W_TIMELINE = 10
_W_PROVENANCE = 20
_W_REPLAY = 30


def score_dispute(inp: RubricInput) -> RubricVerdict:
    """Pure, deterministic rubric scorer.

    Never calls out to a network, never reads a clock, never uses
    randomness. Property-tested for monotonicity in the four intuitive
    axes (rep, evidence, priors, provenance).
    """

    reasons: list[tuple[str, int, str]] = []
    score = 0

    # 1) Reputation delta — bounded, symmetric.
    rep_delta = _clamp(inp.claimant_reputation - inp.respondent_reputation, -100, 100)
    rep_signal = int(rep_delta * _W_REP_DELTA / 100)
    if rep_signal:
        reasons.append(
            (
                "reputation_delta",
                rep_signal,
                f"claimant rep {inp.claimant_reputation} vs respondent {inp.respondent_reputation}",
            )
        )
        score += rep_signal

    # 2) Evidence count — bounded, symmetric.
    ev_delta = _clamp(
        inp.claimant_evidence_count - inp.respondent_evidence_count, -10, 10
    )
    ev_signal = int(ev_delta * _W_EVIDENCE / 10)
    if ev_signal:
        reasons.append(
            (
                "evidence_count",
                ev_signal,
                f"claimant {inp.claimant_evidence_count} vs respondent "
                f"{inp.respondent_evidence_count} evidence items",
            )
        )
        score += ev_signal

    # 3) Prior disputes — more priors → less credibility.
    pd_delta = _clamp(
        inp.respondent_prior_disputes - inp.claimant_prior_disputes, -20, 20
    )
    pd_signal = int(pd_delta * _W_PRIOR_DISPUTES / 20)
    if pd_signal:
        reasons.append(
            (
                "prior_disputes",
                pd_signal,
                f"claimant priors {inp.claimant_prior_disputes} vs respondent "
                f"{inp.respondent_prior_disputes}",
            )
        )
        score += pd_signal

    # 4) Timeline — extremely fast disputes are noise, extremely late
    #    ones are shopping. Small bounded penalty either way. Sweet spot
    #    is 10min–24h.
    t = inp.time_to_dispute_seconds
    if t < 60:
        reasons.append(("timeline", -_W_TIMELINE // 2, "dispute opened <60s after escrow"))
        score += -_W_TIMELINE // 2
    elif t > 30 * 24 * 3600:
        reasons.append(
            ("timeline", -_W_TIMELINE // 2, "dispute opened >30 days after escrow")
        )
        score += -_W_TIMELINE // 2

    # 5) Provenance verified — big positive for the claimant if the
    #    evidence blobs actually hash into the on-chain Merkle root.
    if inp.evidence_provenance_verified and inp.claimant_evidence_count > 0:
        reasons.append(
            (
                "provenance_verified",
                _W_PROVENANCE,
                "every evidence blob verified against on-chain Merkle root",
            )
        )
        score += _W_PROVENANCE

    # 6) Replay-guard flagged — hard negative regardless of who did it.
    #    A replay attempt anywhere in the flow is a strong integrity
    #    breach and MUST escalate to the arbiter panel.
    if inp.x402_replay_flagged:
        reasons.append(
            (
                "x402_replay_flagged",
                -_W_REPLAY,
                "replay-guard fired on at least one submission",
            )
        )
        score -= _W_REPLAY

    # Clamp final score.
    score = _clamp(score, -100, 100)

    if score >= 30:
        label = "claimant"
    elif score <= -30:
        label = "respondent"
    else:
        label = "insufficient"

    # Arbiter panel is always required for above-cap or replay-flagged
    # disputes — that's a safety property, not a rubric decision.
    needs_panel = (
        inp.x402_replay_flagged
        or inp.escrow_amount_motes >= 10_000_000_000  # 10 CSPR cap
        or label == "insufficient"
    )

    return RubricVerdict(
        score=score, label=label, reasons=reasons, needs_arbiter_panel=needs_panel
    )


def _clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, v))


# --- Optional advisory narrative ------------------------------------------ #


def narrate_verdict(
    verdict: RubricVerdict,
    *,
    llm_client: Any | None = None,
    enable_llm: bool = False,
) -> str:
    """Advisory: build a short human-readable explanation of the verdict.

    Returns a template-based string by default. If `enable_llm=True` and
    a `llm_client` is passed, an LLM narrative is *optionally* attached
    (with a hard SAFETY_FILTER around the input). The narrative is
    ADVISORY ONLY — it MUST NOT be treated as evidence and does not
    change the score.
    """

    header = (
        f"[Rubric verdict — {verdict.label.upper()}] "
        f"score={verdict.score:+d}  needs_arbiter_panel={verdict.needs_arbiter_panel}"
    )
    lines = [header, ""]
    for name, delta, note in verdict.reasons:
        sign = "+" if delta > 0 else ""
        lines.append(f"  • {name:24s} {sign}{delta:+3d}  — {note}")

    if not verdict.reasons:
        lines.append("  (no rubric signals fired — panel required)")

    lines.append("")
    lines.append(
        "  NOTE: this rubric is a pure function of the inputs above. The "
        "arbiter panel makes the binding decision; this text is advisory."
    )

    text = "\n".join(lines)

    if enable_llm and llm_client is not None:
        try:
            from server.agentic_safety import filter_untrusted  # optional
        except Exception:
            filter_untrusted = lambda s: s  # noqa: E731 — advisory fallback

        try:
            # ADVISORY: the LLM never sees the raw evidence, only the
            # already-scored verdict reasons. Even so, we filter.
            safe = filter_untrusted(text)
            addition = llm_client.narrate(safe)  # duck-typed shim
            text += "\n\n--- Advisory (LLM, non-binding) ---\n" + addition
        except Exception as exc:  # never let LLM path break the verdict
            logger.debug("LLM narration skipped: %s", exc)

    return text
