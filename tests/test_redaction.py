"""Tests for server/redaction.py — PII / secret redaction for public trace,
evidence, and log surfaces.

Covers:
- `hash_content` — determinism, prefix format, length control
- `redact_text` — emails, API keys, JWTs, bearer tokens, phone, credit-card
- `redact_evidence` — description hashing + truncation + keeps public fields
- `redact_prompt_for_log` — collapses full prompt to metadata only
- Idempotency and no-op safety
"""

from __future__ import annotations

import hashlib
import re

import pytest

from server.redaction import (
    hash_content,
    redact_evidence,
    redact_prompt_for_log,
    redact_text,
)

# ---------------------------------------------------------------------------
# hash_content
# ---------------------------------------------------------------------------


def test_hash_content_deterministic():
    a = hash_content("hello world")
    b = hash_content("hello world")
    assert a == b
    assert a.startswith("sha256:")
    # 12 hex chars by default
    assert len(a) == len("sha256:") + 12


def test_hash_content_matches_stdlib():
    text = "quentin@adspower.com"
    got = hash_content(text)
    expected_hex = hashlib.sha256(text.encode()).hexdigest()[:12]
    assert got == f"sha256:{expected_hex}"


def test_hash_content_rejects_bad_chars():
    with pytest.raises(ValueError):
        hash_content("x", chars=2)
    with pytest.raises(ValueError):
        hash_content("x", chars=100)


def test_hash_content_bytes_input():
    got = hash_content(b"\x00\x01\x02")
    assert got.startswith("sha256:")


# ---------------------------------------------------------------------------
# redact_text — PII patterns
# ---------------------------------------------------------------------------


def test_redact_email():
    out = redact_text("Contact me at quentin@adspower.com for details")
    assert "quentin@adspower.com" not in out
    assert "<email:sha256:" in out


def test_redact_multiple_emails():
    out = redact_text("a@x.com talked to b@y.co about c@z.io")
    # None of the raw addresses should survive
    for raw in ("a@x.com", "b@y.co", "c@z.io"):
        assert raw not in out
    # Three redaction tokens
    assert out.count("<email:sha256:") == 3


def test_redact_bearer_token():
    raw = "Authorization: Bearer sk-live-abcdefghijklmnop1234567890abcdef"
    out = redact_text(raw)
    assert "sk-live-abcdefghijklmnop1234567890abcdef" not in out
    assert "<secret:sha256:" in out


def test_redact_openai_style_key():
    raw = "key=sk-proj-XXXXXXXXXXXXXXXXXXXXXXXXXX in config"
    out = redact_text(raw)
    assert "sk-proj-XXXXXXXXXXXXXXXXXXXXXXXXXX" not in out
    assert "<secret:sha256:" in out


def test_redact_jwt():
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NSJ9.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
    out = redact_text(f"token={jwt} rest of message")
    assert jwt not in out
    assert "<secret:sha256:" in out


def test_redact_phone_number():
    out = redact_text("call me on +1 (555) 123-4567 tonight")
    # Digits should be replaced
    assert "555" not in out or "<phone:sha256:" in out
    assert "<phone:sha256:" in out


def test_redact_leaves_safe_text_alone():
    safe = "escrow released after 30 seconds, contract=verifier_gate"
    assert redact_text(safe) == safe


def test_redact_idempotent():
    once = redact_text("email me at test@example.com right away")
    twice = redact_text(once)
    assert once == twice


def test_redact_truncation():
    long = "x" * 500
    out = redact_text(long, max_len=100)
    assert len(out) == 100
    assert out.endswith("…")


def test_redact_none_or_empty_safe():
    assert redact_text("") == ""


# ---------------------------------------------------------------------------
# redact_evidence
# ---------------------------------------------------------------------------


