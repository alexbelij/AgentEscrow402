"""W.2 — Zero-knowledge amount privacy, wired into the escrow lifecycle.

`server/zk_amount.py` implements the crypto primitive (Pedersen commitments +
bit-decomposition range proofs) as a standalone, opt-in `/zk/*` audit surface
— see `docs/ZK_AMOUNT_PRIVACY.md`. That doc's own "Future work" section
flagged the gap this module closes: the primitive was never wired into the
`/escrows/*` create/release path, so a confidential escrow could only be
demoed by calling `/zk/prove` by hand alongside a normal (fully plaintext)
escrow. This module is the bridge:

- `seal_amount()` — called from `create_escrow` when the caller opts in via
  `EscrowRequest.confidential=True`. Produces a Pedersen commitment + range
  proof bound to the escrow's `service_hash` (prevents cross-escrow proof
  replay), and returns the fields to store/return.
- `redact_amount_field()` — applied to every outbound `EscrowRecord`/dict for
  a confidential escrow so the plaintext `amount` never crosses the wire.
- `reveal()` — verifies a caller-supplied `(amount, blinding)` opens the
  stored commitment and matches the server's private ledger amount, for the
  one legitimate disclosure path (sender/receiver/auditor who already holds
  the blinding).

Threat model, scope, and non-goals are unchanged from `docs/ZK_AMOUNT_PRIVACY.md`
— this module does not add new crypto, it plumbs the existing primitive into
the existing lifecycle. Notably (still true here): the server's own private
store keeps the plaintext amount (real fund movement requires it — there is
no on-chain amount-hiding contract in this repo, see that doc's Non-goals);
what changes is that the amount now never appears in an API response for a
confidential escrow, and disclosure is a distinct, auditable, cryptographically
verified action instead of always-on.
"""

from __future__ import annotations

from typing import Any

from server.zk_amount import Commitment, RangeProof, ZKError, prove_range, verify_open, verify_range

# Wire-visible sentinel for a redacted amount. `EscrowRequest.amount` already
# enforces `gt=0`, so `-1` cannot collide with any real amount and is
# unambiguous to API consumers checking `amount < 0` before rendering.
REDACTED_AMOUNT = -1

# Default range-proof bit width for the escrow lifecycle. Deliberately
# narrower than `zk_amount.AMOUNT_BITS` (64, the standalone /zk/* default):
# proving/verifying cost is ~linear in bit count (measured ~15-25ms/bit on
# the hackathon pod — see docs/ZK_AMOUNT_PRIVACY.md perf table), and this
# path runs synchronously inside the escrow create/reveal HTTP handlers.
# 48 bits caps a confidential escrow at 2^48 motes (~281,474 CSPR at
# 1e9 motes/CSPR) — comfortably above realistic escrow sizes — while
# keeping create-with-proof latency in the ~0.7-1.1s range instead of ~1.4-2s
# at 64 bits. Callers who need the full 64-bit range can still get it via
# the standalone /zk/prove endpoint and are not forced through this path.
ESCROW_RANGE_BITS = 48


class ConfidentialEscrowError(Exception):
    """Raised when sealing or revealing a confidential escrow amount fails."""


# Private, in-process store for the range proof + blinding factor of every
# confidential escrow, keyed by service_hash. Deliberately NOT part of
# `EscrowRecord`/`SandboxStore._escrows` — those flow into API responses and
# (best-effort) Postgres, and `blinding` must never appear in either. This
# is process-local like `SandboxStore` itself (sandbox/demo mode only); a
# production build would put this behind the same access control as the
# escrow's own private ledger amount, not a plain module dict.
_confidential_ledger: dict[str, dict[str, Any]] = {}


def store_seal(service_hash: str, sealed: dict[str, Any]) -> None:
    """Persist a `seal_amount()` result (including `blinding`) for later reveal."""
    _confidential_ledger[service_hash] = dict(sealed)


def get_seal(service_hash: str) -> dict[str, Any] | None:
    """Fetch the stored seal for `service_hash`, or None if not confidential."""
    return _confidential_ledger.get(service_hash)


def clear_seal(service_hash: str) -> None:
    """Drop a stored seal (test isolation helper; not called from app.py)."""
    _confidential_ledger.pop(service_hash, None)


