"""
W3C Verifiable Credentials 2.0 receipts for AE402 escrow events.

Issues cryptographically verifiable receipts (VCs) for escrow lifecycle
events (release, refund, resolve). Receipts are portable, verifiable
without contacting AE402, and follow the W3C VC 2.0 data model.

Data model reference:
  https://www.w3.org/TR/vc-data-model-2.0/

Design decisions
----------------
* Proof suite: **Ed25519Signature2020** over JCS-canonicalized JSON.
  Chosen over LD-Proofs / DataIntegrityProofs because it needs *no*
  external JSON-LD processor and gives byte-exact reproducible signatures.
  The credential itself uses JSON-LD contexts for interoperability, but
  the proof itself signs the JCS canonicalization of the credential
  (excluding the `proof` field).

* JCS = JSON Canonicalization Scheme (RFC 8785). We implement the
  subset AE402 emits: recursively-sorted string keys, UTF-8, no
  whitespace, integers preserved as integers, no floats.

* Issuer DID: `did:key:z...` derived directly from the Ed25519 public
  key (multibase base58btc + multicodec `ed25519-pub` header 0xed01).
  No DID resolver needed — the key is self-contained in the DID.

* Zero external deps except `pynacl` (already a dep for Ed25519 elsewhere
  in AE402). No JSON-LD libraries required.

* Deterministic: two calls with the same inputs (including timestamp)
  produce byte-identical VCs. This is critical for on-chain anchoring.

Threat model
------------
- **Forgery**: infeasible without issuer signing key (Ed25519, 128-bit
  classical security).
- **Tamper**: any change to the credential body invalidates the proof
  (JCS re-canonicalization + Ed25519 verify).
- **Replay**: receipts include `issuanceDate` + escrow-specific
  `service_hash` in `credentialSubject`; verifier MUST check both
  against expected escrow.
- **Key compromise**: rotate issuer key → re-issue receipts under new
  DID; old receipts remain verifiable under the old DID.
- **Revocation**: not in v1 (receipts attest historical events, so
  revocation semantics don't apply the same way as identity VCs). If
  needed, add `credentialStatus` field in v2.
"""

from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass, field
from typing import Any, Literal

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VC_CONTEXT_V2 = "https://www.w3.org/ns/credentials/v2"
AE402_CONTEXT = "https://ae402.dev/contexts/escrow-receipt/v1"

RECEIPT_TYPES = {
    "release": "EscrowReleaseReceipt",
    "refund": "EscrowRefundReceipt",
    "resolve": "EscrowResolveReceipt",
}

# multicodec prefix for ed25519-pub: 0xed 0x01
ED25519_MULTICODEC = b"\xed\x01"

# ---------------------------------------------------------------------------
# base58btc (Bitcoin alphabet) — zero-dep implementation
# ---------------------------------------------------------------------------

_B58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_B58_INDEX = {c: i for i, c in enumerate(_B58_ALPHABET)}


def _b58encode(raw: bytes) -> str:
    if not raw:
        return ""
    n_leading_zeros = 0
    for b in raw:
        if b == 0:
            n_leading_zeros += 1
        else:
            break
    n = int.from_bytes(raw, "big")
    out = ""
    while n > 0:
        n, rem = divmod(n, 58)
        out = _B58_ALPHABET[rem] + out
    return "1" * n_leading_zeros + out


def _b58decode(s: str) -> bytes:
    if s == "":
        return b""
    n_leading_ones = 0
    for c in s:
        if c == "1":
            n_leading_ones += 1
        else:
            break
    n = 0
    for c in s:
        if c not in _B58_INDEX:
            raise ValueError(f"invalid base58 char: {c!r}")
        n = n * 58 + _B58_INDEX[c]
    # figure out byte length
    body = b""
    if n > 0:
        byte_len = (n.bit_length() + 7) // 8
        body = n.to_bytes(byte_len, "big")
    return b"\x00" * n_leading_ones + body


# ---------------------------------------------------------------------------
# JCS — JSON Canonicalization Scheme (RFC 8785) subset
# ---------------------------------------------------------------------------


