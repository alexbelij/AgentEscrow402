"""CEP-88 event monitor with SSE fallback polling."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

import httpx

logger = logging.getLogger(__name__)

# C11: last-known chain-tip block height, published by whatever EventMonitor
# instance is running. Read by flash_guard integration in server/app.py via
# get_last_block_height(); 0 means "unknown", in which case the block-delay
# half of flash_guard is skipped. Written from a single background task,
# read by request handlers — int assignment is atomic in CPython so we do
# not need an explicit lock.
_LAST_KNOWN_BLOCK_HEIGHT: int = 0


def get_last_block_height() -> int:
    """Return the last block height observed by any EventMonitor.

    Returns 0 when the monitor has not observed any block yet (fresh
    process, sandbox mode, or offline test suite). Callers must treat 0
    as "unknown" and skip block-based checks accordingly.
    """
    return _LAST_KNOWN_BLOCK_HEIGHT


class EventMonitor:
    """Monitors Casper contract events via SSE with polling fallback."""

    def __init__(
        self,
        node_url: str,
        contract_hash: str,
        poll_interval: float = 5.0,
    ) -> None:
        self._node_url = node_url
        self._contract_hash = contract_hash
        self._poll_interval = poll_interval
        self._handlers: dict[str, list[Callable]] = {}
        self._running = False
        self._last_block_height = 0
        self._http = httpx.AsyncClient(timeout=30.0)

    def on(self, event_type: str, handler: Callable) -> None:
        self._handlers.setdefault(event_type, []).append(handler)

    async def start(self) -> None:
        self._running = True
        logger.info("Event monitor started for %s", self._contract_hash)
        try:
            await self._try_sse()
        except Exception:
            logger.warning("SSE unavailable, falling back to polling")
            await self._poll_loop()

    async def stop(self) -> None:
        self._running = False
        await self._http.aclose()

    async def _try_sse(self) -> None:
        sse_url = f"{self._node_url}/events/main"
        async with self._http.stream("GET", sse_url) as stream:
            async for line in stream.aiter_lines():
                if not self._running:
                    break
                if line.startswith("data:"):
                    await self._process_sse_event(line[5:].strip())

    async def _poll_loop(self) -> None:
        while self._running:
            try:
                await self._poll_once()
            except Exception:
                logger.exception("Poll cycle failed")
            await asyncio.sleep(self._poll_interval)

    async def _poll_once(self) -> None:
        resp = await self._http.post(
            self._node_url + "/rpc",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "chain_get_block",
                "params": {},
            },
        )
        body = resp.json()
        result = body.get("result", {})
        block = result.get("block", {})
        header = block.get("header", {})
        height = header.get("height", 0)

        # C11: publish the observed tip so flash_guard's block-delay half
        # can consult it from request handlers without a monitor reference.
        global _LAST_KNOWN_BLOCK_HEIGHT
        if height > _LAST_KNOWN_BLOCK_HEIGHT:
            _LAST_KNOWN_BLOCK_HEIGHT = height
        if height <= self._last_block_height:
            return

        self._last_block_height = height
        transfers = block.get("body", {}).get("transfer_hashes", [])
        for tx_hash in transfers:
            await self._check_deploy_events(tx_hash)

    async def _check_deploy_events(self, deploy_hash: str) -> None:
        resp = await self._http.post(
            self._node_url + "/rpc",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "info_get_deploy",
                "params": {"deploy_hash": deploy_hash},
            },
        )
        body = resp.json()
        result = body.get("result", {})
        transforms = (
            result.get("execution_results", [{}])[0]
            .get("result", {})
            .get("Success", {})
            .get("effect", {})
            .get("transforms", [])
        )
        for transform in transforms:
            written = transform.get("transform", {})
            if isinstance(written, dict) and "WriteCLValue" in written:
                await self._dispatch(written["WriteCLValue"])

    async def _dispatch(self, cl_value: dict[str, Any]) -> None:
        parsed = cl_value.get("parsed")
        if not isinstance(parsed, dict):
            return
        event_type = parsed.get("type", "")
        handlers = self._handlers.get(event_type, [])
        for handler in handlers:
            try:
                await handler(parsed)
            except Exception:
                logger.exception("Handler failed for event %s", event_type)

    async def _process_sse_event(self, data: str) -> None:
        import json

        try:
            event = json.loads(data)
        except json.JSONDecodeError:
            return

        deploy_processed = event.get("DeployProcessed")
        if deploy_processed is None:
            return

        transforms = (
            deploy_processed.get("execution_result", {}).get("Success", {}).get("effect", {}).get("transforms", [])
        )
        for transform in transforms:
            written = transform.get("transform", {})
            if isinstance(written, dict) and "WriteCLValue" in written:
                await self._dispatch(written["WriteCLValue"])
