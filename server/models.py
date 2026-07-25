"""Data models for AgentEscrow402."""

from __future__ import annotations

from enum import Enum

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

# AE-1: canonical wire field for value transfer is `amount_motes` (integer
# motes; 1 CSPR = 1_000_000_000 motes). Existing clients that send `amount`
# continue to work — every model below accepts both names on input via
# `validation_alias=AliasChoices("amount_motes", "amount")` and Pydantic
# `populate_by_name=True`. Python attribute stays `.amount` so ~100 call
# sites are unchanged; OpenAPI description flags `amount_motes` as the
# canonical name and `amount` as a legacy alias slated for removal in v2.
# See AE_AUDIT_REPORT_2026-07-24.md AE-1 Gap #1.
_AMOUNT_ALIAS = AliasChoices("amount_motes", "amount")
_AMOUNT_DESCRIPTION = (
    "Deposit amount in motes (1 CSPR = 1_000_000_000 motes). "
    "Canonical wire name is `amount_motes`; legacy `amount` is accepted "
    "as an input alias and will be removed in API v2."
)


class EscrowStatus(str, Enum):
    PENDING = "pending"
    RELEASED = "released"
    REFUNDED = "refunded"
    EXPIRED = "expired"
    DISPUTED = "disputed"
    RESOLVED = "resolved"
    # Backward-compatible aliases used by older batch tests / integrations.
    COMPLETED = "released"
    FAILED = "refunded"


class EscrowRequest(BaseModel):
    """Request to create a new escrow."""

    model_config = ConfigDict(populate_by_name=True)

    receiver: str = Field(
        ...,
        pattern=r"^(account-hash-)?[0-9a-fA-F]{64}$",
        description="Casper account hash of the receiver (raw 64-hex or account-hash- prefixed)",
    )
    amount: int = Field(
        ...,
        gt=0,
        validation_alias=_AMOUNT_ALIAS,
        description=_AMOUNT_DESCRIPTION,
    )
    service_hash: str = Field(..., min_length=64, max_length=64, pattern=r"^[0-9a-fA-F]{64}$")
    ttl: int = Field(default=300, ge=60, le=86400, description="Time-to-live in seconds")
    # Set when the wallet-connected caller already built, signed (via their
    # own Casper Wallet/Ledger/MetaMask through CSPR.click) and submitted a
    # session-wasm transaction that funds this escrow's deposit directly
    # from their own main purse (see `sendCreateEscrowTx` in
    # frontend/src/lib/liveTx.ts). In that case the backend does not sign
    # or submit anything itself — it only polls contract state and confirms
    # the escrow actually exists on-chain before creating hosted records.
    wallet_tx_hash: str | None = Field(default=None, min_length=1, max_length=128)
    # The connected wallet's own public key (hex) — recorded locally as
    # `sender` so the console's identity-gating (Escrows.tsx `canActOnEscrow`)
    # matches the real on-chain sender. Required whenever `wallet_tx_hash`
    # is set; ignored otherwise (identity comes from `_extract_sender`).
    sender_public_key_hex: str | None = Field(default=None, min_length=1, max_length=140)
    # W.2: opt-in confidential-amount escrow. When true, the server still
    # needs `amount` for real fund movement / insurance-fee accounting (this
    # is not on-chain amount-hiding — see docs/ZK_AMOUNT_PRIVACY.md Non-goals)
    # but the create response and all subsequent GETs redact the plaintext
    # `amount` field, exposing only a Pedersen commitment + range proof.
    # Reveal requires the caller to supply the blinding factor they hold
    # privately (POST /escrows/{service_hash}/reveal) — the server never
    # persists or logs the blinding.
    confidential: bool = Field(
        default=False,
        description=(
            "Opt-in zero-knowledge amount privacy (Tier Wow W.2). When true, "
            "amount is hidden behind a Pedersen commitment + range proof in "
            "every API response; use POST /escrows/{service_hash}/reveal with "
            "the blinding factor to disclose it."
        ),
    )


class EscrowRecord(BaseModel):
    """On-chain escrow record.

    Optional ML-KEM fields are returned by create_escrow so the console can
    prove that post-quantum metadata encryption actually ran for the demo.
    """

    sender: str
    receiver: str
    amount: int
    service_hash: str
    status: EscrowStatus
    created_at: int
    ttl: int
    deploy_hash: str | None = None
    mlkem_ciphertext: str | None = None
    mlkem_decap_key: str | None = None
    mlkem_algorithm: str | None = None
    # W.2: present only when the escrow was created with confidential=True.
    # `amount` above is redacted (set to -1, a value no real amount can take
    # since amount > 0 is enforced) in every response for such escrows —
    # the real amount lives only in the server's private store, needed for
    # actual fund movement, never returned over the wire.
    confidential: bool = False
    commitment: str | None = None
    range_proof_bits: int | None = None


