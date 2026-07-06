"""Application configuration."""

from __future__ import annotations

import base64
import os
import tempfile
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    casper_node_url: str = ""
    casper_chain_name: str = "casper-test"
    nownodes_api_key: str = ""
    casper_private_key_path: str = ""
    host: str = "0.0.0.0"
    port: int = 8000
    sandbox: bool = True
    default_ttl: int = 300
    insurance_fee_bps: int = 200  # 2% = 200 basis points
    contract_hash: str = ""
    manager_contract_hash: str = ""
    insurance_contract_hash: str = ""
    # Package hash (not contract hash) of the insurance-pool contract --
    # required by the pool-funder session-wasm's `deposit()` cross-contract
    # call (runtime::call_versioned_contract needs the package, not the
    # contract, hash). See contracts/pool-funder/src/main.rs.
    insurance_package_hash: str = ""
    vrf_contract_hash: str = ""
    allow_hosted_demo_identity: bool = False
    # Hex-encoded (tag-prefixed) Ed25519 public keys of the registered
    # arbiters, mirroring the on-chain `arbiter_list`. Used to verify
    # arbiter vote signatures locally in sandbox mode (live mode relies on
    # the contract's own on-chain verification, but checking here too gives
    # callers a fast, clear 4xx instead of waiting for an on-chain revert).
    arbiter_pubkeys: tuple[str, ...] = ()
    arbiter_threshold: int = 3
    # A1 hardening: mirrors the on-chain `release_cap` default (see
    # DEFAULT_RELEASE_CAP_MOTES in contracts/escrow/src/main.rs). Used only
    # for the backend's fast-fail check in /release and /escrow/atomic-swap/
    # reveal; the contract's own on-chain value is authoritative. Keep in
    # sync if set_release_cap() is ever called to change the on-chain cap.
    release_cap_motes: int = 1_000_000_000_000
    # Shared secret required (via X-Admin-Key header) to reach the
    # installer-only admin routes (configure_fee/set_release_cap/
    # set_arbiters/emergency_freeze). Empty by default => those routes are
    # disabled (fail closed), not open, until explicitly configured.
    admin_api_key: str = ""
    # Account hash of the backend's own operator/deployer key (the account
    # that pays gas as the "spender"/relayer in the CEP-18 gasless permit
    # flow -- see CasperClient.cep18_permit/cep18_transfer_from). Derived
    # once from alexbelij_secret_key.pem via casper-js-sdk; update if the
    # operator key is ever rotated.
    casper_operator_account_hash: str = "74c96cd0073c4c973b70e7925adca8a4ba58ffcb9737304631381b82695007a8"

    @classmethod
    def from_env(cls) -> Config:
        key_path = os.getenv("CASPER_PRIVATE_KEY_PATH", "")

        # Support DEPLOYER_KEY_B64 — decode to temp file
        key_b64 = os.getenv("DEPLOYER_KEY_B64", "")
        if key_b64 and not key_path:
            raw = base64.b64decode(key_b64)
            fd, key_path = tempfile.mkstemp(suffix=".pem", prefix="deployer_")
            with os.fdopen(fd, "wb") as f:
                f.write(raw)
            os.chmod(key_path, 0o600)

        sandbox_str = os.getenv("SANDBOX", "true").lower()
        sandbox = sandbox_str == "true"

        return cls(
            casper_node_url=os.getenv("CASPER_NODE_URL", ""),
            casper_chain_name=os.getenv("CASPER_CHAIN_NAME", os.getenv("CASPER_CHAIN", "casper-test")),
            nownodes_api_key=os.getenv("NOWNODES_API_KEY", ""),
            casper_private_key_path=key_path,
            host=os.getenv("HOST", "0.0.0.0"),
            port=int(os.getenv("PORT", "8000")),
            sandbox=sandbox,
            default_ttl=int(os.getenv("DEFAULT_TTL", "300")),
            insurance_fee_bps=int(os.getenv("INSURANCE_FEE_BPS", "200")),
            contract_hash=os.getenv("ESCROW_CONTRACT_HASH", ""),
            # Deployed once, rarely redeployed; env-overridable so a future
            # redeploy of any of these never requires a frontend code change
            # (previously hardcoded in frontend/src/components/console/Contracts.tsx).
            manager_contract_hash=os.getenv(
                "MANAGER_CONTRACT_HASH",
                "bfa8c02cb3ab0f9d7bf03335f324973675200a597162e1e5fa4cb5a77dff675d",
            ),
            insurance_contract_hash=os.getenv(
                "INSURANCE_CONTRACT_HASH",
                # e128780f... is the redeployed insurance-pool contract with
                # the A1 arbiter-quorum fix on claim()/withdraw() (the old
                # e36b958d... contract had a fully public claim()/withdraw()
                # -- see contracts/insurance-pool/src/main.rs commit history).
                "e128780fd7e41159df4ca14d8584c7ef0cea2d75e6d5ba4166d94ca41f2d8929",
            ),
            insurance_package_hash=os.getenv(
                "INSURANCE_PACKAGE_HASH",
                "4458f5ed31f84314718969d5f6e8112f1589770330930c9ad37feaedb501add7",
            ),
            vrf_contract_hash=os.getenv(
                "VRF_CONTRACT_HASH",
                # 78ae2870... is the redeployed vrf-arbiter contract with the
                # register_arbiter() session-arg fix (top-level "amount" arg
                # required by the node's Mint ARG_AMOUNT spending-limit check;
                # see contracts/arbiter-registrar/src/main.rs commit history).
                # The old 5d65bedf... contract's register_arbiter() write path
                # always failed with Mint error 21 (UnapprovedSpendingAmount).
                "78ae28702deeb2eadec573d95b870f68b928a82a3566e292ff33a9ae2c779c93",
            ),
            allow_hosted_demo_identity=os.getenv("ALLOW_HOSTED_DEMO_IDENTITY", "false").lower() == "true",
            arbiter_pubkeys=tuple(
                p.strip() for p in os.getenv("ARBITER_PUBKEYS", "").split(",") if p.strip()
            ),
            arbiter_threshold=int(os.getenv("ARBITER_THRESHOLD", "3")),
            release_cap_motes=int(os.getenv("RELEASE_CAP_MOTES", "1000000000000")),
            admin_api_key=os.getenv("ADMIN_API_KEY", ""),
            casper_operator_account_hash=os.getenv(
                "CASPER_OPERATOR_ACCOUNT_HASH",
                "74c96cd0073c4c973b70e7925adca8a4ba58ffcb9737304631381b82695007a8",
            ),
        )


def get_config() -> Config:
    """Dependency injection helper for FastAPI."""
    return Config.from_env()
