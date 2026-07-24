"""
Two-Key Smart Account (cold/hot) — client-side helpers.

This module gives off-chain signers a deterministic, on-chain-compatible way
to build the exact byte string the ``two-key-account`` WASM contract will
verify Ed25519 signatures against, plus small helpers around the anti-replay
nonce state.

Design mirrors ``contracts/two-key-account/src/main.rs``:

* Domain prefix: ``ae402:two-key:v1``
* Signed message: ``{DOMAIN}:{action}:{contract_id}:{nonce}:{payload_hash}``
* Nonces are per-role (cold / hot), monotonic, and consumed exactly once.

Never import a Casper Ed25519 signing library into this module — the module
stays framework-agnostic and returns raw bytes so callers can plug in
``casper-client``/``pycspr``/hardware signers as they see fit.

Threat model summary — full doc: docs/TWO_KEY_ACCOUNT.md.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Callable, Literal, Protocol

DOMAIN = "ae402:two-key:v1"

Role = Literal["cold", "hot"]
Action = Literal[
    "exec",
    "rotate_hot",
    "rotate_cold",
    "freeze",
    "unfreeze",
    "set_spend_cap",
    "renounce",
]

COLD_ACTIONS: frozenset[Action] = frozenset(
    {"rotate_hot", "rotate_cold", "freeze", "unfreeze", "set_spend_cap", "renounce"}
)
HOT_ACTIONS: frozenset[Action] = frozenset({"exec"})


def _validate_action_role(action: Action, role: Role) -> None:
    if role == "cold" and action not in COLD_ACTIONS:
        raise ValueError(
            f"action {action!r} is not a cold-key action; expected one of {sorted(COLD_ACTIONS)}"
        )
    if role == "hot" and action not in HOT_ACTIONS:
        raise ValueError(
            f"action {action!r} is not a hot-key action; expected one of {sorted(HOT_ACTIONS)}"
        )


def build_signed_message(
    action: Action,
    contract_id: str,
    nonce: int,
    payload_hash: str,
    *,
    role: Role | None = None,
) -> bytes:
    """Deterministic message the contract verifies signatures against.

    Byte-for-byte identical to the ``build_signed_message`` function in
    ``contracts/two-key-account/src/main.rs`` — invariant-tested in
    ``contracts/tests/src/two_key_account_property_tests.rs``.

    Args:
        action: Entrypoint being invoked.
        contract_id: Stable identifier of the deployed account contract
            (hex-encoded contract hash). Bound into the signature so a
            valid signature on contract A cannot be replayed on B.
        nonce: The current per-role nonce as read from on-chain state.
            Must equal what the contract expects — otherwise the tx
            reverts with ``ERR_NONCE_MISMATCH``.
        payload_hash: A caller-chosen hash (e.g. sha256 of the intended
            action payload). Bound into the signature so signing one
            payload doesn't authorise another.
        role: Optional role guard. If given, raises ``ValueError`` when
            ``action`` is not one of that role's allowed actions.

    Returns:
        UTF-8 bytes; feed straight into the Ed25519 signer.
    """
    if role is not None:
        _validate_action_role(action, role)
    if nonce < 0 or nonce > 0xFFFF_FFFF_FFFF_FFFF:
        raise ValueError(f"nonce out of u64 range: {nonce}")
    if ":" in action:
        raise ValueError("action must not contain ':'")
    return f"{DOMAIN}:{action}:{contract_id}:{nonce}:{payload_hash}".encode("utf-8")


def payload_hash_of(payload: bytes) -> str:
    """SHA-256 hex digest — the recommended payload_hash construction."""
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class AccountState:
    """Snapshot of the on-chain state relevant to signing the next tx."""

    contract_id: str
    cold_pubkey_hex: str
    hot_pubkey_hex: str
    cold_nonce: int
    hot_nonce: int
    frozen: bool
    renounced: bool
    hot_spend_cap_motes: int

    def next_nonce_for(self, role: Role) -> int:
        return self.cold_nonce if role == "cold" else self.hot_nonce

    def can_exec(self) -> bool:
        return not (self.frozen or self.renounced)

    def can_admin(self) -> bool:
        return not self.renounced


class Signer(Protocol):
    def sign(self, message: bytes) -> bytes: ...


@dataclass
class SignedCall:
    action: Action
    role: Role
    pubkey_hex: str
    signature_hex: str
    nonce: int
    payload_hash: str
    contract_id: str

    def named_args(self) -> dict[str, object]:
        """Named args ready to feed into a Casper deploy builder."""
        args: dict[str, object] = {
            "contract_id": self.contract_id,
            "nonce": self.nonce,
            "payload_hash": self.payload_hash,
        }
        if self.role == "hot":
            args["hot_pubkey"] = self.pubkey_hex
            args["hot_signature"] = self.signature_hex
        else:
            args["cold_pubkey"] = self.pubkey_hex
            args["cold_signature"] = self.signature_hex
        return args


def prepare_call(
    state: AccountState,
    action: Action,
    payload: bytes,
    sign: Callable[[bytes], bytes],
    *,
    role: Role | None = None,
) -> SignedCall:
    """Assemble a ready-to-submit signed call.

    The ``sign`` callable receives the exact bytes ``build_signed_message``
    returns; whatever it returns is hex-encoded into ``signature_hex``.
    """
    inferred_role: Role
    if role is not None:
        inferred_role = role
    elif action in HOT_ACTIONS:
        inferred_role = "hot"
    else:
        inferred_role = "cold"

    if inferred_role == "hot" and not state.can_exec():
        raise RuntimeError(
            "hot-key exec disallowed: account is frozen or renounced"
        )
    if inferred_role == "cold" and not state.can_admin():
        raise RuntimeError("cold-key ops disallowed: account is renounced")

    nonce = state.next_nonce_for(inferred_role)
    ph = payload_hash_of(payload)
    msg = build_signed_message(action, state.contract_id, nonce, ph, role=inferred_role)
    signature = sign(msg)
    pubkey = state.cold_pubkey_hex if inferred_role == "cold" else state.hot_pubkey_hex
    return SignedCall(
        action=action,
        role=inferred_role,
        pubkey_hex=pubkey,
        signature_hex=signature.hex(),
        nonce=nonce,
        payload_hash=ph,
        contract_id=state.contract_id,
    )


__all__ = [
    "DOMAIN",
    "Role",
    "Action",
    "COLD_ACTIONS",
    "HOT_ACTIONS",
    "AccountState",
    "Signer",
    "SignedCall",
    "build_signed_message",
    "payload_hash_of",
    "prepare_call",
]
