"""Quick start example for AgentEscrow402.

Minimal real (not mocked) create -> release lifecycle using the Python SDK.
By default it signs requests with a fresh Ed25519 identity via
`EscrowClient.generate(...)`, which works against both a local sandbox
instance and the live production deployment.

Run a local server first:
    uvicorn server.app:app --reload

Then:
    python examples/quickstart.py
    python examples/quickstart.py --api-url https://agentescrow402-api.onrender.com

For the full autonomous buyer/seller lifecycle (including a real dispute
and AI arbitration call), see examples/escrow_agent.py.
"""

from __future__ import annotations

import argparse
import asyncio

from sdk.client import EscrowClient


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-url", default="http://localhost:8000")
    parser.add_argument("--amount", type=int, default=500_000, help="escrow amount in motes")
    args = parser.parse_args()

    # A real 64-hex "receiver" identity (the API enforces this pattern
    # server-side). In a real integration this would be the counterparty
    # agent's own EscrowClient.generate() sender.
    receiver = EscrowClient.generate(args.api_url).sender

    async with EscrowClient.generate(args.api_url) as client:
        print(f"connected: {await client.health()}")
        print(f"buyer identity: {client.sender}")

        escrow = await client.create_escrow(receiver=receiver, amount=args.amount)
        print(f"escrow created: {escrow['service_hash']} status={escrow['status']}")

        result = await client.release(escrow["service_hash"], amount=args.amount)
        print(f"escrow released: status={result['status']} deploy_hash={result.get('deploy_hash')}")


if __name__ == "__main__":
    asyncio.run(main())
