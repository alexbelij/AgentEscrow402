#!/usr/bin/env python3
"""Read-only helper for verifying MultiAssetEscrow + test-token on-chain
state during manual testnet exercises (docs/evidence/*). Not part of the
server runtime -- a throwaway-style operational script, same spirit as
scripts/verify_cep18_balance.py / scripts/snapshot_escrow_state.py.

Usage:
    python3 scripts/query_multi_asset_state.py balance <token_contract_hash> <owner_hex_or_contract-hex>
    python3 scripts/query_multi_asset_state.py escrow <escrow_contract_hash> <service_hash>
"""

import json
import os
import sys

import requests

RPC = os.environ.get("CASPER_RPC", "https://node.testnet.cspr.cloud/rpc")
API_KEY = os.environ.get("CSPR_CLOUD_API_KEY")


def rpc(method, params):
    headers = {"Content-Type": "application/json"}
    if API_KEY:
        headers["Authorization"] = API_KEY
    resp = requests.post(
        RPC,
        headers=headers,
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise RuntimeError(data["error"])
    return data["result"]


def state_root_hash():
    return rpc("chain_get_state_root_hash", {})["state_root_hash"]


def query_dict(contract_hash, dict_name, item_key):
    srh = state_root_hash()
    result = rpc(
        "state_get_dictionary_item",
        {
            "state_root_hash": srh,
            "dictionary_identifier": {
                "ContractNamedKey": {
                    "key": f"hash-{contract_hash}",
                    "dictionary_name": dict_name,
                    "dictionary_item_key": item_key,
                }
            },
        },
    )
    return result.get("stored_value", {}).get("CLValue", {})


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    cmd = sys.argv[1]
    if cmd == "balance":
        contract_hash, owner_key = sys.argv[2], sys.argv[3]
        try:
            raw = query_dict(contract_hash, "balances", owner_key)
            print(json.dumps({"owner": owner_key, "balance_raw": raw.get("parsed")}, indent=2))
        except RuntimeError as exc:
            print(json.dumps({"owner": owner_key, "balance_raw": 0, "note": f"no dict entry ({exc})"}))
    elif cmd == "escrow":
        contract_hash, service_hash = sys.argv[2], sys.argv[3]
        raw = query_dict(contract_hash, "escrows", service_hash)
        print(json.dumps(raw, indent=2))
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
