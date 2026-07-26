"""Real Casper adapter for the HTLC bridge — L85 (Casper leg).

The "truthful" counterpart to `bridge_htlc.py` (deterministic mock) and
`bridge_evm_adapter.py` (Sepolia EVM leg) on the *Casper* side of an atomic
cross-chain swap.

State machine is identical across all three legs:

    EMPTY -> LOCKED -> CLAIMED | REFUNDED

Hashlock is **sha256(preimage)** — same primitive on both chains — so the
same `(preimage, hashlock_hex)` pair reveals atomically on both legs when
the swap completes. Timelock is in **milliseconds** on Casper (matching
`bridge_htlc.py` and `HTLC.sol` — Casper's `runtime::get_blocktime()`
returns ms since Unix epoch).

The Casper HTLC contract is deployed at:

    hash-5d5a8d79bd37841234cc9c814937609974715fce214ac814e78eb7528ea0a435

(canonical entry in `deploy-out/onchain.json` → `casper_htlc`, published
after ROADMAP L85 deploy 2026-07-26).

Design goals mirror `bridge_evm_adapter.py`:

- Same semantics as the deterministic mock. The mock is the oracle;
  this adapter is diff-tested against it (same preimage → same logical
  outcome: CLAIMED or REFUNDED).
- No secrets in logs. The deployer PEM is loaded via the vault and never
  passed as a CLI arg / printed / embedded in a commit.
- Idempotent, inspectable: every call returns the deploy hash + status so
  callers/tests can assert on real on-chain outcomes.

Non-goals:
- Deploying new HTLC contract instances per swap — the contract is
  installed once (see `server/casper_tx/deploy_casper_htlc.mjs`) and
  reused across every swap on this chain.
- Fee/gas tuning — payment defaults are set to the well-known ceiling for
  each entry point on Casper 2.0 testnet.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

_SCRIPT_DIR = Path(__file__).resolve().parent / "casper_tx"
_LIFECYCLE_SCRIPT = _SCRIPT_DIR / "bridge_casper_htlc_lifecycle.mjs"
_ONCHAIN_JSON = Path(__file__).resolve().parent.parent / "deploy-out" / "onchain.json"

# Payment ceilings per entry point (motes). Casper 2.0 testnet — these
# are the well-known safe values from existing lifecycle scripts. Lock
# needs a real purse-to-purse transfer + dictionary write; claim/refund
# do a purse-to-account transfer + dictionary write.
_PAYMENT_LOCK = "10000000000"   # 10 CSPR
_PAYMENT_CLAIM = "10000000000"  # 10 CSPR
_PAYMENT_REFUND = "10000000000"  # 10 CSPR

# get_status is read-only via query_global_state on the contract's
# `htlc_locks` dictionary — no deploy submitted, no payment.


class CasperAdapterError(Exception):
    """Raised for any Casper-side interaction failure (reverted deploy,
    RPC error, missing key, invalid state)."""


@dataclass
class DeployResult:
    deploy_hash: str
    status: str  # "success" | "failure" | "pending"
    block_hash: Optional[str] = None
    error_message: Optional[str] = None
    cost: Optional[int] = None

    @property
    def ok(self) -> bool:
        return self.status == "success"


def load_htlc_deployment() -> Dict[str, Any]:
    """Read the canonical Casper HTLC contract entry from onchain.json.

    Every field is returned untouched (`hash-` prefixes preserved) so
    callers pass them straight to RPC methods that expect prefixed keys.
    """
    if not _ONCHAIN_JSON.exists():
        raise CasperAdapterError(f"no onchain.json at {_ONCHAIN_JSON}")
    doc = json.loads(_ONCHAIN_JSON.read_text())
    entry = doc.get("contracts", {}).get("casper_htlc")
    if not entry:
        raise CasperAdapterError(
            "onchain.json has no 'casper_htlc' entry — deploy the Casper "
            "HTLC contract first (see server/casper_tx/deploy_casper_htlc.mjs)"
        )
    return entry


def sha256_hashlock(preimage: bytes) -> str:
    """Same primitive as `bridge_evm_adapter.sha256_hashlock` and
    `bridge_htlc.derive_hashlock`. Returns the lowercase 64-char hex of
    sha256(preimage). This is what the Casper contract's `hashlock_hex`
    argument expects."""
    return hashlib.sha256(preimage).hexdigest()


# ── Deploy submission ────────────────────────────────────────────────

def _run_lifecycle(env: Dict[str, str]) -> DeployResult:
    """Invoke the node-side lifecycle script (which owns casper-js-sdk)
    and parse its stdout JSON. Any failure is normalised into
    CasperAdapterError so callers only see one exception type."""
    import subprocess

    # Merge caller env on top of parent env (RPC endpoint, API key,
    # deployer PEM path), passing NO secrets on the command line.
    full_env = os.environ.copy()
    full_env.update(env)
    # We only need the CWD for node's module resolution; the script
    # itself has no relative path dependencies beyond `casper-js-sdk`
    # in casper_tx/node_modules.
    completed = subprocess.run(
        ["node", str(_LIFECYCLE_SCRIPT)],
        cwd=str(_SCRIPT_DIR),
        env=full_env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    if completed.returncode != 0:
        raise CasperAdapterError(
            f"lifecycle script failed (exit {completed.returncode}): "
            f"{completed.stderr.strip() or completed.stdout.strip()}"
        )
    # The script emits one JSON object per line; the last line is the
    # authoritative result. Anything before is progress logging.
    lines = [ln for ln in completed.stdout.strip().split("\n") if ln.strip()]
    if not lines:
        raise CasperAdapterError("lifecycle script produced no output")
    try:
        payload = json.loads(lines[-1])
    except json.JSONDecodeError as e:
        raise CasperAdapterError(f"lifecycle script emitted non-JSON: {lines[-1]}") from e
    if not payload.get("success"):
        raise CasperAdapterError(payload.get("error") or f"lifecycle script reported failure: {payload}")
    return DeployResult(
        deploy_hash=payload["hash"],
        status=payload.get("status", "pending"),
        block_hash=payload.get("block_hash"),
        error_message=payload.get("error_message"),
        cost=payload.get("cost"),
    )


def _base_env(
    *,
    key_path: str,
    key_algo: str,
    rpc_url: str,
    api_key: Optional[str],
) -> Dict[str, str]:
    env = {
        "PEM_PATH": key_path,
        "KEY_ALGO": key_algo,
        "CASPER_RPC": rpc_url,
    }
    if api_key:
        env["CSPR_CLOUD_API_KEY"] = api_key
    return env


def casper_lock(
    *,
    hashlock_hex: str,
    timelock_ms: int,
    receiver_hex: str,
    amount_motes: int,
    contract_hash: str,
    key_path: str,
    key_algo: str = "secp256k1",
    rpc_url: str,
    api_key: Optional[str] = None,
    wait_for_inclusion: bool = True,
) -> DeployResult:
    """Call HTLC.lock(hashlock, timelock, receiver, source_purse, amount) on-chain.

    - `contract_hash` is the addressable-entity/contract hash (with or
      without a `hash-` / `contract-` prefix — normalised inside the
      lifecycle script).
    - `receiver_hex` is the recipient's account-hash hex (64 chars, no prefix).
    - `amount_motes` must match the actual value transferred from the
      caller's main purse.
    - `wait_for_inclusion=True` blocks until the deploy is executed and
      returns the on-chain status. `False` returns as soon as the
      deploy is accepted by the RPC.
    """
    env = _base_env(key_path=key_path, key_algo=key_algo, rpc_url=rpc_url, api_key=api_key)
    env.update({
        "ACTION": "lock",
        "CONTRACT_HASH": contract_hash,
        "HASHLOCK_HEX": hashlock_hex,
        "TIMELOCK_MS": str(timelock_ms),
        "RECEIVER_HEX": receiver_hex,
        "AMOUNT_MOTES": str(amount_motes),
        "PAYMENT_MOTES": _PAYMENT_LOCK,
        "WAIT_FOR_INCLUSION": "1" if wait_for_inclusion else "0",
    })
    return _run_lifecycle(env)


def casper_claim(
    *,
    hashlock_hex: str,
    preimage: bytes,
    contract_hash: str,
    key_path: str,
    key_algo: str = "secp256k1",
    rpc_url: str,
    api_key: Optional[str] = None,
    wait_for_inclusion: bool = True,
) -> DeployResult:
    """Call HTLC.claim(hashlock, preimage). Reverts (ERR_PREIMAGE_MISMATCH)
    if sha256(preimage) != hashlock, or (ERR_TIMELOCK_EXPIRED) if
    blocktime >= timelock. The contract does NOT enforce caller == receiver
    — funds always go to the `receiver` recorded at lock time regardless
    of who submits claim."""
    env = _base_env(key_path=key_path, key_algo=key_algo, rpc_url=rpc_url, api_key=api_key)
    env.update({
        "ACTION": "claim",
        "CONTRACT_HASH": contract_hash,
        "HASHLOCK_HEX": hashlock_hex,
        "PREIMAGE_HEX": preimage.hex(),
        "PAYMENT_MOTES": _PAYMENT_CLAIM,
        "WAIT_FOR_INCLUSION": "1" if wait_for_inclusion else "0",
    })
    return _run_lifecycle(env)


def casper_refund(
    *,
    hashlock_hex: str,
    contract_hash: str,
    key_path: str,
    key_algo: str = "secp256k1",
    rpc_url: str,
    api_key: Optional[str] = None,
    wait_for_inclusion: bool = True,
) -> DeployResult:
    """Call HTLC.refund(hashlock). Reverts (ERR_TIMELOCK_NOT_EXPIRED) if
    blocktime < timelock, or (ERR_NOT_LOCKED) if the swap isn't in the
    LOCKED state. Refund always returns funds to the `sender` recorded
    at lock time regardless of caller."""
    env = _base_env(key_path=key_path, key_algo=key_algo, rpc_url=rpc_url, api_key=api_key)
    env.update({
        "ACTION": "refund",
        "CONTRACT_HASH": contract_hash,
        "HASHLOCK_HEX": hashlock_hex,
        "PAYMENT_MOTES": _PAYMENT_REFUND,
        "WAIT_FOR_INCLUSION": "1" if wait_for_inclusion else "0",
    })
    return _run_lifecycle(env)


def casper_status(
    *,
    hashlock_hex: str,
    contract_hash: str,
    rpc_url: str,
    api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """Read-only lookup. Returns {"status": ..., "amount": ..., "record": ...}
    where status ∈ {"EMPTY", "LOCKED", "CLAIMED", "REFUNDED"} matches the
    EVM leg's `evm_status` return shape.

    Reads directly from the contract's `htlc_locks` named dictionary via
    query_global_state, bypassing any state cached in a running node
    subprocess — the source of truth is always chain state at
    query time.
    """
    env = {
        "CASPER_RPC": rpc_url,
        "ACTION": "get_status",
        "CONTRACT_HASH": contract_hash,
        "HASHLOCK_HEX": hashlock_hex,
    }
    if api_key:
        env["CSPR_CLOUD_API_KEY"] = api_key
    result = _run_lifecycle(env)
    # get_status action encodes its payload in `error_message` (misnomer —
    # the lifecycle script reuses the field for read-only responses).
    if not result.error_message:
        return {"status": "EMPTY", "amount": 0, "record": None}
    parsed = json.loads(result.error_message)
    return parsed
