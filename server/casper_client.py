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
_CEP18_TRANSFER_SCRIPT = _SCRIPT_DIR / "cep18_transfer.mjs"
_CEP18_PERMIT_SCRIPT = _SCRIPT_DIR / "cep18_permit.mjs"
_CEP18_TRANSFER_FROM_SCRIPT = _SCRIPT_DIR / "cep18_transfer_from.mjs"
_CEP78_MINT_SCRIPT = _SCRIPT_DIR / "cep78_mint.mjs"
_CEP78_TRANSFER_SCRIPT = _SCRIPT_DIR / "cep78_transfer.mjs"
_SWAP_LIFECYCLE_SCRIPT = _SCRIPT_DIR / "swap_lifecycle.mjs"
_ADMIN_OPS_SCRIPT = _SCRIPT_DIR / "admin_ops.mjs"
_FUND_POOL_SCRIPT = _SCRIPT_DIR / "fund_pool.mjs"
_INSURANCE_CLAIM_SCRIPT = _SCRIPT_DIR / "insurance_claim.mjs"
_POOL_FUNDER_WASM = _SCRIPT_DIR / "pool_funder.wasm"

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
        self._insurance_contract_hash = cfg.insurance_contract_hash
        self._insurance_package_hash = cfg.insurance_package_hash
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

    async def release(
        self,
        service_hash: str,
        arbiter_pubkeys: list[str] | None = None,
        arbiter_signatures: list[str] | None = None,
    ) -> str:
        """Submit `release` tx.

        `arbiter_pubkeys`/`arbiter_signatures` are only required (and only
        checked on-chain) when this escrow's amount exceeds the contract's
        A1 release_cap -- see `require_arbiter_cap_approval` in
        contracts/escrow/src/main.rs. Below cap, pass None/empty lists;
        the contract accepts empty vecs there.
        """
        return await self._lifecycle(
            "release", service_hash, arbiter_pubkeys or [], arbiter_signatures or []
        )

    async def refund(self, service_hash: str) -> str:
        return await self._lifecycle("refund", service_hash)

    async def dispute(self, service_hash: str) -> str:
        return await self._lifecycle("dispute", service_hash)

    async def resolve(
        self,
        service_hash: str,
        in_favor_of: str,
        arbiter_pubkeys: list[str],
        arbiter_signatures: list[str],
    ) -> str:
        """Submit `resolve` tx: 3-of-5 arbiter multisig dispute resolution.

        Any account may submit this call -- the contract itself verifies
        each (pubkey, signature) pair on-chain via `casper_types::crypto::
        verify`, checking (a) the pubkey is a registered arbiter and (b)
        the signature is real, over the canonical message
        `"resolve:{service_hash}:{in_favor_of}"`. We sign the *transaction*
        with the configured deployer key (any submitter works), but the
        arbiter *votes* themselves must be pre-signed off-chain by the
        actual arbiters with their own keys.
        """
        if not self._contract_hash:
            raise RuntimeError("contract_hash not configured")
        if not self._key_path:
            raise RuntimeError("private key not configured")
        if in_favor_of not in ("sender", "receiver"):
            raise ValueError(f"in_favor_of must be 'sender' or 'receiver', got: {in_favor_of!r}")
        if not arbiter_pubkeys:
            raise ValueError("arbiter_pubkeys must be non-empty")
        if len(arbiter_pubkeys) != len(arbiter_signatures):
            raise ValueError("arbiter_pubkeys and arbiter_signatures must have the same length")

        return await self._run_node_script(
            _RESOLVE_SCRIPT,
            {
                "CONTRACT_HASH": self._contract_hash,
                "SERVICE_HASH": service_hash,
                "IN_FAVOR_OF": in_favor_of,
                "ARBITER_PUBKEYS_JSON": json.dumps(arbiter_pubkeys),
                "ARBITER_SIGNATURES_JSON": json.dumps(arbiter_signatures),
                "PEM_PATH": self._key_path,
                "KEY_ALGO": "secp256k1",
                "CASPER_RPC": self._rpc_url,
            },
        )

    async def _lifecycle(
        self,
        entry_point: str,
        service_hash: str,
        arbiter_pubkeys: list[str] | None = None,
        arbiter_signatures: list[str] | None = None,
    ) -> str:
        if not self._contract_hash:
            raise RuntimeError("contract_hash not configured")
        if not self._key_path:
            raise RuntimeError("private key not configured")
        env = {
            "CONTRACT_HASH": self._contract_hash,
            "ENTRY_POINT": entry_point,
            "SERVICE_HASH": service_hash,
            "PEM_PATH": self._key_path,
            "KEY_ALGO": "secp256k1",
            "CASPER_RPC": self._rpc_url,
        }
        if entry_point == "release":
            env["ARBITER_PUBKEYS_JSON"] = json.dumps(arbiter_pubkeys or [])
            env["ARBITER_SIGNATURES_JSON"] = json.dumps(arbiter_signatures or [])
        return await self._run_node_script(_LIFECYCLE_SCRIPT, env)

    async def commit_swap(self, service_hash: str, commit_hash: str) -> str:
        """Submit on-chain `commit_swap` tx (HTLC atomic-swap first step).
        The contract requires the deploy's caller to be the escrow's sender
        -- this client always signs with the configured operator key, so
        this only works correctly for escrows where that operator key *is*
        the sender (true for escrows created through this same custodial
        backend). Returns tx hash."""
        if not self._contract_hash:
            raise RuntimeError("contract_hash not configured")
        if not self._key_path:
            raise RuntimeError("private key not configured")
        return await self._run_node_script(
            _SWAP_LIFECYCLE_SCRIPT,
            {
                "CONTRACT_HASH": self._contract_hash,
                "ENTRY_POINT": "commit_swap",
                "SERVICE_HASH": service_hash,
                "COMMIT_HASH": commit_hash,
                "PEM_PATH": self._key_path,
                "KEY_ALGO": "secp256k1",
                "CASPER_RPC": self._rpc_url,
            },
        )

    async def reveal_swap(
        self,
        service_hash: str,
        preimage: str,
        arbiter_pubkeys: list[str] | None = None,
        arbiter_signatures: list[str] | None = None,
    ) -> str:
        """Submit on-chain `reveal_swap` tx (HTLC atomic-swap second step).
        The contract itself has no caller-identity check here (the HTLC
        model: knowing the preimage IS the authorization) -- a successful
        call verifies sha256(preimage) == commit_hash on-chain and directly
        releases escrowed funds to the receiver as part of the same
        transaction. Above the A1 release_cap, an arbiter quorum is also
        required (`arbiter_pubkeys`/`arbiter_signatures`) -- see
        `require_arbiter_cap_approval` in main.rs; below cap pass
        None/empty lists. Returns tx hash."""
        if not self._contract_hash:
            raise RuntimeError("contract_hash not configured")
        if not self._key_path:
            raise RuntimeError("private key not configured")
        return await self._run_node_script(
            _SWAP_LIFECYCLE_SCRIPT,
            {
                "CONTRACT_HASH": self._contract_hash,
                "ENTRY_POINT": "reveal_swap",
                "SERVICE_HASH": service_hash,
                "PREIMAGE": preimage,
                "ARBITER_PUBKEYS_JSON": json.dumps(arbiter_pubkeys or []),
                "ARBITER_SIGNATURES_JSON": json.dumps(arbiter_signatures or []),
                "PEM_PATH": self._key_path,
                "KEY_ALGO": "secp256k1",
                "CASPER_RPC": self._rpc_url,
            },
        )

    # ── Installer-only administrative operations ───────────────────────────
    # All four calls below only succeed on-chain if this client's configured
    # key is the contract's installer account (ERR_UNAUTHORIZED otherwise).
    # API-level access control lives in server/admin_api.py.

    async def configure_fee(self, new_fee_bps: int) -> str:
        """Update the insurance fee (basis points, contract-enforced max 1000 = 10%)."""
        return await self._admin_op("configure_fee", {"NEW_FEE_BPS": str(new_fee_bps)})

    async def set_release_cap(self, new_cap_motes: int) -> str:
        """Update the A1 release cap (motes) above which release()/reveal_swap()
        require arbiter-quorum cap-approval. Self-heals the release_cap named
        key into existence on first call for entities upgraded before it existed."""
        return await self._admin_op("set_release_cap", {"NEW_CAP_MOTES": str(new_cap_motes)})

    async def set_arbiters(self, arbiters: list[str]) -> str:
        """Replace the whole on-chain arbiter_list used by resolve() and the
        A1 cap-approval quorum check. Pass the full desired list, not a delta."""
        if not arbiters:
            raise ValueError("arbiters must be non-empty")
        return await self._admin_op("set_arbiters", {"ARBITERS_JSON": json.dumps(arbiters)})

    async def emergency_freeze(self) -> str:
        """Freeze escrow-contract state changes (release/refund/dispute/
        resolve/commit_swap/reveal_swap all check `require_not_frozen()`).
        Reversible via `unfreeze()` -- see below."""
        return await self._admin_op("emergency_freeze", {})

    async def unfreeze(self) -> str:
        """Resume operations after `emergency_freeze` (installer only).
        Added in commit 4a63775 -- previously freezing was one-way and
        required a full contract upgrade to resume; that limitation no
        longer applies to contracts deployed with `unfreeze` in their
        entry_points (verify via `state_get_item` if unsure which source
        version a given deployed contract_hash corresponds to)."""
        return await self._admin_op("unfreeze", {})

    async def _admin_op(self, entry_point: str, extra_env: dict[str, str]) -> str:
        if not self._contract_hash:
            raise RuntimeError("contract_hash not configured")
        if not self._key_path:
            raise RuntimeError("private key not configured")
        return await self._run_node_script(
            _ADMIN_OPS_SCRIPT,
            {
                "CONTRACT_HASH": self._contract_hash,
                "ENTRY_POINT": entry_point,
                "PEM_PATH": self._key_path,
                "KEY_ALGO": "secp256k1",
                "CASPER_RPC": self._rpc_url,
                **extra_env,
            },
        )

    async def deposit_to_insurance_pool(self, amount: int) -> str:
        """Deposit `amount` motes (from the backend operator's own account)
        into the insurance-pool contract's purse via the `pool-funder`
        session-wasm (contracts/pool-funder/src/main.rs).

        A plain deploy arg carrying a purse URef has its access rights
        stripped by the RPC layer before the contract ever sees it (the
        `deposit()` entry point would then fail with a Mint permission
        error), so this session code instead creates a fresh purse, funds
        it from the caller's own main purse (full rights in session
        context), and makes a *native* `runtime::call_versioned_contract`
        into `deposit()` -- native intra-VM calls don't strip URef rights,
        only RPC-serialized deploy args do. Live-verified end-to-end on
        testnet (see AE402 skill / commit history for deploy hashes).
        """
        if not self._insurance_package_hash:
            raise RuntimeError("insurance_package_hash not configured")
        if not self._key_path:
            raise RuntimeError("private key not configured")
        if not _POOL_FUNDER_WASM.exists():
            # Deliberately don't include the absolute sandbox filesystem path
            # in the exception message -- server/insurance.py surfaces `str(e)`
            # in its 502 response detail, and that path has no value to an API
            # caller (only to server-side logs/ops).
            logger.error("pool-funder wasm not found at %s", _POOL_FUNDER_WASM)
            raise RuntimeError("pool-funder wasm not found (deployment misconfigured)")
        return await self._run_node_script(
            _FUND_POOL_SCRIPT,
            {
                "WASM_PATH": str(_POOL_FUNDER_WASM),
                "PACKAGE_HASH": self._insurance_package_hash,
                "AMOUNT_MOTES": str(amount),
                "PEM_PATH": self._key_path,
                "KEY_ALGO": "secp256k1",
                "CASPER_RPC": self._rpc_url,
            },
        )

    async def claim_from_insurance_pool(
        self,
        escrow_id: str,
        amount: int,
        arbiter_pubkeys: list[str],
        arbiter_signatures: list[str],
        evidence: str = "",
    ) -> str:
        """Submit `claim()` against the insurance-pool contract (A1 fix:
        requires a 3-of-5 arbiter quorum, see `require_arbiter_quorum` in
        contracts/insurance-pool/src/main.rs). The backend operator key
        signs+submits the deploy and becomes the on-chain claimant/payout
        recipient -- callers must have already collected real arbiter
        votes over `"claim:{escrow_id}:{operator_account_hash}:{amount}"`
        (see `sdk/arbiter_signing.py`-style signing, or
        `server/arbiter_crypto.build_*_message` for the canonical message).
        """
        if not self._insurance_contract_hash:
            raise RuntimeError("insurance_contract_hash not configured")
        if not self._key_path:
            raise RuntimeError("private key not configured")
        if not arbiter_pubkeys or len(arbiter_pubkeys) != len(arbiter_signatures):
            raise ValueError("arbiter_pubkeys and arbiter_signatures must be non-empty and equal length")
        return await self._run_node_script(
            _INSURANCE_CLAIM_SCRIPT,
            {
                "CONTRACT_HASH": self._insurance_contract_hash,
                "ESCROW_ID": escrow_id,
                "AMOUNT_MOTES": str(amount),
                "EVIDENCE": evidence,
                "ARBITER_PUBKEYS_JSON": json.dumps(arbiter_pubkeys),
                "ARBITER_SIGNATURES_JSON": json.dumps(arbiter_signatures),
                "PEM_PATH": self._key_path,
                "KEY_ALGO": "secp256k1",
                "CASPER_RPC": self._rpc_url,
            },
        )

    async def get_deploy_error(self, deploy_hash: str) -> str | None:
        """Check a submitted deploy/transaction's execution result for a
        contract-level revert (e.g. `User error: N`). Returns None if it
        executed successfully, the error string if it reverted, or None if
        it hasn't been included in a finalized block yet (indistinguishable
        from "still pending" from this RPC alone -- callers should retry).

        CSPR.click / casper-js-sdk `ContractCallBuilder`/`SessionBuilder`
        submissions are Casper 2.0 Transactions (Version1), not legacy
        Deploys -- `info_get_deploy` returns a "No such deploy" RPC error for
        these hashes (caught below), so we try `info_get_transaction` first
        and only fall back to the legacy `info_get_deploy` shape for older
        hosted-key deploys.
        """
        try:
            result = await self._rpc(
                "info_get_transaction",
                {"transaction_hash": {"Version1": deploy_hash}},
            )
            execution_info = result.get("execution_info") or {}
            if not execution_info:
                return None
            execution_result = execution_info.get("execution_result") or {}
            outcome = execution_result.get("Version2") or execution_result.get("Version1") or {}
            return outcome.get("error_message")
        except Exception:
            pass

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
        expected_status: str | tuple[str, ...],
        *,
        deploy_hash: str | None = None,
        attempts: int = 20,
        delay_seconds: float = 2.5,
    ) -> tuple[bool, str | None]:
        """Poll on-chain contract state until it reflects a wallet-submitted
        release/refund/dispute call, or give up.

        We deliberately do NOT try to parse the deploy's execution result to
        decide *success* — Casper contract state is the source of truth, and
        the contract itself enforces `get_caller()` == sender/receiver for
        these entry points. If the on-chain `escrows` dict shows the expected
        status, the wallet's own signed transaction genuinely executed the
        entry point as that caller; there is nothing left to trust.

        On timeout (still not confirmed after all attempts), we *do* take
        one look at the deploy's own execution result purely to improve the
        error message: a deploy that reverted (e.g. "User error: N" from a
        `get_caller()` mismatch when a real wallet tries to act on an escrow
        it isn't the sender/receiver of) is a permanent failure, not a slow
        one, and the caller-facing message should say so instead of
        suggesting the user "wait and refresh".

        `expected_status` may be a single status string or a tuple of
        acceptable statuses -- e.g. `refund()` on-chain can land as either
        "refunded" (called before TTL) or "expired" (called after TTL) and
        the caller can't know in advance which branch a given wallet-signed
        call will take, so both must count as success.

        Returns (confirmed, revert_reason). `revert_reason` is only ever set
        when `confirmed` is False and we found a concrete on-chain failure.
        """
        expected_statuses = (
            (expected_status,) if isinstance(expected_status, str) else expected_status
        )
        for _ in range(attempts):
            record = await self.get_escrow(service_hash)
            if record is not None and record.status.value in expected_statuses:
                return True, None
            await asyncio.sleep(delay_seconds)

        revert_reason: str | None = None
        if deploy_hash:
            try:
                revert_reason = await self.get_deploy_error(deploy_hash)
            except Exception:
                logger.exception("Failed to check deploy execution result for %s", deploy_hash)
        return False, revert_reason

    async def confirm_wallet_created_escrow(
        self,
        service_hash: str,
        *,
        deploy_hash: str | None = None,
        attempts: int = 10,
        delay_seconds: float = 1.5,
    ) -> tuple[bool, str | None]:
        """Poll on-chain contract state until a wallet-submitted session-wasm
        create-escrow transaction (see `sendCreateEscrowTx` in
        frontend/src/lib/liveTx.ts) has actually landed, or give up.

        Mirrors `confirm_wallet_lifecycle_tx`: on-chain state is the source
        of truth (the contract itself only ever records an escrow once the
        real deposit transfer succeeded from the caller's own purse), we
        just check for existence rather than a specific status transition.
        On timeout we take one look at the deploy's own execution result to
        distinguish "still pending" from a genuine revert (e.g. the
        `InvalidAccessRights`-style purse errors this flow exists to avoid).
        """
        for _ in range(attempts):
            record = await self.get_escrow(service_hash)
            if record is not None:
                return True, None
            await asyncio.sleep(delay_seconds)

        revert_reason: str | None = None
        if deploy_hash:
            try:
                revert_reason = await self.get_deploy_error(deploy_hash)
            except Exception:
                logger.exception("Failed to check deploy execution result for %s", deploy_hash)
        return False, revert_reason

    async def confirm_wallet_insurance_claim(
        self,
        claimant_account_hash: str,
        escrow_id: str,
        *,
        deploy_hash: str | None = None,
        attempts: int = 20,
        delay_seconds: float = 2.5,
    ) -> tuple[bool, str | None]:
        """Poll the insurance-pool contract's `claims` dict until it shows a
        wallet-submitted `claim()` call for this claimant/escrow_id, or give
        up. Mirrors `confirm_wallet_lifecycle_tx` -- on-chain state (not the
        deploy's own execution result) is the source of truth, since the
        contract's `claim()` entry point pays out to `runtime::get_caller()`
        directly; if the dict shows `last_escrow_id == escrow_id` for this
        claimant's account hash, the wallet's own signed transaction genuinely
        executed and was paid.

        `claimant_account_hash` may be passed either as raw 64-char hex or
        `account-hash-{hex}` -- the on-chain dict is keyed by the Rust
        `AccountHash`'s `Display`/`to_string()` impl, which is plain lowercase
        hex with **no** `account-hash-` prefix (that prefix only comes from
        `to_formatted_string()`, which this contract does not use), so any
        prefix is stripped here before querying.
        """
        if not self._insurance_contract_hash:
            return False, "insurance contract hash not configured"
        dict_key = claimant_account_hash.replace("account-hash-", "")
        for _ in range(attempts):
            raw = await self.query_contract_dict(
                "claims", dict_key, contract_hash=self._insurance_contract_hash
            )
            parsed = raw.get("parsed") if raw else None
            if parsed and isinstance(parsed, list) and len(parsed) >= 3:
                last_escrow_id = parsed[2]
                if last_escrow_id == escrow_id:
                    return True, None
            await asyncio.sleep(delay_seconds)

        revert_reason: str | None = None
        if deploy_hash:
            try:
                revert_reason = await self.get_deploy_error(deploy_hash)
            except Exception:
                logger.exception("Failed to check deploy execution result for %s", deploy_hash)
        return False, revert_reason

    # ── Read operations (direct JSON-RPC) ─────────────────────────────────

    async def query_contract_dict(
        self, dict_name: str, key: str, contract_hash: str | None = None
    ) -> dict[str, Any] | None:
        """Read one dictionary entry from a deployed contract.

        `contract_hash` defaults to this client's own escrow contract
        (`self._contract_hash`) for backwards compatibility, but callers
        querying a *different* deployed contract (e.g. the vrf-arbiter
        contract) must pass its hash explicitly -- silently defaulting to
        the escrow contract here previously caused `vrf_election.py` to
        query the wrong contract entirely (see
        skills/projects/ae402_hackathon for the writeup).
        """
        target_hash = contract_hash or self._contract_hash
        try:
            srh = await self._get_state_root_hash()
            result = await self._rpc(
                "state_get_dictionary_item",
                {
                    "state_root_hash": srh,
                    "dictionary_identifier": {
                        "ContractNamedKey": {
                            "key": f"hash-{target_hash}",
                            "dictionary_name": dict_name,
                            "dictionary_item_key": key,
                        }
                    },
                },
            )
            return result.get("stored_value", {}).get("CLValue", {})
        except Exception:
            logger.exception("Failed to query dict %s[%s] on contract %s", dict_name, key, target_hash)
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

    # ── CEP-18 token operations ────────────────────────────────────────────
    #
    # Real on-chain CEP-18 support (B1). Uses the same "Node.js subprocess
    # for writes, direct JSON-RPC for reads" split as the rest of this
    # client. `contract_hash` here is the *token's* contract hash (distinct
    # from `self._contract_hash`, which is always the escrow contract) --
    # every multi-asset escrow can reference a different CEP-18 token.
    #
    # Custodial-demo model: like create_escrow()/_lifecycle(), the actual
    # on-chain call is always signed by this client's configured operator
    # key (self._key_path). The x402 `sender` field is the logical payer
    # whose signed x402 header authorized the payment off-chain; the
    # operator key is the funded account that actually holds/moves the
    # AE402 demo token on testnet. This mirrors how CSPR escrow funding
    # already works in create_escrow().

    async def cep18_transfer(self, contract_hash: str, recipient_hex: str, amount: int) -> str:
        """Call the CEP-18 `transfer` entry point. Returns tx hash."""
        if not self._key_path:
            raise RuntimeError("private key not configured")
        recipient_hex = (
            recipient_hex.replace("account-hash-", "")
            if recipient_hex.startswith("account-hash-")
            else recipient_hex
        )
        if len(recipient_hex) != 64:
            raise ValueError(f"recipient must be 64-char hex account hash, got: {recipient_hex!r}")

        return await self._run_node_script(
            _CEP18_TRANSFER_SCRIPT,
            {
                "CONTRACT_HASH": contract_hash,
                "RECIPIENT_HEX": recipient_hex,
                "AMOUNT": str(amount),
                "PEM_PATH": self._key_path,
                "KEY_ALGO": "secp256k1",
                "CASPER_RPC": self._rpc_url,
            },
        )

    async def _get_cep18_named_keys(self, contract_hash: str) -> dict[str, str]:
        """Named keys of a CEP-18 contract entity (uref-per-field storage:
        name/symbol/decimals/total_supply are plain urefs, balances/
        allowances are dictionary seed-urefs). Cached per contract_hash for
        the lifetime of this client instance."""
        cache = getattr(self, "_cep18_named_keys_cache", None)
        if cache is None:
            cache = {}
            self._cep18_named_keys_cache = cache
        if contract_hash in cache:
            return cache[contract_hash]
        result = await self._rpc(
            "state_get_entity",
            {"entity_identifier": {"ContractHash": f"contract-{contract_hash}"}},
        )
        named_keys = result["entity"]["Contract"]["contract"]["named_keys"]
        parsed = {nk["name"]: nk["key"] for nk in named_keys}
        cache[contract_hash] = parsed
        return parsed

    async def get_cep18_balance(self, contract_hash: str, account_hash_hex: str) -> int:
        """Real on-chain CEP-18 balance for an account, via the contract's
        `balances` dictionary (dictionary_item_key = base64(0x00 + account
        hash bytes), matching casper-ecosystem/cep18's own client-js
        `balanceOf` implementation)."""
        import base64

        account_hash_hex = (
            account_hash_hex.replace("account-hash-", "")
            if account_hash_hex.startswith("account-hash-")
            else account_hash_hex
        )
        named_keys = await self._get_cep18_named_keys(contract_hash)
        balances_uref = named_keys.get("balances")
        if not balances_uref:
            raise RuntimeError(f"contract {contract_hash} has no 'balances' named key")

        key_bytes = bytes([0]) + bytes.fromhex(account_hash_hex)
        dictionary_item_key = base64.b64encode(key_bytes).decode()

        srh = await self._get_state_root_hash()
        try:
            result = await self._rpc(
                "state_get_dictionary_item",
                {
                    "state_root_hash": srh,
                    "dictionary_identifier": {
                        "URef": {
                            "seed_uref": balances_uref,
                            "dictionary_item_key": dictionary_item_key,
                        }
                    },
                },
            )
        except RuntimeError:
            # No entry yet for this account => balance 0 (same as CEP-18's
            # own reference client: absence of a dict entry means zero).
            return 0
        parsed = result.get("stored_value", {}).get("CLValue", {}).get("parsed")
        return int(parsed) if parsed is not None else 0

    # ── CEP-2612-inspired gasless permit (AE402 fork extension) ────────────
    #
    # Unlike cep18_transfer() above (custodial: moves the *operator's own*
    # balance), this pair actually moves tokens out of the real token
    # owner's (the connected wallet's) own balance -- the owner only signs
    # a canonical off-chain message (see server/casper_tx/cep18_permit.mjs
    # docstring for the exact message layout, must match the frontend
    # signer + the Rust contract's `permit()` byte-for-byte), then this
    # client (as the relayer) submits + pays gas for both permit() (grants
    # the allowance, signature-gated) and transfer_from() (pulls the funds
    # using that allowance) -- the owner never has to submit a transaction,
    # pay gas, or hand over their private key.

    async def get_cep18_permit_nonce(self, contract_hash: str, owner_account_hash_hex: str) -> int:
        """Reads the next expected permit nonce for `owner` directly from
        the contract's `permit_nonces` dictionary (no tx needed). 0 if
        `permit()` has never succeeded for this owner (dictionary entry,
        or the dictionary itself, may not exist yet)."""
        owner_account_hash_hex = (
            owner_account_hash_hex.replace("account-hash-", "")
            if owner_account_hash_hex.startswith("account-hash-")
            else owner_account_hash_hex
        )
        named_keys = await self._get_cep18_named_keys(contract_hash)
        nonces_uref = named_keys.get("permit_nonces")
        if not nonces_uref:
            return 0
        owner_bytes = bytes([0]) + bytes.fromhex(owner_account_hash_hex)
        # Must match Rust's `make_dictionary_item_key(&owner, &owner)`:
        # blake2b-256(owner_bytes ++ owner_bytes), hex-encoded.
        import hashlib

        dictionary_item_key = hashlib.blake2b(owner_bytes + owner_bytes, digest_size=32).hexdigest()
        srh = await self._get_state_root_hash()
        try:
            result = await self._rpc(
                "state_get_dictionary_item",
                {
                    "state_root_hash": srh,
                    "dictionary_identifier": {
                        "URef": {
                            "seed_uref": nonces_uref,
                            "dictionary_item_key": dictionary_item_key,
                        }
                    },
                },
            )
        except RuntimeError:
            return 0
        parsed = result.get("stored_value", {}).get("CLValue", {}).get("parsed")
        return int(parsed) if parsed is not None else 0

    async def cep18_permit(
        self,
        contract_hash: str,
        owner_account_hash_hex: str,
        owner_public_key_hex: str,
        spender_account_hash_hex: str,
        amount: int,
        deadline_ms: int,
        signature_hex: str,
    ) -> str:
        """Submits (and pays gas for) the owner-signed `permit()` call.
        Reverts on-chain (raises here) if the signature doesn't match, the
        deadline has passed, or the public key doesn't hash to `owner`."""
        if not self._key_path:
            raise RuntimeError("private key not configured")
        return await self._run_node_script(
            _CEP18_PERMIT_SCRIPT,
            {
                "CONTRACT_HASH": contract_hash,
                "OWNER_ACCOUNT_HASH": owner_account_hash_hex.replace("account-hash-", ""),
                "OWNER_PUBLIC_KEY": owner_public_key_hex,
                "SPENDER_ACCOUNT_HASH": spender_account_hash_hex.replace("account-hash-", ""),
                "AMOUNT": str(amount),
                "DEADLINE": str(deadline_ms),
                "SIGNATURE": signature_hex,
                "PEM_PATH": self._key_path,
                "KEY_ALGO": "secp256k1",
                "CASPER_RPC": self._rpc_url,
            },
        )

    async def cep18_transfer_from(
        self,
        contract_hash: str,
        owner_account_hash_hex: str,
        recipient_account_hash_hex: str,
        amount: int,
    ) -> str:
        """Pulls `amount` from `owner`'s balance into `recipient`, using an
        allowance previously granted (e.g. by cep18_permit() above). Must
        be submitted by the account that holds that allowance as spender
        (here: this client's own operator key, the relayer)."""
        if not self._key_path:
            raise RuntimeError("private key not configured")
        return await self._run_node_script(
            _CEP18_TRANSFER_FROM_SCRIPT,
            {
                "CONTRACT_HASH": contract_hash,
                "OWNER_ACCOUNT_HASH": owner_account_hash_hex.replace("account-hash-", ""),
                "RECIPIENT_ACCOUNT_HASH": recipient_account_hash_hex.replace("account-hash-", ""),
                "AMOUNT": str(amount),
                "PEM_PATH": self._key_path,
                "KEY_ALGO": "secp256k1",
                "CASPER_RPC": self._rpc_url,
            },
        )

    async def get_cep18_token_info(self, contract_hash: str) -> dict[str, Any]:
        """Real on-chain CEP-18 token metadata (name/symbol/decimals)."""
        named_keys = await self._get_cep18_named_keys(contract_hash)
        info: dict[str, Any] = {"symbol": None, "decimals": None, "name": None}
        for field, rpc_key in (("name", "name"), ("symbol", "symbol"), ("decimals", "decimals")):
            uref = named_keys.get(rpc_key)
            if not uref:
                continue
            result = await self._rpc("query_global_state", {"key": uref, "state_identifier": None})
            info[field] = result.get("stored_value", {}).get("CLValue", {}).get("parsed")
        return info

    # ── CEP-78 (NFT) ────────────────────────────────────────────────────────

    async def cep78_mint(
        self, contract_hash: str, owner_hex: str, name: str, token_uri: str, checksum: str = ""
    ) -> str:
        """Call the CEP-78 `mint` entry point. Returns tx hash. Uses the
        contract's built-in CEP78 metadata schema (name/token_uri/checksum;
        checksum defaults to all-zeros placeholder for demo tokens since we
        don't compute real asset hashes here)."""
        if not self._key_path:
            raise RuntimeError("private key not configured")
        owner_hex = (
            owner_hex.replace("account-hash-", "") if owner_hex.startswith("account-hash-") else owner_hex
        )
        if len(owner_hex) != 64:
            raise ValueError(f"owner must be 64-char hex account hash, got: {owner_hex!r}")

        return await self._run_node_script(
            _CEP78_MINT_SCRIPT,
            {
                "CONTRACT_HASH": contract_hash,
                "OWNER_HEX": owner_hex,
                "NAME": name,
                "TOKEN_URI": token_uri,
                "CHECKSUM": checksum or "0" * 68,
                "PEM_PATH": self._key_path,
                "KEY_ALGO": "secp256k1",
                "CASPER_RPC": self._rpc_url,
            },
        )

    async def cep78_transfer(
        self, contract_hash: str, token_id: int, source_hex: str, target_hex: str
    ) -> str:
        """Call the CEP-78 `transfer` entry point (Ordinal identifier mode).
        Returns tx hash. Note: the contract requires the deploy's caller to
        be the token owner/approved account, so `source_hex` must correspond
        to the signing key configured on this client (custodial-demo model,
        same as create_escrow/cep18_transfer)."""
        if not self._key_path:
            raise RuntimeError("private key not configured")
        source_hex = (
            source_hex.replace("account-hash-", "") if source_hex.startswith("account-hash-") else source_hex
        )
        target_hex = (
            target_hex.replace("account-hash-", "") if target_hex.startswith("account-hash-") else target_hex
        )
        if len(source_hex) != 64 or len(target_hex) != 64:
            raise ValueError("source/target must be 64-char hex account hashes")

        return await self._run_node_script(
            _CEP78_TRANSFER_SCRIPT,
            {
                "CONTRACT_HASH": contract_hash,
                "TOKEN_ID": str(token_id),
                "SOURCE_HEX": source_hex,
                "TARGET_HEX": target_hex,
                "PEM_PATH": self._key_path,
                "KEY_ALGO": "secp256k1",
                "CASPER_RPC": self._rpc_url,
            },
        )

    async def _get_cep78_named_keys(self, contract_hash: str) -> dict[str, str]:
        """Named keys of a CEP-78 contract entity, cached per contract_hash."""
        cache = getattr(self, "_cep78_named_keys_cache", None)
        if cache is None:
            cache = {}
            self._cep78_named_keys_cache = cache
        if contract_hash in cache:
            return cache[contract_hash]
        result = await self._rpc(
            "state_get_entity",
            {"entity_identifier": {"ContractHash": f"contract-{contract_hash}"}},
        )
        named_keys = result["entity"]["Contract"]["contract"]["named_keys"]
        parsed = {nk["name"]: nk["key"] for nk in named_keys}
        cache[contract_hash] = parsed
        return parsed

    async def get_cep78_owner(self, contract_hash: str, token_id: int) -> str | None:
        """Real on-chain owner (account-hash-... string) of an Ordinal-mode
        CEP-78 token, via the contract's `token_owners` dictionary."""
        named_keys = await self._get_cep78_named_keys(contract_hash)
        owners_uref = named_keys.get("token_owners")
        if not owners_uref:
            raise RuntimeError(f"contract {contract_hash} has no 'token_owners' named key")

        srh = await self._get_state_root_hash()
        try:
            result = await self._rpc(
                "state_get_dictionary_item",
                {
                    "state_root_hash": srh,
                    "dictionary_identifier": {
                        "URef": {"seed_uref": owners_uref, "dictionary_item_key": str(token_id)}
                    },
                },
            )
        except RuntimeError:
            return None
        return result.get("stored_value", {}).get("CLValue", {}).get("parsed")

    async def get_cep78_balance(self, contract_hash: str, account_hash_hex: str) -> int:
        """Real on-chain CEP-78 NFT count owned by an account. CEP-78 has no
        single 'balanceOf' dictionary (unlike CEP-18); this counts matches by
        checking the `token_owners` dictionary entry for every minted token
        id (0..number_of_minted_tokens-1). Fine for demo-scale collections
        (this AE402 test collection has total_token_supply=1000 but only a
        handful of tokens actually minted during testing)."""
        account_hash_hex = (
            account_hash_hex.replace("account-hash-", "")
            if account_hash_hex.startswith("account-hash-")
            else account_hash_hex
        )
        target = f"account-hash-{account_hash_hex}"
        named_keys = await self._get_cep78_named_keys(contract_hash)
        minted_uref = named_keys.get("number_of_minted_tokens")
        if not minted_uref:
            raise RuntimeError(f"contract {contract_hash} has no 'number_of_minted_tokens' named key")
        minted_result = await self._rpc("query_global_state", {"key": minted_uref, "state_identifier": None})
        minted_count = minted_result.get("stored_value", {}).get("CLValue", {}).get("parsed") or 0

        owners = await asyncio.gather(
            *[self.get_cep78_owner(contract_hash, i) for i in range(int(minted_count))]
        )
        return sum(1 for owner in owners if owner == target)

    async def get_cep78_token_info(self, contract_hash: str) -> dict[str, Any]:
        """Real on-chain CEP-78 collection metadata (name/symbol/total supply/minted count)."""
        named_keys = await self._get_cep78_named_keys(contract_hash)
        info: dict[str, Any] = {
            "collection_name": None,
            "collection_symbol": None,
            "total_token_supply": None,
            "number_of_minted_tokens": None,
        }
        field_map = {
            "collection_name": "collection_name",
            "collection_symbol": "collection_symbol",
            "total_token_supply": "total_token_supply",
            "number_of_minted_tokens": "number_of_minted_tokens",
        }
        for field, rpc_key in field_map.items():
            uref = named_keys.get(rpc_key)
            if not uref:
                continue
            result = await self._rpc("query_global_state", {"key": uref, "state_identifier": None})
            info[field] = result.get("stored_value", {}).get("CLValue", {}).get("parsed")
        return info

    async def close(self) -> None:
        await self._http.aclose()