class BatchEscrowItem(BaseModel):
    """A single escrow spec within a batch-create request."""

    model_config = ConfigDict(populate_by_name=True)

    receiver: str = Field(
        ...,
        pattern=r"^(account-hash-)?[0-9a-fA-F]{64}$",
        description="Casper account hash of the receiver (raw 64-hex or account-hash- prefixed)",
    )
    amount: int = Field(
        ...,
        gt=0,
        validation_alias=_AMOUNT_ALIAS,
        description=_AMOUNT_DESCRIPTION,
    )
    service_hash: str = Field(..., min_length=64, max_length=64, pattern=r"^[0-9a-fA-F]{64}$")
    ttl: int = Field(default=300, ge=60, le=86400, description="Time-to-live in seconds")


class BatchEscrowRequest(BaseModel):
    """Request to create up to 50 escrows in a single on-chain deploy via
    escrow-manager.create_batch()."""

    escrows: list[BatchEscrowItem] = Field(..., min_length=1, max_length=50)


class BatchEscrowResponse(BaseModel):
    """Result of a batch escrow creation."""

    deploy_hash: str | None = None
    created: int
    records: list[EscrowRecord]


class ReleaseRequest(BaseModel):
    service_hash: str = Field(..., min_length=64, max_length=64)
    # Set when the wallet-connected caller already built, signed (via their
    # own Casper Wallet/Ledger/MetaMask through CSPR.click) and submitted the
    # on-chain transaction directly. In that case the backend does not sign
    # or submit anything itself — it only polls contract state and confirms
    # the entry point actually executed before updating hosted records.
    wallet_tx_hash: str | None = Field(default=None, min_length=1, max_length=128)
    # A1 hardening: only required (and only checked, on-chain and here) when
    # this escrow's amount exceeds the contract's release_cap. Below cap,
    # omit both or leave as empty lists. Each pubkey/signature pair is a
    # real Ed25519 signature by a registered arbiter over
    # "release:{service_hash}:cap_approval" — see arbiter_crypto.build_cap_approval_message.
    arbiter_pubkeys: list[str] = Field(default_factory=list)
    arbiter_signatures: list[str] = Field(default_factory=list)


class RefundRequest(BaseModel):
    service_hash: str = Field(..., min_length=64, max_length=64)
    wallet_tx_hash: str | None = Field(default=None, min_length=1, max_length=128)


class DisputeRequest(BaseModel):
    service_hash: str = Field(..., min_length=64, max_length=64)
    reason_hash: str = Field(..., min_length=64, max_length=64)
    wallet_tx_hash: str | None = Field(default=None, min_length=1, max_length=128)


class ResolveRequest(BaseModel):
    service_hash: str = Field(..., min_length=64, max_length=64)
    in_favor_of: str = Field(..., pattern="^(sender|receiver)$")
    # Each arbiter casts their vote as a real Ed25519 signature (hex,
    # AsymmetricType tag-prefixed) over "resolve:{service_hash}:{in_favor_of}",
    # verified on-chain in the resolve() entry point -- not just a claimed
    # account-hash. arbiter_pubkeys[i] must correspond to arbiter_signatures[i].
    arbiter_pubkeys: list[str]
    arbiter_signatures: list[str]


class RevealAmountRequest(BaseModel):
    """W.2: disclose the plaintext amount of a confidential escrow.

    The caller must supply the blinding factor they hold privately (received
    out-of-band when the escrow was created with `confidential: true`). The
    server never persists or logs this value beyond the request lifetime of
    this call.
    """

    blinding: str = Field(
        ...,
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-fA-F]{64}$",
        description="32-byte blinding factor, hex, as returned at escrow creation.",
    )


class RevealAmountResponse(BaseModel):
    service_hash: str
    amount: int
    verified: bool


# ---------------------------------------------------------------------------
# Installer-only admin request models (configure_fee / set_release_cap /
# set_arbiters / emergency_freeze entry points)
# ---------------------------------------------------------------------------


class ConfigureFeeRequest(BaseModel):
    new_fee_bps: int = Field(..., ge=0, le=1000, description="Basis points, contract max 1000 = 10%")


class SetReleaseCapRequest(BaseModel):
    new_cap_motes: int = Field(..., gt=0, description="New A1 release cap, in motes")


class SetArbitersRequest(BaseModel):
    arbiters: list[str] = Field(
        ..., min_length=1, description="Full replacement arbiter_list — hex-encoded Ed25519 pubkeys"
    )


class ReputationRecord(BaseModel):
    agent: str
    completed: int = 0
    disputed: int = 0
    slashed: int = 0
    last_active: int = 0
    score: int = 50


class PaymentHeader(BaseModel):
    """x402 payment header parsed from Authorization."""

    version: str = "x402-v1"
    escrow_hash: str
    amount: int
    sender: str
    signature: str
    timestamp: int = 0
    nonce: str = ""


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "0.3.0"
    sandbox: bool = True
    chain: str = ""
    contract_hash: str = ""
    db: str = "disconnected"
    uptime: int = 0
    mode: str = "sandbox"  # "sandbox" | "live" — explicit mode indicator
    # Strict / fail-loud capability breakdown. Populated by
    # Config.strict_mode_capabilities(); see server/strict.py.
    # When enabled=True, every documented silent-fallback branch raises
    # StrictModeError instead of returning a mock response.
    strict_mode: dict = {}
