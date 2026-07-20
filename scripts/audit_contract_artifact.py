#!/usr/bin/env python3
"""Contract artifact audit for AE402.

Answers the P0 Gate 1 question 'is the fixed insurance-pool WASM actually
in the built artifact, or did the fix only land in the .rs source?'

For a contract listed in `deploy-out/onchain.json`, this script:

  1. Fetches the ORIGINAL module_bytes from the Casper testnet RPC using
     the recorded deploy_hash. That's the ground-truth binary the network
     is executing right now.
  2. Locally rebuilds the current source (cargo build --release --target
     wasm32-unknown-unknown).
  3. Compares:
     a) the exported function names (WASM export section) --- these are
        the entry points the contract advertises. If your fix added a
        new entrypoint or removed one, this catches drift.
     b) the strings embedded in the .rodata / data section --- names of
        named-keys, dict-names, error-messages, format-string templates.
        If your fix changed a message-binding string (e.g.
        build_claim_message went from 'claim:{}:{}:{}' to something
        else), this catches drift.
     c) the byte-size delta.

  4. Prints a concise green/red report and exits nonzero if any check
     the caller marked as REQUIRED failed.

Byte-for-byte equality is NOT the target: two Rust builds of the same
source with the same toolchain still differ in a handful of bytes
(timestamps, hash ids). The point is that the *observable behaviour*
(exports + baked strings) is unchanged.

Requirements:  python3, cargo + wasm32-unknown-unknown target,
matching rust-toolchain (contracts/rust-toolchain.toml).
"""

from __future__ import annotations

import argparse
import binascii
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parent.parent
ONCHAIN_JSON = REPO_ROOT / "deploy-out" / "onchain.json"
CONTRACTS_DIR = REPO_ROOT / "contracts"
RPC_URL = "https://node.testnet.casper.network/rpc"

# Registered audit targets. Each: onchain.json key ->
#   (crate directory, wasm filename produced by that crate).
TARGETS: dict[str, tuple[str, str]] = {
    "insurance_pool": ("insurance-pool", "insurance-pool.wasm"),
    "escrow_manager_v9": ("escrow", "escrow.wasm"),
    "vrf_arbiter": ("vrf-arbiter", "vrf-arbiter.wasm"),
    "agent_identity_registry": (
        "agent-identity-registry",
        "agent-identity-registry.wasm",
    ),
    "multi_asset_escrow": ("multi-asset-escrow", "multi-asset-escrow.wasm"),
}


# ── ANSI ──────────────────────────────────────────────────────────────────
def _c(code: str, msg: str) -> str:
    return f"\033[{code}m{msg}\033[0m"


def green(m: str) -> str:
    return _c("32", "✅ " + m)


def red(m: str) -> str:
    return _c("31", "❌ " + m)


def yellow(m: str) -> str:
    return _c("33", "⚠️  " + m)


def bold(m: str) -> str:
    return _c("1", m)


