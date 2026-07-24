"""AgentEscrow402 SDK — Python client, LangChain tool, MCP server, offline verifier.

Publishable pip package (``pip install .`` from repo root). Wraps the
AgentEscrow402 HTTP API with:

- ``EscrowClient`` — async client with Ed25519 x402 signing, full escrow lifecycle.
- ``verify`` — offline Ed25519 verification of arbiter multisig vote signatures.
- ``arbiter_signing`` — canonical message builders (byte-for-byte matches the Rust contract).

Ships the ``ae402`` console script (see ``sdk/cli.py``).
"""

from sdk.client import X402_VERSION, EscrowClient
from sdk.verify import (
    build_cap_approval_message,
    build_insurance_claim_message,
    build_resolve_message,
    count_valid_cap_approval_votes,
    count_valid_insurance_claim_votes,
    count_valid_votes,
    verify_ed25519_vote,
)

__all__ = [
    "EscrowClient",
    "X402_VERSION",
    "build_cap_approval_message",
    "build_insurance_claim_message",
    "build_resolve_message",
    "count_valid_cap_approval_votes",
    "count_valid_insurance_claim_votes",
    "count_valid_votes",
    "verify_ed25519_vote",
]

__version__ = "0.2.0"
