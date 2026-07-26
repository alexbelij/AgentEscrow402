"""
Arbiter commit-reveal scheme (A) — MEV-resistance for verdict votes.

Naive on-chain arbiter voting leaks the verdict the instant the first
signature lands. A crafty counterparty (or the arbiter themselves) can
front-run the reveal to profit from advance knowledge. This module
adds a two-phase commit-reveal so *nobody* — including other arbiters
— sees the verdict before every commit has landed.

Phase 1 — COMMIT
    Each arbiter posts:
        commit = keccak256(verdict || salt || arbiter_pubkey)
    The chain records `commits[arbiter] = commit_hash`.

Phase 2 — REVEAL (after commit-quorum + a small delay)
    Each arbiter posts `(verdict, salt)`. The chain checks
    `commits[arbiter] == keccak256(verdict||salt||arbiter_pubkey)` and
    only then counts the vote. A mismatch is a slashing offence
    (see server/slashing.py).

Determinism
-----------
`build_commit()` and `verify_reveal()` are pure functions of their
inputs. Every property tested for:
  - commit is unique per (verdict, salt, arbiter)
  - verify_reveal fires only when *all three* fields match
  - a tampered salt / verdict / arbiter is always rejected
  - short-salt-brute-force resistance (salt must be ≥ 128 bits)

Related:
- server/arbiter_crypto.py  (signature checking; used AFTER reveal)
- server/slashing.py        (equivocation + reveal-mismatch penalties)
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Literal

Verdict = Literal["claimant", "respondent", "abstain"]

# Salts must have at least this many bytes of entropy to defeat
# brute-force pre-image search on the commit hash.
_MIN_SALT_BYTES = 16

# Domain-separation tag so this commit hash can never collide with
# another AE402 commit domain by accident.
_DOMAIN = b"AE402_ARBITER_COMMIT_V1"


class CommitRevealError(ValueError):
    pass


@dataclass(frozen=True)
class Commitment:
    arbiter_pubkey_hex: str
    commit_hash_hex: str


@dataclass(frozen=True)
class Reveal:
    arbiter_pubkey_hex: str
    verdict: Verdict
    salt_hex: str


def _canonical_verdict(v: str) -> Verdict:
    v_lc = v.strip().lower()
    if v_lc not in ("claimant", "respondent", "abstain"):
        raise CommitRevealError(f"invalid verdict {v!r}")
    return v_lc  # type: ignore[return-value]


def _hex_to_bytes(h: str, *, name: str) -> bytes:
    h_clean = h.removeprefix("0x")
    try:
        return bytes.fromhex(h_clean)
    except ValueError as exc:
        raise CommitRevealError(f"invalid {name} hex: {exc}") from exc


def build_commit(
    *, verdict: str, salt_hex: str, arbiter_pubkey_hex: str
) -> Commitment:
    """Compute the commit hash for one arbiter's vote.

    Pure: same input → same commit hash, byte-for-byte.
    """
    verdict_c = _canonical_verdict(verdict)
    salt = _hex_to_bytes(salt_hex, name="salt")
    if len(salt) < _MIN_SALT_BYTES:
        raise CommitRevealError(
            f"salt must be at least {_MIN_SALT_BYTES} bytes; got {len(salt)}"
        )
    pk = _hex_to_bytes(arbiter_pubkey_hex, name="arbiter_pubkey")
    if not pk:
        raise CommitRevealError("arbiter_pubkey_hex must not be empty")

    hasher = hashlib.sha256()
    hasher.update(_DOMAIN)
    hasher.update(verdict_c.encode("ascii"))
    hasher.update(b"\x00")
    hasher.update(salt)
    hasher.update(b"\x00")
    hasher.update(pk)

    return Commitment(
        arbiter_pubkey_hex=arbiter_pubkey_hex,
        commit_hash_hex=hasher.hexdigest(),
    )


def verify_reveal(*, reveal: Reveal, expected_commit_hex: str) -> bool:
    """Check that a reveal matches its previously-posted commit.

    Returns True on match; False on any mismatch (invalid verdict,
    tampered salt, wrong arbiter, whatever). Never raises on
    mismatches — the caller decides how to slash.
    """
    try:
        recomputed = build_commit(
            verdict=reveal.verdict,
            salt_hex=reveal.salt_hex,
            arbiter_pubkey_hex=reveal.arbiter_pubkey_hex,
        )
    except CommitRevealError:
        return False
    return _constant_time_eq(recomputed.commit_hash_hex, expected_commit_hex)


def _constant_time_eq(a: str, b: str) -> bool:
    if len(a) != len(b):
        return False
    result = 0
    for x, y in zip(a.encode(), b.encode()):
        result |= x ^ y
    return result == 0
