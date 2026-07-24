"""Redaction utilities for evidence, prompts, and public trace endpoints.

AE402 hardening: evidence descriptions, LLM prompts, and reasoning strings may
contain PII (emails, phone numbers, credit-card-like patterns) or accidental
secrets (API keys, JWTs, bearer tokens). Anything surfaced via public trace,
history, or receipt endpoints — and anything written to server logs — MUST
pass through this module first.

Design principles:
- Deterministic: same input → same output, so audit hashes remain stable.
- Hash-preserving: raw content is replaced with `sha256:xxxxxxxx…` (12-hex
  prefix) so a third party with the raw content can still verify the hash.
- Conservative: only well-known patterns are matched; when in doubt we redact,
  not leak.
- No-op on already-redacted text: idempotent so double-application is safe.

See docs/REDACTION.md for the full contract and threat model.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

# ---------------------------------------------------------------------------
# Regex patterns — kept conservative; the goal is fail-safe, not zero-FP
# ---------------------------------------------------------------------------

# Email: RFC 5321 loose match. `local@domain.tld` with domain length ≥ 2 chars.
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")

# API keys / bearer tokens / JWT-like patterns.
# - "Bearer xxx" style headers
# - "sk-..." / "pk-..." / "AKIA..." — OpenAI/Anthropic/AWS common prefixes
# - Long alnum sequences (>= 32 chars) that look like keys
_BEARER_RE = re.compile(r"(?i)\b(bearer|api[_-]?key|token)\s*[:=]\s*[A-Za-z0-9._\-]{16,}")
_KEY_PREFIX_RE = re.compile(r"\b(sk|pk|rk|AKIA|xoxb|xoxp|ghp|gho|ghu|ghs|glpat)[_-][A-Za-z0-9_-]{16,}\b")
# JWT: three base64url segments separated by dots
_JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")

# PEM / OpenSSH private key markers — hard leak indicators.
_PEM_MARKER_RE = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY[A-Z0-9 ]*-----" r"[\s\S]+?" r"-----END [A-Z0-9 ]*PRIVATE KEY[A-Z0-9 ]*-----"
)

# Long unbroken base64/base64url chunk (40+ chars). Matches SSH key bodies,
# large tokens, and mnemonic-free key blobs that escape the specific patterns
# above. Requires a mix of case OR presence of `+/=` to avoid gobbling plain
# hex hashes (which we treat as public refs by design).
_LONG_BASE64_RE = re.compile(r"\b(?=[A-Za-z0-9+/=]{40,})(?=.*[A-Z])(?=.*[a-z])[A-Za-z0-9+/=]{40,}\b")

# Casper hex keys: 32-byte hex (64 chars) prefixed with 01/02 (ed25519/secp)
# We do NOT redact these globally because the whole app talks about escrow
# hashes and account keys; instead, callers use `hash_content` explicitly.

# Phone numbers: 10+ digits, allowing spaces / dashes / parens / leading +.
# We require the *terminal* char to be a digit so we don't gobble adjacent
# punctuation, but skip \b anchors — Python's \b treats `+` as a word break,
# which prevents matching international-format numbers like `+1 (555)…`.
# Additionally require at least one separator ( / - / . / space / paren ) so
# a bare digit run (which is more likely an id/hash fragment) does not match.
_PHONE_RE = re.compile(r"\+?\d[\d]{0,3}[\s.\-()][\d\s.\-()]{6,}\d")

# Credit-card-like: 13-19 digits (allow spaces/dashes between groups)
_CC_RE = re.compile(r"\b(?:\d[ -]?){13,19}\b")

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def hash_content(content: str | bytes, *, prefix: str = "sha256", chars: int = 12) -> str:
    """Return a stable short hash reference for arbitrary content.

    The result is safe to log or expose publicly: it identifies the content
    for verification without leaking it.

    Example: `hash_content("hello")` → `"sha256:2cf24dba5fb0a30e"`.
    """
    if isinstance(content, str):
        content = content.encode("utf-8")
    digest = hashlib.sha256(content).hexdigest()
    if chars < 4 or chars > 64:
        raise ValueError("chars must be between 4 and 64")
    return f"{prefix}:{digest[:chars]}"


def redact_text(text: str, *, max_len: int | None = 300) -> str:
    """Redact PII/secrets from arbitrary text, safe for public exposure.

    Emails → `<email:sha256:xxxx>`; API keys / JWTs / bearer tokens →
    `<secret:sha256:xxxx>`; phone-like → `<phone:sha256:xxxx>`; credit-card-like
    → `<cc:sha256:xxxx>`. Anything not matched is left as-is.

    If `max_len` is set, output is truncated (with `…` marker) to that many
    characters after redaction.
    """
    if not text:
        return text

    def _sub(pattern: re.Pattern[str], label: str, s: str) -> str:
        return pattern.sub(lambda m: f"<{label}:{hash_content(m.group(0))}>", s)

    # Order matters: match specific patterns (bearer/jwt/key-prefix) BEFORE
    # the loose credit-card regex, which would otherwise gobble digit-heavy
    # portions of a JWT payload.
    # PEM/OpenSSH first — largest span, avoids re-matching pieces of the body.
    text = _sub(_PEM_MARKER_RE, "secret", text)
    text = _sub(_BEARER_RE, "secret", text)
    text = _sub(_JWT_RE, "secret", text)
    text = _sub(_KEY_PREFIX_RE, "secret", text)
    # Long base64 blobs after JWT (JWT is a stricter sub-pattern).
    text = _sub(_LONG_BASE64_RE, "secret", text)
    text = _sub(_EMAIL_RE, "email", text)
    text = _sub(_CC_RE, "cc", text)
    text = _sub(_PHONE_RE, "phone", text)

    if max_len is not None and len(text) > max_len:
        text = text[: max_len - 1] + "…"
    return text


def redact_evidence(evidence: Any) -> dict[str, Any]:
    """Redact a single DisputeEvidence-like object for public trace exposure.

    Accepts either a pydantic BaseModel with the DisputeEvidence fields, or a
    plain dict. Returns a dict with:

    - `escrow_id`, `claimant`: kept as-is (already public on-chain refs).
    - `evidence_type`, `timestamp`: kept as-is.
    - `content_hash`: kept as-is (it *is* the redacted reference).
    - `description`: replaced with `redact_text(description)` capped at 120.
    - `description_hash`: `sha256:xxxxxxxx…` of the RAW description so a
      third party with the original can verify.
    """
    if hasattr(evidence, "model_dump"):
        data = evidence.model_dump()
    elif hasattr(evidence, "dict"):
        data = evidence.dict()  # type: ignore[attr-defined]
    elif isinstance(evidence, dict):
        data = dict(evidence)
    else:
        raise TypeError(f"redact_evidence expected dict or BaseModel, got {type(evidence)!r}")

    raw_desc = data.get("description", "") or ""
    # Redaction expands most tokens (email/key → `<email:sha256:xxxx>`), so we
    # allow a slightly larger post-redaction budget (240) than the raw upstream
    # `description[:80]` cap seen at prompt-build time.
    data["description"] = redact_text(raw_desc, max_len=240)
    data["description_hash"] = hash_content(raw_desc)
    return data


def redact_prompt_for_log(prompt: str) -> str:
    """Redact an LLM arbitration prompt for logging.

    Prompts contain evidence descriptions (already truncated but raw). For
    server logs we replace the entire prompt body with metadata only:
    `prompt.sha256=xxxx… len=N`. Callers that want the raw prompt should
    read the request payload, not the log.
    """
    return f"prompt.sha256={hash_content(prompt).split(':', 1)[1]} len={len(prompt)}"


__all__ = [
    "hash_content",
    "redact_text",
    "redact_evidence",
    "redact_prompt_for_log",
]