def test_redact_evidence_dict_preserves_public_fields():
    ev = {
        "escrow_id": "abc123",
        "claimant": "01a1b2c3",
        "evidence_type": "text",
        "content_hash": "deadbeef" * 8,
        "description": "customer email quentin@adspower.com complained about delay",
        "timestamp": 1_700_000_000,
    }
    out = redact_evidence(ev)
    assert out["escrow_id"] == "abc123"
    assert out["claimant"] == "01a1b2c3"
    assert out["evidence_type"] == "text"
    assert out["content_hash"] == "deadbeef" * 8
    assert out["timestamp"] == 1_700_000_000
    # description got redacted
    assert "quentin@adspower.com" not in out["description"]
    # AND hash of raw description is present
    assert out["description_hash"].startswith("sha256:")


def test_redact_evidence_hash_verifiable():
    """Third party with the raw description can verify the exposed hash."""
    raw_desc = "screenshot showed 401 error at 12:03 UTC"
    ev = {
        "escrow_id": "e1",
        "claimant": "c1",
        "evidence_type": "text",
        "content_hash": "0" * 64,
        "description": raw_desc,
        "timestamp": 1_700_000_000,
    }
    out = redact_evidence(ev)
    # Reproduce the hash
    expected = f"sha256:{hashlib.sha256(raw_desc.encode()).hexdigest()[:12]}"
    assert out["description_hash"] == expected


def test_redact_evidence_pydantic_model():
    from server.ai_arbitration import DisputeEvidence

    ev = DisputeEvidence(
        escrow_id="e1",
        claimant="c1",
        evidence_type="text",
        content_hash="0" * 64,
        description="sent invoice to accounting@corp.example on 2026-07-15",
        timestamp=1_700_000_000,
    )
    out = redact_evidence(ev)
    assert "accounting@corp.example" not in out["description"]
    assert out["description_hash"].startswith("sha256:")
    assert out["claimant"] == "c1"


def test_redact_evidence_rejects_bad_types():
    with pytest.raises(TypeError):
        redact_evidence("not an object")


# ---------------------------------------------------------------------------
# redact_prompt_for_log
# ---------------------------------------------------------------------------


def test_redact_prompt_for_log_metadata_only():
    prompt = (
        "Dispute ID: abc\nSENDER evidence: [1] type=text claimant=01a1b2c3... "
        "description=raw text with secrets sk-live-abc123456789def"
    )
    out = redact_prompt_for_log(prompt)
    assert "sk-live-abc123456789def" not in out
    assert "raw text with secrets" not in out
    assert out.startswith("prompt.sha256=")
    assert f"len={len(prompt)}" in out


def test_redact_prompt_for_log_short_output():
    """Prompt-log line should be well under 200 chars regardless of prompt size."""
    huge = "x" * 10_000
    out = redact_prompt_for_log(huge)
    assert len(out) < 200


# ---------------------------------------------------------------------------
# Integration: grep-style check that a redacted trace-like blob contains no
# raw secrets or emails
# ---------------------------------------------------------------------------


def test_grep_no_raw_secrets_in_redacted_output():
    """Compose a hostile evidence set and confirm the redacted blob doesn't
    contain any of the raw sensitive tokens."""
    raw_secrets = [
        "attacker@evil.example.com",
        "sk-live-ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NSJ9.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c",
        "+1 (555) 987-6543",
    ]
    hostile_description = (
        "please contact attacker@evil.example.com "
        "using key sk-live-ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 or "
        "JWT eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NSJ9.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c "
        "call +1 (555) 987-6543 anytime"
    )
    ev = {
        "escrow_id": "e1",
        "claimant": "c1",
        "evidence_type": "text",
        "content_hash": "0" * 64,
        "description": hostile_description,
        "timestamp": 1_700_000_000,
    }
    out = redact_evidence(ev)
    blob = repr(out)
    for raw in raw_secrets:
        assert raw not in blob, f"raw secret leaked: {raw!r}"
    # And redaction markers are present
    assert "<email:sha256:" in blob
    assert "<secret:sha256:" in blob
    # Digit-heavy tokens got redacted as phone or credit-card (both are secret-like)
    assert re.search(r"<(phone|cc):sha256:", blob) is not None


