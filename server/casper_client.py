"""Casper Network client for AgentEscrow402.

Uses proven casper-js-sdk scripts (Node.js subprocess) for transaction submission,
and direct JSON-RPC for read operations.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import pathlib
from typing import Any

import httpx

from server.config import Config
from server.models import EscrowRecord, EscrowStatus, ReputationRecord

logger = logging.getLogger(__name__)

# Directory containing the bundled Node.js tx scripts + wasm
_SCRIPT_DIR = pathlib.Path(__file__).parent / "casper_tx"
_CREATE_SCRIPT = _SCRIPT_DIR / "create_escrow.mjs"
_LIFECYCLE_SCRIPT = _SCRIPT_DIR / "lifecycle.mjs"
_RESOLVE_SCRIPT = _SCRIPT_DIR / "resolve.mjs"

# Status int → EscrowStatus string (matches contract STATUS_* constants)
_STATUS_MAP = {
    0: "pending",
    1: "released",
    2: "refunded",
    3: "expired",
    4: "disputed",
    5: "resolved",
}

RPC_TESTNET = "https://node.testnet.casper.network/rpc"


class CasperClient:
    """Casper 2.0 client.

    * Reads: JSON-RPC (state_get_dictionary_item).
    * Writes: subprocess to Node.js scripts (casper-js-sdk 5.0.12).
    """

    def __init__(self, cfg: Config) -> None:
        self._contract_hash = cfg.contract_hash
        self._key_path = cfg.casper_private_key_path
        self._rpc_url = RPC_TESTNET  # always use the working testnet node
        self._http = httpx.AsyncClient(timeout=30.0)

    # ── Internal helpers ───────────────────────────────────────────────────

    async def _rpc(self, method: str, params: dict[str, Any] | None = None) -> Any:
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
        resp = await self._http.post(self._rpc_url, json=payload)
        resp.raise_for_status()
        body = resp.json()
        if "error" in body:
            raise RuntimeError(f"RPC {method} error: {body['error']}")
        return body.get("result")

    async def _get_state_root_hash(self) -> str:
        """Return the latest state root hash (Casper 2.2 Version2 block format)."""
        result = await self._rpc("chain_get_block", {})
        try:
            # Casper 2.2+ returns block_with_signatures.block.Version2.header.state_root_hash
            return (
                result["block_with_signatures"]["block"]["Version2"]["header"]["state_root_hash"]
            )
        except (KeyError, TypeError):
            pass
        # Fallback: Casper 1.x / older testnet nodes
        try:
            return result["block"]["header"]["state_root_hash"]
        except (KeyError, TypeError):
            raise RuntimeError("Cannot extract state_root_hash from chain_get_block response")

    async def _run_node_script(
        self, script: pathlib.Path, env_extra: dict[str, str]
    ) -> str:
        """Run a Node.js tx script. Returns tx hash on success, raises on failure."""
        env = {**os.environ, **env_extra}
        proc = await asyncio.create_subprocess_exec(
            "node",
            str(script),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30.0)
        except asyncio.TimeoutError:
            proc.kill()
            raise RuntimeError("Node.js tx script timed out after 30 s")

        raw = stdout.decode().strip()
        if stderr:
            logger.debug("casper_tx stderr: %s", stderr.decode()[:500])

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            raise RuntimeError(f"Unexpected script output: {raw[:200]}")

        if not data.get("success"):
            raise RuntimeError(f"Casper tx failed: {data.get('error', 'unknown')}")

        return data["hash"]

    # ── Write operations (via Node.js subprocess) ──────────────────────────

    async def create_escrow(
        self,
        sender: str,
        receiver: str,
        amount: int,
        service_hash: str,
        ttl: int,
    ) -> str:
        """Submit create-escrow session-wasm tx. Returns tx hash."""
        if not self._contract_hash:
            raise RuntimeError("contract_hash not configured")
        if not self._key_path:
            raise RuntimeError("private key not configured")

        # receiver may arrive as "account-hash-{hex}" or raw 64-char hex
        receiver_hex = (
            receiver.replace("account-hash-", "") if receiver.startswith("account-hash-") else receiver
        )
        if len(receiver_hex) != 64:
            raise ValueError(f"receiver must be 64-char hex account hash, got: {receiver!r}")

        return await self._run_node_script(
            _CREATE_SCRIPT,
            {
                "CONTRACT_HASH": self._contract_hash,
                "RECEIVER_HEX": receiver_hex,
                "AMOUNT_MOTES": str(amount),
                "SERVICE_HASH": service_hash,
                "TTL_SECS": str(ttl),
                "PEM_PATH": self._key_path,
                "KEY_ALGO": "secp256k1",
                "CASPER_RPC": self._rpc_url,
                "WASM_PATH": str(_SCRIPT_DIR / "escrow_funder.wasm"),
            },
        )

    async def release(self, service_hash: str) -> str:
        return await self._lifecycle("release", service_hash)

    async def refund(self, service_hash: str) -> str:
        return await self._lifecycle("refund", service_hash)

    async def dispute(self, service_hash: str) -> str:
        return await self._lifecycle("dispute", service_hash)

    async def resolve(
        self,
        service_hash: str,
        in_favor_of: str,
        arbiter_accounts: list[str],
    ) -> str:
        """Submit `resolve` tx: 3-of-5 arbiter multisig dispute resolution.

        Any account may submit this call (the contract checks
        `arbiter_accounts` against the on-chain registered `arbiter_list`,
        not the transaction signer's identity). We sign with the configured
        deployer key by default.
        """
        if not self._contract_hash:
            raise RuntimeError("contract_hash not configured")
        if not self._key_path:
            raise RuntimeError("private key not configured")
        if in_favor_of not in ("sender", "receiver"):
            raise ValueError(f"in_favor_of must be 'sender' or 'receiver', got: {in_favor_of!r}")
        if not arbiter_accounts:
            raise ValueError("arbiter_accounts must be non-empty")

        return await self._run_node_script(
            _RESOLVE_SCRIPT,
            {
                "CONTRACT_HASH": self._contract_hash,
                "SERVICE_HASH": service_hash,
                "IN_FAVOR_OF": in_favor_of,
                "ARBITER_ACCOUNTS_JSON": json.dumps(arbiter_accounts),
                "PEM_PATH": self._key_path,
                "KEY_ALGO": "secp256k1",
                "CASPER_RPC": self._rpc_url,
            },
        )

    async def _lifecycle(self, entry_point: str, service_hash: str) -> str:
        if not self._contract_hash:
            raise RuntimeError("contract_hash not configured")
        if not self._key_path:
            raise RuntimeError("private key not configured")
        return await self._run_node_script(
            _LIFECYCLE_SCRIPT,
            {
                "CONTRACT_HASH": self._contract_hash,
                "ENTRY_POINT": entry_point,
                "SERVICE_HASH": service_hash,
                "PEM_PATH": self._key_path,
                "KEY_ALGO": "secp256k1",
                "CASPER_RPC": self._rpc_url,
            },
        )

    async def get_deploy_error(self, deploy_hash: str) -> str | None:
        """Check a submitted deploy's execution result for a contract-level
        revert (e.g. `User error: N`). Returns None if it executed
        successfully, the error string if it reverted, or None if the
        deploy hasn't been included in a finalized block yet (indistinguishable
        from "still pending" from this RPC alone -- callers should retry).
        """
        try:
            result = await self._rpc("info_get_deploy", {"deploy_hash": deploy_hash})
        except Exception:
            return None
        execution_results = result.get("execution_results") or []
        if not execution_results:
            return None
        outcome = execution_results[0].get("result", {})
        if "Failure" in outcome:
            return outcome["Failure"].get("error_message", "unknown execution failure")
        return None

    async def confirm_wallet_lifecycle_tx(
        self,
        service_hash: str,
        expected_status: str,
        *,
        attempts: int = 10,
        delay_seconds: float = 1.5,
    ) -> bool:
        """Poll on-chain contract state until it reflects a wallet-submitted
        release/refund/dispute call, or give up.

        We deliberately do NOT try to parse the deploy's execution result to
        decide success — Casper contract state is the source of truth, and
        the contract itself enforces `get_caller()` == sender/receiver for
        these entry points. If the on-chain `escrows` dict shows the expected
        status, the wallet's own signed transaction genuinely executed the
        entry point as that caller; there is nothing left to trust.
        """
        for _ in range(attempts):
            record = await self.get_escrow(service_hash)
            if record is not None and record.status.value == expected_status:
                return True
            await asyncio.sleep(delay_seconds)
        return False

    # ── Read operations (direct JSON-RPC) ─────────────────────────────────

    async def query_contract_dict(
        self, dict_name: str, key: str
    ) -> dict[str, Any] | None:
        try:
            srh = await self._get_state_root_hash()
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
        """Read escrow record from on-chain dict.

        On-chain tuple layout (EscrowRecord in main.rs):
          ((sender, receiver, amount_str), (service_hash, status_u64, created_at_u64), (ttl_u64, fee_bps_u64))
        """
        raw = await self.query_contract_dict("escrows", service_hash)
        if raw is None:
            return None
        parsed = raw.get("parsed")
        if not parsed or not isinstance(parsed, list) or len(parsed) < 3:
            return None

        try:
            inner0 = parsed[0]  # [sender, receiver, amount_str]
            inner1 = parsed[1]  # [service_hash, status_int, created_at]
            inner2 = parsed[2]  # [ttl, fee_bps]

            status_int = int(inner1[1])
            status_str = _STATUS_MAP.get(status_int, "pending")

            # created_at is stored on-chain in milliseconds; convert to seconds
            created_at_raw = int(inner1[2])
            created_at = created_at_raw // 1000 if created_at_raw > 1_000_000_000_000 else created_at_raw

            return EscrowRecord(
                sender=inner0[0],
                receiver=inner0[1],
                amount=int(inner0[2]),
                service_hash=inner1[0],
                status=EscrowStatus(status_str),
                created_at=created_at,
                ttl=int(inner2[0]),
            )
        except (IndexError, KeyError, ValueError, TypeError) as exc:
            logger.warning("get_escrow parse error: %s | parsed=%s", exc, parsed)
            return None

    async def get_reputation(self, agent: str) -> ReputationRecord:
        raw = await self.query_contract_dict("reputation", agent)
        if raw is None:
            return ReputationRecord(agent=agent)
        parsed = raw.get("parsed")
        if not parsed or not isinstance(parsed, list) or len(parsed) < 5:
            return ReputationRecord(agent=agent)
        try:
            return ReputationRecord(
                agent=agent,
                completed=int(parsed[0]),
                disputed=int(parsed[1]),
                slashed=int(parsed[2]),
                last_active=int(parsed[3]),
                score=float(parsed[4]),
            )
        except (IndexError, ValueError, TypeError):
            return ReputationRecord(agent=agent)

    async def close(self) -> None:
        await self._http.aclose()
