"""Tests for the bridge production path (I).

Covers:
  I.1  bridge-mode selector + safety fuse
  I.2  relayer decision loop (claim-propagation + refund-on-expiry)
  I.3  diff-test: mock adapter and (fake) real-adapter outcomes agree
  I.5  refund lifecycle end-to-end via the relayer
"""

from __future__ import annotations

import asyncio
import time

import pytest

from server.bridge_mode import BridgeModeError, is_live_chain, resolve_mode
from server.bridge_relayer import BridgeRelayer, RelayerConfig

# --- I.1 mode selector ---------------------------------------------------- #


def test_default_mode_is_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AE402_BRIDGE_MODE", raising=False)
    r = resolve_mode()
    assert r.mode == "mock"
    assert r.source == "default"
    assert is_live_chain() is False


def test_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AE402_BRIDGE_MODE", "sepolia")
    r = resolve_mode()
    assert r.mode == "sepolia"
    assert r.source == "env"
    assert is_live_chain() is True


def test_kwarg_beats_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AE402_BRIDGE_MODE", "sepolia")
    r = resolve_mode(mode="mock")
    assert r.mode == "mock"
    assert r.source == "kwarg"


def test_unknown_mode_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AE402_BRIDGE_MODE", "elrond")
    with pytest.raises(BridgeModeError, match="unknown"):
        resolve_mode()


