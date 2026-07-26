"""Tests for `server.compliance` — the deterministic compliance policy
engine for regulated jurisdictions (T3.7)."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from server.compliance import (
    ComplianceEngine,
    ComplianceRejection,
    JurisdictionPolicy,
    JurisdictionRegime,
    ReportReason,
)
from server.identity_registry import VerificationLevel

MOTES = 10**9  # 1 CSPR


@pytest.fixture
def engine() -> ComplianceEngine:
    return ComplianceEngine()


# ── Unrestricted jurisdictions ──────────────────────────────────────────


def test_unrestricted_small_tx_permitted_no_reporting(engine: ComplianceEngine):
    d = engine.evaluate("US", VerificationLevel.UNVERIFIED, amount_motes=10 * MOTES)
    assert d.permitted
    assert not d.rejections
    assert not d.requires_reporting


def test_unrestricted_still_gated_by_unverified_verification_is_fine(engine: ComplianceEngine):
    # Unrestricted jurisdictions have no min_verification requirement.
    d = engine.evaluate("GB", VerificationLevel.UNVERIFIED, amount_motes=1 * MOTES)
    assert d.permitted


def test_unrestricted_large_tx_still_permitted_but_reported(engine: ComplianceEngine):
    d = engine.evaluate("SG", VerificationLevel.FULL, amount_motes=15_000 * MOTES)
    assert d.permitted
    assert d.requires_reporting
    assert ReportReason.LARGE_TRANSACTION in d.report_reasons


# ── Prohibited jurisdictions ─────────────────────────────────────────────


@pytest.mark.parametrize("cc", ["KP", "IR"])
def test_prohibited_jurisdiction_always_blocked(engine: ComplianceEngine, cc: str):
    d = engine.evaluate(cc, VerificationLevel.FULL, amount_motes=1)
    assert not d.permitted
    assert ComplianceRejection.JURISDICTION_PROHIBITED in d.rejections
    assert d.regime is JurisdictionRegime.PROHIBITED


def test_prohibited_jurisdiction_attempt_is_itself_reported(engine: ComplianceEngine):
    # Even though blocked, the attempt is a compliance signal worth a record.
    d = engine.evaluate("KP", VerificationLevel.FULL, amount_motes=1)
    assert d.requires_reporting
    assert ReportReason.RESTRICTED_JURISDICTION in d.report_reasons


def test_prohibited_jurisdiction_no_amount_or_verification_override(engine: ComplianceEngine):
    # No amount is small enough, no verification tier is high enough.
    d = engine.evaluate("IR", VerificationLevel.FULL, amount_motes=0)
    assert not d.permitted


# ── Restricted jurisdictions — verification gating ──────────────────────


def test_restricted_jurisdiction_insufficient_verification_rejected(engine: ComplianceEngine):
    d = engine.evaluate("NG", VerificationLevel.UNVERIFIED, amount_motes=1 * MOTES)
    assert not d.permitted
    assert ComplianceRejection.INSUFFICIENT_VERIFICATION in d.rejections


def test_restricted_jurisdiction_exact_min_verification_passes(engine: ComplianceEngine):
    # NG requires ENHANCED — exactly ENHANCED should pass (>=, not >).
    d = engine.evaluate("NG", VerificationLevel.ENHANCED, amount_motes=1 * MOTES)
    assert ComplianceRejection.INSUFFICIENT_VERIFICATION not in d.rejections


def test_restricted_jurisdiction_higher_than_min_verification_passes(engine: ComplianceEngine):
    d = engine.evaluate("NG", VerificationLevel.FULL, amount_motes=1 * MOTES)
    assert ComplianceRejection.INSUFFICIENT_VERIFICATION not in d.rejections


def test_restricted_jurisdiction_permitted_when_all_gates_pass(engine: ComplianceEngine):
    d = engine.evaluate("TR", VerificationLevel.BASIC, amount_motes=1 * MOTES)
    assert d.permitted
    assert d.requires_reporting  # restricted jurisdiction is always reported
    assert ReportReason.RESTRICTED_JURISDICTION in d.report_reasons


# ── Restricted jurisdictions — caps ──────────────────────────────────────


def test_restricted_jurisdiction_single_tx_cap_exceeded(engine: ComplianceEngine):
    # NG cap is 5,000 CSPR per tx.
    d = engine.evaluate("NG", VerificationLevel.FULL, amount_motes=6_000 * MOTES)
    assert not d.permitted
    assert ComplianceRejection.TRANSACTION_CAP_EXCEEDED in d.rejections


def test_restricted_jurisdiction_single_tx_at_exact_cap_passes(engine: ComplianceEngine):
    d = engine.evaluate("NG", VerificationLevel.FULL, amount_motes=5_000 * MOTES)
    assert ComplianceRejection.TRANSACTION_CAP_EXCEEDED not in d.rejections


def test_restricted_jurisdiction_daily_volume_cap_exceeded(engine: ComplianceEngine):
    # NG daily cap is 20,000 CSPR; prior 18,000 + this 3,000 = 21,000 > cap.
    d = engine.evaluate(
        "NG",
        VerificationLevel.FULL,
        amount_motes=3_000 * MOTES,
        prior_volume_today_motes=18_000 * MOTES,
    )
    assert not d.permitted
    assert ComplianceRejection.DAILY_VOLUME_CAP_EXCEEDED in d.rejections


def test_restricted_jurisdiction_daily_volume_at_exact_cap_passes(engine: ComplianceEngine):
    d = engine.evaluate(
        "NG",
        VerificationLevel.FULL,
        amount_motes=2_000 * MOTES,
        prior_volume_today_motes=18_000 * MOTES,
    )
    assert ComplianceRejection.DAILY_VOLUME_CAP_EXCEEDED not in d.rejections


def test_restricted_jurisdiction_approaching_daily_cap_flagged_for_rolling_report(engine: ComplianceEngine):
    # 80%+ of daily cap triggers a rolling-volume report even if permitted.
    d = engine.evaluate(
        "NG",
        VerificationLevel.FULL,
        amount_motes=1_000 * MOTES,
        prior_volume_today_motes=16_500 * MOTES,  # 17,500 / 20,000 = 87.5%
    )
    assert d.permitted
    assert ReportReason.ROLLING_VOLUME_THRESHOLD in d.report_reasons


def test_restricted_jurisdiction_multiple_rejections_all_surfaced(engine: ComplianceEngine):
    # Insufficient verification AND over the single-tx cap simultaneously.
    d = engine.evaluate("VE", VerificationLevel.UNVERIFIED, amount_motes=2_000 * MOTES)
    assert not d.permitted
    assert ComplianceRejection.INSUFFICIENT_VERIFICATION in d.rejections
    assert ComplianceRejection.TRANSACTION_CAP_EXCEEDED in d.rejections
    assert len(d.rejections) == 2


# ── Unknown jurisdiction — fail closed ───────────────────────────────────


def test_unknown_jurisdiction_fails_closed(engine: ComplianceEngine):
    d = engine.evaluate("ZZ", VerificationLevel.FULL, amount_motes=1)
    assert not d.permitted
    assert ComplianceRejection.UNKNOWN_JURISDICTION in d.rejections
    assert d.regime is JurisdictionRegime.PROHIBITED  # reported as the most conservative regime


def test_unknown_jurisdiction_not_reported_separately(engine: ComplianceEngine):
    # Unknown-jurisdiction short-circuits before the reporting logic runs —
    # requires_reporting stays False; the rejection itself is the signal.
    d = engine.evaluate("ZZ", VerificationLevel.FULL, amount_motes=1)
    assert not d.requires_reporting


# ── Country-code normalization ───────────────────────────────────────────


def test_country_code_is_case_and_whitespace_normalized(engine: ComplianceEngine):
    d1 = engine.evaluate("us", VerificationLevel.UNVERIFIED, amount_motes=1)
    d2 = engine.evaluate(" US ", VerificationLevel.UNVERIFIED, amount_motes=1)
    assert d1.permitted and d2.permitted
    assert d1.country_code == "US"
    assert d2.country_code == "US"


# ── Custom policy table (replaceability) ─────────────────────────────────


def test_engine_accepts_custom_policy_table_wholesale():
    custom = ComplianceEngine(
        policies={
            "FR": JurisdictionPolicy("FR", JurisdictionRegime.UNRESTRICTED),
            "XX": JurisdictionPolicy("XX", JurisdictionRegime.PROHIBITED),
        }
    )
    assert custom.evaluate("FR", VerificationLevel.UNVERIFIED, amount_motes=1).permitted
    assert not custom.evaluate("XX", VerificationLevel.FULL, amount_motes=1).permitted
    # Default-table-only jurisdictions are gone once the table is replaced.
    assert not custom.evaluate("US", VerificationLevel.FULL, amount_motes=1).permitted


def test_engine_accepts_custom_large_transaction_threshold():
    custom = ComplianceEngine(large_transaction_threshold_motes=100 * MOTES)
    d = custom.evaluate("US", VerificationLevel.FULL, amount_motes=150 * MOTES)
    assert d.requires_reporting
    assert ReportReason.LARGE_TRANSACTION in d.report_reasons


# ── list_jurisdictions ────────────────────────────────────────────────────


def test_list_jurisdictions_stable_sorted_order(engine: ComplianceEngine):
    codes = [p.country_code for p in engine.list_jurisdictions()]
    assert codes == sorted(codes)
    assert "US" in codes and "KP" in codes


# ── Determinism / purity ─────────────────────────────────────────────────


def test_evaluate_is_pure_same_inputs_same_output(engine: ComplianceEngine):
    d1 = engine.evaluate(
        "NG", VerificationLevel.BASIC, amount_motes=3_000 * MOTES, prior_volume_today_motes=1_000 * MOTES
    )
    d2 = engine.evaluate(
        "NG", VerificationLevel.BASIC, amount_motes=3_000 * MOTES, prior_volume_today_motes=1_000 * MOTES
    )
    assert d1 == d2


# ── Property-based tests ──────────────────────────────────────────────────


@given(amount=st.integers(min_value=0, max_value=10**15))
def test_property_prohibited_never_permitted_regardless_of_amount(amount: int):
    engine = ComplianceEngine()
    d = engine.evaluate("KP", VerificationLevel.FULL, amount_motes=amount)
    assert not d.permitted


@given(amount=st.integers(min_value=0, max_value=4_999 * MOTES))
def test_property_unrestricted_below_reporting_threshold_never_requires_reporting(amount: int):
    engine = ComplianceEngine()
    d = engine.evaluate("US", VerificationLevel.FULL, amount_motes=amount)
    assert d.permitted
    assert not d.requires_reporting


@given(
    verification=st.sampled_from(list(VerificationLevel)),
    amount=st.integers(min_value=0, max_value=10**12),
)
def test_property_unknown_jurisdiction_always_fails_closed(verification: VerificationLevel, amount: int):
    engine = ComplianceEngine()
    d = engine.evaluate("Q1", verification, amount_motes=amount)
    assert not d.permitted
    assert ComplianceRejection.UNKNOWN_JURISDICTION in d.rejections
