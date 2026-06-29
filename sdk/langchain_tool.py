"""LangChain-compatible tool wrapper for escrow payments."""

from __future__ import annotations

from typing import Any

from sdk.client import EscrowClient


class EscrowPaymentTool:
    """Tool for AI agents to manage on-chain escrow payments.

    Drop-in for LangChain or any framework that calls ``tool.run()``.

    Supported actions:
        create   — lock funds (requires ``receiver``, ``amount``, optional ``ttl``)
        release  — release funds (requires ``service_hash``)
        refund   — refund funds (requires ``service_hash``)
        dispute  — open dispute (requires ``service_hash``, ``reason_hash``)
        status   — check escrow (requires ``service_hash``)
        reputation — query agent score (requires ``agent``)

    Example::

        tool = EscrowPaymentTool("http://localhost:8000", sender="agent-001")
        result = await tool.run("create", receiver="svc-007", amount=5000)
    """

    name = "escrow_payment"
    description = (
        "Create, release, refund, or dispute escrow payments on Casper Network. "
        "Also query escrow status and agent reputation."
    )

    def __init__(self, base_url: str, sender: str) -> None:
        self._client = EscrowClient(base_url=base_url, sender=sender)

    async def run(self, action: str, **kwargs: Any) -> dict[str, Any]:
        handlers = {
            "create": lambda: self._client.create_escrow(
                receiver=kwargs["receiver"],
                amount=kwargs["amount"],
                ttl=kwargs.get("ttl", 300),
            ),
            "release": lambda: self._client.release(kwargs["service_hash"]),
            "refund": lambda: self._client.refund(kwargs["service_hash"]),
            "dispute": lambda: self._client.dispute(
                kwargs["service_hash"], kwargs["reason_hash"]
            ),
            "status": lambda: self._client.get_escrow(kwargs["service_hash"]),
            "reputation": lambda: self._client.get_reputation(kwargs["agent"]),
        }
        handler = handlers.get(action)
        if handler is None:
            return {"error": f"Unknown action: {action}"}
        return await handler()

    async def close(self) -> None:
        await self._client.close()