def _jcs_canonicalize(value: Any) -> bytes:
    """Return the RFC 8785 canonical JSON encoding of `value`.

    Supports the subset AE402 emits: dict (string keys), list, str, int,
    bool, None. Floats are rejected — receipts must not contain floats
    (amounts are integer motes).
    """

    def _encode(v: Any) -> str:
        if v is None:
            return "null"
        if v is True:
            return "true"
        if v is False:
            return "false"
        if isinstance(v, int) and not isinstance(v, bool):
            return str(v)
        if isinstance(v, float):
            raise TypeError("JCS: float values not permitted in AE402 receipts " "(use integer motes)")
        if isinstance(v, str):
            # json.dumps handles UTF-8 escaping per RFC 8259
            return json.dumps(v, ensure_ascii=False)
        if isinstance(v, list):
            return "[" + ",".join(_encode(x) for x in v) + "]"
        if isinstance(v, dict):
            # sort keys lexicographically (UTF-16 code units per RFC 8785
            # — Python's default str comparison is code-point-based which
            # matches for BMP; AE402 keys are all ASCII so this is safe)
            items = sorted(v.items(), key=lambda kv: kv[0])
            return "{" + ",".join(f"{json.dumps(k, ensure_ascii=False)}:{_encode(val)}" for k, val in items) + "}"
        raise TypeError(f"JCS: unsupported type {type(v).__name__}")

    return _encode(value).encode("utf-8")


# ---------------------------------------------------------------------------
# did:key encoding
# ---------------------------------------------------------------------------


def pubkey_to_did_key(pubkey_bytes: bytes) -> str:
    """Encode an Ed25519 public key as a `did:key:z...` identifier.

    Format: did:key:z<base58btc(multicodec(ed25519-pub) || pubkey)>
    """
    if len(pubkey_bytes) != 32:
        raise ValueError(f"Ed25519 public key must be 32 bytes, got {len(pubkey_bytes)}")
    prefixed = ED25519_MULTICODEC + pubkey_bytes
    b58 = _b58encode(prefixed)
    # `z` = base58btc multibase prefix
    return f"did:key:z{b58}"


def did_key_to_pubkey(did: str) -> bytes:
    """Decode a `did:key:z...` (Ed25519) back to the raw 32-byte pubkey."""
    if not did.startswith("did:key:z"):
        raise ValueError(f"Not a did:key identifier: {did!r}")
    b58 = did[len("did:key:z") :]
    try:
        decoded = _b58decode(b58)
    except ValueError as exc:
        raise ValueError(f"Invalid base58 in did:key: {exc}") from exc
    if not decoded.startswith(ED25519_MULTICODEC):
        raise ValueError("did:key is not Ed25519 (wrong multicodec prefix)")
    pubkey = decoded[len(ED25519_MULTICODEC) :]
    if len(pubkey) != 32:
        raise ValueError(f"Decoded pubkey length {len(pubkey)} != 32")
    return pubkey


# ---------------------------------------------------------------------------
# Issuer
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IssuerKey:
    """Issuer signing key (Ed25519). Wraps `cryptography` Ed25519PrivateKey."""

    private_key: Ed25519PrivateKey = field(repr=False)

    @classmethod
    def from_seed(cls, seed_bytes: bytes) -> "IssuerKey":
        if len(seed_bytes) != 32:
            raise ValueError(f"Ed25519 seed must be 32 bytes, got {len(seed_bytes)}")
        return cls(private_key=Ed25519PrivateKey.from_private_bytes(seed_bytes))

    @classmethod
    def from_seed_b64(cls, seed_b64: str) -> "IssuerKey":
        s = seed_b64.replace("-", "+").replace("_", "/")
        pad = "=" * (-len(s) % 4)
        return cls.from_seed(base64.b64decode(s + pad))

    @classmethod
    def generate(cls) -> "IssuerKey":
        return cls(private_key=Ed25519PrivateKey.generate())

    @property
    def pubkey(self) -> bytes:
        return self.private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)

    @property
    def seed(self) -> bytes:
        """Return the 32-byte private-key seed (raw)."""
        return self.private_key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())

    @property
    def did(self) -> str:
        return pubkey_to_did_key(self.pubkey)

    def sign(self, msg: bytes) -> bytes:
        return self.private_key.sign(msg)


