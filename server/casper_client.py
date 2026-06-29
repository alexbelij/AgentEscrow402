"""Casper Network SDK wrapper."""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

import httpx

from server.config import Config
from server.models import EscrowRecord, EscrowStatus, ReputationRecord

logger = logging.getLogger(__name__)


class CasperClient:
    """Thin wrapper around the Casper JSON-RPC API."""

    def __init__(self, cfg: Config) -> None:
        self._node_url = cfg.casper_node_url
        self._chain = cfg.casper_chain_name
        self._contract_hash = cfg.contract_hash
        self._http = httpx.AsyncClient(timeout=30.0)

    async def _rpc(self, method: str, params: dict[str, Any] | None = None) -> Any:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params or {},
        }
        resp = await self._http.post(self._node_url + "/rpc", json=payload)
        resp.raise_for_status()
        body = resp.json()
        if "error" in body:
            raise RuntimeError(f"RPC error: {body['error']}")
        return body.get("result")

    async def get_state_root_hash(self) -> str:
        result = await self._rpc("chain_get_state_root_hash")
        return result["state_root_hash"]

    async def query_contract_dict(
        self, dict_name: str, key: str
    ) -> dict[str, Any] | None:
        try:
            srh = await self.get_state_root_hash()
            result = await self._rpc(
                "state_get_dictionary_item",
                {
                    "state_root_hash": srh,
                    "dictionary_identifier": {
                        "ContractNamedKey": {
                            "key": f"hash-{self._contract_hash}",
                            "dictionary_name": dict_name,
                            "dictionary_item_key": key,
                        }
                    },
                },
            )
            return result.get("stored_value", {}).get("CLValue", {})
        except Exception:
            logger.exception("Failed to query dict %s[%s]", dict_name, key)
            return None

    async def get_escrow(self, service_hash: str) -> EscrowRecord | None:
        raw = await self.query_contract_dict("escrows", service_hash)
        if raw is None:
            return None
        parsed = raw.get("parsed")
        if not parsed:
            return None
        return EscrowRecord(
            sender=parsed[0],
            receiver=parsed[1],
            amount=int(parsed[2]),
            service_hash=parsed[3],
            status=EscrowStatus(["pending", "released", "refunded", "expired", "disputed", "resolved"][parsed[4]]),
            created_at=parsed[5],
            ttl=parsed[6],
        )

    async def get_reputation(self, agent: str) -> ReputationRecord:
        raw = await self.query_contract_dict("reputation", agent)
        if raw is None:
            return ReputationRecord(agent=agent)
        parsed = raw.get("parsed")
        if not parsed:
            return ReputationRecord(agent=agent)
        return ReputationRecord(
            agent=agent,
            completed=parsed[0],
            disputed=parsed[1],
            slashed=parsed[2],
            last_active=parsed[3],
            score=parsed[4],
        )

    async def close(self) -> None:
        await self._http.aclose()