def test_mainnet_refused_without_ack(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AE402_BRIDGE_MODE", "mainnet")
    monkeypatch.delenv("AE402_BRIDGE_ALLOW_MAINNET", raising=False)
    with pytest.raises(BridgeModeError, match="mainnet"):
        resolve_mode()


def test_mainnet_allowed_with_explicit_ack(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AE402_BRIDGE_MODE", "mainnet")
    monkeypatch.setenv("AE402_BRIDGE_ALLOW_MAINNET", "1")
    r = resolve_mode()
    assert r.mode == "mainnet"
    assert is_live_chain() is True


# --- I.2 relayer decision loop ------------------------------------------- #


def _swap(
    *,
    leg_a_status: str,
    leg_b_status: str,
    preimage: str | None = None,
    a_timelock: float = 1e12,
    b_timelock: float = 1e12,
) -> dict:
    return {
        "swap_id": "SW-1",
        "state": {
            "legs": [
                {
                    "leg_id": "A",
                    "status": leg_a_status,
                    "preimage": preimage if leg_a_status == "CLAIMED" else None,
                    "timelock": a_timelock,
                },
                {
                    "leg_id": "B",
                    "status": leg_b_status,
                    "preimage": preimage if leg_b_status == "CLAIMED" else None,
                    "timelock": b_timelock,
                },
            ]
        },
    }


def _run(relayer: BridgeRelayer) -> None:
    asyncio.get_event_loop_policy()  # touch to ensure loop is available
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(relayer.tick())
    finally:
        loop.close()


def test_relayer_no_op_when_both_locked_and_in_time() -> None:
    calls: list[dict] = []

    def claim(p: dict) -> None:
        calls.append({"kind": "claim", **p})

    def refund(p: dict) -> None:
        calls.append({"kind": "refund", **p})

    swap = _swap(
        leg_a_status="LOCKED",
        leg_b_status="LOCKED",
        a_timelock=time.time() + 3600,
        b_timelock=time.time() + 1800,
    )
    r = BridgeRelayer(
        get_swaps=lambda: [swap],
        claim_fn=claim,
        refund_fn=refund,
        config=RelayerConfig(max_ticks=1),
    )
    _run(r)
    assert calls == []
    assert r.stats.ticks == 1
    assert r.stats.claims_initiated == 0
    assert r.stats.refunds_initiated == 0


def test_relayer_propagates_preimage() -> None:
    calls: list[dict] = []
    swap = _swap(
        leg_a_status="CLAIMED",
        leg_b_status="LOCKED",
        preimage="0xdeadbeef",
        a_timelock=time.time() + 3600,
        b_timelock=time.time() + 1800,
    )

    def claim(p: dict) -> None:
        calls.append({"kind": "claim", **p})

    def refund(p: dict) -> None:
        calls.append({"kind": "refund", **p})

    r = BridgeRelayer(
        get_swaps=lambda: [swap],
        claim_fn=claim,
        refund_fn=refund,
        config=RelayerConfig(max_ticks=1),
    )
    _run(r)
    assert len(calls) == 1
    assert calls[0]["kind"] == "claim"
    assert calls[0]["leg_id"] == "B"
    assert calls[0]["preimage"] == "0xdeadbeef"
    assert r.stats.claims_initiated == 1


def test_relayer_refunds_on_expiry() -> None:
    """I.5 — a leg whose timelock has passed while still LOCKED must refund."""
    calls: list[dict] = []
    swap = _swap(
        leg_a_status="LOCKED",
        leg_b_status="LOCKED",
        a_timelock=time.time() - 60,  # expired
        b_timelock=time.time() + 3600,
    )

    def claim(p: dict) -> None:
        calls.append({"kind": "claim", **p})

    def refund(p: dict) -> None:
        calls.append({"kind": "refund", **p})

    r = BridgeRelayer(
        get_swaps=lambda: [swap],
        claim_fn=claim,
        refund_fn=refund,
        config=RelayerConfig(max_ticks=1),
    )
    _run(r)
    assert len(calls) == 1
    assert calls[0]["kind"] == "refund"
    assert calls[0]["leg_id"] == "A"
    assert r.stats.refunds_initiated == 1


def test_relayer_dry_run_is_idempotent_noop() -> None:
    calls: list[dict] = []
    swap = _swap(
        leg_a_status="CLAIMED",
        leg_b_status="LOCKED",
        preimage="0xabc",
        a_timelock=time.time() + 3600,
        b_timelock=time.time() + 3600,
    )
    r = BridgeRelayer(
        get_swaps=lambda: [swap],
        claim_fn=lambda p: calls.append({"kind": "claim", **p}),
        refund_fn=lambda p: calls.append({"kind": "refund", **p}),
        config=RelayerConfig(max_ticks=1, dry_run=True),
    )
    _run(r)
    assert calls == []
    assert r.stats.claims_initiated == 0


def test_relayer_survives_action_exception() -> None:
    """A crashing claim_fn must not stop the loop from processing other swaps."""
    swaps = [
        _swap(
            leg_a_status="CLAIMED",
            leg_b_status="LOCKED",
            preimage="0xff",
            a_timelock=time.time() + 3600,
            b_timelock=time.time() + 3600,
        ),
        _swap(
            leg_a_status="LOCKED",
            leg_b_status="LOCKED",
            a_timelock=time.time() - 60,
            b_timelock=time.time() + 3600,
        ),
    ]
    calls: list[dict] = []

    def claim(_: dict) -> None:
        raise RuntimeError("simulated RPC failure")

    def refund(p: dict) -> None:
        calls.append({"kind": "refund", **p})

    r = BridgeRelayer(
        get_swaps=lambda: swaps,
        claim_fn=claim,
        refund_fn=refund,
        config=RelayerConfig(max_ticks=1),
    )
    _run(r)
    # The refund on the second swap still fires.
    assert any(c["kind"] == "refund" for c in calls)
    assert r.stats.errors >= 1


# --- I.3 diff-test: mock vs "real" adapter agree on outcomes ------------- #


class _FakeRealAdapter:
    """Stand-in for the Web3 adapter used in tests.

    Mirrors the mock's semantics deterministically so the diff-test can
    run offline; the real adapter is exercised by
    tests/test_bridge_evm_sepolia_integration.py (skipped in CI).
    """

    def __init__(self) -> None:
        self.state = "PROPOSED"
        self.preimage: str | None = None

    def lock(self, hashlock: str, timelock: int) -> str:
        assert self.state == "PROPOSED"
        self.state = "LOCKED"
        return "tx-lock-1"

    def claim(self, preimage: str) -> str:
        assert self.state == "LOCKED"
        self.state = "CLAIMED"
        self.preimage = preimage
        return "tx-claim-1"

    def refund(self) -> str:
        assert self.state == "LOCKED"
        self.state = "REFUNDED"
        return "tx-refund-1"


def test_diff_test_mock_vs_fake_real_claim_path() -> None:
    """Same (hashlock, timelock, preimage) → same CLAIMED terminal state.

    Uses the real HTLCRegistry API from server/bridge_htlc.py, so this
    is a genuine diff against the live mock. The fake real adapter is
    a small in-process shim mirroring the on-chain semantics; the
    heavy Sepolia adapter is exercised by the (skipped-in-CI)
    integration test.
    """
    from server.bridge_htlc import (
        HTLCRegistry,
        HTLCStatus,
        compute_hashlock,
    )

    preimage = bytes.fromhex("22" * 32)
    hashlock_hex = compute_hashlock(preimage)

    reg = HTLCRegistry()
    swap = reg.initiate_swap(
        hashlock_hex=hashlock_hex,
        casper_initiator="alice.casper",
        casper_counterparty="bob.casper",
        casper_amount=1_000_000,
        casper_timelock_ms=1_000_000,
        evm_initiator="alice.evm",
        evm_counterparty="bob.evm",
        evm_amount=500_000,
        evm_timelock_ms=500_000,
        now_ms=0,
    )
    reg.lock(swap.casper_leg.leg_id, now_ms=1)
    reg.lock(swap.evm_leg.leg_id, now_ms=2)
    reg.claim(swap.evm_leg.leg_id, preimage_hex=preimage.hex(), now_ms=3)
    reg.claim(swap.casper_leg.leg_id, preimage_hex=preimage.hex(), now_ms=4)

    updated = reg.get_swap(swap.swap_id)
    assert updated.casper_leg.status == HTLCStatus.CLAIMED
    assert updated.evm_leg.status == HTLCStatus.CLAIMED

    fake = _FakeRealAdapter()
    fake.lock(hashlock_hex, timelock=500_000)
    fake.claim(preimage=preimage.hex())
    assert fake.state == "CLAIMED"
    assert fake.preimage == preimage.hex()


def test_diff_test_mock_vs_fake_real_refund_path() -> None:
    """Same input, no claim, expiry → both adapters end REFUNDED."""
    from server.bridge_htlc import (
        HTLCRegistry,
        HTLCStatus,
        compute_hashlock,
    )

    preimage = bytes.fromhex("aa" * 32)
    hashlock_hex = compute_hashlock(preimage)

    reg = HTLCRegistry()
    swap = reg.initiate_swap(
        hashlock_hex=hashlock_hex,
        casper_initiator="alice.casper",
        casper_counterparty="bob.casper",
        casper_amount=1_000_000,
        casper_timelock_ms=1_000_000,
        evm_initiator="alice.evm",
        evm_counterparty="bob.evm",
        evm_amount=500_000,
        evm_timelock_ms=500_000,
        now_ms=0,
    )
    reg.lock(swap.casper_leg.leg_id, now_ms=1)
    reg.lock(swap.evm_leg.leg_id, now_ms=2)
    # Advance past the EVM timelock (shorter one) — refund the EVM leg
    # first (safety property: shorter timelock refunds first).
    reg.refund(swap.evm_leg.leg_id, now_ms=500_001)
    reg.refund(swap.casper_leg.leg_id, now_ms=1_000_001)

    updated = reg.get_swap(swap.swap_id)
    assert updated.casper_leg.status == HTLCStatus.REFUNDED
    assert updated.evm_leg.status == HTLCStatus.REFUNDED

    fake = _FakeRealAdapter()
    fake.lock(hashlock_hex, timelock=500_000)
    fake.refund()
    assert fake.state == "REFUNDED"
