"""Real EVM (Sepolia) adapter for the HTLC bridge — T3.4-B.

This is the "truthful" counterpart to the deterministic in-memory mock in
`bridge_htlc.py` (T3.4-A). Where the mock computes state transitions
in-process with zero I/O, this module drives an ACTUAL deployed
`contracts/HTLC.sol` instance on Sepolia via Web3.py: real RPC calls, real
signed transactions, real gas, real block confirmations.

Design goals:

- Same semantics as the mock: lock(hashlock, timelock) / claim(preimage) /
  refund(). The mock is the oracle — this adapter is diff-tested against
  it (same preimage/hashlock/timelock inputs must produce the same
  logical outcome: CLAIMED with funds moved, or REFUNDED with funds
  returned).
- No secrets in logs. The private key is loaded once from the vault file
  on disk by the caller (never passed as a CLI arg / printed / embedded
  in a commit) and used only to sign locally via eth_account.
- Idempotent, inspectable: every call returns the tx hash + receipt
  status so callers/tests can assert on real on-chain outcomes, not
  just "no exception raised".

Non-goals:
- Deploying new contract instances per swap (see `scripts/deploy_htlc_sepolia.py`
  for that — one-time deploy, address recorded in
  `docs/tier3/T3.4-B-deployment.json`).
- Gas estimation tuning / EIP-1559 fee markets — uses legacy gasPrice for
  simplicity since Sepolia is a testnet and cost is not a concern here.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from eth_account import Account
from eth_utils import keccak
from web3 import Web3
from web3.contract.contract import Contract
from web3.exceptions import ContractCustomError, ContractLogicError

CHAIN_ID = 11155111  # Sepolia
DEFAULT_RPC_URLS = [
    "https://ethereum-sepolia-rpc.publicnode.com",
    "https://rpc.sepolia.org",
    "https://sepolia.gateway.tenderly.co",
]

_DEPLOYMENT_RECORD = Path(__file__).resolve().parent.parent / "docs" / "tier3" / "T3.4-B-deployment.json"


class EvmAdapterError(Exception):
    """Raised for any on-chain interaction failure (reverted tx, bad RPC, etc)."""


# Custom Solidity error selectors declared in contracts/HTLC.sol — computed
# once so revert data can be decoded into the same human-readable names the
# contract source uses, instead of a raw "0x6f43bb63"-style hex string.
_CUSTOM_ERROR_NAMES = [
    "AlreadyLocked()",
    "NotLocked()",
    "NotRecipient()",
    "NotSender()",
    "TimelockExpired()",
    "TimelockNotExpired()",
    "PreimageMismatch()",
    "ZeroAmount()",
    "ZeroRecipient()",
    "TimelockInPast()",
]
_SELECTOR_TO_NAME = {keccak(text=sig)[:4].hex(): sig.split("(")[0] for sig in _CUSTOM_ERROR_NAMES}


def _decode_revert(exc: Exception) -> str:
    """Best-effort: turn a ContractCustomError/ContractLogicError's raw
    selector into the matching Solidity error name from HTLC.sol."""
    data = getattr(exc, "data", None)
    if isinstance(data, str):
        selector = data if data.startswith("0x") else "0x" + data
        selector = selector[:10]
        name = _SELECTOR_TO_NAME.get(selector)
        if name:
            return name
    return str(exc)


@dataclass
class TxResult:
    tx_hash: str
    status: int  # 1 = success, 0 = reverted
    block_number: int
    gas_used: int

    @property
    def ok(self) -> bool:
        return self.status == 1


def load_deployment() -> Dict[str, Any]:
    """Load the recorded Sepolia deployment (address + ABI) written by
    scripts/deploy_htlc_sepolia.py."""
    if not _DEPLOYMENT_RECORD.exists():
        raise EvmAdapterError(
            f"no deployment record at {_DEPLOYMENT_RECORD} — run " "scripts/deploy_htlc_sepolia.py first"
        )
    return json.loads(_DEPLOYMENT_RECORD.read_text())


def connect(rpc_urls: Optional[list[str]] = None) -> Web3:
    """Connect to the first reachable Sepolia RPC endpoint."""
    for url in rpc_urls or DEFAULT_RPC_URLS:
        try:
            w3 = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 20}))
            if w3.is_connected() and w3.eth.chain_id == CHAIN_ID:
                return w3
        except Exception:  # noqa: BLE001
            continue
    raise EvmAdapterError("no reachable Sepolia RPC endpoint")


def get_contract(w3: Web3, deployment: Optional[Dict[str, Any]] = None) -> Contract:
    deployment = deployment or load_deployment()
    return w3.eth.contract(
        address=Web3.to_checksum_address(deployment["contract_address"]),
        abi=deployment["abi"],
    )


# Minimum gasPrice floor for Sepolia — public RPCs sometimes report a
# fee that is at or below the mempool's current min-inclusion floor,
# causing "replacement transaction underpriced" / "transaction
# underpriced" errors. 2 gwei is negligible on a testnet but reliably
# gets included within a block or two.
_MIN_GAS_PRICE_GWEI = 5

# Custom-error selectors from contracts/HTLC.sol (keccak(name())[:4]).
# Populated lazily so we don't force eth_utils.keccak evaluation at
# import time; a stray unknown selector falls through as its hex code.
_CUSTOM_ERROR_NAMES = (
    "AlreadyLocked",
    "NotLocked",
    "NotRecipient",
    "NotSender",
    "PreimageMismatch",
    "TimelockExpired",
    "TimelockInPast",
    "TimelockNotExpired",
    "ZeroAmount",
    "ZeroRecipient",
)
_ERROR_SELECTORS: Dict[str, str] = {}


def _build_selectors() -> Dict[str, str]:
    if not _ERROR_SELECTORS:
        for name in _CUSTOM_ERROR_NAMES:
            sel = "0x" + keccak(text=f"{name}()").hex()[:8]
            _ERROR_SELECTORS[sel] = name
    return _ERROR_SELECTORS


def _decode_revert(exc: Exception) -> str:
    """Turn a web3 revert exception into a short, deterministic message.
    Recognises HTLC.sol's custom errors by 4-byte selector; falls back
    to the raw hex / string form for anything unrecognised."""
    if isinstance(exc, ContractCustomError):
        data = getattr(exc, "data", None) or (exc.args[0] if exc.args else "")
        if isinstance(data, str) and data.startswith("0x") and len(data) >= 10:
            selector = data[:10].lower()
            name = _build_selectors().get(selector)
            if name:
                return f"{name}() [selector={selector}]"
            return f"unknown custom error selector={selector}"
        return str(exc)
    if isinstance(exc, ContractLogicError):
        return str(exc)
    return str(exc)


def _send(w3: Web3, acct: Account, fn, value_wei: int = 0) -> TxResult:
    # "pending" nonce accounts for tx already broadcast but not yet mined
    # so we don't collide with our own outstanding tx.
    nonce = w3.eth.get_transaction_count(acct.address, "pending")
    base_gas_price = max(w3.eth.gas_price, w3.to_wei(_MIN_GAS_PRICE_GWEI, "gwei"))
    # NOTE: web3.py's `build_transaction` runs a preflight eth_call to
    # detect reverts before returning, so it can itself raise
    # ContractCustomError / ContractLogicError — catch here, not just
    # around estimate_gas.
    try:
        tx = fn.build_transaction(
            {
                "from": acct.address,
                "nonce": nonce,
                "gasPrice": base_gas_price,
                "chainId": CHAIN_ID,
                "value": value_wei,
            }
        )
        tx["gas"] = w3.eth.estimate_gas(tx)
    except (ContractCustomError, ContractLogicError) as e:
        raise EvmAdapterError(f"reverted: {_decode_revert(e)}") from e
    except Exception as e:  # noqa: BLE001
        raise EvmAdapterError(f"tx build/estimate failed: {_decode_revert(e)}") from e

    # Broadcast with up to 3 retries on "replacement transaction
    # underpriced" — Sepolia public nodes require the new tx's gasPrice
    # to be at least 10% higher than any prior tx for the same nonce.
    # Doubling on each retry converges fast.
    gas_price = base_gas_price
    last_err = None
    for attempt in range(5):
        tx["gasPrice"] = gas_price
        signed = acct.sign_transaction(tx)
        try:
            tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
            break
        except Exception as e:  # noqa: BLE001
            msg = str(e).lower()
            last_err = e
            if "underpriced" in msg or "replacement" in msg or "already known" in msg:
                gas_price = int(gas_price * 2)
                continue
            if "nonce too low" in msg or "nonce too high" in msg:
                # mempool advanced between our nonce fetch and broadcast
                # (a prior tx of ours mined, or another node saw a newer
                # nonce first) — refetch and re-sign with same content.
                tx["nonce"] = w3.eth.get_transaction_count(acct.address, "pending")
                continue
            raise EvmAdapterError(f"broadcast failed: {e}") from e
    else:
        raise EvmAdapterError(f"broadcast failed after retries: {last_err}") from last_err
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)
    return TxResult(
        tx_hash=tx_hash.hex(),
        status=receipt.status,
        block_number=receipt.blockNumber,
        gas_used=receipt.gasUsed,
    )


def evm_lock(
    w3: Web3,
    acct: Account,
    contract: Contract,
    hashlock_hex: str,
    timelock_unix: int,
    amount_wei: int,
) -> TxResult:
    """Call HTLC.lock(hashlock, timelock) with msg.value = amount_wei."""
    hashlock_bytes = bytes.fromhex(hashlock_hex.removeprefix("0x"))
    fn = contract.functions.lock(hashlock_bytes, timelock_unix)
    result = _send(w3, acct, fn, value_wei=amount_wei)
    if not result.ok:
        raise EvmAdapterError(f"lock() reverted: {result}")
    return result


def evm_claim(w3: Web3, acct: Account, contract: Contract, preimage: bytes) -> TxResult:
    """Call HTLC.claim(preimage). Reverts if sha256(preimage) != hashlock,
    caller != recipient, or timelock already expired."""
    fn = contract.functions.claim(preimage)
    result = _send(w3, acct, fn)
    if not result.ok:
        raise EvmAdapterError(f"claim() reverted: {result}")
    return result


def evm_refund(w3: Web3, acct: Account, contract: Contract) -> TxResult:
    """Call HTLC.refund(). Reverts if timelock not yet passed or caller != sender."""
    fn = contract.functions.refund()
    result = _send(w3, acct, fn)
    if not result.ok:
        raise EvmAdapterError(f"refund() reverted: {result}")
    return result


def evm_status(contract: Contract) -> Dict[str, Any]:
    """Read-only getStatus() — mirrors bridge_htlc.py leg status dict."""
    sender, recipient, hashlock, timelock, amount, status = contract.functions.getStatus().call()
    return {
        "sender": sender,
        "recipient": recipient,
        "hashlock": hashlock.hex(),
        "timelock": timelock,
        "amount": amount,
        "status": ["EMPTY", "LOCKED", "CLAIMED", "REFUNDED"][status],
    }


def sha256_hashlock(preimage: bytes) -> str:
    """Matches the Solidity contract's `sha256(preimage)` and the Python
    mock's hashlock derivation — same primitive on both legs."""
    return hashlib.sha256(preimage).hexdigest()
