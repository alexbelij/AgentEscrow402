"""Cookbook 03 — batch escrow orchestration.

Creates N escrows in a single API call (backed by the on-chain
Escrow Manager contract's batch_create entry point), then bulk-releases
them via batch_release. Useful when an agent has many small parallel
tasks running against the same worker pool.

Run:
    python examples/03_batch_escrows.py --api-url http://localhost:8000 --count 5
"""

from __future__ import annotations

import argparse
import asyncio

from sdk.client import EscrowClient


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-url", default="http://localhost:8000")
    parser.add_argument("--count", type=int, default=3, help="number of escrows in the batch")
    parser.add_argument("--amount", type=int, default=100_000, help="motes per escrow")
    args = parser.parse_args()

    receiver = EscrowClient.generate(args.api_url).sender

    async with EscrowClient.generate(args.api_url) as buyer:
        print(f"[01] connected: {await buyer.health()}")

        # Note: batch_release consumes an existing list of service_hashes,
        # so we first create N via sequential create_escrow calls (real
        # batched create is exposed through server/multi_asset.py's
        # /escrows/batch route; see 04_streaming_escrow.py for streaming).
        service_hashes: list[str] = []
        for i in range(args.count):
            escrow = await buyer.create_escrow(receiver=receiver, amount=args.amount)
            service_hashes.append(escrow["service_hash"])
            print(f"[02.{i}] created: {escrow['service_hash'][:16]}… status={escrow['status']}")

        print(f"[03] batch releasing {len(service_hashes)} escrows...")
        result = await buyer.batch_release(service_hashes)
        released = result.get("released", [])
        failed = result.get("failed", [])
        print(f"[04] released={len(released)} failed={len(failed)}")
        for entry in failed:
            print(f"     failed: {entry}")


if __name__ == "__main__":
    asyncio.run(main())