# ---------------------------------------------------------------------------
# Receipt issuance
# ---------------------------------------------------------------------------


ReceiptEvent = Literal["release", "refund", "resolve"]


def _iso8601_utc(ts: int) -> str:
    """Format a Unix epoch second as W3C VC-compatible ISO-8601 UTC."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def _multibase_b58btc(raw: bytes) -> str:
    """multibase base58btc encoding: `z` prefix + base58."""
    return "z" + _b58encode(raw)


def _multibase_decode(s: str) -> bytes:
    if not s.startswith("z"):
        raise ValueError(f"Only base58btc multibase (z...) supported, got {s[:2]!r}")
    return _b58decode(s[1:])


def issue_receipt(
    issuer: IssuerKey,
    *,
    event: ReceiptEvent,
    service_hash: str,
    escrow_id: str,
    payer: str,
    receiver: str,
    amount_motes: int,
    asset: str = "CSPR",
    issuance_ts: int | None = None,
    extra_claims: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Issue a W3C VC 2.0 receipt for an escrow lifecycle event.

    Parameters
    ----------
    issuer : IssuerKey
        Signing key. Issuer DID is derived automatically.
    event : "release" | "refund" | "resolve"
        Which lifecycle event this receipt attests.
    service_hash : str
        The AE402 service hash (identifies the escrow).
    escrow_id : str
        Human-readable escrow identifier (may equal service_hash).
    payer, receiver : str
        Casper public keys or DIDs of the parties.
    amount_motes : int
        Non-negative integer amount, in motes (base unit).
    asset : str
        Asset symbol, default "CSPR".
    issuance_ts : int | None
        Unix epoch seconds; defaults to `time.time()`. Pass explicitly for
        deterministic issuance (e.g. reissue-anchored-on-block-time).
    extra_claims : dict | None
        Additional claims folded into `credentialSubject`. Keys must not
        collide with reserved names below.

    Returns
    -------
    dict
        The signed VC as a JSON-serializable dict. Includes `proof`.
    """
    if event not in RECEIPT_TYPES:
        raise ValueError(f"Unknown receipt event {event!r}")
    if not isinstance(amount_motes, int) or isinstance(amount_motes, bool):
        raise TypeError("amount_motes must be an int (not float, not bool)")
    if amount_motes < 0:
        raise ValueError("amount_motes must be non-negative")
    if not service_hash:
        raise ValueError("service_hash is required")

    ts = int(issuance_ts if issuance_ts is not None else time.time())

    subject: dict[str, Any] = {
        "id": f"urn:ae402:escrow:{escrow_id}",
        "type": "AE402Escrow",
        "serviceHash": service_hash,
        "event": event,
        "payer": payer,
        "receiver": receiver,
        "amount": {"value": amount_motes, "asset": asset},
    }
    if extra_claims:
        reserved = set(subject.keys())
        collisions = reserved & set(extra_claims.keys())
        if collisions:
            raise ValueError(f"extra_claims collide with reserved keys: {sorted(collisions)}")
        subject.update(extra_claims)

    credential: dict[str, Any] = {
        "@context": [VC_CONTEXT_V2, AE402_CONTEXT],
        "type": ["VerifiableCredential", RECEIPT_TYPES[event]],
        "issuer": issuer.did,
        "issuanceDate": _iso8601_utc(ts),
        "credentialSubject": subject,
    }

    # Sign the JCS canonicalization of the credential (proof excluded).
    signing_input = _jcs_canonicalize(credential)
    sig = issuer.sign(signing_input)

    credential["proof"] = {
        "type": "Ed25519Signature2020",
        "created": _iso8601_utc(ts),
        "verificationMethod": f"{issuer.did}#{issuer.did.split(':')[-1]}",
        "proofPurpose": "assertionMethod",
        "proofValue": _multibase_b58btc(sig),
    }
    return credential


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------


class VerificationError(Exception):
    """Base class for VC verification failures."""


class ProofMissingError(VerificationError):
    pass


class ProofMalformedError(VerificationError):
    pass


class SignatureInvalidError(VerificationError):
    pass


