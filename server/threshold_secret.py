"""Threshold secret sharing for escrow release (T3.1).

Shamir Secret Sharing (SSS) over GF(2^256-ish prime) — split a release secret
into `m` shares such that any `n` (n <= m) shares reconstruct it, but fewer
than `n` reveal nothing (information-theoretic).

Use case for AE402:
  * User creates escrow with release-secret S (a symmetric key that encrypts
    the release-authorization envelope, or is committed to on-chain).
  * S is split into shares s_1..s_m distributed to m independent arbiters /
    trustees / cold-storage nodes.
  * Release requires collecting >=n shares; server reconstructs S from any
    n shares and uses it to sign / decrypt the release action.
  * A single compromised or offline arbiter cannot block or forge release.

This module is *self-contained* — pure-Python Shamir over a 256-bit prime
(secp256k1 group order — reuse of the existing crypto choice from W.2).
No new dependencies.

Layered on top:
  * `ThresholdEscrowRelease` — helper that AEAD-encrypts a release payload
    with a random 32-byte key, then splits the key.
"""

from __future__ import annotations

import hmac
import os
import secrets
from dataclasses import dataclass
from hashlib import sha256

# Prime used for share arithmetic — secp256k1 curve order n.
# Any prime > 2^256 works; reusing the group order keeps compatibility with
# the ZK amount module and secp256k1 signatures used elsewhere.
_PRIME = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141


def _modinv(a: int, m: int) -> int:
    """Modular inverse via extended Euclidean algorithm."""
    a = a % m
    if a == 0:
        raise ZeroDivisionError("no inverse for 0")
    g, x, _ = _extended_gcd(a, m)
    if g != 1:
        raise ZeroDivisionError("no inverse")
    return x % m


