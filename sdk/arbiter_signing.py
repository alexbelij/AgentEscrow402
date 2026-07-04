"""Helper for arbiters to cast a real, cryptographically-signed resolve() vote.

Each arbiter signs the canonical message `"resolve:{service_hash}:{in_favor_of}"`
with their own Ed25519 private key. The resulting (pubkey_hex, signature_hex)
pair is what `AgentEscrow402Client.resolve()` sends to the backend, which
forwards it on-chain where `casper_types::crypto::verify` checks it against
the registered `arbiter_list` -- so a vote can only be produced by someone who
actually holds an arbiter's private key, and only for that exact escrow +
verdict (no replay across escrows or flipped outcomes).
"""

from __future__ import annotations

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import load_pem_private_key

ED25519_TAG_HEX = "01"


def sign_arbiter_vote(pem_path: str, service_hash: str, in_favor_of: str) -> tuple[str, str]:
    """Sign a resolve() vote with an arbiter's PKCS8 Ed25519 PEM private key.

    Returns (pubkey_hex, signature_hex), both tag-prefixed hex strings in
    the same format the contract's `arbiter_list` and `resolve()` expect.
    """
    with open(pem_path, "rb") as f:
        private_key = load_pem_private_key(f.read(), password=None)
    if not isinstance(private_key, Ed25519PrivateKey):
        raise ValueError(f"{pem_path} is not an Ed25519 private key")

    message = f"resolve:{service_hash}:{in_favor_of}".encode("utf-8")
    signature = private_key.sign(message)
    pubkey_raw = private_key.public_key().public_bytes_raw()

    pubkey_hex = ED25519_TAG_HEX + pubkey_raw.hex()
    signature_hex = ED25519_TAG_HEX + signature.hex()
    return pubkey_hex, signature_hex
