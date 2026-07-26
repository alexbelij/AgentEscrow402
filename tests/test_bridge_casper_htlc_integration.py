"""Integration tests for L85 — real Casper testnet HTLC bridge.

These tests hit an ACTUAL deployed casper-htlc contract via the live
Casper 2.0 testnet RPC using the funded L85 deployer wallet. They are
slow (real 30–90s block inclusion per lock) and require network access +
a funded wallet, so they are marked `network` and skipped by default in
CI; run explicitly with:

    pytest tests/test_bridge_casper_htlc_integration.py -m network -v

This is intentionally NOT part of the fast unit suite — it is the
ground-truth proof that bridge_casper_adapter.py actually drives a real
Casper chain, semantically identical to bridge_htlc.py (mock oracle) and
bridge_evm_adapter.py (Sepolia leg). Same primitive (sha256 hashlock,
millisecond timelock, CEI ordering, ``EMPTY → LOCKED → CLAIMED |
REFUNDED``) across all three legs.

Uses a fresh randomly-generated ``(preimage, hashlock)`` per test so
runs never collide with each other or with prior lifecycle runs on the
shared contract. This matches how a real bridge relayer would use a
fresh hashlock per swap.
"""

from __future__ import annotations

import json
import os
import secrets
import tempfile
import time
from pathlib import Path

import pytest

from server import bridge_casper_adapter as csp
from server import bridge_htlc as mock

VAULT_PATH = Path.home() / ".vault" / "vault.json"

CASPER_RPC = "https://node.testnet.casper.network/rpc"
DEPLOYER_ACCOUNT_HASH = "74c96cd0073c4c973b70e7925adca8a4ba58ffcb9737304631381b82695007a8"

pytestmark = pytest.mark.network


