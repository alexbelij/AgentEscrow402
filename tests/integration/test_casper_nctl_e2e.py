"""End-to-end escrow lifecycle test against a local NCTL Casper network.

This suite is gated by the `casper_net` pytest marker and is auto-skipped
when the local NCTL container isn't reachable (see conftest.py).

What it covers
--------------
1. **connectivity** — the RPC endpoint is up and reports a genesis chain.
2. **funded accounts** — the predefined user accounts exist on-chain and
   are funded by the faucet.
3. **contract deploy** — deploy `escrow_funder.wasm` (session code that
   installs the escrow contract) via the bundled Node.js SDK script.
4. **escrow lifecycle** — create → get → release, and separately
   create → refund, both driven through the same `CasperClient` the
   production API uses.

The heavy write paths (3, 4) call out to the Node.js scripts in
`server/casper_tx/`, so this test also requires `node` and the SDK's
node_modules on PATH (image already has both).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import pathlib
import subprocess
import time
import uuid
from typing import Any

import httpx
import pytest

from server.casper_client import CasperClient
from server.config import Config

pytestmark = pytest.mark.casper_net


# ---------------------------------------------------------------------------
# 1. Connectivity
# ---------------------------------------------------------------------------


def test_nctl_rpc_reachable(nctl_rpc_url: str) -> None:
    """Fundamental smoke: RPC responds and reports a chain name."""
    r = httpx.post(
        nctl_rpc_url,
        json={"jsonrpc": "2.0", "id": 1, "method": "info_get_status", "params": []},
        timeout=5.0,
    )
    r.raise_for_status()
    result = r.json()["result"]
    assert "chainspec_name" in result or "build_version" in result, result


def test_nctl_produces_blocks(wait_for_block) -> None:
    """A local network with DEPLOY_DELAY=5sec should produce a new block
    within 60 seconds. If this hangs it means the validator round is
    misconfigured — every downstream test would fail anyway."""
    new_height = wait_for_block(timeout=60.0)
    assert new_height > 0


# ---------------------------------------------------------------------------
# 2. Funded accounts
# ---------------------------------------------------------------------------


def _query_account_balance(rpc_url: str, public_key_hex: str) -> int:
    """Return the account main-purse balance in motes, via state_get_balance."""
    # Step 1: get main purse URef via state_get_entity.
    entity_res = httpx.post(
        rpc_url,
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "state_get_entity",
            "params": {"entity_identifier": {"PublicKey": public_key_hex}},
        },
        timeout=10.0,
    ).json()
    # Casper 2.x returns either { result: { entity: { AddressableEntity: {...} } } }
    # or, for un-migrated accounts, { result: { entity: { Account: {...} } } }.
    result = entity_res.get("result", {})
    entity = result.get("entity", {}) or {}
    main_purse: str | None = None
    if "AddressableEntity" in entity:
        main_purse = entity["AddressableEntity"].get("entity", {}).get("main_purse")
    elif "Account" in entity:
        main_purse = entity["Account"].get("main_purse")
    if not main_purse:
        # Not yet migrated / fresh account — treat as zero rather than error.
        return 0

    # Step 2: state_get_balance on the URef.
    balance_res = httpx.post(
        rpc_url,
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "state_get_balance",
            "params": {"state_root_hash": result["state_root_hash"], "purse_uref": main_purse},
        },
        timeout=10.0,
    ).json()
    return int(balance_res.get("result", {}).get("balance_value", "0"))


def test_faucet_is_funded(nctl_rpc_url: str, faucet_public_key_hex: str) -> None:
    balance = _query_account_balance(nctl_rpc_url, faucet_public_key_hex)
    # NCTL faucet is initialised with a huge balance (~1e33 motes).
    assert balance > 10**20, f"faucet balance suspiciously low: {balance}"


def test_predefined_users_exist(nctl_rpc_url: str, user_keys: dict[int, dict[str, str]]) -> None:
    """PREDEFINED_ACCOUNTS=true should ship at least users 1..3."""
    assert set(user_keys.keys()) >= {1, 2, 3}, f"missing users, got {list(user_keys)}"
    for u, info in user_keys.items():
        assert info["public_key_hex"], f"user-{u} public_key_hex empty"
        assert pathlib.Path(info["pem_path"]).exists(), f"user-{u} pem missing"


# ---------------------------------------------------------------------------
# 3. Contract deploy (session-wasm install)
# ---------------------------------------------------------------------------


_SCRIPT_DIR = pathlib.Path(__file__).parent.parent.parent / "server" / "casper_tx"
_DEPLOY_SCRIPT = _SCRIPT_DIR / "deploy_contract_legacy.mjs"
_ESCROW_WASM = _SCRIPT_DIR / "escrow_funder.wasm"


def _has_node_env() -> bool:
    """`node` on PATH + casper-js-sdk installed next to the scripts."""
    if not _SCRIPT_DIR.exists() or not _DEPLOY_SCRIPT.exists() or not _ESCROW_WASM.exists():
        return False
    try:
        subprocess.run(["node", "--version"], capture_output=True, timeout=5, check=True)
    except (subprocess.SubprocessError, FileNotFoundError):
        return False
    node_modules = _SCRIPT_DIR.parent / "node_modules" / "casper-js-sdk"
    return node_modules.exists()


@pytest.fixture(scope="session")
def deployed_escrow_contract_hash(
    nctl_rpc_url: str,
    faucet_pem_path: pathlib.Path,
    wait_for_block,
) -> str:
    """Deploy the escrow contract from `escrow_funder.wasm` and return the
    installed contract hash. Skips the whole test that depends on it if
    the Node.js toolchain isn't available."""
    if not _has_node_env():
        pytest.skip("node / casper-js-sdk not installed; skipping contract deploy")

    env = {
        **os.environ,
        "CASPER_RPC": nctl_rpc_url,
        "CHAIN_NAME": "casper-net-1",
        "PEM_PATH": str(faucet_pem_path),
        "KEY_ALGO": "ed25519",  # NCTL default
        "WASM_PATH": str(_ESCROW_WASM),
        "PAYMENT_MOTES": os.getenv("NCTL_DEPLOY_PAYMENT", "300000000000"),  # 300 CSPR
    }
    result = subprocess.run(
        ["node", str(_DEPLOY_SCRIPT)],
        capture_output=True,
        text=True,
        env=env,
        timeout=90,
    )
    assert result.returncode == 0, f"deploy failed: {result.stderr}\n{result.stdout}"
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload.get("success"), payload
    deploy_hash = payload["hash"]

    # Wait for inclusion + contract entry to appear in named keys.
    wait_for_block(timeout=90.0)
    contract_hash = payload.get("contract_hash") or ""
    assert contract_hash and len(contract_hash) == 64, f"no contract hash in deploy payload: {payload}"
    return contract_hash


