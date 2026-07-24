"""Offline Ed25519 verification of arbiter multisig vote signatures.

Byte-for-byte Python equivalent of ``sdk-ts/verify.ts`` and
``server/arbiter_crypto.py``. Canonical messages must match the Rust
contract's ``build_resolve_message`` / ``build_cap_approval_message`` /
``build_insurance_claim_message``.

Standalone module — no server-side dependency, safe to embed in any client
that already has the ``cryptography`` package (a transitive dep of the
SDK's Ed25519 identity path).

All ``count_valid_*`` helpers deduplicate by pubkey and only count votes
from the ``registered`` arbiter set, mirroring what the Rust contract does
on-chain.
"""

from __future__ import annotations

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

ED25519_TAG_HEX = "01"


# ---------------------------------------------------------------------------
# Canonical message builders (byte-for-byte parity with Rust contract).
# ---------------------------------------------------------------------------


def build_resolve_message(service_hash: str, in_favor_of: str) -> bytes:
    """Canonical message an arbiter signs to cast a ``resolve()`` vote."""
    return f"resolve:{service_hash}:{in_favor_of}".encode("utf-8")


def build_cap_approval_message(action: str, service_hash: str) -> bytes:
    """Canonical message an arbiter signs to approve an above-cap
    ``release()``/``reveal_swap()`` payout (A1 hardening).

    ``action`` must be ``"release"`` or ``"reveal_swap"``.
    """
    return f"{action}:{service_hash}:cap_approval".encode("utf-8")


def build_insurance_claim_message(escrow_id: str, claimant_account_hash: str, amount: int) -> bytes:
    """Canonical message an arbiter signs to approve an insurance-pool
    ``claim()`` payout (A1 hardening).

    ``claimant_account_hash`` is the raw lowercase-hex account hash of the
    caller who will submit the on-chain ``claim()`` deploy.
    """
    return f"claim:{escrow_id}:{claimant_account_hash}:{amount}".encode("utf-8")


# ---------------------------------------------------------------------------
# Internal parsers — never throw, return ``None`` on malformed input.
# ---------------------------------------------------------------------------


def _pubkey_from_hex(pubkey_hex: str) -> Ed25519PublicKey | None:
    if not pubkey_hex.lower().startswith(ED25519_TAG_HEX):
        return None
    try:
        raw = bytes.fromhex(pubkey_hex[2:])
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


# ---------------------------------------------------------------------------
# Public verification helpers.
# ---------------------------------------------------------------------------


def verify_ed25519_vote(pubkey_hex: str, sig_hex: str, message: bytes) -> bool:
    """Verify a single arbiter vote against an arbitrary message.

    Returns ``False`` for any malformed input or invalid signature.
    Never raises.
    """
    public_key = _pubkey_from_hex(pubkey_hex)
    sig_bytes = _signature_bytes_from_hex(sig_hex)
    if public_key is None or sig_bytes is None:
        return False
    try:
        public_key.verify(sig_bytes, message)
        return True
    except InvalidSignature:
        return False


def count_valid_votes_for_message(
    pubkeys: list[str],
    signatures: list[str],
    registered: tuple[str, ...] | list[str],
    message: bytes,
) -> int:
    """Count how many submitted votes are valid against ``message``.

    Deduplicates by pubkey; only counts votes from the ``registered`` set.
    """
    registered_set = set(registered)
    seen: set[str] = set()
    valid = 0
    for pubkey_hex, sig_hex in zip(pubkeys, signatures):
        if pubkey_hex in seen or pubkey_hex not in registered_set:
            continue
        if not verify_ed25519_vote(pubkey_hex, sig_hex, message):
            continue
        valid += 1
        seen.add(pubkey_hex)
    return valid


def count_valid_votes(
    pubkeys: list[str],
    signatures: list[str],
    registered: tuple[str, ...] | list[str],
    service_hash: str,
    in_favor_of: str,
) -> int:
    """Convenience wrapper: count valid resolve()-verdict votes."""
    return count_valid_votes_for_message(
        pubkeys, signatures, registered, build_resolve_message(service_hash, in_favor_of)
    )


def count_valid_cap_approval_votes(
    pubkeys: list[str],
    signatures: list[str],
    registered: tuple[str, ...] | list[str],
    action: str,
    service_hash: str,
) -> int:
    """Convenience wrapper: count valid cap-approval votes."""
    return count_valid_votes_for_message(
        pubkeys, signatures, registered, build_cap_approval_message(action, service_hash)
    )


def count_valid_insurance_claim_votes(
    pubkeys: list[str],
    signatures: list[str],
    registered: tuple[str, ...] | list[str],
    escrow_id: str,
    claimant_account_hash: str,
    amount: int,
) -> int:
    """Convenience wrapper: count valid insurance-claim votes."""
    return count_valid_votes_for_message(
        pubkeys,
        signatures,
        registered,
        build_insurance_claim_message(escrow_id, claimant_account_hash, amount),
    )


__all__ = [
    "ED25519_TAG_HEX",
    "build_resolve_message",
    "build_cap_approval_message",
    "build_insurance_claim_message",
    "verify_ed25519_vote",
    "count_valid_votes_for_message",
    "count_valid_votes",
    "count_valid_cap_approval_votes",
    "count_valid_insurance_claim_votes",
]
