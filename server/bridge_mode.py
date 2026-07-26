"""
Bridge mode selector (I.1).

Central switch that picks the adapter driving the EVM leg of a bridge
swap. Everything above the adapter is agnostic; the switch chooses
between:

  - "mock":     deterministic in-memory adapter (default; tests / demo)
  - "sepolia":  real Sepolia RPC via server.bridge_evm_adapter
  - "mainnet":  real mainnet — REJECTED unless an explicit safety flag
                 is also set (see check_mainnet_guard)

Selection order:
  1. Explicit `mode=` kwarg (highest precedence, for tests).
  2. `AE402_BRIDGE_MODE` environment variable.
  3. Default: "mock".

The relayer daemon (`server/bridge_relayer.py`) also reads this switch;
if the operator flips `AE402_BRIDGE_MODE=sepolia` at boot, both the
API and the relayer point at the real chain in lockstep.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

BridgeMode = Literal["mock", "sepolia", "mainnet"]

_VALID_MODES: tuple[BridgeMode, ...] = ("mock", "sepolia", "mainnet")


class BridgeModeError(ValueError):
    """Raised when the requested mode is invalid or refused by policy."""


@dataclass(frozen=True)
class ResolvedMode:
    mode: BridgeMode
    source: str  # "kwarg" | "env" | "default"


def resolve_mode(*, mode: str | None = None) -> ResolvedMode:
    """Return the concrete mode and where it came from.

    Raises `BridgeModeError` on an unknown mode string, or on "mainnet"
    without the explicit safety-ack env var
    (`AE402_BRIDGE_ALLOW_MAINNET=1`).
    """

    if mode is not None:
        chosen = mode
        source = "kwarg"
    else:
        env_val = os.environ.get("AE402_BRIDGE_MODE", "").strip().lower()
        if env_val:
            chosen = env_val
            source = "env"
        else:
            chosen = "mock"
            source = "default"

    if chosen not in _VALID_MODES:
        raise BridgeModeError(f"unknown AE402_BRIDGE_MODE={chosen!r}; expected one of " f"{list(_VALID_MODES)!r}")

    if chosen == "mainnet" and os.environ.get("AE402_BRIDGE_ALLOW_MAINNET") != "1":
        raise BridgeModeError(
            "mainnet bridge is refused unless AE402_BRIDGE_ALLOW_MAINNET=1 "
            "is set — this is a safety fuse, not a production toggle"
        )

    return ResolvedMode(mode=chosen, source=source)


def is_live_chain(mode: BridgeMode | None = None) -> bool:
    """True iff the resolved mode drives a real network."""
    r = resolve_mode(mode=mode)
    return r.mode in ("sepolia", "mainnet")