def test_contract_is_installed(deployed_escrow_contract_hash: str) -> None:
    assert len(deployed_escrow_contract_hash) == 64
    int(deployed_escrow_contract_hash, 16)  # is hex


# ---------------------------------------------------------------------------
# 4. Escrow lifecycle: create → release
# ---------------------------------------------------------------------------


def _make_client(rpc_url: str, contract_hash: str, faucet_pem: pathlib.Path) -> CasperClient:
    """CasperClient wired against NCTL. We reuse production code paths."""
    cfg = Config(
        contract_hash=contract_hash,
        casper_rpc_url=rpc_url,
        casper_chain_name="casper-net-1",
        deployer_pem_path=str(faucet_pem),
        deployer_key_algo="ed25519",
        sandbox=False,
    )
    return CasperClient(cfg)


@pytest.mark.asyncio
async def test_escrow_create_and_release(
    nctl_rpc_url: str,
    deployed_escrow_contract_hash: str,
    faucet_pem_path: pathlib.Path,
    user_keys: dict[int, dict[str, str]],
    wait_for_block,
) -> None:
    """Full happy-path lifecycle: create escrow → verify on-chain → release."""
    client = _make_client(nctl_rpc_url, deployed_escrow_contract_hash, faucet_pem_path)

    receiver_hex = user_keys[2]["public_key_hex"]
    service_hash = hashlib.sha256(f"nctl-e2e-{uuid.uuid4().hex}".encode()).hexdigest()
    amount_motes = 5_000_000_000  # 5 CSPR
    ttl_secs = 3600

    # 1. Create.
    create_result = await client.create_escrow(
        receiver_public_key_hex=receiver_hex,
        service_hash=service_hash,
        amount=amount_motes,
        ttl_secs=ttl_secs,
    )
    assert create_result.success, create_result
    wait_for_block(timeout=60.0)

    # 2. Read back.
    record = await client.get_escrow(service_hash)
    assert record is not None, "escrow not readable after create"
    assert record.amount == amount_motes
    assert record.ttl == ttl_secs
    assert record.status.value == "pending"

    # 3. Release.
    release_result = await client.release_escrow(service_hash)
    assert release_result.success, release_result
    wait_for_block(timeout=60.0)

    # 4. Confirm state transition.
    record_after = await client.get_escrow(service_hash)
    assert record_after is not None
    assert record_after.status.value == "released", record_after


@pytest.mark.asyncio
async def test_escrow_create_and_refund(
    nctl_rpc_url: str,
    deployed_escrow_contract_hash: str,
    faucet_pem_path: pathlib.Path,
    user_keys: dict[int, dict[str, str]],
    wait_for_block,
) -> None:
    """Refund path: create → refund. Uses a fresh service_hash so it is
    independent of the release test."""
    client = _make_client(nctl_rpc_url, deployed_escrow_contract_hash, faucet_pem_path)

    receiver_hex = user_keys[2]["public_key_hex"]
    service_hash = hashlib.sha256(f"nctl-e2e-refund-{uuid.uuid4().hex}".encode()).hexdigest()
    amount_motes = 2_500_000_000  # 2.5 CSPR

    create_result = await client.create_escrow(
        receiver_public_key_hex=receiver_hex,
        service_hash=service_hash,
        amount=amount_motes,
        ttl_secs=3600,
    )
    assert create_result.success, create_result
    wait_for_block(timeout=60.0)

    refund_result = await client.refund_escrow(service_hash)
    assert refund_result.success, refund_result
    wait_for_block(timeout=60.0)

    record = await client.get_escrow(service_hash)
    assert record is not None
    assert record.status.value == "refunded", record
