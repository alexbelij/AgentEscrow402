"""Local (off-chain) verification of arbiter multisig vote signatures.

Mirrors the on-chain check performed inside the `resolve()` Rust entry
point (`contracts/escrow/src/main.rs`): each arbiter's vote is a real
Ed25519 signature over a canonical message binding it to one specific
escrow and verdict, so a vote cannot be replayed for a different escrow or
forged without the arbiter's private key.

This module lets the backend reject invalid/insufficient votes fast (clear
4xx) before submitting a transaction, and lets sandbox mode enforce the
same crypto guarantee even without a real chain call. Live mode's real
authorization always comes from the contract's own on-chain verification;
this is a defense-in-depth / fast-fail convenience layer, not a
replacement for it.
"""

from __future__ import annotations

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

ED25519_TAG_HEX = "01"


def build_resolve_message(service_hash: str, in_favor_of: str) -> bytes:
    """Canonical message an arbiter signs to cast a resolve() vote.

    Must exactly match `build_resolve_message` in the Rust contract.
    """
    return f"resolve:{service_hash}:{in_favor_of}".encode("utf-8")


def build_cap_approval_message(action: str, service_hash: str) -> bytes:
    """Canonical message an arbiter signs to approve an above-cap
    release()/reveal_swap() payout (A1 hardening).

    Must exactly match `build_cap_approval_message` in the Rust contract.
    `action` is "release" or "reveal_swap".
    """
    return f"{action}:{service_hash}:cap_approval".encode("utf-8")


def build_insurance_claim_message(escrow_id: str, claimant_account_hash: str, amount: int) -> bytes:
    """Canonical message an arbiter signs to approve an insurance-pool
    `claim()` payout (A1 hardening, see `build_claim_message` in
    contracts/insurance-pool/src/main.rs). `claimant_account_hash` must be
    the raw lowercase-hex account hash (no `account-hash-` prefix) of
    whichever account will actually submit+sign the on-chain `claim()`
    deploy -- the contract binds the vote to `runtime::get_caller()`, not
    to any identity carried in the request body.
    """
    return f"claim:{escrow_id}:{claimant_account_hash}:{amount}".encode("utf-8")


def count_valid_insurance_claim_votes(
    pubkeys: list[str],
    signatures: list[str],
    registered: tuple[str, ...],
    escrow_id: str,
    claimant_account_hash: str,
    amount: int,
) -> int:
    """Same as `count_valid_votes`, but for an insurance-pool `claim()`
    payout approval message instead of an escrow resolve() verdict."""
    message = build_insurance_claim_message(escrow_id, claimant_account_hash, amount)
    return count_valid_votes_for_message(pubkeys, signatures, registered, message)


def _pubkey_from_hex(pubkey_hex: str) -> Ed25519PublicKey | None:
    if not pubkey_hex.lower().startswith(ED25519_TAG_HEX):
        return None  # only ed25519 arbiter keys are supported (secp256k1 arbiters not modeled)
    raw_hex = pubkey_hex[2:]
    try:
        raw = bytes.fromhex(raw_hex)
    except ValueError:
        return None
    if len(raw) != 32:
        return None
    try:
        return Ed25519PublicKey.from_public_bytes(raw)
    except Exception:
        return None


def _signature_bytes_from_hex(sig_hex: str) -> bytes | None:
    if not sig_hex.lower().startswith(ED25519_TAG_HEX):
        return None
    try:
        raw = bytes.fromhex(sig_hex[2:])
    except ValueError:
        return None
    if len(raw) != 64:
        return None
    return raw


def count_valid_votes(
    pubkeys: list[str],
    signatures: list[str],
    registered: tuple[str, ...],
    service_hash: str,
    in_favor_of: str,
) -> int:
    """Return how many of the submitted votes are valid, deduplicated by pubkey.

    A vote is valid iff: the pubkey is in the registered arbiter list, and
    the signature verifies against the canonical resolve message for this
    exact escrow + verdict.
    """
    message = build_resolve_message(service_hash, in_favor_of)
    return count_valid_votes_for_message(pubkeys, signatures, registered, message)


def count_valid_cap_approval_votes(
    pubkeys: list[str],
    signatures: list[str],
    registered: tuple[str, ...],
    action: str,
    service_hash: str,
) -> int:
    """Same as `count_valid_votes`, but for the A1 above-cap release()/
    reveal_swap() approval message instead of a resolve() verdict vote."""
    message = build_cap_approval_message(action, service_hash)
    return count_valid_votes_for_message(pubkeys, signatures, registered, message)


def count_valid_votes_for_message(
    pubkeys: list[str],
    signatures: list[str],
    registered: tuple[str, ...],
    message: bytes,
) -> int:
    seen: set[str] = set()
    valid = 0
    for pubkey_hex, sig_hex in zip(pubkeys, signatures):
        if pubkey_hex in seen or pubkey_hex not in registered:
            continue
        public_key = _pubkey_from_hex(pubkey_hex)
        sig_bytes = _signature_bytes_from_hex(sig_hex)
        if public_key is None or sig_bytes is None:
            continue
        try:
            public_key.verify(sig_bytes, message)
        except InvalidSignature:
            continue
        valid += 1
        seen.add(pubkey_hex)
    return valid
