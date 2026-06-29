"""LangChain tool wrapper for escrow payments."""

from __future__ import annotations

from typing import Any

from sdk.client import EscrowClient


class EscrowPaymentTool:
    """LangChain-compatible tool for AI agent escrow payments.

    Usage with LangChain:
        tool = EscrowPaymentTool(base_url="http://localhost:8000", sender="agent-001")
        # Agent can call tool.run(action="create", receiver="...", amount=1000)
    """

    name = "escrow_payment"
    description = (
        "Create, release, or refund escrow payments on Casper Network. "
        "Actions: create, release, refund, status, reputation."
    )

    def __init__(self, base_url: str, sender: str) -> None:
        self._client = EscrowClient(base_url=base_url, sender=sender)

    async def run(self, action: str, **kwargs: Any) -> dict[str, Any]:
        if action == "create":
            return await self._client.create_escrow(
                receiver=kwargs["receiver"],
                amount=kwargs["amount"],
                ttl=kwargs.get("ttl", 300),
            )
        elif action == "release":
            return await self._client.release(kwargs["service_hash"])
        elif action == "refund":
            return await self._client.refund(kwargs["service_hash"])
        elif action == "status":
            return await self._client.get_escrow(kwargs["service_hash"])
        elif action == "reputation":
            return await self._client.get_reputation(kwargs["agent"])
        else:
            return {"error": f"Unknown action: {action}"}

    async def close(self) -> None:
        await self._client.close()
