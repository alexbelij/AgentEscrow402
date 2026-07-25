"""Redacted audit trace for arbitration and escrow lifecycle events (AE-A2).

The audit trace is a *deterministic, non-reversible* event log that a judge
(or a downstream verifier) can inspect to see what the system did — WITHOUT
leaking raw prompts, secrets, or PII. Each event stores hashes, decisions,
and structural metadata only.

Design constraints
------------------

- **No raw prompts.** Prompt text is never persisted. If a caller passes a
  prompt, we hash it (sha256) and store only the hex digest.
- **No secrets.** Provider keys, wallet keys, session tokens — the module
  refuses to accept anything that matches a well-known secret shape
  (starts with `sk-`, `ghp_`, contains `PRIVATE KEY`, etc.).
- **No PII.** Fields the module *does* persist are enumerated below;
  everything else is dropped. Callers that want to associate an event
  with an entity pass a *hash* of the entity id, not the id itself.
- **Deterministic.** Given the same event payload and the same wall-clock
  (which we make explicit — see `timestamp` param), two runs produce the
  same event id and the same serialisation. This is what makes it
  reproducible from a fixture.

Event shape (persisted, JSON-serialisable)
------------------------------------------

    {
      "event_id":      "<sha256 of canonical pre-image>",
      "event_type":    "arbitration_start" | "evidence_processed" | ...,
      "timestamp":     "<ISO-8601 UTC>",
      "actor_hash":    "<sha256 of actor id>" | null,
      "subject_hash":  "<sha256 of subject id>" | null,     # dispute_id, escrow_id, ...
      "decision":      "favor_sender" | ... | null,
      "provider":      "groq" | "nvidia" | "openrouter" | "heuristic" | null,
      "confidence":    <float 0..1> | null,
      "evidence_root": "<sha256 hex>" | null,
      "prompt_hash":   "<sha256 hex>" | null,
      "attributes":    { <flat map of allow-listed keys → scalar> }
    }

The `event_id` is `sha256(event_type|timestamp|actor_hash|subject_hash|
decision|provider|confidence|evidence_root|prompt_hash|<sorted attributes>)`
— a small tamper-evident anchor. Chaining events into a Merkle-linked
audit *lineage* is the job of `merkle_provenance.compute_merkle_root`
over the sequence of event_ids; this module is intentionally the leaf
producer and not the tree builder.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Iterable, Optional


# ---------------------------------------------------------------------------
# Redaction / PII guard
# ---------------------------------------------------------------------------

# Anything that matches one of these patterns is *never* stored — even
# inside `attributes`. The value is replaced by `[REDACTED:<shape>]` so
# a judge can see something *was* provided and where, without the
# secret itself leaking into the log.
_SECRET_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^sk-[A-Za-z0-9_\-]{20,}$"), "openai_key"),
    (re.compile(r"^gsk_[A-Za-z0-9_\-]{20,}$"), "groq_key"),
    (re.compile(r"^nvapi-[A-Za-z0-9_\-]{20,}$"), "nvidia_key"),
    (re.compile(r"^sk-or-[A-Za-z0-9_\-]{20,}$"), "openrouter_key"),
    (re.compile(r"^ghp_[A-Za-z0-9]{20,}$"), "github_token"),
    (re.compile(r"^github_pat_[A-Za-z0-9_]{20,}$"), "github_pat"),
    (re.compile(r"^AKIA[0-9A-Z]{16}$"), "aws_key"),
    (re.compile(r"-----BEGIN [A-Z ]+PRIVATE KEY-----"), "private_key_pem"),
    # Long hex-only strings look like private keys / wallet secrets. We
    # accept SHA-256 digests (exactly 64 hex chars) as a common false
    # positive — those get through the pattern gate because they are
    # explicit non-secret hashes callers pass in.
    (re.compile(r"^[0-9a-fA-F]{128,}$"), "hex_secret"),
]

# Attribute keys that will NEVER be persisted verbatim, regardless of
# value. Their values are dropped, replaced by a sentinel.
_BLOCKED_ATTR_KEYS: frozenset[str] = frozenset(
    {
        "prompt",
        "prompt_text",
        "raw_prompt",
        "system_prompt",
        "user_prompt",
        "api_key",
        "secret",
        "password",
        "token",
        "authorization",
        "email",
        "phone",
        "ssn",
        "ip",
        "wallet_key",
        "private_key",
    }
)

# Attribute keys that ARE allowed through — enumerated so a typo can't
# silently exfiltrate something new.
_ALLOWED_ATTR_KEYS: frozenset[str] = frozenset(
    {
        "escrow_amount_cspr",
        "escrow_amount_motes",
        "sender_evidence_count",
        "receiver_evidence_count",
        "escalated_to_panel",
        "escalation_reason",
        "chain_index",
        "parent_event_id",
        "parent_evidence_root",
        "risk_factor_count",
        "handler_version",
        "policy_version",
        "hitl_sink",
        "prompt_length",  # length, not content
        "fixture_id",
        "scenario",
    }
)


_HASH_MARKER = "[REDACTED:hash]"


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _redact_scalar(value: Any) -> Any:
    """Return the value unchanged if safe; otherwise a redaction marker.

    We only allow: bool, int, float, None, and short (≤256 char) strings
    that don't match a secret pattern. Anything else is dropped.
    """
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        if len(value) > 256:
            # Long strings are suspicious — could be a prompt, a payload,
            # or a serialised secret. Store its shape only.
            return f"[REDACTED:string:len={len(value)}]"
        for pattern, label in _SECRET_PATTERNS:
            if pattern.match(value):
                return f"[REDACTED:{label}]"
        return value
    return f"[REDACTED:type={type(value).__name__}]"


def _sanitize_attributes(attributes: Optional[dict[str, Any]]) -> dict[str, Any]:
    if not attributes:
        return {}
    clean: dict[str, Any] = {}
    for key, value in attributes.items():
        if not isinstance(key, str):
            continue
        if key in _BLOCKED_ATTR_KEYS:
            clean[key] = _HASH_MARKER
            continue
        if key not in _ALLOWED_ATTR_KEYS:
            # Unknown attribute — refuse to persist. Judge should not
            # see arbitrary key names either, since a key name itself
            # can leak intent.
            continue
        clean[key] = _redact_scalar(value)
    return clean


# ---------------------------------------------------------------------------
# Event shape
# ---------------------------------------------------------------------------


ALLOWED_EVENT_TYPES: frozenset[str] = frozenset(
    {
        "arbitration_start",
        "evidence_processed",
        "provider_selected",
        "decision_made",
        "escalation_triggered",
        "hitl_dispatched",
        "receipt_committed",
    }
)


ALLOWED_DECISIONS: frozenset[str] = frozenset(
    {
        "favor_sender",
        "favor_receiver",
        "split",
        "escalate",
        "abstain",
    }
)


ALLOWED_PROVIDERS: frozenset[str] = frozenset(
    {
        "groq",
        "nvidia",
        "openrouter",
        "gemini",
        "heuristic",
    }
)


@dataclass(frozen=True)
class AuditEvent:
    """One redacted audit event.

    Callers should never construct this directly — use `emit_event` so
    the redaction pipeline runs. The dataclass is exposed for typing and
    for tests that want to introspect a persisted event.
    """

    event_id: str
    event_type: str
    timestamp: str
    actor_hash: Optional[str]
    subject_hash: Optional[str]
    decision: Optional[str]
    provider: Optional[str]
    confidence: Optional[float]
    evidence_root: Optional[str]
    prompt_hash: Optional[str]
    attributes: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _hash_id(raw: Optional[str]) -> Optional[str]:
    if raw is None:
        return None
    if not isinstance(raw, str) or not raw:
        return None
    return _sha256_hex(raw)


def _canonical_preimage(
    *,
    event_type: str,
    timestamp: str,
    actor_hash: Optional[str],
    subject_hash: Optional[str],
    decision: Optional[str],
    provider: Optional[str],
    confidence: Optional[float],
    evidence_root: Optional[str],
    prompt_hash: Optional[str],
    attributes: dict[str, Any],
) -> str:
    """Deterministic canonicalisation for event_id computation.

    Uses a sorted JSON-like layout with `None` normalised to empty
    string so the pre-image is stable across Python versions and
    unrelated to insertion order.
    """
    parts: list[str] = [
        event_type,
        timestamp,
        actor_hash or "",
        subject_hash or "",
        decision or "",
        provider or "",
        f"{confidence:.6f}" if confidence is not None else "",
        evidence_root or "",
        prompt_hash or "",
    ]
    # Sorted, JSON-serialised, compact — matches what a JS port would do.
    parts.append(json.dumps(attributes, sort_keys=True, separators=(",", ":")))
    return "|".join(parts)


def emit_event(
    *,
    event_type: str,
    timestamp: Optional[datetime] = None,
    actor_id: Optional[str] = None,
    subject_id: Optional[str] = None,
    decision: Optional[str] = None,
    provider: Optional[str] = None,
    confidence: Optional[float] = None,
    evidence_root: Optional[str] = None,
    prompt: Optional[str] = None,
    attributes: Optional[dict[str, Any]] = None,
) -> AuditEvent:
    """Build a redacted event.

    Guarantees
    ~~~~~~~~~~
    - `actor_id` / `subject_id` are hashed, never persisted verbatim.
    - `prompt` is hashed to `prompt_hash`, never persisted verbatim.
    - `attributes` are filtered against the allow-list; blocked keys
      collapse to a sentinel; unknown keys are dropped.
    - `event_id` is a sha256 over a canonical pre-image, so the same
      inputs produce the same id in any language.
    """
    if event_type not in ALLOWED_EVENT_TYPES:
        raise ValueError(
            f"unknown event_type: {event_type!r} (allowed: {sorted(ALLOWED_EVENT_TYPES)})"
        )
    if decision is not None and decision not in ALLOWED_DECISIONS:
        raise ValueError(f"unknown decision: {decision!r}")
    if provider is not None and provider not in ALLOWED_PROVIDERS:
        raise ValueError(f"unknown provider: {provider!r}")
    if confidence is not None and not (0.0 <= confidence <= 1.0):
        raise ValueError(f"confidence out of range: {confidence!r}")

    ts = timestamp if timestamp is not None else datetime.now(timezone.utc)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    ts_iso = ts.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    prompt_hash = _sha256_hex(prompt) if prompt else None

    clean_attrs = _sanitize_attributes(attributes)

    actor_hash = _hash_id(actor_id)
    subject_hash = _hash_id(subject_id)

    preimage = _canonical_preimage(
        event_type=event_type,
        timestamp=ts_iso,
        actor_hash=actor_hash,
        subject_hash=subject_hash,
        decision=decision,
        provider=provider,
        confidence=confidence,
        evidence_root=evidence_root,
        prompt_hash=prompt_hash,
        attributes=clean_attrs,
    )
    event_id = _sha256_hex(preimage)

    return AuditEvent(
        event_id=event_id,
        event_type=event_type,
        timestamp=ts_iso,
        actor_hash=actor_hash,
        subject_hash=subject_hash,
        decision=decision,
        provider=provider,
        confidence=confidence,
        evidence_root=evidence_root,
        prompt_hash=prompt_hash,
        attributes=clean_attrs,
    )


# ---------------------------------------------------------------------------
# Merkle lineage — chains audit events across arbitration steps
# ---------------------------------------------------------------------------


def compute_chain_root(event_ids: Iterable[str]) -> str:
    """Deterministic chain root over an ordered sequence of event_ids.

    Chain math:
      chain_0     = sha256("chain:genesis")
      chain_{i+1} = sha256(chain_i || event_id_i)

    This is *not* a Merkle tree — it's a linear hash chain, because
    audit events are inherently ordered (start → decision → escalate →
    ...). If a downstream wants a tree, it can feed `event_ids` into
    `merkle_provenance.compute_merkle_root` instead.

    Empty chain has a well-defined root: sha256("chain:genesis").
    """
    running = _sha256_hex("chain:genesis")
    for eid in event_ids:
        if not isinstance(eid, str) or not eid:
            continue
        running = _sha256_hex(running + eid)
    return running


@dataclass(frozen=True)
class LineageLink:
    """One step in an evidence lineage chain — links an arbitration
    (or appeal) to its parent evidence set.

    Used to prove that a follow-up arbitration was *derived* from a
    specific prior evidence root, and that the chain of derivation is
    tamper-evident. Two use cases:

    1. **Appeal**: appeal(v2) references the original arbitration's
       evidence_root as `parent_evidence_root`.
    2. **Multi-step batch**: intermediate arbitrations feed into a
       final one; each step declares its predecessor.

    Lineage math:
      link_hash = sha256("<parent_evidence_root>|<current_evidence_root>|<step_index>")
    """

    parent_evidence_root: str
    current_evidence_root: str
    step_index: int

    @property
    def link_hash(self) -> str:
        preimage = f"{self.parent_evidence_root}|{self.current_evidence_root}|{self.step_index}"
        return _sha256_hex(preimage)


def compute_lineage_root(links: Iterable[LineageLink]) -> str:
    """Fold lineage links into a single tamper-evident root.

    lineage_0     = sha256("lineage:genesis")
    lineage_{i+1} = sha256(lineage_i || link_hash_i)
    """
    running = _sha256_hex("lineage:genesis")
    for link in links:
        running = _sha256_hex(running + link.link_hash)
    return running


__all__ = [
    "AuditEvent",
    "LineageLink",
    "ALLOWED_EVENT_TYPES",
    "ALLOWED_DECISIONS",
    "ALLOWED_PROVIDERS",
    "emit_event",
    "compute_chain_root",
    "compute_lineage_root",
]
