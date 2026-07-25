"""Integration tests for T3.4-B — real Sepolia testnet.

These tests hit an ACTUAL deployed HTLC.sol instance via a live RPC
connection and the funded T3.4-B test wallet. They are slow (real block
confirmations, ~12s/tx on Sepolia) and require network access + a funded
wallet, so they are marked `integration` and skipped by default in CI;
run explicitly with:

    pytest tests/test_bridge_evm_sepolia_integration.py -m network -v

This is intentionally NOT part of the fast unit suite — it is the
ground-truth proof that bridge_evm_adapter.py actually drives a real
chain, diff-tested against the deterministic mock's semantics from
T3.4-A (same preimage/hashlock logic, same accept/reject decisions).
"""
import json
import time
from pathlib import Path

import pytest
from eth_account import Account

from server import bridge_evm_adapter as evm

VAULT_PATH = Path.home() / ".vault" / "vault.json"

pytestmark = pytest.mark.network


def _load_wallet():
    with open(VAULT_PATH) as f:
        vault = json.load(f)
    node = vault
    for part in "team.ae402_bridge_sepolia_testwallet".split("."):
        node = node[part]
    val = node["value"] if "value" in node else node
    priv = val["privkey"].strip()
    if not priv.startswith("0x"):
        priv = "0x" + priv
    hexpart = priv[2:]
    if len(hexpart) > 64:
        hexpart = hexpart[:64]
    priv = "0x" + hexpart
    acct = Account.from_key(priv)
    assert acct.address.lower() == val["address"].lower()
    return acct


@pytest.fixture(scope="module")
def w3():
    return evm.connect()


@pytest.fixture(scope="module")
def acct():
    return _load_wallet()


@pytest.fixture(scope="module")
def deployment():
    return evm.load_deployment()


@pytest.fixture(scope="module")
def contract(w3, deployment):
    return evm.get_contract(w3, deployment)


def test_deployment_record_matches_chain(w3, deployment, contract):
    """The recorded deployment really exists on-chain with EMPTY status
    (or LOCKED/CLAIMED/REFUNDED if a previous test run already used it)."""
    code = w3.eth.get_code(deployment["contract_address"])
    assert len(code) > 0, "no bytecode at recorded contract address — not actually deployed"
    status = evm.evm_status(contract)
    assert status["status"] in {"EMPTY", "LOCKED", "CLAIMED", "REFUNDED"}


