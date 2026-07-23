"""Append-only, tamper-evident audit log with signed Merkle roots (AE-Audit).

Design goals:

  - **Append-only hash chain.** Every entry commits to the hash of the
    previous entry (`prev_hash`), so re-ordering, deleting, or inserting a
    past entry breaks the chain deterministically — the classic "signed
    audit log" construction used by e.g. Certificate Transparency logs and
    tamper-evident SIEM pipelines.
  - **Periodic signed roots.** Rather than sign every single entry (cheap
    to skip one signature), the log computes a Merkle root over a
    contiguous *checkpoint* of entries and signs that root once with the
    operator's Ed25519 key. Anyone holding the signed root + the entries
    can independently recompute the root and verify the signature — this
    gives you the same tamper-evidence as a per-entry signature at a
    fraction of the crypto operations, and is the same Ed25519 signing
    primitive already used for arbiter votes (see `server/arbiter_crypto.py`
    / `sdk/arbiter_signing.py`).
  - **Reuses the existing Merkle math.** Checkpoint roots are computed with
    the exact same leaf/parent hashing rules as
    `server/merkle_provenance.py` (sha256 leaves, sha256(left||right)
    parents, odd-node duplication, defined empty-batch root) so there is
    only one Merkle implementation to reason about in this codebase.

This module is intentionally dependency-light: stdlib hashlib for hashing,
`cryptography`'s Ed25519 primitives for signing (already a hard dependency
of the backend, see `server/arbiter_crypto.py`). No I/O, no wall-clock
inside the hashing/signing functions themselves -- callers supply the
timestamp, which keeps this deterministic and easy to test.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

ED25519_TAG_HEX = "01"

# Genesis previous-hash: the chain's first entry commits to this constant
# rather than to nothing, so "no prior entry" is itself a fixed, checkable
# value (mirrors how `merkle_provenance` defines a root for the empty
# batch instead of leaving it undefined).
GENESIS_HASH = hashlib.sha256(b"ae402-audit-log-genesis").hexdigest()


def _sha256_hex(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _canonical_payload_hash(payload: dict[str, Any]) -> str:
    """Deterministic hash of an arbitrary JSON-serializable payload.

    `sort_keys=True` + no extra whitespace guarantees the same payload
    hashes the same way regardless of dict insertion order, so callers on
    different code paths that build "the same" event still commit to the
    same hash.
    """
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return _sha256_hex(canonical)


@dataclass(frozen=True)
class AuditLogEntry:
    """One append-only audit log record.

    `entry_hash` binds this entry's own content AND the previous entry's
    hash together -- that's the hash-chain link. Two logs with the same
    entries in the same order always produce the same `entry_hash` at
    every position; changing, reordering, or deleting any past entry
    changes every `entry_hash` after it.
    """

    seq: int
    event_type: str
    payload_hash: str
    timestamp: int
    prev_hash: str
    entry_hash: str = field(compare=False, default="")

    def __post_init__(self) -> None:
        computed = _entry_hash(self.seq, self.event_type, self.payload_hash, self.timestamp, self.prev_hash)
        if not self.entry_hash:
            object.__setattr__(self, "entry_hash", computed)
        elif self.entry_hash != computed:
            raise ValueError(f"AuditLogEntry seq={self.seq}: entry_hash does not match its own fields")


def _entry_hash(seq: int, event_type: str, payload_hash: str, timestamp: int, prev_hash: str) -> str:
    preimage = f"{seq}:{event_type}:{payload_hash}:{timestamp}:{prev_hash}"
    return _sha256_hex(preimage)


# ---------------------------------------------------------------------------
# Merkle root over a checkpoint of entries (same math as merkle_provenance)
# ---------------------------------------------------------------------------


def _build_levels(leaf_hashes: list[str]) -> list[list[str]]:
    if not leaf_hashes:
        return [[_sha256_hex("empty")]]
    levels: list[list[str]] = [list(leaf_hashes)]
    current = list(leaf_hashes)
    while len(current) > 1:
        nxt: list[str] = []
        for i in range(0, len(current), 2):
            left = current[i]
            right = current[i + 1] if i + 1 < len(current) else current[i]
            nxt.append(_sha256_hex(left + right))
        levels.append(nxt)
        current = nxt
    return levels


def compute_checkpoint_root(entries: list[AuditLogEntry]) -> str:
    """Merkle root over a checkpoint's entry hashes.

    An empty checkpoint has the well-defined root `sha256("empty")`,
    matching `merkle_provenance.compute_merkle_root([])`.
    """
    return _build_levels([e.entry_hash for e in entries])[-1][0]


def verify_chain(entries: list[AuditLogEntry], genesis_hash: str = GENESIS_HASH) -> bool:
    """True iff every entry's prev_hash correctly links to the one before
    it (or to `genesis_hash` for the first entry) and every entry_hash is
    internally consistent with its own fields.

    A single edited, reordered, deleted, or forged entry anywhere in the
    list makes this return False.
    """
    expected_prev = genesis_hash
    for entry in entries:
        if entry.prev_hash != expected_prev:
            return False
        if entry.entry_hash != _entry_hash(
            entry.seq, entry.event_type, entry.payload_hash, entry.timestamp, entry.prev_hash
        ):
            return False
        expected_prev = entry.entry_hash
    return True


# ---------------------------------------------------------------------------
# Signing / verifying a checkpoint root
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SignedCheckpoint:
    """A checkpoint root plus the operator's signature over it.

    `start_seq`/`end_seq` are inclusive and record which entries this root
    covers, so a verifier knows exactly which slice of the chain to
    recompute the root from.
    """

    root: str
    start_seq: int
    end_seq: int
    signature_hex: str
    pubkey_hex: str


def _checkpoint_message(root: str, start_seq: int, end_seq: int) -> bytes:
    """Canonical message signed over a checkpoint -- binds the root to the
    exact seq range it covers, so a signature can't be replayed to claim
    coverage of a different (larger or smaller) slice of the log."""
    return f"audit-checkpoint:{start_seq}:{end_seq}:{root}".encode("utf-8")


def sign_checkpoint(private_key: Ed25519PrivateKey, entries: list[AuditLogEntry]) -> SignedCheckpoint:
    if not entries:
        raise ValueError("cannot sign a checkpoint with no entries")
    root = compute_checkpoint_root(entries)
    start_seq, end_seq = entries[0].seq, entries[-1].seq
    signature = private_key.sign(_checkpoint_message(root, start_seq, end_seq))
    pubkey_raw = private_key.public_key().public_bytes_raw()
    return SignedCheckpoint(
        root=root,
        start_seq=start_seq,
        end_seq=end_seq,
        signature_hex=ED25519_TAG_HEX + signature.hex(),
        pubkey_hex=ED25519_TAG_HEX + pubkey_raw.hex(),
    )


def verify_checkpoint_signature(checkpoint: SignedCheckpoint) -> bool:
    """True iff `signature_hex` is a valid Ed25519 signature by
    `pubkey_hex` over this exact (root, start_seq, end_seq)."""
    if not checkpoint.pubkey_hex.startswith(ED25519_TAG_HEX) or not checkpoint.signature_hex.startswith(
        ED25519_TAG_HEX
    ):
        return False
    try:
        pubkey = Ed25519PublicKey.from_public_bytes(bytes.fromhex(checkpoint.pubkey_hex[len(ED25519_TAG_HEX):]))
        signature = bytes.fromhex(checkpoint.signature_hex[len(ED25519_TAG_HEX):])
    except ValueError:
        return False
    message = _checkpoint_message(checkpoint.root, checkpoint.start_seq, checkpoint.end_seq)
    try:
        pubkey.verify(signature, message)
        return True
    except InvalidSignature:
        return False


def verify_checkpoint_against_entries(checkpoint: SignedCheckpoint, entries: list[AuditLogEntry]) -> bool:
    """Full check: the checkpoint's signature is valid AND recomputing the
    Merkle root from the given entries (which must be exactly the
    [start_seq, end_seq] slice) reproduces the signed root."""
    if not entries:
        return False
    if entries[0].seq != checkpoint.start_seq or entries[-1].seq != checkpoint.end_seq:
        return False
    if compute_checkpoint_root(entries) != checkpoint.root:
        return False
    return verify_checkpoint_signature(checkpoint)


# ---------------------------------------------------------------------------
# In-process append-only log
# ---------------------------------------------------------------------------


class AuditLog:
    """Minimal in-process append-only audit log.

    Not a persistence layer on its own -- entries live in memory for the
    lifetime of the process, exactly like the rest of this backend's
    sandbox-mode state (see `server/db.py` for the optional Neon-backed
    persistence path other modules use; wiring this log to durable storage
    is a follow-up, not blocking the chain/signing primitives here).
    """

    def __init__(self, genesis_hash: str = GENESIS_HASH) -> None:
        self._genesis_hash = genesis_hash
        self._entries: list[AuditLogEntry] = []

    def append(self, event_type: str, payload: dict[str, Any], timestamp: Optional[int] = None) -> AuditLogEntry:
        seq = len(self._entries)
        prev_hash = self._entries[-1].entry_hash if self._entries else self._genesis_hash
        ts = timestamp if timestamp is not None else int(time.time())
        payload_hash = _canonical_payload_hash(payload)
        entry = AuditLogEntry(
            seq=seq,
            event_type=event_type,
            payload_hash=payload_hash,
            timestamp=ts,
            prev_hash=prev_hash,
        )
        self._entries.append(entry)
        return entry

    @property
    def entries(self) -> list[AuditLogEntry]:
        return list(self._entries)

    def verify(self) -> bool:
        return verify_chain(self._entries, genesis_hash=self._genesis_hash)

    def checkpoint(self, private_key: Ed25519PrivateKey, since_seq: int = 0) -> SignedCheckpoint:
        """Sign a checkpoint covering entries from `since_seq` to the
        current tail (inclusive of both ends)."""
        slice_ = [e for e in self._entries if e.seq >= since_seq]
        return sign_checkpoint(private_key, slice_)


__all__ = [
    "GENESIS_HASH",
    "ED25519_TAG_HEX",
    "AuditLogEntry",
    "AuditLog",
    "SignedCheckpoint",
    "compute_checkpoint_root",
    "verify_chain",
    "sign_checkpoint",
    "verify_checkpoint_signature",
    "verify_checkpoint_against_entries",
]
