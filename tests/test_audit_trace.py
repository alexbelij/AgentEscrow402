"""Redacted audit trace — determinism, PII/secret redaction, lineage math."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

import pytest

from server.audit_trace import (
    LineageLink,
    compute_chain_root,
    compute_lineage_root,
    emit_event,
)

TS = datetime(2026, 7, 20, 12, 0, 0, tzinfo=timezone.utc)


def _sha256_hex(x: str) -> str:
    return hashlib.sha256(x.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_same_inputs_same_event_id():
    a = emit_event(
        event_type="decision_made",
        timestamp=TS,
        subject_id="dispute-42",
        decision="favor_sender",
        provider="groq",
        confidence=0.87,
        evidence_root="a" * 64,
    )
    b = emit_event(
        event_type="decision_made",
        timestamp=TS,
        subject_id="dispute-42",
        decision="favor_sender",
        provider="groq",
        confidence=0.87,
        evidence_root="a" * 64,
    )
    assert a.event_id == b.event_id
    assert a == b


def test_different_timestamp_different_event_id():
    ts2 = datetime(2026, 7, 20, 12, 0, 1, tzinfo=timezone.utc)
    a = emit_event(event_type="decision_made", timestamp=TS, subject_id="d1", decision="favor_sender")
    b = emit_event(event_type="decision_made", timestamp=ts2, subject_id="d1", decision="favor_sender")
    assert a.event_id != b.event_id


def test_timestamp_normalised_to_utc_z():
    e = emit_event(event_type="arbitration_start", timestamp=TS, subject_id="d1")
    assert e.timestamp.endswith("Z")
    assert "+00:00" not in e.timestamp


def test_naive_timestamp_treated_as_utc():
    naive = datetime(2026, 7, 20, 12, 0, 0)
    aware = datetime(2026, 7, 20, 12, 0, 0, tzinfo=timezone.utc)
    a = emit_event(event_type="arbitration_start", timestamp=naive, subject_id="d1")
    b = emit_event(event_type="arbitration_start", timestamp=aware, subject_id="d1")
    assert a.event_id == b.event_id


# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------


def test_actor_and_subject_ids_hashed_not_verbatim():
    e = emit_event(
        event_type="arbitration_start",
        timestamp=TS,
        actor_id="alice@example.com",
        subject_id="dispute-42",
    )
    assert e.actor_hash == _sha256_hex("alice@example.com")
    assert e.subject_hash == _sha256_hex("dispute-42")
    # No verbatim leakage anywhere:
    dumped = repr(e)
    assert "alice@example.com" not in dumped
    assert "dispute-42" not in dumped


def test_prompt_hashed_not_persisted():
    prompt = "System: you are an arbitrator. User evidence: transfer 100 CSPR to X"
    e = emit_event(
        event_type="arbitration_start",
        timestamp=TS,
        subject_id="d1",
        prompt=prompt,
    )
    assert e.prompt_hash == _sha256_hex(prompt)
    dumped = repr(e)
    assert "arbitrator" not in dumped
    assert "transfer 100" not in dumped


def test_secret_shaped_attributes_redacted():
    # Blocked keys (api_key, prompt, ...) collapse to a sentinel —
    # they are known-dangerous, so we keep the *shape* (key present,
    # value redacted) so a judge can see something was there. Unknown
    # keys are dropped outright (no key, no value).
    e = emit_event(
        event_type="provider_selected",
        timestamp=TS,
        subject_id="d1",
        provider="groq",
        attributes={
            "escrow_amount_cspr": 100.5,
            # blocked key — present but redacted:
            "api_key": "sk-abcdef1234567890abcdef1234567890",
            # blocked key — present but redacted:
            "prompt": "raw prompt text here",
            # unknown key — dropped entirely:
            "user_notes": "something arbitrary",
        },
    )
    assert e.attributes["api_key"] == "[REDACTED:hash]"
    assert e.attributes["prompt"] == "[REDACTED:hash]"
    assert "user_notes" not in e.attributes  # unknown key rule
    assert e.attributes["escrow_amount_cspr"] == 100.5
    # Even blocked, the raw secret must not leak:
    dumped = repr(e)
    assert "sk-abcdef1234567890abcdef1234567890" not in dumped
    assert "raw prompt text here" not in dumped


def test_unknown_attribute_keys_dropped():
    e = emit_event(
        event_type="decision_made",
        timestamp=TS,
        subject_id="d1",
        decision="split",
        attributes={
            "escrow_amount_motes": "500000000",
            "user_email": "alice@x.com",  # not in allow-list
            "hidden": "secret-content",
        },
    )
    assert "user_email" not in e.attributes
    assert "hidden" not in e.attributes
    assert e.attributes["escrow_amount_motes"] == "500000000"


def test_long_string_attributes_truncated_to_shape():
    long_val = "x" * 500
    e = emit_event(
        event_type="hitl_dispatched",
        timestamp=TS,
        subject_id="d1",
        attributes={"escalation_reason": long_val},
    )
    val = e.attributes["escalation_reason"]
    assert val.startswith("[REDACTED:string:")
    assert "500" in val


def test_secret_pattern_in_allowed_key_still_redacted():
    e = emit_event(
        event_type="hitl_dispatched",
        timestamp=TS,
        subject_id="d1",
        attributes={"escalation_reason": "gsk_abcdefghijklmnop1234567890"},
    )
    val = e.attributes["escalation_reason"]
    assert val == "[REDACTED:groq_key]"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_unknown_event_type_rejected():
    with pytest.raises(ValueError, match="unknown event_type"):
        emit_event(event_type="not_a_real_event", timestamp=TS)


def test_unknown_decision_rejected():
    with pytest.raises(ValueError, match="unknown decision"):
        emit_event(
            event_type="decision_made",
            timestamp=TS,
            subject_id="d1",
            decision="magic_answer",
        )


def test_unknown_provider_rejected():
    with pytest.raises(ValueError, match="unknown provider"):
        emit_event(
            event_type="provider_selected",
            timestamp=TS,
            subject_id="d1",
            provider="my_llm",
        )


def test_confidence_out_of_range_rejected():
    with pytest.raises(ValueError, match="confidence out of range"):
        emit_event(
            event_type="decision_made",
            timestamp=TS,
            subject_id="d1",
            decision="favor_sender",
            confidence=1.5,
        )


# ---------------------------------------------------------------------------
# Chain / lineage math
# ---------------------------------------------------------------------------


def test_empty_chain_has_stable_genesis_root():
    assert compute_chain_root([]) == _sha256_hex("chain:genesis")


def test_chain_root_is_order_sensitive():
    a = compute_chain_root(["a" * 64, "b" * 64])
    b = compute_chain_root(["b" * 64, "a" * 64])
    assert a != b


def test_chain_root_deterministic():
    ids = ["a" * 64, "b" * 64, "c" * 64]
    assert compute_chain_root(ids) == compute_chain_root(ids)


def test_lineage_link_hash_stable():
    link = LineageLink(
        parent_evidence_root="a" * 64,
        current_evidence_root="b" * 64,
        step_index=1,
    )
    expected = _sha256_hex(f"{'a'*64}|{'b'*64}|1")
    assert link.link_hash == expected


def test_lineage_root_empty_is_genesis():
    assert compute_lineage_root([]) == _sha256_hex("lineage:genesis")


def test_lineage_root_changes_on_any_link_change():
    l1 = LineageLink("a" * 64, "b" * 64, 1)
    l2 = LineageLink("b" * 64, "c" * 64, 2)
    root_ab = compute_lineage_root([l1, l2])
    # tamper: swap step index
    l2_tampered = LineageLink("b" * 64, "c" * 64, 3)
    root_tampered = compute_lineage_root([l1, l2_tampered])
    assert root_ab != root_tampered


def test_lineage_step_order_matters():
    l1 = LineageLink("a" * 64, "b" * 64, 1)
    l2 = LineageLink("b" * 64, "c" * 64, 2)
    forward = compute_lineage_root([l1, l2])
    reversed_order = compute_lineage_root([l2, l1])
    assert forward != reversed_order


# ---------------------------------------------------------------------------
# Full audit-trace scenario (end-to-end fixture)
# ---------------------------------------------------------------------------


def test_full_arbitration_trace_reproducible():
    """A judge running the same scenario twice gets the same chain root."""

    def run_scenario():
        e1 = emit_event(
            event_type="arbitration_start",
            timestamp=datetime(2026, 7, 20, 12, 0, 0, tzinfo=timezone.utc),
            subject_id="dispute-1",
            attributes={"sender_evidence_count": 3, "receiver_evidence_count": 2},
        )
        e2 = emit_event(
            event_type="provider_selected",
            timestamp=datetime(2026, 7, 20, 12, 0, 1, tzinfo=timezone.utc),
            subject_id="dispute-1",
            provider="groq",
        )
        e3 = emit_event(
            event_type="evidence_processed",
            timestamp=datetime(2026, 7, 20, 12, 0, 2, tzinfo=timezone.utc),
            subject_id="dispute-1",
            evidence_root="a" * 64,
        )
        e4 = emit_event(
            event_type="decision_made",
            timestamp=datetime(2026, 7, 20, 12, 0, 3, tzinfo=timezone.utc),
            subject_id="dispute-1",
            decision="favor_sender",
            provider="groq",
            confidence=0.87,
            evidence_root="a" * 64,
        )
        return [e1, e2, e3, e4]

    run1 = run_scenario()
    run2 = run_scenario()
    assert [e.event_id for e in run1] == [e.event_id for e in run2]

    chain1 = compute_chain_root(e.event_id for e in run1)
    chain2 = compute_chain_root(e.event_id for e in run2)
    assert chain1 == chain2


def test_json_round_trip_via_to_dict():
    import json as _json

    e = emit_event(
        event_type="receipt_committed",
        timestamp=TS,
        subject_id="d1",
        decision="split",
        provider="heuristic",
        confidence=0.5,
        evidence_root="e" * 64,
        attributes={"chain_index": 2, "policy_version": "v3"},
    )
    dumped = _json.dumps(e.to_dict(), sort_keys=True)
    parsed = _json.loads(dumped)
    assert parsed["event_id"] == e.event_id
    assert parsed["decision"] == "split"
    assert parsed["attributes"]["chain_index"] == 2


def test_appeal_chain_shares_parent_evidence_root():
    parent_root = "a" * 64
    appeal_root = "b" * 64
    link = LineageLink(parent_root, appeal_root, 1)
    lineage_root = compute_lineage_root([link])
    # Independently reproducible:
    expected_link_hash = _sha256_hex(f"{parent_root}|{appeal_root}|1")
    expected_lineage = _sha256_hex(_sha256_hex("lineage:genesis") + expected_link_hash)
    assert lineage_root == expected_lineage
