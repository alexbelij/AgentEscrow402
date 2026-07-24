"""
Range-Proof Registry — client-side helpers.

Byte-for-byte compatible with ``contracts/range-proof-registry/src/main.rs``.
Two sides of the protocol live here:

1. **Prover**  — Pedersen-style hiding commitment to an amount and a
   deterministic ``blake2b(...)`` hash over a full off-chain proof blob,
   plus the canonical ``register_commitment`` argument tuple that the
   WASM contract accepts.

2. **Arbiter** — canonical, domain-separated preimage builders and
   Ed25519 sign / verify helpers for ``attest`` and ``mark_fraud``.
   The preimages are the anti-replay foundation: they embed the
   deployment's ``self_package_hash`` so a signature made against one
   deployed instance cannot be replayed against another.

The Pedersen group implemented here is a **prime-field, discrete-log
group** — ``commitment = (g^amount * h^randomness) mod p`` in a
2048-bit safe prime. That gives real hiding (statistically
indistinguishable commitments for uniformly-random ``randomness``) and
binding (breaking it needs a discrete-log). It intentionally does NOT
carry a bulletproof range-proof: the on-chain verifier is
arbiter-attested, and the *proof itself* is verified deterministically
off-chain by arbiters running :func:`verify_range_proof` in this
module. See :func:`build_range_proof` for the proof format.

Threat model + full protocol spec: ``docs/RANGE_PROOFS.md``.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from typing import Sequence

DOMAIN = "ae402:range-proof:v1"
DOMAIN_ATTEST = "attest"
DOMAIN_FRAUD = "fraud"
DOMAIN_ADMIN_ROTATE = "admin_rotate"

HASH_LEN = 32
COMMITMENT_MAX_LEN = 512
MAX_ARBITERS = 32

# 2048-bit safe prime (RFC 3526 group 14 modulus). We use the standard
# DH-safe modulus and pick g=2 as the first generator; h is derived
# deterministically from a nothing-up-my-sleeve seed so nobody can know
# ``log_g(h)`` — otherwise the commitment scheme is broken (the prover
# could open to any amount).
_P_HEX = (
    "FFFFFFFFFFFFFFFFC90FDAA22168C234C4C6628B80DC1CD1"
    "29024E088A67CC74020BBEA63B139B22514A08798E3404DD"
    "EF9519B3CD3A431B302B0A6DF25F14374FE1356D6D51C245"
    "E485B576625E7EC6F44C42E9A637ED6B0BFF5CB6F406B7ED"
    "EE386BFB5A899FA5AE9F24117C4B1FE649286651ECE45B3D"
    "C2007CB8A163BF0598DA48361C55D39A69163FA8FD24CF5F"
    "83655D23DCA3AD961C62F356208552BB9ED529077096966D"
    "670C354E4ABC9804F1746C08CA18217C32905E462E36CE3B"
    "E39E772C180E86039B2783A2EC07A28FB5C55DF06F4C52C9"
    "DE2BCBF6955817183995497CEA956AE515D2261898FA0510"
    "15728E5A8AACAA68FFFFFFFFFFFFFFFF"
)
_P = int(_P_HEX, 16)
_Q = (_P - 1) // 2  # order of the prime-order subgroup
_G = 2  # standard generator; a QR mod _P.


def _derive_h() -> int:
    """Return a second generator h whose discrete-log wrt g is unknown.

    Uses a nothing-up-my-sleeve derivation: hash the ASCII string
    ``"ae402:range-proof:v1:h_generator"`` to a 512-bit integer and
    square it mod p to land in the QR subgroup. Deterministic across
    all clients.
    """
    seed = b"ae402:range-proof:v1:h_generator"
    x = int.from_bytes(hashlib.sha512(seed).digest(), "big")
    return pow(x, 2, _P)


_H = _derive_h()

# 64 hex chars = 32 bytes = HASH_LEN * 2.
HEX32_LEN = HASH_LEN * 2


# ══════════════════════════════════════════════════════════════════════
# Hex + hashing helpers
# ══════════════════════════════════════════════════════════════════════


def _hex(b: bytes) -> str:
    return b.hex()


def _blake2b_32(data: bytes) -> bytes:
    return hashlib.blake2b(data, digest_size=HASH_LEN).digest()


# ══════════════════════════════════════════════════════════════════════
# Pedersen commitment
# ══════════════════════════════════════════════════════════════════════


def _u64_bytes_be(n: int) -> bytes:
    if n < 0 or n >= 2**64:
        raise ValueError(f"amount out of u64 range: {n}")
    return n.to_bytes(8, "big")


@dataclass(frozen=True)
class PedersenCommitment:
    """Pedersen commitment to a u64 amount.

    ``commitment_bytes`` is the big-endian minimal-length encoding of
    ``(g^amount * h^randomness) mod p``. That's what the on-chain
    ``register_commitment`` entry point stores (hex-encoded). The
    ``randomness`` is the prover's private opening factor — keep it
    secret; publishing it lets anyone recompute the amount.
    """

    commitment_bytes: bytes
    randomness: int

    @property
    def commitment_hex(self) -> str:
        return _hex(self.commitment_bytes)

    @property
    def randomness_hash(self) -> bytes:
        """BLAKE2b-256 of the randomness's big-endian encoding.

        Published on-chain by ``open()`` as a public commitment to the
        randomness value that was used — so any observer with knowledge
        of the actual randomness can prove openings are consistent
        across multiple escrows.
        """
        rand_bytes = self.randomness.to_bytes((self.randomness.bit_length() + 7) // 8 or 1, "big")
        return _blake2b_32(rand_bytes)


def pedersen_commit(amount: int, randomness: int | None = None) -> PedersenCommitment:
    """Compute ``g^amount * h^r mod p`` with a fresh or supplied ``r``.

    Args:
        amount: Non-negative u64 amount to hide.
        randomness: Optional caller-supplied opening factor. Defaults to
            a fresh 256-bit cryptographically-random integer reduced
            mod ``q`` (subgroup order). Test suites pin this to get
            deterministic vectors.

    Raises:
        ValueError: If amount is negative or out of u64 range.
    """
    if amount < 0 or amount >= 2**64:
        raise ValueError(f"amount out of u64 range: {amount}")
    if randomness is None:
        randomness = secrets.randbelow(_Q - 1) + 1
    if randomness <= 0 or randomness >= _Q:
        raise ValueError("randomness must be in [1, q)")

    commitment_int = (pow(_G, amount, _P) * pow(_H, randomness, _P)) % _P
    # Big-endian minimal encoding — hex length may vary but is deterministic.
    commitment_bytes = commitment_int.to_bytes((commitment_int.bit_length() + 7) // 8 or 1, "big")
    return PedersenCommitment(commitment_bytes=commitment_bytes, randomness=randomness)


def verify_pedersen_opening(commitment_bytes: bytes, amount: int, randomness: int) -> bool:
    """Check ``commitment == g^amount * h^randomness mod p``."""
    if amount < 0 or amount >= 2**64:
        return False
    if randomness <= 0 or randomness >= _Q:
        return False
    expected = (pow(_G, amount, _P) * pow(_H, randomness, _P)) % _P
    actual = int.from_bytes(commitment_bytes, "big")
    return expected == actual


# ══════════════════════════════════════════════════════════════════════
# Range proof (off-chain, deterministic)
# ══════════════════════════════════════════════════════════════════════
#
# The proof itself is a compact JSON-like structure — a signed
# statement by the prover of the form:
#
#     { "domain": "ae402:range-proof:v1:proof",
#       "commitment": "<hex>",
#       "min": <int>, "max": <int>,
#       "witness_hash": "<blake2b-256 hex of (amount || randomness)>" }
#
# The proof is NOT zero-knowledge on its own — its role is to give the
# arbiter, who is *trusted* off-chain and receives the plaintext
# witness on a private channel, a canonical thing to hash and attest
# to on-chain. The hiding property comes from the Pedersen commitment;
# the range check is the arbiter's off-chain job.
#
# For a future upgrade to true ZK, replace :func:`build_range_proof`
# and :func:`verify_range_proof` with a Bulletproofs implementation
# and add a separate on-chain "verified proof" path — but keep the
# arbiter fallback for gas-budget compatibility.


@dataclass(frozen=True)
class RangeProof:
    """A deterministic, arbiter-verifiable range-proof witness."""

    commitment_hex: str
    min_amount: int
    max_amount: int
    amount: int
    randomness: int

    def to_bytes(self) -> bytes:
        """Deterministic canonical serialisation for hashing."""
        parts = [
            b"ae402:range-proof:v1:proof",
            self.commitment_hex.encode("ascii"),
            str(self.min_amount).encode("ascii"),
            str(self.max_amount).encode("ascii"),
            str(self.amount).encode("ascii"),
            str(self.randomness).encode("ascii"),
        ]
        return b":".join(parts)

    def proof_hash(self) -> bytes:
        """BLAKE2b-256 of the canonical byte encoding."""
        return _blake2b_32(self.to_bytes())


def build_range_proof(
    commitment: PedersenCommitment,
    amount: int,
    min_amount: int,
    max_amount: int,
) -> RangeProof:
    """Package the arbiter-verifiable proof of a range statement.

    The proof binds:
      * the commitment,
      * the declared range,
      * the plaintext amount and randomness (delivered privately to
        the arbiter, NOT published on-chain — only the hash is).

    Raises ``ValueError`` if the amount is out of the declared range
    or if the commitment does not open to (amount, randomness).
    """
    if min_amount > max_amount:
        raise ValueError("min_amount > max_amount")
    if amount < min_amount or amount > max_amount:
        raise ValueError(f"amount {amount} not in [{min_amount}, {max_amount}]")
    if not verify_pedersen_opening(commitment.commitment_bytes, amount, commitment.randomness):
        raise ValueError("commitment does not open to (amount, randomness)")
    return RangeProof(
        commitment_hex=commitment.commitment_hex,
        min_amount=min_amount,
        max_amount=max_amount,
        amount=amount,
        randomness=commitment.randomness,
    )


def verify_range_proof(proof: RangeProof) -> bool:
    """Deterministic off-chain proof verification.

    Returns True iff:
      * min_amount ≤ amount ≤ max_amount,
      * the commitment hex opens to (amount, randomness) under the
        canonical Pedersen group above.

    Arbiter workflow:
      1. Receive the RangeProof struct on a private channel from the
         prover.
      2. Call this function. If it returns True, call
         :func:`build_attest_preimage` + sign with your Ed25519 key,
         then submit the signature on-chain via ``attest()``.
      3. If it returns False, call :func:`build_fraud_preimage` +
         sign, submit via ``mark_fraud()`` with a reason hash of your
         choice (e.g. hash of a human-readable dispute note).
    """
    if proof.min_amount > proof.max_amount:
        return False
    if proof.amount < proof.min_amount or proof.amount > proof.max_amount:
        return False
    try:
        commitment_bytes = bytes.fromhex(proof.commitment_hex)
    except ValueError:
        return False
    return verify_pedersen_opening(commitment_bytes, proof.amount, proof.randomness)


# ══════════════════════════════════════════════════════════════════════
# Canonical preimages (byte-for-byte parity with main.rs)
# ══════════════════════════════════════════════════════════════════════


def _require_hex(name: str, value: str, exact_len: int | None = None) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be str hex, got {type(value).__name__}")
    if exact_len is not None and len(value) != exact_len:
        raise ValueError(f"{name} must be {exact_len} hex chars ({exact_len // 2} bytes), got {len(value)}")
    try:
        bytes.fromhex(value)
    except ValueError as e:  # noqa: BLE001
        raise ValueError(f"{name} is not valid hex: {e}") from e


def build_attest_preimage(
    self_package_hex: str,
    escrow_id_hex: str,
    commitment_hex: str,
    proof_hash_hex: str,
    min_amount: int,
    max_amount: int,
) -> bytes:
    """Canonical Ed25519 preimage for ``attest()``.

    Format (ASCII, single line, colon-delimited):

        ae402:range-proof:v1:attest:<pkg>:<escrow>:<commit>:<proof_hash>:<min>:<max>

    where ``<pkg>``, ``<escrow>``, ``<commit>``, ``<proof_hash>`` are
    lowercase hex without ``0x`` prefix.

    Byte-for-byte parity with ``contracts/range-proof-registry/src/main.rs``
    and ``contracts/tests/src/range_proof_registry_property_tests.rs``.
    """
    _require_hex("self_package_hex", self_package_hex)
    _require_hex("escrow_id_hex", escrow_id_hex, exact_len=HEX32_LEN)
    _require_hex("commitment_hex", commitment_hex)
    _require_hex("proof_hash_hex", proof_hash_hex, exact_len=HEX32_LEN)
    if not (0 <= min_amount < 2**64):
        raise ValueError(f"min_amount out of u64 range: {min_amount}")
    if not (0 <= max_amount < 2**64):
        raise ValueError(f"max_amount out of u64 range: {max_amount}")
    if min_amount > max_amount:
        raise ValueError("min_amount > max_amount")

    msg = (
        f"{DOMAIN}:{DOMAIN_ATTEST}:{self_package_hex}"
        f":{escrow_id_hex}:{commitment_hex}:{proof_hash_hex}"
        f":{min_amount}:{max_amount}"
    )
    return msg.encode("ascii")


def build_fraud_preimage(
    self_package_hex: str,
    escrow_id_hex: str,
    commitment_hex: str,
    proof_hash_hex: str,
    reason_hash_hex: str,
) -> bytes:
    """Canonical Ed25519 preimage for ``mark_fraud()``.

    Format:

        ae402:range-proof:v1:fraud:<pkg>:<escrow>:<commit>:<proof_hash>:<reason_hash>
    """
    _require_hex("self_package_hex", self_package_hex)
    _require_hex("escrow_id_hex", escrow_id_hex, exact_len=HEX32_LEN)
    _require_hex("commitment_hex", commitment_hex)
    _require_hex("proof_hash_hex", proof_hash_hex, exact_len=HEX32_LEN)
    _require_hex("reason_hash_hex", reason_hash_hex, exact_len=HEX32_LEN)

    msg = (
        f"{DOMAIN}:{DOMAIN_FRAUD}:{self_package_hex}"
        f":{escrow_id_hex}:{commitment_hex}:{proof_hash_hex}"
        f":{reason_hash_hex}"
    )
    return msg.encode("ascii")


# ══════════════════════════════════════════════════════════════════════
# Ed25519 sign / verify (soft dependency on `cryptography` or `nacl`)
# ══════════════════════════════════════════════════════════════════════


def sign_attest(
    signing_key_bytes: bytes,
    *,
    self_package_hex: str,
    escrow_id_hex: str,
    commitment_hex: str,
    proof_hash_hex: str,
    min_amount: int,
    max_amount: int,
) -> bytes:
    """Sign the attest preimage with an Ed25519 signing key (32-byte seed)."""
    msg = build_attest_preimage(
        self_package_hex,
        escrow_id_hex,
        commitment_hex,
        proof_hash_hex,
        min_amount,
        max_amount,
    )
    return _ed25519_sign(signing_key_bytes, msg)


def sign_fraud(
    signing_key_bytes: bytes,
    *,
    self_package_hex: str,
    escrow_id_hex: str,
    commitment_hex: str,
    proof_hash_hex: str,
    reason_hash_hex: str,
) -> bytes:
    msg = build_fraud_preimage(
        self_package_hex,
        escrow_id_hex,
        commitment_hex,
        proof_hash_hex,
        reason_hash_hex,
    )
    return _ed25519_sign(signing_key_bytes, msg)


def verify_attest(
    public_key_bytes: bytes,
    signature_bytes: bytes,
    *,
    self_package_hex: str,
    escrow_id_hex: str,
    commitment_hex: str,
    proof_hash_hex: str,
    min_amount: int,
    max_amount: int,
) -> bool:
    msg = build_attest_preimage(
        self_package_hex,
        escrow_id_hex,
        commitment_hex,
        proof_hash_hex,
        min_amount,
        max_amount,
    )
    return _ed25519_verify(public_key_bytes, signature_bytes, msg)


def verify_fraud(
    public_key_bytes: bytes,
    signature_bytes: bytes,
    *,
    self_package_hex: str,
    escrow_id_hex: str,
    commitment_hex: str,
    proof_hash_hex: str,
    reason_hash_hex: str,
) -> bool:
    msg = build_fraud_preimage(
        self_package_hex,
        escrow_id_hex,
        commitment_hex,
        proof_hash_hex,
        reason_hash_hex,
    )
    return _ed25519_verify(public_key_bytes, signature_bytes, msg)


def _ed25519_sign(seed: bytes, message: bytes) -> bytes:
    if len(seed) != 32:
        raise ValueError("Ed25519 signing seed must be 32 bytes")
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PrivateKey,
        )
    except ImportError:  # pragma: no cover
        try:
            import nacl.signing  # type: ignore
        except ImportError as e:  # pragma: no cover
            raise RuntimeError(
                "Neither `cryptography` nor `PyNaCl` is installed — " "install one to use Ed25519 sign/verify helpers."
            ) from e
        return nacl.signing.SigningKey(seed).sign(message).signature

    priv = Ed25519PrivateKey.from_private_bytes(seed)
    return priv.sign(message)


def _ed25519_verify(public_key: bytes, signature: bytes, message: bytes) -> bool:
    if len(public_key) != 32:
        return False
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PublicKey,
        )
    except ImportError:  # pragma: no cover
        try:
            import nacl.exceptions  # type: ignore
            import nacl.signing  # type: ignore
        except ImportError as e:  # pragma: no cover
            raise RuntimeError(
                "Neither `cryptography` nor `PyNaCl` is installed — " "install one to use Ed25519 sign/verify helpers."
            ) from e
        try:
            nacl.signing.VerifyKey(public_key).verify(message, signature)
            return True
        except nacl.exceptions.BadSignatureError:  # pragma: no cover
            return False

    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(signature, message)
        return True
    except InvalidSignature:
        return False


# ══════════════════════════════════════════════════════════════════════
# Full-workflow helper: prover → arbiter tuple
# ══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class RegisterBundle:
    """Everything the caller of ``register_commitment`` needs to pass in.

    Convenience wrapper — you can also build the pieces individually
    with :func:`pedersen_commit` + :func:`build_range_proof`.
    """

    escrow_id_hex: str
    commitment_hex: str
    proof_hash_hex: str
    min_amount: int
    max_amount: int
    arbiter_set_hex: tuple[str, ...]
    threshold: int
    # Kept private to the prover; never publish on-chain until open().
    randomness: int
    amount: int
    # The raw range-proof — deliver privately to arbiters for verification.
    proof: RangeProof


def build_register_bundle(
    *,
    escrow_id_hex: str,
    amount: int,
    min_amount: int,
    max_amount: int,
    arbiter_set_hex: Sequence[str],
    threshold: int,
    randomness: int | None = None,
) -> RegisterBundle:
    """One-call helper: commit + build proof + pack the ``register`` args.

    Returns a :class:`RegisterBundle` whose fields map 1:1 to the
    on-chain ``register_commitment`` entry-point named args (plus the
    private ``randomness``/``amount``/``proof`` used off-chain by
    arbiters).
    """
    _require_hex("escrow_id_hex", escrow_id_hex, exact_len=HEX32_LEN)
    if not isinstance(arbiter_set_hex, Sequence) or len(arbiter_set_hex) == 0:
        raise ValueError("arbiter_set_hex must be a non-empty sequence")
    if len(arbiter_set_hex) > MAX_ARBITERS:
        raise ValueError(f"too many arbiters: {len(arbiter_set_hex)} > {MAX_ARBITERS}")
    if threshold <= 0 or threshold > len(arbiter_set_hex):
        raise ValueError(f"threshold out of range: {threshold}")
    for i, a in enumerate(arbiter_set_hex):
        _require_hex(f"arbiter_set_hex[{i}]", a)
    if len(set(arbiter_set_hex)) != len(arbiter_set_hex):
        raise ValueError("arbiter_set_hex must have unique entries")

    commit = pedersen_commit(amount, randomness=randomness)
    proof = build_range_proof(commit, amount, min_amount, max_amount)
    proof_hash = proof.proof_hash()
    return RegisterBundle(
        escrow_id_hex=escrow_id_hex,
        commitment_hex=commit.commitment_hex,
        proof_hash_hex=_hex(proof_hash),
        min_amount=min_amount,
        max_amount=max_amount,
        arbiter_set_hex=tuple(arbiter_set_hex),
        threshold=threshold,
        randomness=commit.randomness,
        amount=amount,
        proof=proof,
    )


__all__ = [
    "DOMAIN",
    "HASH_LEN",
    "HEX32_LEN",
    "MAX_ARBITERS",
    "COMMITMENT_MAX_LEN",
    "PedersenCommitment",
    "RangeProof",
    "RegisterBundle",
    "pedersen_commit",
    "verify_pedersen_opening",
    "build_range_proof",
    "verify_range_proof",
    "build_attest_preimage",
    "build_fraud_preimage",
    "sign_attest",
    "sign_fraud",
    "verify_attest",
    "verify_fraud",
    "build_register_bundle",
]