def _deploy_fresh_htlc(w3, acct):
    """Deploy a brand-new HTLC.sol instance so each test starts in EMPTY
    state — mirrors the "one leg per swap" invariant from bridge_htlc.py."""
    import solcx

    contracts_path = Path(__file__).resolve().parent.parent / "contracts" / "HTLC.sol"
    solcx.set_solc_version("0.8.20")
    compiled = solcx.compile_source(
        contracts_path.read_text(),
        output_values=["abi", "bin"],
        solc_version="0.8.20",
    )
    key = [k for k in compiled if k.endswith(":HTLC")][0]
    abi, bytecode = compiled[key]["abi"], compiled[key]["bin"]

    HTLC = w3.eth.contract(abi=abi, bytecode=bytecode)
    nonce = w3.eth.get_transaction_count(acct.address, "pending")
    # Adaptive floor: 1.5x current gas price, min 1 gwei. Sepolia gas is
    # currently ~1 gwei; a hard 5-gwei floor forces 5x overpay and
    # exhausts the test wallet faster than needed.
    current_gas = w3.eth.gas_price
    base_gas_price = max(int(current_gas * 3 // 2), w3.to_wei(1, "gwei"))
    tx = HTLC.constructor(acct.address).build_transaction(
        {"from": acct.address, "nonce": nonce, "gasPrice": base_gas_price, "chainId": evm.CHAIN_ID}
    )
    tx["gas"] = w3.eth.estimate_gas(tx)
    gas_price = base_gas_price
    for _ in range(5):
        tx["gasPrice"] = gas_price
        signed = acct.sign_transaction(tx)
        try:
            tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
            break
        except Exception as e:  # noqa: BLE001
            m = str(e).lower()
            if "underpriced" in m or "replacement" in m or "already known" in m:
                gas_price = int(gas_price * 2)
                continue
            if "nonce too low" in m or "nonce too high" in m:
                tx["nonce"] = w3.eth.get_transaction_count(acct.address, "pending")
                continue
            raise
    else:
        raise RuntimeError("deploy broadcast failed after retries")
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)
    assert receipt.status == 1, "fresh HTLC deploy reverted"
    return w3.eth.contract(address=receipt.contractAddress, abi=abi)


def test_lock_then_claim_happy_path(w3, acct):
    """Real on-chain lock() followed by claim() with the correct preimage,
    on a freshly deployed HTLC instance so this test never depends on
    the recorded contract's state. This is the atomic-swap happy path
    proven against a live chain, not a mock."""
    fresh = _deploy_fresh_htlc(w3, acct)

    initial_status = evm.evm_status(fresh)
    assert initial_status["status"] == "EMPTY"

    preimage = f"t3.4-b-happy-{int(time.time())}".encode()
    hashlock_hex = evm.sha256_hashlock(preimage)
    timelock = int(time.time()) + 300  # 5 minutes out
    amount_wei = w3.to_wei(0.0001, "ether")

    lock_result = evm.evm_lock(w3, acct, fresh, hashlock_hex, timelock, amount_wei)
    assert lock_result.ok
    assert lock_result.status == 1

    mid_status = evm.evm_status(fresh)
    assert mid_status["status"] == "LOCKED"
    assert mid_status["hashlock"] == hashlock_hex
    assert mid_status["amount"] == amount_wei

    claim_result = evm.evm_claim(w3, acct, fresh, preimage)
    assert claim_result.ok
    assert claim_result.status == 1

    final_status = evm.evm_status(fresh)
    assert final_status["status"] == "CLAIMED"
    assert final_status["amount"] == 0


def test_forged_preimage_rejected_on_chain(w3, acct):
    """On a LOCKED HTLC leg on live Sepolia, an attempt to claim with the
    WRONG preimage must revert on-chain (Solidity's `PreimageMismatch`
    error). Proves the Solidity guard is live — not just the Python
    mock's guard.

    Uses the recorded HTLC only if it happens to be LOCKED with a
    hashlock we can't guess; otherwise deploys a fresh instance and
    locks it just to test the reject path."""
    contract = evm.get_contract(w3)
    status = evm.evm_status(contract)
    if status["status"] == "LOCKED":
        target = contract
    else:
        # Need a LOCKED contract to try forged-claim against. Deploy +
        # lock a fresh one — this costs gas but is the only way if the
        # recorded contract is CLAIMED/REFUNDED/EMPTY.
        target = _deploy_fresh_htlc(w3, acct)
        real_preimage = f"correct-secret-{int(time.time())}".encode()
        hashlock_hex = evm.sha256_hashlock(real_preimage)
        timelock = int(time.time()) + 300
        amount_wei = w3.to_wei(0.0001, "ether")
        lock_result = evm.evm_lock(w3, acct, target, hashlock_hex, timelock, amount_wei)
        assert lock_result.ok

    # Wrong preimage — gas-estimation preflight (eth_call) will surface
    # the on-chain revert as ContractCustomError(PreimageMismatch),
    # which our adapter wraps as EvmAdapterError.
    with pytest.raises(evm.EvmAdapterError) as excinfo:
        evm.evm_claim(w3, acct, target, b"wrong-secret-entirely-not-preimage")
    assert "PreimageMismatch" in str(excinfo.value) or "0x6f43bb63" in str(excinfo.value), (
        f"expected PreimageMismatch revert, got: {excinfo.value}"
    )

    status_after = evm.evm_status(target)
    assert status_after["status"] == "LOCKED", "forged preimage must NOT change state off LOCKED"