def seal_amount(amount: int, service_hash: str, bits: int = ESCROW_RANGE_BITS) -> dict[str, Any]:
    """Produce the commitment + range proof for a new confidential escrow.

    The `service_hash` is used verbatim as the range-proof transcript, so a
    proof generated for one escrow cannot be replayed as the proof for a
    different escrow (matches the transcript-binding convention already
    established by `zk_amount.prove_range`/`verify_range`).

    Returns a dict with `commitment` (hex), `range_proof` (JSON-safe dict),
    `range_proof_bits`, and `blinding` (hex scalar). The caller MUST persist
    `blinding` server-side (needed to answer a future `/reveal` call — the
    sender/receiver do not necessarily retain it themselves in this demo's
    trust model, where the server still custodies real funds) but MUST NEVER
    include it in an API response.

    Raises `ConfidentialEscrowError` wrapping the underlying `ZKError` on
    invalid amounts (e.g. `amount >= 2**bits`).
    """
    try:
        commitment, blinding = _commit_only(amount, bits)
        C, proof = prove_range(amount, blinding, transcript=service_hash.encode("utf-8"), bits=bits)
    except ZKError as exc:
        raise ConfidentialEscrowError(f"cannot seal amount {amount} as confidential (bits={bits}): {exc}") from exc
    return {
        "commitment": C.C,
        "range_proof": proof.to_dict(),
        "range_proof_bits": bits,
        "blinding": _encode_blinding(blinding),
    }


def _commit_only(amount: int, bits: int) -> tuple[Commitment, int]:
    from server.zk_amount import commit

    if amount < 0 or amount >= (1 << bits):
        raise ZKError(f"amount {amount} does not fit in {bits} bits (max {(1 << bits) - 1})")
    return commit(amount, blinding=None)


def _encode_blinding(blinding: int) -> str:
    return blinding.to_bytes(32, "big").hex()


def _decode_blinding(blinding_hex: str) -> int:
    try:
        return int(blinding_hex, 16)
    except ValueError as exc:
        raise ConfidentialEscrowError(f"malformed blinding hex: {exc}") from exc


def redact_amount_field(record_dict: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of `record_dict` with `amount` replaced by `REDACTED_AMOUNT`.

    No-op (returns the dict unchanged) unless `record_dict.get("confidential")`
    is true — plain escrows are never touched by this module.
    """
    if not record_dict.get("confidential"):
        return record_dict
    out = dict(record_dict)
    out["amount"] = REDACTED_AMOUNT
    return out


def reveal(
    stored_amount: int,
    blinding_hex: str,
    commitment_hex: str,
) -> dict[str, Any]:
    """Verify a caller-supplied blinding opens the stored commitment to the
    server's private ledger amount, and return the disclosed amount.

    This is the one legitimate disclosure path: the caller must already hold
    the blinding factor (received out-of-band at escrow creation, or fetched
    from the server's private store by an authorized party — this module
    does not decide *authorization*, only cryptographic *correctness*; the
    API layer is responsible for deciding who may call this).

    Raises `ConfidentialEscrowError` if the opening does not verify — this
    means either the wrong blinding was supplied, or (if it somehow matched a
    different amount) that would indicate the commitment was tampered with,
    which Pedersen's binding property makes computationally infeasible.
    """
    blinding = _decode_blinding(blinding_hex)
    commitment = Commitment(C=commitment_hex)
    try:
        opens = verify_open(commitment, stored_amount, blinding)
    except (ZKError, ValueError) as exc:
        # `Commitment(C=...)` does not validate its hex at construction —
        # `ValueError` (bad hex) or `ZKError` (wrong length / off-curve /
        # point-at-infinity) only surfaces once `verify_open` actually
        # decodes it. Both mean "not a usable commitment", same as a wrong
        # opening from this function's caller's point of view.
        raise ConfidentialEscrowError(f"malformed commitment or blinding: {exc}") from exc
    if not opens:
        raise ConfidentialEscrowError(
            "blinding does not open the stored commitment to the ledger amount — "
            "wrong blinding, or commitment/amount mismatch"
        )
    return {"amount": stored_amount, "verified": True}


def verify_seal(
    commitment_hex: str,
    range_proof_dict: dict[str, Any],
    service_hash: str,
    bits: int = ESCROW_RANGE_BITS,
) -> bool:
    """Re-verify a stored (commitment, range_proof) pair against its escrow's
    transcript. Used by tests and by an optional audit endpoint to confirm a
    persisted confidential escrow's proof is still valid (e.g. after a DB
    round-trip) without needing the private amount/blinding.
    """
    try:
        commitment = Commitment(C=commitment_hex)
        proof = RangeProof.from_dict(range_proof_dict)
        if proof.bits() != bits:
            return False
        return verify_range(commitment, proof, transcript=service_hash.encode("utf-8"))
    except (ZKError, ValueError):
        # Same rationale as reveal() above: malformed hex in `commitment_hex`
        # or any `bit_commitments` entry only raises once verify_range
        # actually decodes the points, so the try/except has to wrap that
        # call too, not just construction.
        return False
