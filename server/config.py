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
    allow_hosted_demo_identity: bool = False

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
            allow_hosted_demo_identity=os.getenv("ALLOW_HOSTED_DEMO_IDENTITY", "false").lower() == "true",
        )


def get_config() -> Config:
    """Dependency injection helper for FastAPI."""
    return Config.from_env()
