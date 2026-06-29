"""Application configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Config:
    casper_node_url: str = ""
    casper_chain_name: str = "casper-test"
    casper_private_key_path: str = ""
    host: str = "0.0.0.0"
    port: int = 8000
    sandbox: bool = True
    default_ttl: int = 300
    insurance_fee_bps: int = 200
    contract_hash: str = ""

    @classmethod
    def from_env(cls) -> Config:
        return cls(
            casper_node_url=os.getenv("CASPER_NODE_URL", ""),
            casper_chain_name=os.getenv("CASPER_CHAIN_NAME", "casper-test"),
            casper_private_key_path=os.getenv("CASPER_PRIVATE_KEY_PATH", ""),
            host=os.getenv("HOST", "0.0.0.0"),
            port=int(os.getenv("PORT", "8000")),
            sandbox=os.getenv("SANDBOX", "true").lower() == "true",
            default_ttl=int(os.getenv("DEFAULT_TTL", "300")),
            insurance_fee_bps=int(os.getenv("INSURANCE_FEE_BPS", "200")),
            contract_hash=os.getenv("ESCROW_CONTRACT_HASH", ""),
        )
