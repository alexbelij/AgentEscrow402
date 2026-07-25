"""Detached signature envelope with explicit domain separation.

Threat model
============

The bare-bones x402 payment header historically signs an ad-hoc
concatenation of fields.  That is enough to bind a signature to *the
specific fields it contains*, but it is not enough to prevent

  1. **Cross-purpose replay** — the same signature valid for
     `escrow.deposit` on chain A being replayed against
     `escrow.release` on chain B, because both payloads happen to
     serialize to the same bytes.
  2. **Version drift** — a signature produced under protocol v1 rules
     silently accepted under v2 semantics.
  3. **Chain confusion** — a testnet signature accepted on mainnet, or
     vice-versa.
  4. **In-memory nonce loss** — the OrderedDict store in
     ``server/middleware.py`` is bounded in size AND wiped on restart,
     so a replay window can be re-opened by bouncing the process.

This module provides the canonical primitives to fix all four:

* :class:`DomainSeparator` — the 4-tuple that MUST prefix any signing
  bytes.  Two envelopes that disagree on any field are cryptographically
  distinct.
* :class:`SignedEnvelope` — *detached* signature envelope: the signature
  is a sibling field of the payload, not embedded within it, so the
  payload can be inspected, hashed, or logged without touching the
  signature material.
* :func:`build_signing_bytes` — canonical serializer.  Ties the wire
  bytes to the domain separator, the signer pubkey, the algorithm, the
  nonce, and the timestamp.
* :func:`verify_envelope` — enforces algorithm/domain/nonce/timestamp
  checks *before* trying the crypto, so a mismatch fails fast with a
  clear diagnosis rather than a generic ``bad signature``.
* :class:`PersistentNonceStore` — SQLite-backed nonce store.  Survives
  process restarts, prunes by TTL, and never grows unboundedly.

Backward compatibility
======================

This module is *additive*.  Existing routes decorated with
``@require_payment`` continue to work unchanged.  New surfaces (e.g.
``@require_signed_envelope("escrow.deposit")``) opt into the stricter
contract.  A migration guide lives in ``docs/SIGNED_PAYLOADS.md``.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar, Literal

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.asymmetric.ec import (
    EllipticCurvePublicKey,
    SECP256K1,
    ECDSA,
)
from cryptography.hazmat.primitives.asymmetric import ec, utils
from cryptography.hazmat.primitives import hashes, serialization

# ---------------------------------------------------------------------------
# Protocol constants
# ---------------------------------------------------------------------------

#: Fixed 8-byte magic identifying this envelope format.  Prepended to every
#: signing byte-string so that even a naive receiver that forgets to check
#: the domain separator cannot be tricked into accepting a signature that
#: was crafted for a *different* envelope format (or worse: raw bytes with
#: no envelope at all).
ENVELOPE_MAGIC: bytes = b"AE402SIG"

#: Canonical protocol name recorded inside every DomainSeparator produced by
#: AE402 code paths.  Present so that a shared library used by *another*
#: protocol (e.g. an SDK also serving Casper-Prover) can build a distinct
#: separator without changes to this module.
PROTOCOL_NAME: str = "AgentEscrow402"

#: Current envelope schema version.  Bumped on any wire-format change.
ENVELOPE_VERSION: str = "v1"

#: Default replay window: signatures older than this (or dated more than
#: this in the future) are rejected outright.  Matches the existing
#: ``REPLAY_WINDOW_SECONDS`` in ``server/middleware.py`` for consistency.
DEFAULT_REPLAY_WINDOW_SECONDS: int = 300

#: Default nonce TTL for the persistent store.  Nonces older than this are
#: pruned on the next write.  Longer than the replay window so we never
#: accidentally forget a nonce that could still be replayed.
DEFAULT_NONCE_TTL_SECONDS: int = 900

#: Allowed signature algorithms.  Kept intentionally small; growth requires
#: a version bump and an audit.
Algorithm = Literal["ed25519", "secp256k1"]

#: Purposes recognised by this module.  Extending this list is a
#: version-bumping change, because a receiver upgraded before a sender may
#: reject the new purpose.
KNOWN_PURPOSES: frozenset[str] = frozenset(
    {
        "x402.payment",
        "escrow.deposit",
        "escrow.release",
        "escrow.refund",
        "escrow.dispute",
        "escrow.cap_approval",
        "arbiter.resolve_vote",
        "insurance.claim_vote",
    }
)


# ---------------------------------------------------------------------------
# DomainSeparator
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DomainSeparator:
    """The 4-tuple that binds an envelope to *one specific* protocol,
    version, chain, and purpose.

    All fields are required, non-empty, and immutable.  The 32-byte
    :meth:`digest` is prepended to every signing byte-string.
    """

    protocol: str
    version: str
    chain_id: str
    purpose: str

    def __post_init__(self) -> None:  # noqa: D401 - dataclass hook
        for field_name in ("protocol", "version", "chain_id", "purpose"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value:
                raise ValueError(
                    f"DomainSeparator.{field_name} must be a non-empty string"
                )
            # Reject separators that could collide with our record
            # separators or line-based framing.
            if any(ch in value for ch in (";", "\n", "\r", "\x00")):
                raise ValueError(
                    f"DomainSeparator.{field_name} must not contain ';', "
                    "newline, or NUL"
                )

    def canonical_bytes(self) -> bytes:
        """Deterministic byte representation of the separator."""
        payload = (
            f"{self.protocol};{self.version};{self.chain_id};{self.purpose}"
        )
        return payload.encode("utf-8")

    def digest(self) -> bytes:
        """SHA-256 of ``ENVELOPE_MAGIC || canonical_bytes()``.

        Prepended to every signing payload so that a signature over any
        envelope with a *different* separator is cryptographically
        distinct from one produced under this separator.
        """
        h = hashlib.sha256()
        h.update(ENVELOPE_MAGIC)
        h.update(b"\x00")  # explicit terminator between magic and body
        h.update(self.canonical_bytes())
        return h.digest()

    def hex(self) -> str:
        """Convenience: hex-encoded :meth:`digest`."""
        return self.digest().hex()


# ---------------------------------------------------------------------------
# SignedEnvelope
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SignedEnvelope:
    """Detached-signature envelope.

    The signature is stored *alongside* the payload rather than baked
    into it, so callers can inspect ``payload`` freely (e.g. for logging
    or Merkle inclusion) without touching signature material.

    ``payload`` is stored as a dict; canonical serialization is done by
    :func:`build_signing_bytes`.  Callers MUST NOT sign an arbitrary
    caller-supplied byte string — always go through this envelope.
    """

    domain: DomainSeparator
    payload: dict[str, Any]
    signer_pubkey_hex: str
    algorithm: Algorithm
    nonce: str
    timestamp: int  # unix seconds
    signature_hex: str

    #: Canonical JSON separators (no whitespace, deterministic).  Class
    #: attribute so the same instance is reused across every serialization.
    _JSON_SEPARATORS: ClassVar[tuple[str, str]] = (",", ":")

    def canonical_payload_bytes(self) -> bytes:
        """Deterministic JSON serialization of ``payload``.

        Keys are sorted, whitespace is stripped, so two envelopes with
        semantically identical payloads always serialize to the same
        bytes.  This is the *only* place ``payload`` is turned into
        bytes for signing/verification.
        """
        return json.dumps(
            self.payload,
            sort_keys=True,
            separators=self._JSON_SEPARATORS,
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")

    def to_json(self) -> str:
        """Wire representation of the whole envelope."""
        return json.dumps(
            {
                "domain": {
                    "protocol": self.domain.protocol,
                    "version": self.domain.version,
                    "chain_id": self.domain.chain_id,
                    "purpose": self.domain.purpose,
                },
                "payload": self.payload,
                "signer_pubkey": self.signer_pubkey_hex,
                "algorithm": self.algorithm,
                "nonce": self.nonce,
                "timestamp": self.timestamp,
                "signature": self.signature_hex,
            },
            sort_keys=True,
            separators=self._JSON_SEPARATORS,
            ensure_ascii=False,
            allow_nan=False,
        )

    @classmethod
    def from_dict(cls, obj: dict[str, Any]) -> "SignedEnvelope":
        """Rehydrate an envelope from a JSON-decoded dict.

        Raises :class:`ValueError` on any missing/wrong-typed field.
        """
        required = {
            "domain",
            "payload",
            "signer_pubkey",
            "algorithm",
            "nonce",
            "timestamp",
            "signature",
        }
        missing = required - obj.keys()
        if missing:
            raise ValueError(f"envelope missing fields: {sorted(missing)}")

        dom = obj["domain"]
        if not isinstance(dom, dict):
            raise ValueError("envelope.domain must be an object")

        return cls(
            domain=DomainSeparator(
                protocol=dom["protocol"],
                version=dom["version"],
                chain_id=dom["chain_id"],
                purpose=dom["purpose"],
            ),
            payload=obj["payload"],
            signer_pubkey_hex=str(obj["signer_pubkey"]).lower(),
            algorithm=obj["algorithm"],
            nonce=str(obj["nonce"]),
            timestamp=int(obj["timestamp"]),
            signature_hex=str(obj["signature"]).lower(),
        )


# ---------------------------------------------------------------------------
# Canonical signing bytes
# ---------------------------------------------------------------------------

def build_signing_bytes(envelope: SignedEnvelope) -> bytes:
    """Deterministic bytes that the signer signed / the verifier checks.

    Layout (all length-prefixed with 4-byte big-endian lengths to prevent
    any ambiguity if a future field contains a record separator):

        ENVELOPE_MAGIC (8 bytes)
        0x00
        domain.digest()                       (32 bytes)
        len(signer_pubkey_hex) || pubkey_hex
        len(algorithm)         || algorithm
        len(nonce)             || nonce
        8-byte big-endian timestamp
        len(canonical_payload) || canonical_payload

    Any change to any field flips the signing bytes, and therefore the
    signature.  Two signatures over 'semantically identical' payloads
    with different :class:`DomainSeparator` values will differ in their
    32-byte separator digest, so cross-domain replay is impossible.
    """

    def framed(part: bytes) -> bytes:
        return len(part).to_bytes(4, "big") + part

    payload_bytes = envelope.canonical_payload_bytes()
    parts: list[bytes] = [
        ENVELOPE_MAGIC,
        b"\x00",
        envelope.domain.digest(),
        framed(envelope.signer_pubkey_hex.encode("ascii")),
        framed(envelope.algorithm.encode("ascii")),
        framed(envelope.nonce.encode("utf-8")),
        int(envelope.timestamp).to_bytes(8, "big", signed=False),
        framed(payload_bytes),
    ]
    return b"".join(parts)


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class VerifyResult:
    """Structured outcome of :func:`verify_envelope`.

    ``ok`` is the single success signal; ``reason`` is a short
    machine-readable tag that callers can log/return without leaking
    key material.  A verifier MUST NOT proceed on any result where
    ``ok`` is False, regardless of other fields.
    """

    ok: bool
    reason: str = ""


def _verify_ed25519(pubkey_hex: str, message: bytes, sig_hex: str) -> bool:
    try:
        key_bytes = bytes.fromhex(pubkey_hex)
        sig_bytes = bytes.fromhex(sig_hex)
    except ValueError:
        return False
    if len(key_bytes) != 32 or len(sig_bytes) != 64:
        return False
    try:
        pub = Ed25519PublicKey.from_public_bytes(key_bytes)
        pub.verify(sig_bytes, message)
        return True
    except InvalidSignature:
        return False
    except Exception:
        return False


def _verify_secp256k1(pubkey_hex: str, message: bytes, sig_hex: str) -> bool:
    try:
        key_bytes = bytes.fromhex(pubkey_hex)
        sig_bytes = bytes.fromhex(sig_hex)
    except ValueError:
        return False
    # Compressed pubkey = 33 bytes; compact signature (r||s) = 64 bytes.
    if len(key_bytes) != 33 or len(sig_bytes) != 64:
        return False
    try:
        pub = EllipticCurvePublicKey.from_encoded_point(SECP256K1(), key_bytes)
        r = int.from_bytes(sig_bytes[:32], "big")
        s = int.from_bytes(sig_bytes[32:], "big")
        der_sig = utils.encode_dss_signature(r, s)
        digest = hashlib.sha256(message).digest()
        pub.verify(der_sig, digest, ECDSA(utils.Prehashed(hashes.SHA256())))
        return True
    except InvalidSignature:
        return False
    except Exception:
        return False


def verify_envelope(
    envelope: SignedEnvelope,
    *,
    expected_domain: DomainSeparator,
    now: int | None = None,
    replay_window_seconds: int = DEFAULT_REPLAY_WINDOW_SECONDS,
    nonce_store: "PersistentNonceStore | None" = None,
) -> VerifyResult:
    """Full-stack verification of a :class:`SignedEnvelope`.

    Fails **before** touching the crypto whenever a cheaper check
    already proves the envelope is unusable, so a mismatched domain or
    stale timestamp does not force an expensive signature check.

    ``nonce_store`` is optional; when provided, verified envelopes have
    their ``(nonce, timestamp)`` committed to it.  Callers running
    without a store take responsibility for their own replay defence.
    """
    # 1. Domain separator must match exactly.
    if envelope.domain != expected_domain:
        return VerifyResult(False, "domain_mismatch")

    # 2. Purpose must be one we know about, so a typo cannot open a
    #    dormant surface.
    if envelope.domain.purpose not in KNOWN_PURPOSES:
        return VerifyResult(False, "unknown_purpose")

    # 3. Algorithm allow-list.
    if envelope.algorithm not in ("ed25519", "secp256k1"):
        return VerifyResult(False, "unknown_algorithm")

    # 4. Timestamp window.
    ref_now = now if now is not None else int(time.time())
    delta = ref_now - envelope.timestamp
    if delta > replay_window_seconds:
        return VerifyResult(False, "timestamp_stale")
    if delta < -replay_window_seconds:
        # Future-dated: bounded on the other side too, so an attacker
        # cannot pre-mint envelopes with far-future timestamps.
        return VerifyResult(False, "timestamp_future")

    # 5. Nonce format sanity — reject before hitting the store so a
    #    malformed nonce does not pollute it.
    if not (8 <= len(envelope.nonce) <= 128):
        return VerifyResult(False, "nonce_bad_length")
    if any(ch in envelope.nonce for ch in (";", "\n", "\r", "\x00")):
        return VerifyResult(False, "nonce_bad_chars")

    # 6. Nonce replay check (if store provided).
    if nonce_store is not None:
        if nonce_store.contains(envelope.nonce):
            return VerifyResult(False, "nonce_reused")

    # 7. Signature verification against the canonical bytes.
    signing_bytes = build_signing_bytes(envelope)
    if envelope.algorithm == "ed25519":
        sig_ok = _verify_ed25519(
            envelope.signer_pubkey_hex, signing_bytes, envelope.signature_hex
        )
    else:
        sig_ok = _verify_secp256k1(
            envelope.signer_pubkey_hex, signing_bytes, envelope.signature_hex
        )
    if not sig_ok:
        return VerifyResult(False, "bad_signature")

    # 8. Commit nonce ONLY after every check has passed.  Otherwise a
    #    rejected envelope could still burn a nonce and cause a
    #    legitimate retry with the same nonce to fail.
    if nonce_store is not None:
        nonce_store.remember(envelope.nonce, envelope.timestamp)

    return VerifyResult(True, "ok")


# ---------------------------------------------------------------------------
# Persistent nonce store
# ---------------------------------------------------------------------------

class PersistentNonceStore:
    """SQLite-backed nonce store.

    Survives process restarts.  Prunes entries older than ``ttl_seconds``
    on every write.  Thread-safe for the concurrent-worker access
    pattern (each call opens a short-lived connection under a lock).

    For unit tests use :meth:`in_memory`, which uses a shared in-memory
    database with the same schema.
    """

    _SCHEMA: ClassVar[str] = (
        "CREATE TABLE IF NOT EXISTS nonces ("
        "  nonce TEXT PRIMARY KEY,"
        "  ts    INTEGER NOT NULL"
        ")"
    )

    def __init__(
        self,
        path: str | Path,
        *,
        ttl_seconds: int = DEFAULT_NONCE_TTL_SECONDS,
    ) -> None:
        self._path = str(path)
        self._ttl = int(ttl_seconds)
        self._lock = threading.Lock()
        with self._connect() as conn:
            conn.execute(self._SCHEMA)

    @classmethod
    def in_memory(cls, *, ttl_seconds: int = DEFAULT_NONCE_TTL_SECONDS) -> "PersistentNonceStore":
        """Shared in-memory instance for tests.

        Uses ``file::memory:?cache=shared`` so that multiple connections
        opened by :meth:`_connect` see the same database within one
        process, which mirrors the on-disk semantics.
        """
        # A per-instance unique URI ensures separate in-memory stores in
        # the same process do not accidentally alias each other.
        uri = f"file:aeenvnonces-{id(object())}?mode=memory&cache=shared"
        store = cls.__new__(cls)
        store._path = uri
        store._ttl = int(ttl_seconds)
        store._lock = threading.Lock()
        # Keep a sentinel connection open so the shared cache survives
        # even when transient connections close.
        store._sentinel = sqlite3.connect(uri, uri=True, check_same_thread=False)
        store._sentinel.execute(cls._SCHEMA)
        store._sentinel.commit()
        return store

    def _connect(self) -> sqlite3.Connection:
        if self._path.startswith("file:"):
            conn = sqlite3.connect(self._path, uri=True, check_same_thread=False)
        else:
            conn = sqlite3.connect(self._path, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def contains(self, nonce: str) -> bool:
        """Return True iff ``nonce`` has been remembered and not yet pruned."""
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM nonces WHERE nonce = ? LIMIT 1", (nonce,)
            ).fetchone()
            return row is not None

    def remember(self, nonce: str, timestamp: int) -> None:
        """Commit a nonce.  Prunes stale entries as a side effect."""
        cutoff = int(time.time()) - self._ttl
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO nonces(nonce, ts) VALUES(?, ?)",
                (nonce, int(timestamp)),
            )
            conn.execute("DELETE FROM nonces WHERE ts < ?", (cutoff,))
            conn.commit()

    def size(self) -> int:
        """Current number of remembered nonces (post-prune)."""
        cutoff = int(time.time()) - self._ttl
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM nonces WHERE ts < ?", (cutoff,))
            conn.commit()
            row = conn.execute("SELECT COUNT(*) FROM nonces").fetchone()
            return int(row[0]) if row else 0

    def purge_all(self) -> None:
        """Drop every remembered nonce.  Test-only helper."""
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM nonces")
            conn.commit()


# ---------------------------------------------------------------------------
# Convenience: build+sign helper (test/dev only)
# ---------------------------------------------------------------------------

def sign_envelope_ed25519(
    *,
    domain: DomainSeparator,
    payload: dict[str, Any],
    nonce: str,
    timestamp: int,
    private_key_bytes: bytes,
    public_key_bytes: bytes,
) -> SignedEnvelope:
    """Produce a fully-formed :class:`SignedEnvelope` using ed25519.

    This is intentionally a test/dev helper — production signers live
    in the SDK and hold key material outside the server process.
    """
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
    )

    if len(private_key_bytes) != 32:
        raise ValueError("ed25519 private key must be exactly 32 bytes")
    if len(public_key_bytes) != 32:
        raise ValueError("ed25519 public key must be exactly 32 bytes")

    envelope_stub = SignedEnvelope(
        domain=domain,
        payload=payload,
        signer_pubkey_hex=public_key_bytes.hex(),
        algorithm="ed25519",
        nonce=nonce,
        timestamp=int(timestamp),
        signature_hex="",  # filled after we compute signing bytes
    )
    signing_bytes = build_signing_bytes(envelope_stub)
    priv = Ed25519PrivateKey.from_private_bytes(private_key_bytes)
    sig = priv.sign(signing_bytes)
    return SignedEnvelope(
        domain=envelope_stub.domain,
        payload=envelope_stub.payload,
        signer_pubkey_hex=envelope_stub.signer_pubkey_hex,
        algorithm=envelope_stub.algorithm,
        nonce=envelope_stub.nonce,
        timestamp=envelope_stub.timestamp,
        signature_hex=sig.hex(),
    )


__all__ = [
    "Algorithm",
    "DomainSeparator",
    "SignedEnvelope",
    "VerifyResult",
    "PersistentNonceStore",
    "ENVELOPE_MAGIC",
    "PROTOCOL_NAME",
    "ENVELOPE_VERSION",
    "DEFAULT_REPLAY_WINDOW_SECONDS",
    "DEFAULT_NONCE_TTL_SECONDS",
    "KNOWN_PURPOSES",
    "build_signing_bytes",
    "verify_envelope",
    "sign_envelope_ed25519",
]
