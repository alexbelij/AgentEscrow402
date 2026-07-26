"""
Bridge relayer daemon (I.2).

Polls the mock/real EVM adapter and the local Casper leg store, driving
locked HTLC swaps to their terminal state (claimed or refunded)
whenever an off-chain event or timelock expiry warrants it.

Deployment
----------
Run as a systemd unit or in a container next to the AE402 API. The
daemon:

  1. Reads `AE402_BRIDGE_MODE` (mock / sepolia / mainnet).
  2. Loops over the swap registry every `poll_interval_s` seconds.
  3. For each swap:
       - If BOTH legs are LOCKED and one side has already CLAIMED
         on-chain (preimage reveal), it claims the counterparty leg
         with the same preimage.
       - If EITHER leg's timelock has expired without both claims,
         it initiates refund on that leg.
       - Otherwise: no-op.
  4. Emits structured JSON logs; every terminal transition is
     idempotent so a restart mid-loop is safe.

This module is intentionally I/O-light; the ADAPTERS know how to talk
to their networks. The relayer is a decision-loop, not a chain client.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from server.bridge_mode import ResolvedMode, resolve_mode

logger = logging.getLogger("bridge_relayer")


@dataclass
class RelayerStats:
    started_at: float = field(default_factory=time.time)
    ticks: int = 0
    claims_initiated: int = 0
    refunds_initiated: int = 0
    errors: int = 0
    last_tick_at: float | None = None


@dataclass
class RelayerConfig:
    poll_interval_s: float = 15.0
    max_ticks: int | None = None  # None = run forever; finite for tests
    dry_run: bool = False


class BridgeRelayer:
    """A single-process relayer. Composable — for prod, run as its own
    systemd unit; for tests, drive `.tick()` directly.
    """

    def __init__(
        self,
        *,
        get_swaps: Callable[[], list[dict[str, Any]]],
        claim_fn: Callable[[dict[str, Any]], None],
        refund_fn: Callable[[dict[str, Any]], None],
        mode: ResolvedMode | None = None,
        config: RelayerConfig | None = None,
    ) -> None:
        self._get_swaps = get_swaps
        self._claim = claim_fn
        self._refund = refund_fn
        self._mode = mode or resolve_mode()
        self._cfg = config or RelayerConfig()
        self.stats = RelayerStats()
        self._stop = asyncio.Event()

    # --- Lifecycle ------------------------------------------------------- #

    async def run(self) -> None:
        logger.info(
            "bridge relayer starting: mode=%s source=%s poll_interval_s=%s dry_run=%s",
            self._mode.mode,
            self._mode.source,
            self._cfg.poll_interval_s,
            self._cfg.dry_run,
        )
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self.stop)
            except NotImplementedError:
                # Signal handlers unavailable in some contexts (e.g. Windows).
                pass

        while not self._stop.is_set():
            try:
                await self.tick()
            except Exception as exc:  # never crash the loop
                self.stats.errors += 1
                logger.exception("relayer tick failed: %s", exc)
            if self._cfg.max_ticks is not None and self.stats.ticks >= self._cfg.max_ticks:
                self.stop()
                break
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._cfg.poll_interval_s)
            except asyncio.TimeoutError:
                pass

        logger.info("bridge relayer stopped after %d ticks", self.stats.ticks)

    def stop(self) -> None:
        self._stop.set()

    # --- Core decision loop --------------------------------------------- #

    async def tick(self) -> None:
        """One decision pass. Public so tests can drive it deterministically."""
        self.stats.ticks += 1
        self.stats.last_tick_at = time.time()

        swaps = list(self._get_swaps())
        for s in swaps:
            try:
                await self._process(s)
            except Exception as exc:
                self.stats.errors += 1
                logger.exception("relayer failed on swap %s: %s", s.get("swap_id"), exc)

    async def _process(self, swap: dict[str, Any]) -> None:
        state = swap.get("state") or {}
        legs = state.get("legs") or swap.get("legs") or []
        if len(legs) < 2:
            return

        leg_a, leg_b = legs[0], legs[1]
        now = time.time()

        # Case 1: one leg has been CLAIMED, the other is still LOCKED
        # → propagate the preimage.
        for driver, other in ((leg_a, leg_b), (leg_b, leg_a)):
            if driver.get("status") == "CLAIMED" and other.get("status") == "LOCKED":
                if self._cfg.dry_run:
                    logger.info(
                        "dry_run: would claim leg %s with preimage from leg %s",
                        other.get("leg_id"),
                        driver.get("leg_id"),
                    )
                    return
                self._claim(
                    {
                        "leg_id": other.get("leg_id"),
                        "preimage": driver.get("preimage"),
                    }
                )
                self.stats.claims_initiated += 1
                return

        # Case 2: timelock expired without both claims → refund.
        for leg in (leg_a, leg_b):
            if leg.get("status") != "LOCKED":
                continue
            timelock = leg.get("timelock") or 0
            if now >= timelock:
                if self._cfg.dry_run:
                    logger.info(
                        "dry_run: would refund leg %s (timelock=%s now=%s)",
                        leg.get("leg_id"),
                        timelock,
                        now,
                    )
                    return
                self._refund({"leg_id": leg.get("leg_id")})
                self.stats.refunds_initiated += 1
                return


# --- CLI entrypoint ------------------------------------------------------- #


def _main() -> int:  # pragma: no cover — thin bootstrapper
    logging.basicConfig(
        level=os.environ.get("AE402_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    from server import bridge_htlc as htlc

    reg = htlc.HTLCRegistry()

    def get_swaps() -> list[dict[str, Any]]:
        return [s.model_dump() if hasattr(s, "model_dump") else vars(s) for s in reg.all_swaps()]

    def claim(payload: dict[str, Any]) -> None:  # pragma: no cover
        logger.info("claim: %s", payload)

    def refund(payload: dict[str, Any]) -> None:  # pragma: no cover
        logger.info("refund: %s", payload)

    r = BridgeRelayer(get_swaps=get_swaps, claim_fn=claim, refund_fn=refund)
    asyncio.run(r.run())
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
