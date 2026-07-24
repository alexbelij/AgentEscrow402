"""AgentEscrow402 SDK — Python client + offline receipt verification.

Publishable pip package. Wraps the AgentEscrow402 HTTP API with:

- ``EscrowClient`` — async client, full escrow lifecycle (create/release/refund/dispute + read).
- ``verify`` — offline Ed25519 verification of arbiter multisig vote signatures.
- ``arbiter_signing`` — canonical message builders (must byte-for-byte match the Rust contract).

See ``README.md`` for quick-start.
"""

from agentescrow402_sdk.client import EscrowClient, X402_VERSION
from agentescrow402_sdk.verify import (
    build_cap_approval_message,
    build_insurance_claim_message,
    build_resolve_message,
    verify_ed25519_vote,
)

__all__ = [
    "EscrowClient",
    "X402_VERSION",
    "build_cap_approval_message",
    "build_insurance_claim_message",
    "build_resolve_message",
    "verify_ed25519_vote",
]

__version__ = "0.1.0"