class SchemaError(VerificationError):
    pass


def verify_receipt(
    credential: dict[str, Any],
    *,
    expected_issuer: str | None = None,
) -> dict[str, Any]:
    """Verify a W3C VC 2.0 receipt.

    Returns the credential (with proof preserved) on success. Raises a
    `VerificationError` subclass on any failure.

    If `expected_issuer` (a did:key) is provided, verification also
    checks that the credential's issuer matches.
    """
    if not isinstance(credential, dict):
        raise SchemaError("credential must be a JSON object")

    # ---- structural checks ----
    for field_name in ("@context", "type", "issuer", "issuanceDate", "credentialSubject"):
        if field_name not in credential:
            raise SchemaError(f"missing required field: {field_name}")

    contexts = credential["@context"]
    if not isinstance(contexts, list) or VC_CONTEXT_V2 not in contexts:
        raise SchemaError(f"@context must include {VC_CONTEXT_V2!r}")

    types = credential["type"]
    if not isinstance(types, list) or "VerifiableCredential" not in types:
        raise SchemaError('type must be a list including "VerifiableCredential"')

    issuer_did = credential["issuer"]
    if not isinstance(issuer_did, str) or not issuer_did.startswith("did:key:"):
        raise SchemaError("only did:key issuers supported")

    if expected_issuer is not None and issuer_did != expected_issuer:
        raise VerificationError(f"issuer mismatch: expected {expected_issuer!r}, got {issuer_did!r}")

    proof = credential.get("proof")
    if not proof:
        raise ProofMissingError("credential has no proof")
    if not isinstance(proof, dict):
        raise ProofMalformedError("proof must be an object")
    if proof.get("type") != "Ed25519Signature2020":
        raise ProofMalformedError(f"unsupported proof type: {proof.get('type')!r}")
    if proof.get("proofPurpose") != "assertionMethod":
        raise ProofMalformedError("proofPurpose must be assertionMethod")
    vm = proof.get("verificationMethod")
    if not isinstance(vm, str) or not vm.startswith(issuer_did):
        raise ProofMalformedError("verificationMethod must reference the issuer DID")
    proof_value = proof.get("proofValue")
    if not isinstance(proof_value, str):
        raise ProofMalformedError("proofValue missing or not a string")

    # ---- decode signature ----
    try:
        sig = _multibase_decode(proof_value)
    except ValueError as exc:
        raise ProofMalformedError(f"proofValue decode: {exc}") from exc
    if len(sig) != 64:
        raise ProofMalformedError(f"Ed25519 signature must be 64 bytes, got {len(sig)}")

    # ---- decode pubkey ----
    try:
        pubkey = did_key_to_pubkey(issuer_did)
    except ValueError as exc:
        raise ProofMalformedError(f"issuer DID decode: {exc}") from exc

    # ---- reconstruct signing input (credential without proof) ----
    body = {k: v for k, v in credential.items() if k != "proof"}
    signing_input = _jcs_canonicalize(body)

    # ---- verify ----
    verify_key = Ed25519PublicKey.from_public_bytes(pubkey)
    try:
        verify_key.verify(sig, signing_input)
    except InvalidSignature as exc:
        raise SignatureInvalidError("Ed25519 signature invalid") from exc

    return credential


# ---------------------------------------------------------------------------
# Utility: extract claims
# ---------------------------------------------------------------------------


def receipt_summary(credential: dict[str, Any]) -> dict[str, Any]:
    """Return a compact summary of a verified receipt (no signature, no context).

    Callers SHOULD call `verify_receipt` first; this function does not verify.
    """
    subject = credential.get("credentialSubject", {}) or {}
    amount = subject.get("amount", {}) or {}
    return {
        "issuer": credential.get("issuer"),
        "issued_at": credential.get("issuanceDate"),
        "types": credential.get("type", []),
        "event": subject.get("event"),
        "service_hash": subject.get("serviceHash"),
        "escrow_id": subject.get("id", "").removeprefix("urn:ae402:escrow:"),
        "payer": subject.get("payer"),
        "receiver": subject.get("receiver"),
        "amount_motes": amount.get("value"),
        "asset": amount.get("asset"),
    }
