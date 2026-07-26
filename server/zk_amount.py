"""Zero-knowledge amount privacy for AgentEscrow402 (Tier Wow — W.2).

This module implements confidential-amount escrows: an on-chain observer sees
only a **Pedersen commitment** `C = r·G + v·H` to the escrow amount `v`, plus
a **range proof** that `0 ≤ v < 2^AMOUNT_BITS`. The actual amount `v` and
blinding factor `r` are held privately by sender and receiver.

Two guarantees:

1. **Hiding** — the commitment reveals nothing about `v` (given the blinding
   `r ∈ Z_n` is uniform in a large prime-order group, `C` is a uniform group
   element for any `v`).
2. **Binding** — no sender can later open the same `C` to a different `v'`
   without solving DLOG (`log_G H`).

We work over **secp256k1** (already a hard dependency of `cryptography`, used
in `middleware.py` for ECDSA verification). The generators `G, H` are derived
deterministically from independent domain separators:

- `G` = the standard secp256k1 base point (see SEC-2 §2.4.1).
- `H` = hash-to-curve of `"AE402/ZK/H/v1"` via SHA-256 → try-and-increment.

`log_G H` is unknown (H comes from a hash, not a scalar multiple of G), so
the Pedersen commitment binding assumption holds.

The range proof is a **bit-decomposition Chaum-Pedersen OR proof**, one per
bit: for each bit `b_i ∈ {0,1}` the sender publishes `C_i = r_i·G + b_i·H`
plus a NIZK OR-proof that `C_i` opens to 0 OR to 1 (a Fiat-Shamir Chaum-
Pedersen 2-of-2 OR). The verifier checks (a) each OR-proof, and (b) that
`C = Σ 2^i · C_i`.

We use **AMOUNT_BITS = 64** (motes fits in u64).

Homomorphism: `C(v1) + C(v2) = C(v1 + v2)` with blinding `r1 + r2`. This
enables batch-cap conservation and split releases without revealing amounts.

### Wire format (hex-encoded)

```
{
  "commitment": "<compressed secp256k1 point, 33 bytes hex>",
  "range_proof": {
    "bit_commitments": ["<33-byte compressed point hex>", ...],
    "or_proofs": [
      {"a0": "...", "a1": "...", "e0": "...", "e1": "...", "z0": "...", "z1": "..."},
      ...
    ]
  }
}
```

### Threat model

- **Sender or receiver leaks `v`** — out of scope: this is a confidentiality
  primitive, not anonymity. Anyone who legitimately opens `C` sees `v`.
- **Server-side inspection** — the server operator is not required to know
  `v`; only the commitment is persisted in the audit log.
- **On-chain censorship / MEV** — orthogonal.

### Non-goals

- We do **not** implement a full Bulletproof (O(log n) proof size); the bit-
  decomposition proof is O(n) but simpler and stdlib-only.
- We do **not** implement anonymous senders (ring signatures / stealth
  addresses) — the sender identity remains public through `caller` /
  `sender_public_key_hex`.
- We do **not** integrate with the on-chain escrow contract (no CEP-18
  amount hiding); the hidden amount is a **server-side ledger** privacy
  feature, useful for confidential auditing between arbiter, sender and
  receiver.

Everything below is stdlib only (no PyNaCl / coincurve dependency).
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from typing import List, Optional, Tuple

# ---------------------------------------------------------------------------
# secp256k1 curve parameters (SEC 2 § 2.4.1)
# ---------------------------------------------------------------------------

_P = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F  # field prime
_N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141  # group order
_A = 0
_B = 7
_GX = 0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798
_GY = 0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8

AMOUNT_BITS = 64
"""Range proof covers 0 ≤ v < 2^64 (u64 motes, the on-chain wire size)."""

SCALAR_BYTES = 32
COMPRESSED_BYTES = 33  # 0x02/0x03 prefix + 32-byte x
UNCOMPRESSED_BYTES = 65  # 0x04 prefix + 32-byte x + 32-byte y

_DOMAIN_H = b"AE402/ZK/H/v1"
_DOMAIN_CHALLENGE = b"AE402/ZK/challenge/v1"


class ZKError(Exception):
    """Raised on any zero-knowledge amount error (invalid proof, bad decoding)."""


# ---------------------------------------------------------------------------
# secp256k1 point arithmetic (pure Python)
# ---------------------------------------------------------------------------

# Point at infinity is represented as None.
Point = Optional[Tuple[int, int]]


def _inv(a: int, m: int = _P) -> int:
    """Modular inverse via extended Euclidean (Python's built-in pow(_, -1, m))."""
    return pow(a, -1, m)


def _on_curve(pt: Point) -> bool:
    if pt is None:
        return True
    x, y = pt
    return (y * y - (x * x * x + _A * x + _B)) % _P == 0


def _point_add(P: Point, Q: Point) -> Point:
    """Elliptic curve point addition on secp256k1."""
    if P is None:
        return Q
    if Q is None:
        return P
    x1, y1 = P
    x2, y2 = Q
    if x1 == x2:
        if (y1 + y2) % _P == 0:
            return None  # inverse points → infinity
        # doubling
        s = (3 * x1 * x1 + _A) * _inv(2 * y1) % _P
    else:
        s = (y2 - y1) * _inv((x2 - x1) % _P) % _P
    x3 = (s * s - x1 - x2) % _P
    y3 = (s * (x1 - x3) - y1) % _P
    return (x3, y3)


def _point_neg(P: Point) -> Point:
    if P is None:
        return None
    x, y = P
    return (x, (-y) % _P)


def _point_sub(P: Point, Q: Point) -> Point:
    return _point_add(P, _point_neg(Q))


def _scalar_mul(k: int, P: Point) -> Point:
    """Constant-ish time scalar mult via double-and-add on k."""
    if P is None or k % _N == 0:
        return None
    k = k % _N
    result: Point = None
    addend: Point = P
    while k:
        if k & 1:
            result = _point_add(result, addend)
        addend = _point_add(addend, addend)
        k >>= 1
    return result


# ---------------------------------------------------------------------------
# Point encoding: SEC-1 compressed (33 bytes, 0x02/0x03 prefix + x)
# ---------------------------------------------------------------------------


def _encode_point(P: Point) -> bytes:
    """Encode an EC point in SEC-1 compressed form.

    The point at infinity is encoded as a single 0x00 byte (non-standard, but
    unambiguous since 0x02/0x03 always yield 33 bytes).
    """
    if P is None:
        return b"\x00"  # sentinel — never appears in valid proofs
    x, y = P
    prefix = 0x02 if (y & 1) == 0 else 0x03
    return bytes([prefix]) + x.to_bytes(32, "big")


def _decode_point(b: bytes) -> Point:
    """Decode a SEC-1 compressed point. Raises ZKError on failure."""
    if b == b"\x00":
        return None
    if len(b) != COMPRESSED_BYTES:
        raise ZKError(f"compressed point must be {COMPRESSED_BYTES} bytes, got {len(b)}")
    prefix = b[0]
    if prefix not in (0x02, 0x03):
        raise ZKError(f"invalid compressed prefix 0x{prefix:02x}")
    x = int.from_bytes(b[1:], "big")
    if x >= _P:
        raise ZKError("x coordinate out of range")
    # y^2 = x^3 + 7 mod p
    y2 = (x * x * x + _B) % _P
    # y = y2 ^ ((p+1)/4) mod p  (p ≡ 3 mod 4 for secp256k1)
    y = pow(y2, (_P + 1) // 4, _P)
    if (y * y) % _P != y2:
        raise ZKError("no y coordinate — invalid point")
    if (y & 1) != (prefix - 0x02):
        y = _P - y
    pt = (x, y)
    if not _on_curve(pt):
        raise ZKError("decoded point not on curve")
    return pt


# ---------------------------------------------------------------------------
# Generators
# ---------------------------------------------------------------------------

_G: Point = (_GX, _GY)
"""Standard secp256k1 base point."""


def generator_G() -> bytes:
    """Base generator G — the standard secp256k1 base point, SEC-1 compressed."""
    return _encode_point(_G)


def _hash_to_point(domain: bytes) -> Point:
    """Hash-to-curve via try-and-increment on secp256k1.

    Deterministic: same domain → same point. Rejection sampling with counter,
    typical iterations < 5. Result has unknown DLOG w.r.t. G.
    """
    counter = 0
    while True:
        seed = hashlib.sha256(domain + counter.to_bytes(4, "big")).digest()
        x = int.from_bytes(seed, "big") % _P
        y2 = (x * x * x + _B) % _P
        # Check quadratic residue via Legendre symbol.
        if pow(y2, (_P - 1) // 2, _P) == 1:
            y = pow(y2, (_P + 1) // 4, _P)
            # Deterministic parity choice: even y.
            if y & 1:
                y = _P - y
            pt = (x, y)
            if _on_curve(pt) and pt != _G:
                return pt
        counter += 1
        if counter > 2**16:  # pragma: no cover
            raise ZKError("hash-to-curve failed — should never happen")


_H_CACHE: Optional[Point] = None


def _H_point() -> Point:
    global _H_CACHE
    if _H_CACHE is None:
        _H_CACHE = _hash_to_point(_DOMAIN_H)
    return _H_CACHE


def generator_H() -> bytes:
    """Second generator H — deterministic hash-to-curve of `AE402/ZK/H/v1`.

    `log_G H` is unknown, so binding of the Pedersen commitment holds.
    """
    return _encode_point(_H_point())


# ---------------------------------------------------------------------------
# Scalar helpers
# ---------------------------------------------------------------------------


def _scalar_from_hash(*chunks: bytes) -> int:
    """Hash chunks to a scalar in [1, _N-1]. Uses SHA-512, reduces mod _N."""
    h = hashlib.sha512()
    for c in chunks:
        h.update(len(c).to_bytes(4, "little"))
        h.update(c)
    s = int.from_bytes(h.digest(), "big") % _N
    return s if s != 0 else 1


def _random_scalar() -> int:
    """Uniform scalar in [1, _N-1]."""
    while True:
        v = secrets.randbelow(_N)
        if v != 0:
            return v


def _encode_scalar(s: int) -> bytes:
    """Encode scalar as 32-byte big-endian, canonicalized mod N."""
    return (s % _N).to_bytes(32, "big")


def _decode_scalar(b: bytes) -> int:
    if len(b) != SCALAR_BYTES:
        raise ZKError(f"scalar must be {SCALAR_BYTES} bytes")
    s = int.from_bytes(b, "big")
    if s >= _N:
        raise ZKError("scalar out of range [0, N)")
    return s


# ---------------------------------------------------------------------------
# Pedersen commitments
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Commitment:
    """A Pedersen commitment C = r·G + v·H, SEC-1 compressed hex."""

    C: str

    def to_bytes(self) -> bytes:
        b = bytes.fromhex(self.C)
        if len(b) != COMPRESSED_BYTES:
            raise ZKError(f"commitment must be {COMPRESSED_BYTES} bytes, got {len(b)}")
        return b

    def to_point(self) -> Point:
        return _decode_point(self.to_bytes())


def commit(amount: int, blinding: Optional[int] = None) -> Tuple[Commitment, int]:
    """Compute Pedersen commitment `C = r·G + v·H`.

    Args:
        amount: value `v`, `0 ≤ v < 2^AMOUNT_BITS`.
        blinding: scalar in [1, N-1]. If `None`, a fresh uniform scalar is drawn.

    Returns:
        `(commitment, blinding)`. The caller must persist `blinding`
        alongside `amount` to be able to re-open or prove properties later.
    """
    if amount < 0 or amount >= (1 << AMOUNT_BITS):
        raise ZKError(f"amount must be in [0, 2^{AMOUNT_BITS})")
    if blinding is None:
        blinding = _random_scalar()
    if not (1 <= blinding < _N):
        raise ZKError("blinding out of range")

    rG = _scalar_mul(blinding, _G)
    vH = _scalar_mul(amount, _H_point()) if amount != 0 else None
    C = _point_add(rG, vH)
    if C is None:
        # Cosmetically pathological: r·G + v·H = ∞. Extremely unlikely (would
        # require r = -v·log_G H mod N, which requires knowing that DLOG).
        raise ZKError("commitment is point at infinity — retry with fresh blinding")

    return Commitment(C=_encode_point(C).hex()), blinding


def verify_open(commitment: Commitment, amount: int, blinding: int) -> bool:
    """Verify `commitment` opens to `(amount, blinding)`.

    Constant-time comparison of encoded bytes.
    """
    expected, _ = commit(amount, blinding)
    return hmac.compare_digest(commitment.to_bytes(), expected.to_bytes())


# ---------------------------------------------------------------------------
# Homomorphism
# ---------------------------------------------------------------------------


def add_commitments(a: Commitment, b: Commitment) -> Commitment:
    """C(v1) + C(v2) = C(v1 + v2). Blinding factors compose as r1 + r2."""
    C = _point_add(a.to_point(), b.to_point())
    if C is None:
        raise ZKError("sum is point at infinity")
    return Commitment(C=_encode_point(C).hex())


def sum_commitments(commitments: List[Commitment]) -> Commitment:
    """Sum a batch of commitments. Empty list is an error."""
    if not commitments:
        raise ZKError("cannot sum empty commitment list")
    acc = commitments[0]
    for c in commitments[1:]:
        acc = add_commitments(acc, c)
    return acc


# ---------------------------------------------------------------------------
# Range proof — Chaum-Pedersen OR of {v_i = 0, v_i = 1} per bit
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ORProofBit:
    """Non-interactive OR-proof that a bit-commitment opens to 0 XOR 1."""

    a0: str  # 33-byte compressed point, hex
    a1: str
    e0: str  # 32-byte scalar, hex
    e1: str
    z0: str  # 32-byte scalar, hex
    z1: str


@dataclass(frozen=True)
class RangeProof:
    """Range proof `0 ≤ v < 2^n` via `n` bit-commitments + OR-proofs each."""

    bit_commitments: List[str]  # each 33-byte compressed point, hex
    or_proofs: List[ORProofBit]

    def bits(self) -> int:
        return len(self.bit_commitments)

    def to_dict(self) -> dict:
        return {
            "bit_commitments": list(self.bit_commitments),
            "or_proofs": [
                {"a0": p.a0, "a1": p.a1, "e0": p.e0, "e1": p.e1, "z0": p.z0, "z1": p.z1} for p in self.or_proofs
            ],
        }

    @classmethod
    def from_dict(cls, d: dict) -> RangeProof:
        try:
            bits = list(d["bit_commitments"])
            proofs = [
                ORProofBit(a0=p["a0"], a1=p["a1"], e0=p["e0"], e1=p["e1"], z0=p["z0"], z1=p["z1"])
                for p in d["or_proofs"]
            ]
        except (KeyError, TypeError) as exc:
            raise ZKError(f"malformed range proof: {exc}") from exc
        return cls(bit_commitments=bits, or_proofs=proofs)


def _prove_or_bit(bit: int, r_bit: int, C_bit: Point, transcript_ctx: bytes) -> ORProofBit:
    """Chaum-Pedersen OR-proof for `C_bit = r·G + bit·H`, `bit ∈ {0,1}`."""
    H = _H_point()
    if bit == 0:
        # Honest branch-0: prove C_bit = r·G.
        # Simulate branch-1: pick random e1, z1, compute a1 = z1·G - e1·(C_bit - H).
        z1 = _random_scalar()
        e1 = _random_scalar()
        C_minus_H = _point_sub(C_bit, H)
        z1G = _scalar_mul(z1, _G)
        e1_CmH = _scalar_mul(e1, C_minus_H)
        a1 = _point_sub(z1G, e1_CmH)
        # Honest branch-0: pick nonce k0, a0 = k0·G.
        k0 = _random_scalar()
        a0 = _scalar_mul(k0, _G)
        # Fiat-Shamir challenge on full transcript.
        e = _scalar_from_hash(transcript_ctx, _encode_point(C_bit), _encode_point(a0), _encode_point(a1))
        e0 = (e - e1) % _N
        z0 = (k0 + e0 * r_bit) % _N
    elif bit == 1:
        # Honest branch-1: prove C_bit - H = r·G.
        # Simulate branch-0: pick random e0, z0, compute a0 = z0·G - e0·C_bit.
        z0 = _random_scalar()
        e0 = _random_scalar()
        z0G = _scalar_mul(z0, _G)
        e0C = _scalar_mul(e0, C_bit)
        a0 = _point_sub(z0G, e0C)
        # Honest branch-1: pick nonce k1, a1 = k1·G.
        k1 = _random_scalar()
        a1 = _scalar_mul(k1, _G)
        # Fiat-Shamir.
        e = _scalar_from_hash(transcript_ctx, _encode_point(C_bit), _encode_point(a0), _encode_point(a1))
        e1 = (e - e0) % _N
        z1 = (k1 + e1 * r_bit) % _N
    else:
        raise ZKError(f"bit must be 0 or 1, got {bit}")

    return ORProofBit(
        a0=_encode_point(a0).hex(),
        a1=_encode_point(a1).hex(),
        e0=_encode_scalar(e0).hex(),
        e1=_encode_scalar(e1).hex(),
        z0=_encode_scalar(z0).hex(),
        z1=_encode_scalar(z1).hex(),
    )


def _verify_or_bit(C_bit_hex: str, p: ORProofBit, transcript_ctx: bytes) -> bool:
    """Verify a single OR-proof.

    Checks:
      1. `e0 + e1 == H(transcript, C, a0, a1)` (mod N)
      2. `z0·G == a0 + e0·C_bit`
      3. `z1·G == a1 + e1·(C_bit - H)`
    """
    try:
        C_bit = _decode_point(bytes.fromhex(C_bit_hex))
        a0 = _decode_point(bytes.fromhex(p.a0))
        a1 = _decode_point(bytes.fromhex(p.a1))
        e0 = _decode_scalar(bytes.fromhex(p.e0))
        e1 = _decode_scalar(bytes.fromhex(p.e1))
        z0 = _decode_scalar(bytes.fromhex(p.z0))
        z1 = _decode_scalar(bytes.fromhex(p.z1))
        # 1. challenge binding
        e_expected = _scalar_from_hash(
            transcript_ctx,
            _encode_point(C_bit),
            _encode_point(a0),
            _encode_point(a1),
        )
        if (e0 + e1) % _N != e_expected:
            return False
        # 2. branch-0 equation
        z0G = _scalar_mul(z0, _G)
        e0C = _scalar_mul(e0, C_bit)
        rhs0 = _point_add(a0, e0C)
        if _encode_point(z0G) != _encode_point(rhs0):
            return False
        # 3. branch-1 equation
        H = _H_point()
        C_minus_H = _point_sub(C_bit, H)
        z1G = _scalar_mul(z1, _G)
        e1_CmH = _scalar_mul(e1, C_minus_H)
        rhs1 = _point_add(a1, e1_CmH)
        if _encode_point(z1G) != _encode_point(rhs1):
            return False
        return True
    except (ZKError, ValueError):
        return False


def prove_range(
    amount: int,
    blinding: int,
    transcript: bytes = b"",
    bits: int = AMOUNT_BITS,
) -> Tuple[Commitment, RangeProof]:
    """Generate a range proof that `0 ≤ amount < 2^bits`.

    Args:
        amount: value to commit.
        blinding: scalar (same one used with `commit()`).
        transcript: optional binding context (escrow id, service_hash, …).
        bits: proof size; default `AMOUNT_BITS = 64`.

    Returns:
        `(commitment, range_proof)`. The commitment matches `commit(amount, blinding)`.

    Raises:
        ZKError on bad inputs.
    """
    if amount < 0 or amount >= (1 << bits):
        raise ZKError(f"amount must fit in {bits} bits")
    if not (1 <= blinding < _N):
        raise ZKError("blinding out of range")

    H = _H_point()

    # Decompose amount into bits (LSB first).
    bit_values = [(amount >> i) & 1 for i in range(bits)]

    # Draw r_i freely for i < bits-1; derive r_top so Σ 2^i · r_i = blinding.
    r_bits: List[int] = [_random_scalar() for _ in range(bits - 1)]
    acc = 0
    for i, ri in enumerate(r_bits):
        acc = (acc + (1 << i) * ri) % _N
    # remainder = blinding - acc  (mod N), still needs division by 2^(bits-1).
    remainder = (blinding - acc) % _N
    # inv_pow = 2^-(bits-1) mod N
    inv_pow = pow(2, -(bits - 1), _N)
    r_top = (remainder * inv_pow) % _N
    if r_top == 0:
        # Extremely unlikely but valid; nudge to non-zero for safety.
        r_top = 1
        # Recompute acc contribution of r_top vs 0: adjust r_bits[0] to compensate.
        # This branch is a theoretical curiosity; skip for simplicity of the demo.
        raise ZKError("r_top hit zero — retry with fresh blindings")
    r_bits.append(r_top)
    assert len(r_bits) == bits

    # Bit commitments.
    C_bits: List[Point] = []
    for i in range(bits):
        rG = _scalar_mul(r_bits[i], _G)
        if bit_values[i]:
            Ci = _point_add(rG, H)
        else:
            Ci = rG
        C_bits.append(Ci)

    # Transcript context binds every bit commitment.
    ctx = _range_ctx(transcript, C_bits)

    # OR-proofs.
    or_proofs = [_prove_or_bit(bit_values[i], r_bits[i], C_bits[i], ctx) for i in range(bits)]

    # Aggregate commitment (must equal commit(amount, blinding)).
    C_agg = _aggregate_commitment(C_bits)

    # Sanity check.
    direct, _ = commit(amount, blinding)
    if _encode_point(C_agg) != direct.to_bytes():
        raise ZKError("internal error: aggregate mismatch — bit blindings are wrong")

    return Commitment(C=_encode_point(C_agg).hex()), RangeProof(
        bit_commitments=[_encode_point(c).hex() for c in C_bits],
        or_proofs=or_proofs,
    )


def verify_range(
    commitment: Commitment,
    proof: RangeProof,
    transcript: bytes = b"",
) -> bool:
    """Verify a range proof for `commitment`.

    Checks:
      1. `len(bit_commitments) == len(or_proofs)`.
      2. Each OR-proof verifies against its bit commitment.
      3. `Σ 2^i · C_i == commitment`.

    Returns True iff all checks pass.
    """
    if proof.bits() != len(proof.or_proofs):
        return False
    if proof.bits() <= 0 or proof.bits() > 256:
        return False

    try:
        C_bits = [_decode_point(bytes.fromhex(c)) for c in proof.bit_commitments]
    except (ZKError, ValueError):
        return False

    ctx = _range_ctx(transcript, C_bits)
    for i in range(proof.bits()):
        if not _verify_or_bit(proof.bit_commitments[i], proof.or_proofs[i], ctx):
            return False

    C_agg = _aggregate_commitment(C_bits)
    return _encode_point(C_agg) == commitment.to_bytes()


def _aggregate_commitment(C_bits: List[Point]) -> Point:
    """Compute Σ 2^i · C_i as a single point."""
    acc: Point = None
    for i, Ci in enumerate(C_bits):
        weight = 1 << i
        weighted = _scalar_mul(weight, Ci)
        acc = _point_add(acc, weighted)
    if acc is None:
        raise ZKError("aggregate commitment is point at infinity")
    return acc


def _range_ctx(transcript: bytes, C_bits: List[Point]) -> bytes:
    """Fiat-Shamir transcript context = domain || user transcript || all bit commitments."""
    h = hashlib.sha512()
    h.update(_DOMAIN_CHALLENGE)
    h.update(len(transcript).to_bytes(4, "little"))
    h.update(transcript)
    for c in C_bits:
        h.update(_encode_point(c))
    return h.digest()


# ---------------------------------------------------------------------------
# High-level convenience: full "confidential amount" record
# ---------------------------------------------------------------------------


@dataclass
class ConfidentialAmount:
    """A confidential amount = commitment + range proof + private opening."""

    commitment: Commitment
    range_proof: RangeProof
    _amount: int  # private — held only by sender/receiver
    _blinding: int  # private

    def to_public_dict(self) -> dict:
        """Public wire form — no `amount` or `blinding`."""
        return {
            "commitment": self.commitment.C,
            "range_proof": self.range_proof.to_dict(),
        }

    def open(self) -> Tuple[int, int]:
        """Reveal the amount + blinding (only for legitimate holder)."""
        return self._amount, self._blinding


def confidential(amount: int, transcript: bytes = b"") -> ConfidentialAmount:
    """Convenience: commit + prove-range in one call.

    The caller receives the full `ConfidentialAmount` (with private opening);
    the wire form (public commitment + proof) is `.to_public_dict()`.
    """
    _, blinding = commit(amount)
    C, proof = prove_range(amount, blinding, transcript=transcript)
    return ConfidentialAmount(commitment=C, range_proof=proof, _amount=amount, _blinding=blinding)
