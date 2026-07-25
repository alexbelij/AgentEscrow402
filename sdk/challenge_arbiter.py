"""Client-side helpers for the AE402 challenge-arbiter contract.

The on-chain contract exposes commit-reveal arbiter selection with bonds and
slash-on-non-reveal. Off-chain, an arbiter needs to:

  1. Pick a private 32-byte `nonce`.
  2. Build the canonical reveal preimage.
  3. Blake2b-256 hash it → the commit value that goes on-chain in
     `commit_verdict`.
  4. Sign the preimage with their Ed25519 private key.
  5. Later, submit the (verdict, nonce, recomputed_commit_hex, signature) to
     `reveal_verdict`.

This module implements steps 2–4 in Python. Byte-for-byte matches the on-chain
`canonical_reveal_preimage` and byte-length checks in Rust.

Domain string: `ae402:challenge:v1:reveal:{package_hash}:{dispute_id}:{verdict}:{nonce_hex}:{arbiter_pk_hex}`
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from typing import Optional

__all__ = [
    "DOMAIN",
    "VERDICT_SENDER",
    "VERDICT_RECEIVER",
    "STATUS_PENDING",
    "STATUS_COMMIT_PHASE",
    "STATUS_REVEAL_PHASE",
    "STATUS_FINALIZED_CHALLENGER_WINS",
    "STATUS_FINALIZED_STATUS_QUO",
    "STATUS_FINALIZED_FAILED_QUORUM",
    "canonical_reveal_preimage",
    "compute_commit_hex",
    "sign_reveal",
    "verify_reveal_signature",
    "generate_nonce",
    "CommitBundle",
    "build_commit_bundle",
]

DOMAIN = "ae402:challenge:v1"

VERDICT_SENDER = 1
VERDICT_RECEIVER = 2

STATUS_PENDING = 1
STATUS_COMMIT_PHASE = 2
STATUS_REVEAL_PHASE = 3
STATUS_FINALIZED_CHALLENGER_WINS = 4
STATUS_FINALIZED_STATUS_QUO = 5
STATUS_FINALIZED_FAILED_QUORUM = 6


def canonical_reveal_preimage(
    self_package_hash: str,
    dispute_id: str,
    verdict: int,
    nonce_hex: str,
    arbiter_pk_hex: str,
) -> str:
    """Build the exact byte string the contract hashes on reveal.

    Matches the Rust helper of the same name byte-for-byte:
    `ae402:challenge:v1:reveal:{pkg}:{dispute}:{verdict}:{nonce}:{pk}`.
    Verdict is written as unpadded decimal (u64_to_decimal in main.rs).
    """
    if verdict not in (VERDICT_SENDER, VERDICT_RECEIVER):
        raise ValueError(f"verdict must be 1 (sender) or 2 (receiver), got {verdict}")
    return f"{DOMAIN}:reveal:{self_package_hash}" f":{dispute_id}:{verdict}:{nonce_hex}:{arbiter_pk_hex}"


def compute_commit_hex(preimage: str) -> str:
    """BLAKE2b-256 (32-byte) hash of the canonical reveal preimage, hex-encoded.

    This is exactly what an arbiter submits to `commit_verdict.commit_hex` and
    later re-supplies as `reveal_verdict.recomputed_commit_hex`.
    """
    h = hashlib.blake2b(preimage.encode("utf-8"), digest_size=32)
    return h.hexdigest()


def generate_nonce() -> str:
    """Cryptographically secure 32-byte nonce, hex-encoded.

    Arbiters generate this LOCALLY and never disclose until reveal. The
    contract binds the reveal signature to this exact nonce, so a leaker
    would enable an attacker to grief them only by making the verdict
    predictable — not to forge the signature (they'd still need the private
    key).
    """
    return secrets.token_hex(32)


def sign_reveal(
    private_key_pem: bytes,
    preimage: str,
) -> str:
    """Ed25519-sign the reveal preimage, return hex signature.

    Uses `cryptography` if available; otherwise falls back to `nacl` (PyNaCl).
    Raises RuntimeError if neither is available.
    """
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        key = serialization.load_pem_private_key(private_key_pem, password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError("expected Ed25519PrivateKey PEM")
        sig = key.sign(preimage.encode("utf-8"))
        return sig.hex()
    except ImportError:
        pass

    try:
        import nacl.signing

        signing_key = nacl.signing.SigningKey(private_key_pem[:32])
        return signing_key.sign(preimage.encode("utf-8")).signature.hex()
    except ImportError as exc:
        raise RuntimeError("sign_reveal requires either 'cryptography' or 'pynacl' installed") from exc


def verify_reveal_signature(
    public_key_hex: str,
    preimage: str,
    signature_hex: str,
) -> bool:
    """Verify an Ed25519 signature over the reveal preimage.

    Mirrors the on-chain check. `public_key_hex` is the raw 32-byte Ed25519
    pubkey without the Casper AsymmetricType tag prefix; if the caller has
    a tag-prefixed hex (which Casper's `PublicKey::from_hex` expects), pass
    that hex with the leading tag byte trimmed off (the 02… prefix for
    Ed25519).
    """
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

        # Strip Casper's tag byte (02 for Ed25519) if present
        raw = public_key_hex
        if raw.startswith("02") and len(raw) == 66:
            raw = raw[2:]
        pk = Ed25519PublicKey.from_public_bytes(bytes.fromhex(raw))
        try:
            pk.verify(bytes.fromhex(signature_hex), preimage.encode("utf-8"))
            return True
        except InvalidSignature:
            return False
    except ImportError:
        pass

    try:
        import nacl.exceptions
        import nacl.signing

        raw = public_key_hex
        if raw.startswith("02") and len(raw) == 66:
            raw = raw[2:]
        verify_key = nacl.signing.VerifyKey(bytes.fromhex(raw))
        try:
            verify_key.verify(preimage.encode("utf-8"), bytes.fromhex(signature_hex))
            return True
        except nacl.exceptions.BadSignatureError:
            return False
    except ImportError as exc:
        raise RuntimeError("verify_reveal_signature requires either 'cryptography' or 'pynacl' installed") from exc


@dataclass
class CommitBundle:
    """A ready-to-submit commit + kept-locally reveal payload.

    The `commit_hex` goes on-chain during the commit phase. The `preimage`,
    `nonce_hex`, `verdict`, and `signature_hex` STAY LOCAL until reveal —
    disclosing them early leaks the verdict.
    """

    commit_hex: str
    preimage: str
    nonce_hex: str
    verdict: int
    signature_hex: Optional[str]
    dispute_id: str
    arbiter_pk_hex: str
    self_package_hash: str

    def as_reveal_args(self) -> dict:
        """Named args for `reveal_verdict()` on-chain."""
        if self.signature_hex is None:
            raise ValueError("bundle has no signature — call sign() first")
        return {
            "dispute_id": self.dispute_id,
            "arbiter_pk": self.arbiter_pk_hex,
            "verdict": self.verdict,
            "nonce_hex": self.nonce_hex,
            "recomputed_commit_hex": self.commit_hex,
            "signature_hex": self.signature_hex,
        }


def build_commit_bundle(
    self_package_hash: str,
    dispute_id: str,
    verdict: int,
    arbiter_pk_hex: str,
    private_key_pem: Optional[bytes] = None,
    nonce_hex: Optional[str] = None,
) -> CommitBundle:
    """One-shot builder: pick a nonce, build preimage, hash, sign (if key given).

    Returns a `CommitBundle` whose `commit_hex` is safe to send on-chain now,
    and whose remaining fields are the pre-reveal secret the arbiter must
    protect until reveal_deadline − epsilon.
    """
    nonce = nonce_hex or generate_nonce()
    preimage = canonical_reveal_preimage(self_package_hash, dispute_id, verdict, nonce, arbiter_pk_hex)
    commit_hex = compute_commit_hex(preimage)
    signature_hex = sign_reveal(private_key_pem, preimage) if private_key_pem else None
    return CommitBundle(
        commit_hex=commit_hex,
        preimage=preimage,
        nonce_hex=nonce,
        verdict=verdict,
        signature_hex=signature_hex,
        dispute_id=dispute_id,
        arbiter_pk_hex=arbiter_pk_hex,
        self_package_hash=self_package_hash,
    )
