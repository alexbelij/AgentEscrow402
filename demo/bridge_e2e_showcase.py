#!/usr/bin/env python3
"""
Bridge end-to-end showcase (I.4).

Deterministic walkthrough of a full HTLC cross-chain swap using the
mock EVM adapter. Same nine steps we'd run against Sepolia, only
without a real chain in the loop — so a judge can watch the whole
lifecycle in ~two seconds, byte-for-byte reproducible.

Steps
-----
  1. initiate_swap        (casper + evm legs registered, PROPOSED)
  2. lock casper leg      (LOCKED)
  3. lock evm leg         (LOCKED — both legs now under hashlock)
  4. claim evm leg        (preimage revealed on the EVM side)
  5. claim casper leg     (same preimage propagates on Casper)
  6. verify terminal state (BOTH CLAIMED, atomic swap complete)
  7. (parallel path) start a second swap, only lock, then refund
  8. verify refund state  (REFUNDED, safety invariant honoured)
  9. print summary + exit 0

Related:
  - server/bridge_htlc.py           (state machine under test)
  - server/bridge_evm_adapter.py    (Sepolia adapter — swappable)
  - server/bridge_mode.py           (mode selector)
  - server/bridge_relayer.py        (relayer daemon that drives 4-5 in prod)
  - tests/test_bridge_production_path.py
"""

from __future__ import annotations

import hashlib
import os
import sys

os.environ.setdefault("AE402_BRIDGE_MODE", "mock")

G = "\033[32m"
R = "\033[31m"
Y = "\033[33m"
B = "\033[36m"
D = "\033[2m"
X = "\033[0m"


def _box(title: str) -> None:
    bar = "─" * 62
    print(f"\n{B}┌{bar}┐{X}")
    print(f"{B}│{X} {title}{' ' * (61 - len(title))}{B}│{X}")
    print(f"{B}└{bar}┘{X}")


def _step(idx: int, name: str) -> None:
    print(f"\n{Y}▶ Step {idx} — {name}{X}")


def _ok(msg: str) -> None:
    print(f"  {G}✓{X} {msg}")


def _fail(msg: str) -> None:
    print(f"  {R}✗{X} {msg}")


def _dump(label: str, obj: object) -> None:
    print(f"  {D}{label}: {obj}{X}")


def run() -> int:
    from server.bridge_htlc import (
        HTLCRegistry,
        HTLCStatus,
        compute_hashlock,
    )
    from server.bridge_mode import resolve_mode

    _box(" AE402 · Bridge end-to-end showcase (I.4)")
    mode = resolve_mode()
    print(f"{D}  mode={mode.mode} (source={mode.source}){X}")

    ok = 0
    fail = 0

    def _check(cond: bool, msg: str) -> None:
        nonlocal ok, fail
        if cond:
            _ok(msg)
            ok += 1
        else:
            _fail(msg)
            fail += 1

    # ------------------------------------------------------------------ #
    # Happy path
    # ------------------------------------------------------------------ #
    preimage = hashlib.sha256(b"AE402-happy-path").digest()
    hashlock = compute_hashlock(preimage)
    reg = HTLCRegistry()

    _step(1, "Initiate swap (casper + evm legs → PROPOSED)")
    swap = reg.initiate_swap(
        hashlock_hex=hashlock,
        casper_initiator="alice.casper",
        casper_counterparty="bob.casper",
        casper_amount=1_000_000_000,  # 1 CSPR
        casper_timelock_ms=2_000_000,
        evm_initiator="alice.evm",
        evm_counterparty="bob.evm",
        evm_amount=200_000_000_000_000_000,  # 0.2 ETH-mock
        evm_timelock_ms=1_000_000,
        now_ms=0,
    )
    _dump("swap_id", swap.swap_id[:24] + "…")
    _check(
        swap.casper_leg.status == HTLCStatus.PROPOSED
        and swap.evm_leg.status == HTLCStatus.PROPOSED,
        "both legs PROPOSED",
    )

    _step(2, "Lock casper leg")
    reg.lock(swap.casper_leg.leg_id, now_ms=1)
    updated = reg.get_swap(swap.swap_id)
    _check(updated.casper_leg.status == HTLCStatus.LOCKED, "casper leg LOCKED")

    _step(3, "Lock evm leg (both legs now under hashlock)")
    reg.lock(swap.evm_leg.leg_id, now_ms=2)
    updated = reg.get_swap(swap.swap_id)
    _check(updated.evm_leg.status == HTLCStatus.LOCKED, "evm leg LOCKED")

    _step(4, "Claim evm leg → preimage revealed on-chain")
    reg.claim(swap.evm_leg.leg_id, preimage_hex=preimage.hex(), now_ms=3)
    updated = reg.get_swap(swap.swap_id)
    _check(updated.evm_leg.status == HTLCStatus.CLAIMED, "evm leg CLAIMED")

    _step(5, "Claim casper leg → same preimage propagates")
    reg.claim(swap.casper_leg.leg_id, preimage_hex=preimage.hex(), now_ms=4)
    updated = reg.get_swap(swap.swap_id)
    _check(updated.casper_leg.status == HTLCStatus.CLAIMED, "casper leg CLAIMED")

    _step(6, "Verify atomic swap complete")
    _check(
        updated.casper_leg.status == HTLCStatus.CLAIMED
        and updated.evm_leg.status == HTLCStatus.CLAIMED,
        "both legs CLAIMED — atomic swap complete",
    )

    # ------------------------------------------------------------------ #
    # Refund path
    # ------------------------------------------------------------------ #
    _step(7, "Start second swap → lock → let timelock expire → refund")
    preimage2 = hashlib.sha256(b"AE402-refund-path").digest()
    hashlock2 = compute_hashlock(preimage2)
    swap2 = reg.initiate_swap(
        hashlock_hex=hashlock2,
        casper_initiator="charlie.casper",
        casper_counterparty="dave.casper",
        casper_amount=500_000_000,
        casper_timelock_ms=2_000_000,
        evm_initiator="charlie.evm",
        evm_counterparty="dave.evm",
        evm_amount=100_000_000_000_000_000,
        evm_timelock_ms=1_000_000,
        now_ms=0,
    )
    reg.lock(swap2.casper_leg.leg_id, now_ms=1)
    reg.lock(swap2.evm_leg.leg_id, now_ms=2)
    # Advance past evm (shorter) timelock first — safety invariant.
    reg.refund(swap2.evm_leg.leg_id, now_ms=1_000_001)
    reg.refund(swap2.casper_leg.leg_id, now_ms=2_000_001)

    _step(8, "Verify refund terminal state")
    updated2 = reg.get_swap(swap2.swap_id)
    _check(
        updated2.casper_leg.status == HTLCStatus.REFUNDED
        and updated2.evm_leg.status == HTLCStatus.REFUNDED,
        "both legs REFUNDED — funds returned to initiators",
    )

    # ------------------------------------------------------------------ #
    _box(f" Summary — {ok} pass · {fail} fail")
    if fail > 0:
        print(f"{R}Bridge showcase regressed.{X}")
        return 1
    print(f"{G}All 8 steps green — happy path + refund path both terminal.{X}")
    print(
        f"{D}  To drive the same nine steps against Sepolia, set "
        f"AE402_BRIDGE_MODE=sepolia + run scripts/bridge_smoke_sepolia.py{X}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(run())