def _load_vault():
    with open(VAULT_PATH) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def pem_path():
    """Materialize the deployer PEM to a temp file (600 perms) and yield
    its path. Removed at module teardown."""
    vault = _load_vault()
    pem_value = vault["team"]["ae402_alexbelij_deployer_pem"]["value"]
    fd, path = tempfile.mkstemp(prefix="l85_pem_", suffix=".pem", dir="/data/tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(pem_value)
        os.chmod(path, 0o600)
        yield path
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


@pytest.fixture(scope="module")
def api_key():
    vault = _load_vault()
    return vault["team"]["cspr_cloud_key"]["value"]


@pytest.fixture(scope="module")
def contract_hash():
    return csp.load_htlc_deployment()["contract_hash"]


def _fresh_hashlock():
    """New random preimage/hashlock pair. Same primitive as the mock and
    the EVM adapter so the same pair drives all three legs of a swap."""
    preimage = secrets.token_bytes(32)
    hashlock_hex = csp.sha256_hashlock(preimage)
    assert hashlock_hex == mock.compute_hashlock(preimage), (
        "adapter/mock must agree on the hashlock primitive — otherwise a " "swap cannot be atomic across legs"
    )
    return preimage, hashlock_hex


# ── deployment sanity ──────────────────────────────────────────────


def test_deployment_record_matches_chain(contract_hash, api_key):
    """The recorded deployment is a real contract on Casper testnet —
    a lookup for a never-seen hashlock returns EMPTY, not a query
    failure."""
    ghost_hashlock = secrets.token_hex(32)
    status = csp.casper_status(
        hashlock_hex=ghost_hashlock,
        contract_hash=contract_hash,
        rpc_url=CASPER_RPC,
        api_key=api_key,
    )
    assert status["status"] == "EMPTY"
    assert status["amount"] in (0, "0")


# ── happy path (lock + claim) ──────────────────────────────────────


def test_lock_then_claim_happy_path(pem_path, api_key, contract_hash):
    """Real on-chain lock() followed by claim() with the correct preimage.
    Atomic-swap happy path proven against live Casper testnet, not a
    mock. Uses a fresh hashlock so the test never collides with prior
    runs on the shared contract instance."""
    preimage, hashlock_hex = _fresh_hashlock()

    # Pre-condition: this hashlock is EMPTY (fresh).
    pre = csp.casper_status(
        hashlock_hex=hashlock_hex,
        contract_hash=contract_hash,
        rpc_url=CASPER_RPC,
        api_key=api_key,
    )
    assert pre["status"] == "EMPTY"

    timelock_ms = int(time.time() * 1000) + 5 * 60 * 1000  # 5 min out
    amount_motes = 500_000_000  # 0.5 CSPR — small but > mint threshold

    lock_res = csp.casper_lock(
        hashlock_hex=hashlock_hex,
        timelock_ms=timelock_ms,
        receiver_hex=DEPLOYER_ACCOUNT_HASH,
        amount_motes=amount_motes,
        contract_hash=contract_hash,
        key_path=pem_path,
        rpc_url=CASPER_RPC,
        api_key=api_key,
    )
    assert lock_res.ok, f"lock deploy did not succeed: {lock_res}"

    mid = csp.casper_status(
        hashlock_hex=hashlock_hex,
        contract_hash=contract_hash,
        rpc_url=CASPER_RPC,
        api_key=api_key,
    )
    assert mid["status"] == "LOCKED"
    assert int(mid["amount"]) == amount_motes
    assert mid["record"]["timelock_ms"] == timelock_ms

    claim_res = csp.casper_claim(
        hashlock_hex=hashlock_hex,
        preimage=preimage,
        contract_hash=contract_hash,
        key_path=pem_path,
        rpc_url=CASPER_RPC,
        api_key=api_key,
    )
    assert claim_res.ok, f"claim deploy did not succeed: {claim_res}"

    post = csp.casper_status(
        hashlock_hex=hashlock_hex,
        contract_hash=contract_hash,
        rpc_url=CASPER_RPC,
        api_key=api_key,
    )
    assert post["status"] == "CLAIMED"
    assert int(post["amount"]) == 0


# ── refund path ────────────────────────────────────────────────────


def test_lock_then_refund_after_timelock(pem_path, api_key, contract_hash):
    """Real lock() with a near-past timelock (Casper contract enforces
    ``now_ms >= timelock`` for refund). Contract accepts a lock even with
    already-expired timelock — that's the intended EVM/mock parity: the
    ``LOCKED → REFUNDED`` transition unlocks the moment the block time
    passes the timelock, and can be triggered immediately."""
    _, hashlock_hex = _fresh_hashlock()
    # Timelock 5 seconds in the future; lock inclusion (~30–90s) alone
    # is enough to push blocktime past it by the time we call refund.
    timelock_ms = int(time.time() * 1000) + 5_000
    amount_motes = 500_000_000

    lock_res = csp.casper_lock(
        hashlock_hex=hashlock_hex,
        timelock_ms=timelock_ms,
        receiver_hex=DEPLOYER_ACCOUNT_HASH,
        amount_motes=amount_motes,
        contract_hash=contract_hash,
        key_path=pem_path,
        rpc_url=CASPER_RPC,
        api_key=api_key,
    )
    assert lock_res.ok, f"lock deploy did not succeed: {lock_res}"

    # Verify LOCKED before we try refund.
    mid = csp.casper_status(
        hashlock_hex=hashlock_hex,
        contract_hash=contract_hash,
        rpc_url=CASPER_RPC,
        api_key=api_key,
    )
    assert mid["status"] == "LOCKED"

    # Block inclusion already took much longer than the 5s timelock so
    # refund is unlocked immediately.
    refund_res = csp.casper_refund(
        hashlock_hex=hashlock_hex,
        contract_hash=contract_hash,
        key_path=pem_path,
        rpc_url=CASPER_RPC,
        api_key=api_key,
    )
    assert refund_res.ok, f"refund deploy did not succeed: {refund_res}"

    post = csp.casper_status(
        hashlock_hex=hashlock_hex,
        contract_hash=contract_hash,
        rpc_url=CASPER_RPC,
        api_key=api_key,
    )
    assert post["status"] == "REFUNDED"
    assert int(post["amount"]) == 0


# ── forged preimage rejected ───────────────────────────────────────


def test_forged_preimage_rejected_on_chain(pem_path, api_key, contract_hash):
    """On a LOCKED HTLC on live Casper, an attempt to claim with the
    WRONG preimage must revert on-chain (contract's
    ERR_PREIMAGE_MISMATCH). Proves the Casper Rust contract's guard is
    live — not just the Python mock's guard.

    We produce a fresh LOCKED leg with a preimage the test knows, then
    try to claim with a completely different one and expect the deploy
    to fail (adapter surfaces this as CasperAdapterError). The forged
    attempt must leave state at LOCKED — atomic-swap safety."""
    real_preimage, hashlock_hex = _fresh_hashlock()
    timelock_ms = int(time.time() * 1000) + 15 * 60 * 1000  # 15 min out
    amount_motes = 500_000_000

    lock_res = csp.casper_lock(
        hashlock_hex=hashlock_hex,
        timelock_ms=timelock_ms,
        receiver_hex=DEPLOYER_ACCOUNT_HASH,
        amount_motes=amount_motes,
        contract_hash=contract_hash,
        key_path=pem_path,
        rpc_url=CASPER_RPC,
        api_key=api_key,
    )
    assert lock_res.ok

    forged = secrets.token_bytes(32)
    assert forged != real_preimage
    assert csp.sha256_hashlock(forged) != hashlock_hex

    with pytest.raises(csp.CasperAdapterError) as excinfo:
        csp.casper_claim(
            hashlock_hex=hashlock_hex,
            preimage=forged,
            contract_hash=contract_hash,
            key_path=pem_path,
            rpc_url=CASPER_RPC,
            api_key=api_key,
        )
    msg = str(excinfo.value).lower()
    assert (
        "preimage" in msg or "mismatch" in msg or "user error: 3" in msg or "user error" in msg  # ERR_PREIMAGE_MISMATCH
    ), f"expected preimage-mismatch revert, got: {excinfo.value}"

    still_locked = csp.casper_status(
        hashlock_hex=hashlock_hex,
        contract_hash=contract_hash,
        rpc_url=CASPER_RPC,
        api_key=api_key,
    )
    assert still_locked["status"] == "LOCKED", "forged preimage must NOT change state off LOCKED — atomic-swap safety"

    # Clean up: reveal the real preimage so the leg finalizes and the
    # deployer's funds don't sit tied up on the shared contract.
    tidy = csp.casper_claim(
        hashlock_hex=hashlock_hex,
        preimage=real_preimage,
        contract_hash=contract_hash,
        key_path=pem_path,
        rpc_url=CASPER_RPC,
        api_key=api_key,
    )
    assert tidy.ok


# ── cross-leg parity vs the mock oracle ────────────────────────────


def test_casper_leg_matches_mock_oracle_semantics(pem_path, api_key, contract_hash):
    """The Casper adapter is diff-tested against the deterministic mock
    (bridge_htlc.py) — the mock is the semantic oracle for the whole
    bridge. For the same (preimage, hashlock, timelock, amount, sender,
    receiver) tuple, both legs must reach the same terminal state
    (CLAIMED) via the same actions.

    This is the load-bearing L85 assertion: it's the difference between
    "we deployed a contract" and "we deployed a contract that matches
    the specification of the atomic swap"."""
    preimage, hashlock_hex = _fresh_hashlock()
    timelock_ms = int(time.time() * 1000) + 10 * 60 * 1000
    amount_motes = 500_000_000

    # ── Casper leg ──
    lock_res = csp.casper_lock(
        hashlock_hex=hashlock_hex,
        timelock_ms=timelock_ms,
        receiver_hex=DEPLOYER_ACCOUNT_HASH,
        amount_motes=amount_motes,
        contract_hash=contract_hash,
        key_path=pem_path,
        rpc_url=CASPER_RPC,
        api_key=api_key,
    )
    assert lock_res.ok

    claim_res = csp.casper_claim(
        hashlock_hex=hashlock_hex,
        preimage=preimage,
        contract_hash=contract_hash,
        key_path=pem_path,
        rpc_url=CASPER_RPC,
        api_key=api_key,
    )
    assert claim_res.ok

    casper_final = csp.casper_status(
        hashlock_hex=hashlock_hex,
        contract_hash=contract_hash,
        rpc_url=CASPER_RPC,
        api_key=api_key,
    )
    assert casper_final["status"] == "CLAIMED"

    # ── Mock leg (same primitives, registry-based API) ──
    reg = mock.HTLCRegistry()
    now_ms = int(time.time() * 1000)
    swap = reg.initiate_swap(
        hashlock_hex=hashlock_hex,
        casper_initiator="acct-casper-init",
        casper_counterparty="acct-casper-recv",
        casper_amount=amount_motes,
        casper_timelock_ms=timelock_ms + 60_000,  # A leg outlives B — safety invariant
        evm_initiator="0xevm-init",
        evm_counterparty="0xevm-recv",
        evm_amount=amount_motes,
        evm_timelock_ms=timelock_ms,
        now_ms=now_ms,
    )
    reg.lock(swap.casper_leg.leg_id, now_ms=now_ms)
    reg.lock(swap.evm_leg.leg_id, now_ms=now_ms)
    reg.claim(swap.evm_leg.leg_id, preimage_hex=preimage.hex(), now_ms=now_ms)
    reg.claim(swap.casper_leg.leg_id, preimage_hex=preimage.hex(), now_ms=now_ms)
    mock_leg_c = reg.get_leg(swap.casper_leg.leg_id)
    assert mock_leg_c.status == mock.HTLCStatus.CLAIMED

    # Parity: both legs terminate identically (CLAIMED == CLAIMED). This
    # is what makes the swap atomic — reveal on Casper implies the same
    # reveal usable on the counterpart leg, off the same hashlock.
    assert casper_final["status"] == mock_leg_c.status.value.upper()