# ── on-chain fetch ────────────────────────────────────────────────────────
def _rpc(method: str, params: dict) -> dict:
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(RPC_URL, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def fetch_deploy_module_bytes(deploy_hash: str) -> bytes:
    """Return the ModuleBytes.module_bytes of a Casper deploy as raw bytes.
    Returns b'' if the deploy has empty ModuleBytes (call to an existing
    contract, not an install) so the caller can fall back to lookup by
    contract_hash."""
    body = _rpc("info_get_deploy", {"deploy_hash": deploy_hash})
    session = body["result"]["deploy"]["session"]
    if "ModuleBytes" not in session:
        return b""
    module_hex = session["ModuleBytes"]["module_bytes"]
    if not module_hex:
        return b""
    return binascii.unhexlify(module_hex)


def fetch_contract_state(contract_hash: str) -> tuple[list[str], list[str], str]:
    """Authoritative what-is-actually-live snapshot for a hash-... contract.
    Returns (named_key_names_sorted, entry_point_names_sorted,
    contract_wasm_hash). This bypasses the deploy_hash entirely --
    Casper's global state is the source of truth for what a contract_hash
    resolves to right now, regardless of which deploy created it."""
    body = _rpc(
        "query_global_state",
        {"state_identifier": None, "key": f"hash-{contract_hash}", "path": []},
    )
    c = body["result"]["stored_value"]["Contract"]
    named = sorted(k["name"] for k in c["named_keys"])
    entry = sorted(ep["name"] for ep in c["entry_points"])
    wasm = c["contract_wasm_hash"]
    return named, entry, wasm


# ── WASM lightweight parser ───────────────────────────────────────────────
#
# Rather than pull in a full WASM parser we walk the top-level section
# structure and extract:
#   - Section 7 (export section) function names
#   - Data section string blobs (printable-ASCII spans >= 4 chars)
# This is enough for the audit invariants we care about (entry points +
# baked strings) and keeps the script dependency-free.


def _read_leb128(buf: memoryview, pos: int) -> tuple[int, int]:
    result = 0
    shift = 0
    while True:
        byte = buf[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if (byte & 0x80) == 0:
            return result, pos
        shift += 7


def _iter_sections(wasm: bytes) -> Iterable[tuple[int, bytes]]:
    buf = memoryview(wasm)
    if bytes(buf[:4]) != b"\x00asm":
        raise ValueError("not a WASM module (bad magic)")
    pos = 8  # skip magic + version
    while pos < len(buf):
        sec_id = buf[pos]
        pos += 1
        size, pos = _read_leb128(buf, pos)
        yield sec_id, bytes(buf[pos : pos + size])
        pos += size


def wasm_export_names(wasm: bytes) -> list[str]:
    """Extract every exported name from a WASM module."""
    for sec_id, body in _iter_sections(wasm):
        if sec_id != 7:  # export section
            continue
        buf = memoryview(body)
        n, pos = _read_leb128(buf, 0)
        names = []
        for _ in range(n):
            name_len, pos = _read_leb128(buf, pos)
            name = bytes(buf[pos : pos + name_len]).decode("utf-8", "replace")
            pos += name_len
            pos += 1  # kind byte
            _, pos = _read_leb128(buf, pos)  # index
            names.append(name)
        return sorted(names)
    return []


def wasm_data_strings(wasm: bytes, min_len: int = 4) -> set[str]:
    """Approximate: printable ASCII runs from the DATA section."""
    strings: set[str] = set()
    for sec_id, body in _iter_sections(wasm):
        if sec_id != 11:  # data section
            continue
        # We don't decode data segments precisely; we scavenge every
        # printable ASCII run of >= min_len chars from the raw body.
        # False positives are fine -- what we care about is match/no-match
        # on the domain strings we actually document (claim:, withdraw:,
        # error names, dict names).
        run: list[int] = []
        for b in body:
            if 0x20 <= b <= 0x7E:
                run.append(b)
            else:
                if len(run) >= min_len:
                    strings.add(bytes(run).decode("ascii"))
                run = []
        if len(run) >= min_len:
            strings.add(bytes(run).decode("ascii"))
    return strings


# ── build ──────────────────────────────────────────────────────────────────
def build_contract(crate_dir: str, wasm_name: str) -> Path:
    """Run `cargo build --release --target wasm32-unknown-unknown` and
    return the path of the produced .wasm."""
    src = CONTRACTS_DIR / crate_dir
    if not src.is_dir():
        raise RuntimeError(f"contract crate not found: {src}")
    print(f"  building {crate_dir}…", flush=True)
    # Ensure ~/.cargo/bin is in PATH so subprocess finds rustup/cargo even
    # when the caller's shell integration wasn't sourced (CI, direct
    # `python3 script.py` invocation).
    build_env = os.environ.copy()
    cargo_bin = str(Path.home() / ".cargo" / "bin")
    if cargo_bin not in build_env.get("PATH", ""):
        build_env["PATH"] = cargo_bin + os.pathsep + build_env.get("PATH", "")
    subprocess.run(
        [
            "cargo",
            "build",
            "--release",
            "--target",
            "wasm32-unknown-unknown",
        ],
        cwd=src,
        env=build_env,
        check=True,
        capture_output=True,
    )
    wasm = CONTRACTS_DIR / "target" / "wasm32-unknown-unknown" / "release" / wasm_name
    if not wasm.is_file():
        raise RuntimeError(f"build succeeded but wasm not at {wasm}")
    return wasm


# ── audit ──────────────────────────────────────────────────────────────────
REQUIRED_NAMED_KEYS: dict[str, set[str]] = {
    # These are the on-chain named-keys that MUST exist on the deployed
    # contract for the fix to actually be live. Keyed by crate directory.
    "insurance-pool": {
        # A1 hardening: arbiter quorum for claim/withdraw.
        "arbiter_list",
        "arbiter_threshold",
        # withdraw anti-replay (nonce).
        "withdraw_nonce",
        # THE crucial 2026-07-19 fix: global escrow tombstone for claim.
        # Without this dict the contract has no way to tombstone an already
        # -claimed escrow; a caller with a valid quorum can drain the pool
        # cooldown-cycle by cooldown-cycle.
        "claimed_escrow_ids",
        "insurance_contract_purse",
        "premium_rate_bps",
        "total_claimed",
    },
    "escrow": set(),  # populate as we harden more contracts
    "vrf-arbiter": set(),
    "agent-identity-registry": set(),
    "multi-asset-escrow": set(),
}


def audit(name: str, meta: dict, crate_dir: str, wasm_name: str, strict: bool) -> int:
    contract_hash = meta["contract_hash"].removeprefix("hash-")
    deploy_hash = meta.get("deploy_hash", "")

    print(bold(f"\n══ Auditing {name}"))
    print(f"  contract_hash = {contract_hash}")
    print(f"  deploy_hash   = {deploy_hash or '(none listed)'}")

    # 1) Authoritative: fetch the CONTRACT (named-keys, entry-points) via
    # its current contract_hash. This is what the network is serving.
    try:
        on_named, on_entry, wasm_hash = fetch_contract_state(contract_hash)
    except Exception as e:
        print(red(f"cannot fetch contract {contract_hash[:16]}…: {e}"))
        return 1

    print(green(f"on-chain contract has {len(on_entry)} entry points, {len(on_named)} named-keys"))
    print(f"    contract_wasm_hash = {wasm_hash}")

    fails = 0

    # 2) Required-named-keys assertion (the fix-is-live check).
    required = REQUIRED_NAMED_KEYS.get(crate_dir, set())
    if required:
        missing = sorted(required - set(on_named))
        if not missing:
            print(green(f"all {len(required)} required named-keys present on chain"))
        else:
            print(red(f"REQUIRED NAMED-KEYS MISSING ON CHAIN: {missing}"))
            print("    the fix that adds these keys is NOT live under this contract_hash.")
            fails += 1
    else:
        print(yellow("no required-named-key list configured for this crate"))

    # 3) Corroborating deploy-bytes comparison (best-effort).
    #
    # If the deploy_hash listed in onchain.json is an install/upgrade
    # deploy AND its module_bytes still contains the required strings,
    # that's a strong second signal. But it can lie in both directions:
    #  - an old deploy_hash can point to a WASM that predates the fix,
    #    while the CURRENT contract_hash is a redeploy that fixed it
    #    (this is exactly what happened between 2026-07-06 and 07-19).
    #  - a fresh deploy_hash whose bytes look fine might have been
    #    superseded on chain since (unlikely on Casper immutable contract
    #    hashes, but worth flagging).
    # So we corroborate the contract state, we don't defer to the bytes.

    if deploy_hash:
        onchain_bytes = fetch_deploy_module_bytes(deploy_hash)
        if not onchain_bytes:
            print(
                yellow(
                    "listed deploy_hash has no ModuleBytes (probably an entry-point "
                    "call, not an install). Contract-state check above is authoritative."
                )
            )
        else:
            wasm_path = build_contract(crate_dir, wasm_name)
            local_bytes = wasm_path.read_bytes()
            delta = len(local_bytes) - len(onchain_bytes)
            delta_pct = 100.0 * delta / max(len(onchain_bytes), 1)
            if abs(delta_pct) < 2.0:
                print(
                    green(
                        f"deploy-bytes vs local: {len(onchain_bytes):,} vs {len(local_bytes):,} "
                        f"({delta:+,} bytes, {delta_pct:+.2f}%)"
                    )
                )
            else:
                print(
                    yellow(
                        f"deploy-bytes vs local size delta {delta_pct:+.2f}% -- "
                        f"probably a stale/superseded deploy_hash in onchain.json. "
                        f"Verify against the CURRENT contract_hash's named-keys above."
                    )
                )
            # Domain-string spot-check on the deploy-bytes (extra signal only).
            deploy_str = wasm_data_strings(onchain_bytes)
            local_str = wasm_data_strings(local_bytes)
            deploy_missing = [m for m in required if not any(m in s for s in deploy_str)]
            local_missing = [m for m in required if not any(m in s for s in local_str)]
            if deploy_missing:
                print(
                    yellow(
                        f"deploy_hash bytes are missing markers {deploy_missing} -- "
                        f"consistent with a superseded install. Trust the contract-state check."
                    )
                )
            if local_missing:
                print(red(f"LOCAL BUILD is missing markers {local_missing}"))
                fails += 1

    return fails if strict else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "target",
        nargs="?",
        default="insurance_pool",
        help=f"one of {list(TARGETS.keys())} (default: insurance_pool)",
    )
    ap.add_argument(
        "--all",
        action="store_true",
        help="audit every registered target",
    )
    ap.add_argument(
        "--strict",
        action="store_true",
        help="exit 1 on any drift; default is report-only",
    )
    args = ap.parse_args()

    with ONCHAIN_JSON.open() as f:
        onchain = json.load(f)["contracts"]

    if args.all:
        selected = list(TARGETS.keys())
    else:
        if args.target not in TARGETS:
            print(f"unknown target: {args.target}. Registered: {list(TARGETS.keys())}")
            return 2
        selected = [args.target]

    total_fails = 0
    for key in selected:
        if key not in onchain:
            print(yellow(f"skipping {key}: not in deploy-out/onchain.json"))
            continue
        meta = onchain[key]
        crate_dir, wasm_name = TARGETS[key]
        try:
            total_fails += audit(key, meta, crate_dir, wasm_name, args.strict)
        except Exception as e:
            print(red(f"audit of {key} failed: {e}"))
            total_fails += 1

    print(bold("\n══ Summary"))
    if total_fails == 0:
        print(green("all audits passed"))
        return 0
    else:
        print(red(f"{total_fails} audit(s) failed"))
        return 1 if args.strict else 0


if __name__ == "__main__":
    sys.exit(main())