def _extended_gcd(a: int, b: int) -> tuple[int, int, int]:
    if b == 0:
        return a, 1, 0
    g, x1, y1 = _extended_gcd(b, a % b)
    return g, y1, x1 - (a // b) * y1


def _eval_poly(coeffs: list[int], x: int, prime: int) -> int:
    """Horner evaluation of poly(x) mod prime."""
    acc = 0
    for c in reversed(coeffs):
        acc = (acc * x + c) % prime
    return acc


def _lagrange_interpolate_zero(shares: list[tuple[int, int]], prime: int) -> int:
    """Interpolate polynomial at x=0 given a set of (x_i, y_i) points."""
    total = 0
    k = len(shares)
    for i in range(k):
        xi, yi = shares[i]
        num = 1
        den = 1
        for j in range(k):
            if i == j:
                continue
            xj, _ = shares[j]
            num = (num * (-xj)) % prime
            den = (den * (xi - xj)) % prime
        term = (yi * num % prime) * _modinv(den, prime) % prime
        total = (total + term) % prime
    return total


@dataclass(frozen=True)
class Share:
    """One Shamir share: (index, y-value on the polynomial)."""

    index: int  # x-coordinate, 1..m
    value: int  # y-coordinate, 0..prime-1

    def to_hex(self) -> str:
        """32-byte value + 2-byte index → 68-char hex."""
        return f"{self.index:04x}{self.value:064x}"

    @classmethod
    def from_hex(cls, s: str) -> "Share":
        if len(s) != 68:
            raise ValueError(f"Share hex must be 68 chars, got {len(s)}")
        idx = int(s[:4], 16)
        val = int(s[4:], 16)
        return cls(index=idx, value=val)


def split_secret(secret: bytes, threshold: int, total_shares: int) -> list[Share]:
    """Split a 32-byte secret into `total_shares` shares; any `threshold` reconstruct.

    Args:
        secret: 32-byte secret to split.
        threshold: minimum number of shares required to reconstruct (n).
        total_shares: total number of shares to generate (m). Must be >= threshold.

    Returns:
        List of `total_shares` distinct Share objects.

    Raises:
        ValueError: on invalid parameter combinations.
    """
    if not isinstance(secret, (bytes, bytearray)):
        raise TypeError("secret must be bytes")
    if len(secret) != 32:
        raise ValueError(f"secret must be exactly 32 bytes, got {len(secret)}")
    if threshold < 2:
        raise ValueError("threshold must be >= 2 (else no protection)")
    if total_shares < threshold:
        raise ValueError(f"total_shares ({total_shares}) < threshold ({threshold})")
    if total_shares > 255:
        raise ValueError("total_shares must be <= 255 (index fits in 1 byte)")

    secret_int = int.from_bytes(secret, "big")
    if secret_int >= _PRIME:
        # extraordinarily unlikely for a random 32-byte secret, but guard
        raise ValueError("secret exceeds prime field")

    # Random polynomial: f(x) = secret + a_1*x + a_2*x^2 + ... + a_{n-1}*x^{n-1}
    coeffs = [secret_int]
    for _ in range(threshold - 1):
        coeffs.append(secrets.randbelow(_PRIME))

    shares = []
    for i in range(1, total_shares + 1):
        y = _eval_poly(coeffs, i, _PRIME)
        shares.append(Share(index=i, value=y))
    return shares


def reconstruct_secret(shares: list[Share]) -> bytes:
    """Reconstruct a 32-byte secret from >= threshold shares.

    Args:
        shares: at least `threshold` distinct shares.

    Returns:
        The original 32-byte secret.

    Raises:
        ValueError: if fewer than 2 shares, or duplicate indices.
    """
    if len(shares) < 2:
        raise ValueError("need at least 2 shares")
    indices = [s.index for s in shares]
    if len(set(indices)) != len(indices):
        raise ValueError("duplicate share indices")

    points = [(s.index, s.value) for s in shares]
    secret_int = _lagrange_interpolate_zero(points, _PRIME)
    return secret_int.to_bytes(32, "big")


# ---------- Threshold-gated escrow release payload ----------

# Simple AEAD: HKDF-derive an HMAC-SHA256 key from the reconstructed secret,
# encrypt via AES-CTR (stdlib), authenticate via HMAC. Standalone: no external
# AEAD library. This is a demo-quality primitive — for prod use `cryptography`
# AESGCM. We stay stdlib-only to avoid new deps.


def _hkdf_expand(secret: bytes, info: bytes, length: int) -> bytes:
    """RFC 5869 HKDF-Expand (SHA-256) — stdlib only."""
    okm = b""
    t = b""
    counter = 1
    while len(okm) < length:
        t = hmac.new(secret, t + info + bytes([counter]), sha256).digest()
        okm += t
        counter += 1
    return okm[:length]


def _xor_ctr(key: bytes, iv: bytes, data: bytes) -> bytes:
    """CTR-mode XOR keystream using HMAC-SHA256 as PRF. Not AES, but
    equivalent security under HMAC-SHA256 PRF assumption. Stdlib-only."""
    out = bytearray()
    counter = 0
    while len(out) < len(data):
        block = hmac.new(key, iv + counter.to_bytes(8, "big"), sha256).digest()
        out += block
        counter += 1
    return bytes(a ^ b for a, b in zip(data, out))


def encrypt_release_payload(secret: bytes, plaintext: bytes) -> bytes:
    """AEAD-encrypt a release payload with a 32-byte secret.

    Wire format: iv(16) || ciphertext || mac(32)
    """
    if len(secret) != 32:
        raise ValueError("secret must be 32 bytes")
    enc_key = _hkdf_expand(secret, b"ae402-threshold-release-enc", 32)
    mac_key = _hkdf_expand(secret, b"ae402-threshold-release-mac", 32)
    iv = os.urandom(16)
    ciphertext = _xor_ctr(enc_key, iv, plaintext)
    mac = hmac.new(mac_key, iv + ciphertext, sha256).digest()
    return iv + ciphertext + mac


def decrypt_release_payload(secret: bytes, wire: bytes) -> bytes:
    """AEAD-decrypt; raises ValueError on MAC mismatch."""
    if len(secret) != 32:
        raise ValueError("secret must be 32 bytes")
    if len(wire) < 16 + 32:
        raise ValueError("wire too short")
    iv, rest = wire[:16], wire[16:]
    ciphertext, mac = rest[:-32], rest[-32:]
    enc_key = _hkdf_expand(secret, b"ae402-threshold-release-enc", 32)
    mac_key = _hkdf_expand(secret, b"ae402-threshold-release-mac", 32)
    expected = hmac.new(mac_key, iv + ciphertext, sha256).digest()
    if not hmac.compare_digest(mac, expected):
        raise ValueError("MAC verification failed")
    return _xor_ctr(enc_key, iv, ciphertext)


# ---------- High-level convenience wrapper ----------


@dataclass
class ThresholdReleaseBundle:
    """A full threshold-gated release bundle for an escrow.

    Contains:
      * `encrypted_payload` — the AEAD ciphertext of the release authorization
      * `shares_hex` — a list of hex-encoded shares to distribute out-of-band
      * `threshold` / `total` — SSS parameters
    """

    encrypted_payload: bytes
    shares_hex: list[str]
    threshold: int
    total: int

    def collect_and_decrypt(self, share_hexes: list[str]) -> bytes:
        """Given >=threshold shares, decrypt and return the release payload."""
        if len(share_hexes) < self.threshold:
            raise ValueError(f"need {self.threshold} shares, got {len(share_hexes)}")
        shares = [Share.from_hex(h) for h in share_hexes]
        secret = reconstruct_secret(shares)
        return decrypt_release_payload(secret, self.encrypted_payload)


def build_threshold_release(payload: bytes, threshold: int, total: int) -> ThresholdReleaseBundle:
    """Build a threshold-gated release bundle for a payload.

    Convenience wrapper: generate a random 32-byte key, encrypt the payload
    under it, split the key into `total` shares with `threshold` needed.

    Args:
        payload: release authorization data (arbitrary bytes).
        threshold: shares required to reconstruct (n).
        total: total shares generated (m).
    """
    secret = os.urandom(32)
    encrypted = encrypt_release_payload(secret, payload)
    shares = split_secret(secret, threshold, total)
    return ThresholdReleaseBundle(
        encrypted_payload=encrypted,
        shares_hex=[s.to_hex() for s in shares],
        threshold=threshold,
        total=total,
    )
