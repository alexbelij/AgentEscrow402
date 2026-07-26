#!/usr/bin/env python3
"""One-shot deploy script for HTLC.sol to Sepolia testnet (T3.4-B).

Compiles `contracts/HTLC.sol`, deploys it with the T3.4-B bridge test
wallet (address + recipient both default to the wallet's own address —
fine for a deploy smoke test / diff harness; a real swap leg would pass a
distinct counterparty address), and writes the deployment record (address
+ tx hash + ABI) to `docs/tier3/T3.4-B-deployment.json` so
`server/bridge_evm_adapter.py::load_deployment()` can pick it up.

The private key is read directly from the vault file on disk
(~/.vault/vault.json, team.ae402_bridge_sepolia_testwallet) — never
printed, never passed as a CLI arg, never logged.

Usage:
    .venv/bin/python scripts/deploy_htlc_sepolia.py [--recipient 0x...]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import solcx
from eth_account import Account

from server import bridge_evm_adapter as evm

VAULT_PATH = Path.home() / ".vault" / "vault.json"
VAULT_KEY = "ae402_bridge_sepolia_testwallet"
CONTRACT_SOURCE = Path(__file__).resolve().parent.parent / "contracts" / "HTLC.sol"
DEPLOYMENT_RECORD = Path(__file__).resolve().parent.parent / "docs" / "tier3" / "T3.4-B-deployment.json"


def _load_wallet() -> tuple[Account, str]:
    data = json.loads(VAULT_PATH.read_text())
    entry = data["team"][VAULT_KEY]
    value = entry["value"] if "value" in entry else entry
    priv = value["privkey"].strip()
    if not priv.startswith("0x"):
        priv = "0x" + priv
    acct = Account.from_key(priv)
    assert acct.address.lower() == value["address"].lower(), "vault address/privkey mismatch"
    return acct, value["address"]


def _compile() -> tuple[list, str]:
    solcx.install_solc("0.8.20")
    solcx.set_solc_version("0.8.20")
    compiled = solcx.compile_source(CONTRACT_SOURCE.read_text(), output_values=["abi", "bin"], solc_version="0.8.20")
    key = next(k for k in compiled if k.endswith(":HTLC"))
    return compiled[key]["abi"], compiled[key]["bin"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--recipient", default=None, help="recipient address; defaults to the wallet's own address")
    args = parser.parse_args()

    acct, wallet_address = _load_wallet()
    recipient = args.recipient or wallet_address

    w3 = evm.connect()
    print(f"connected to Sepolia (chain_id={w3.eth.chain_id}) as {acct.address}", file=sys.stderr)

    abi, bytecode = _compile()
    HTLC = w3.eth.contract(abi=abi, bytecode=bytecode)
    nonce = w3.eth.get_transaction_count(acct.address)
    tx = HTLC.constructor(recipient).build_transaction(
        {"from": acct.address, "nonce": nonce, "gasPrice": w3.eth.gas_price, "chainId": evm.CHAIN_ID}
    )
    tx["gas"] = w3.eth.estimate_gas(tx)
    signed = acct.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    print(f"deploy tx sent: {tx_hash.hex()} — waiting for confirmation...", file=sys.stderr)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
    if receipt.status != 1:
        print("DEPLOY FAILED — tx reverted", file=sys.stderr)
        return 1

    record = {
        "network": "sepolia",
        "chain_id": evm.CHAIN_ID,
        "deployer": acct.address,
        "recipient": recipient,
        "tx_hash": tx_hash.hex(),
        "block_number": receipt.blockNumber,
        "gas_used": receipt.gasUsed,
        "contract_address": receipt.contractAddress,
        "abi": abi,
    }
    DEPLOYMENT_RECORD.parent.mkdir(parents=True, exist_ok=True)
    DEPLOYMENT_RECORD.write_text(json.dumps(record, indent=2))

    print(json.dumps({k: v for k, v in record.items() if k != "abi"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
