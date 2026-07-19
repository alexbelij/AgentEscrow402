"""ML-KEM-768 (FIPS 203) metadata encryption for AgentEscrow402.

Uses MLKEM768 from cryptography>=43.0 + AES-256-GCM for hybrid encryption.
Per-escrow keypair: sender gets decapsulation key, metadata stays confidential on-chain.

API:
  encrypt_metadata(plaintext: str) -> EncryptedMetadata
  decrypt_metadata(payload: EncryptedMetadata, decap_key_b64: str) -> str
"""

from __future__ import annotations

import base64
import json
import logging
import os
from dataclasses import asdict, dataclass

from cryptography.hazmat.primitives.asymmetric.mlkem import MLKEM768PrivateKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

logger = logging.getLogger(__name__)

# ML-KEM-768 returns (shared_secret_32B, ciphertext_1088B) from encapsulate()
# NOTE: return order is (shared_secret, ciphertext) — NOT (ciphertext, shared_secret)


@dataclass
class EncryptedMetadata:
    """Encrypted escrow metadata bundle (safe to store on-chain or in DB)."""

    # Base64-encoded ML-KEM-768 ciphertext (1088 bytes → 1452 chars b64)
    kem_ciphertext_b64: str
    # Base64-encoded AES-256-GCM nonce (12 bytes)
    aes_nonce_b64: str
    # Base64-encoded AES-256-GCM ciphertext
    aes_ciphertext_b64: str
    # Algorithm tag for future-proofing
    algorithm: str = "MLKEM768+AES256GCM"

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, s: str) -> "EncryptedMetadata":
        return cls(**json.loads(s))


def generate_keypair() -> tuple[str, str]:
    """Generate ML-KEM-768 keypair. Returns (encap_key_b64, decap_key_b64).

    encap_key = public key  → share with anyone who can encrypt
    decap_key = private key → give ONLY to the escrow sender
    """
    priv = MLKEM768PrivateKey.generate()
    pub = priv.public_key()

    encap_key_b64 = base64.b64encode(pub.public_bytes_raw()).decode()
    decap_key_b64 = base64.b64encode(priv.private_bytes_raw()).decode()
    return encap_key_b64, decap_key_b64


def encrypt_metadata(plaintext: str, encap_key_b64: str) -> EncryptedMetadata:
    """Encrypt plaintext using ML-KEM-768 KEM + AES-256-GCM.

    Args:
        plaintext:     The metadata string to encrypt (e.g. JSON with description).
        encap_key_b64: Base64-encoded ML-KEM-768 public (encapsulation) key.

    Returns:
        EncryptedMetadata bundle.
    """
    from cryptography.hazmat.primitives.asymmetric.mlkem import MLKEM768PublicKey

    raw_pub = base64.b64decode(encap_key_b64)
    pub = MLKEM768PublicKey.from_public_bytes(raw_pub)

    # Encapsulate: shared_secret (32 bytes), kem_ciphertext (1088 bytes)
    shared_secret, kem_ciphertext = pub.encapsulate()

    # Derive 32-byte AES key directly from shared secret (already 32 bytes)
    aes_key = shared_secret
    nonce = os.urandom(12)

    aes = AESGCM(aes_key)
    ciphertext = aes.encrypt(nonce, plaintext.encode(), None)

    return EncryptedMetadata(
        kem_ciphertext_b64=base64.b64encode(kem_ciphertext).decode(),
        aes_nonce_b64=base64.b64encode(nonce).decode(),
        aes_ciphertext_b64=base64.b64encode(ciphertext).decode(),
    )


def decrypt_metadata(payload: EncryptedMetadata, decap_key_b64: str) -> str:
    """Decrypt metadata using the ML-KEM-768 private (decapsulation) key.

    Args:
        payload:       EncryptedMetadata bundle.
        decap_key_b64: Base64-encoded ML-KEM-768 private key (from generate_keypair).

    Returns:
        Decrypted plaintext string.
    """
    from cryptography.hazmat.primitives.asymmetric.mlkem import MLKEM768PrivateKey

    raw_priv = base64.b64decode(decap_key_b64)
    priv = MLKEM768PrivateKey.from_seed_bytes(raw_priv)

    kem_ciphertext = base64.b64decode(payload.kem_ciphertext_b64)
    shared_secret = priv.decapsulate(kem_ciphertext)

    aes_key = shared_secret
    nonce = base64.b64decode(payload.aes_nonce_b64)
    aes_ct = base64.b64decode(payload.aes_ciphertext_b64)

    aes = AESGCM(aes_key)
    plaintext = aes.decrypt(nonce, aes_ct, None)
    return plaintext.decode()