# ---------------------------------------------------------------------------
# Regression tests: preimage-attack surface & Casper-specific edge cases
# ---------------------------------------------------------------------------


def test_pem_private_key_body_redacted():
    """An -----BEGIN PRIVATE KEY----- block must not leak its body verbatim."""
    pem = (
        "-----BEGIN OPENSSH PRIVATE KEY-----\n"
        "MIIEpAIBAAKCAQEA1234567890abcdefABCDEF1234567890abcdefABCDEF\n"
        "QICQIBAAKCAQEAaBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789\n"
        "-----END OPENSSH PRIVATE KEY-----"
    )
    out = redact_text(pem, max_len=1000)
    assert "MIIEpAIBAAKCAQEA" not in out
    assert "BEGIN OPENSSH PRIVATE KEY" not in out
    assert "<secret:sha256:" in out


def test_long_base64_blob_redacted():
    """A 40+ char mixed-case base64 token (e.g. session cookie) is a secret."""
    body = "aGVsbG9Xb3JsZFRoaXNJc0FTZXNzaW9uS2V5MTIzNDU2Nzg5AbCdEf"
    text = f"cookie: session={body}"
    out = redact_text(text)
    assert body not in out
    assert "<secret:sha256:" in out


def test_casper_account_hex_preserved():
    """Casper account keys (65-char hex with 01/02 prefix) are public refs —
    they must NOT be redacted, otherwise the audit chain breaks."""
    pk = "020273e0a6f9b7f27b30f89f6c7b71c8fe6f7f52c1d78e6c8b3f6a9e2d4b0c1e2f3a"
    text = f"claimant account: {pk}"
    out = redact_text(text)
    assert pk in out


def test_escrow_and_dispute_ids_preserved():
    """Escrow/dispute IDs are opaque hex refs, must survive redaction."""
    ids = [
        "escrow_deadbeefcafebabe",
        "dispute_7f3d8c9e1a2b",
        "block 12345678901",  # bare digit run — must not be treated as phone
    ]
    for raw in ids:
        assert redact_text(raw) == raw, f"public id got redacted: {raw!r}"


def test_redaction_is_idempotent_on_all_patterns():
    """Double-application must be a fixed-point — no drift, no re-nesting."""
    cases = [
        "call +1 (555) 987-6543 anytime",
        "contact +7 495 123 45 67 for info",
        "reach me at a@b.com or bearer=abcdefghijklmnop1234",
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
        "eyJzdWIiOiIxMjM0NTY3ODkwIn0."
        "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c",
        "session=aGVsbG9Xb3JsZFRoaXNJc0FTZXNzaW9uS2V5MTIzNDU2Nzg5AbC",
        "sk_test_ABCDEFGHIJ1234567890abcdef",
    ]
    for raw in cases:
        r1 = redact_text(raw, max_len=500)
        r2 = redact_text(r1, max_len=500)
        r3 = redact_text(r2, max_len=500)
        assert r1 == r2 == r3, f"non-idempotent for {raw!r}: {r1!r} != {r2!r}"
        # No nested tokens — a <secret:...> must not contain <phone:...> inside
        assert "<phone:sha256:" not in r1.replace("<phone:sha256:", "", 1) or r1.count("<phone:") == 1


def test_redact_text_preserves_analysis_hash_context():
    """Arbitration reasoning: only PII redacted, verdict words survive."""
    reasoning = (
        "The sender's evidence at a@b.com shows delivery on 2026-07-15. "
        "Refund is not justified given proof-of-work hash matches."
    )
    out = redact_text(reasoning)
    assert "a@b.com" not in out
    # Verdict-carrying words remain
    for word in ("Refund", "justified", "proof-of-work", "hash"):
        assert word in out
