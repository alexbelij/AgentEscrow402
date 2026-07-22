"""Cookbook 04 — streaming escrow with time-vested claims.

Creates a streaming escrow (funds vest linearly over a duration) and
demonstrates claiming the currently-vested portion at intervals.
Streaming escrows are exposed via the /escrows/stream endpoints and
are useful for pay-per-second agent work or long-running compute jobs.

Run:
    python examples/04_streaming_escrow.py --api-url http://localhost:8000

Notes:
- The /escrows/stream endpoint requires the server to have the
  multi_asset router enabled (it is enabled by default in
  server/app.py). Against a stripped sandbox that has disabled the
  router the example will surface a clean 404 and exit.
"""

from __future__ import annotations

import argparse
import asyncio

import httpx

from sdk.client import EscrowClient


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-url", default="http://localhost:8000")
    parser.add_argument("--total-amount", type=int, default=1_000_000, help="total motes vesting")
    parser.add_argument("--duration-seconds", type=int, default=60)
    args = parser.parse_args()

    receiver = EscrowClient.generate(args.api_url).sender

    async with EscrowClient.generate(args.api_url) as buyer:
        print(f"[01] connected: {await buyer.health()}")

        # Streaming create is an extension route not on the base client;
        # go raw for the create, then use the client for claim_stream.
        try:
            async with httpx.AsyncClient(base_url=args.api_url, timeout=30.0) as raw:
                r = await raw.post(
                    "/escrows/stream",
                    json={
                        "sender": buyer.sender,
                        "receiver": receiver,
                        "total_amount": args.total_amount,
                        "duration_seconds": args.duration_seconds,
                    },
                )
                if r.status_code == 404:
                    print("[02] /escrows/stream not available on this server (multi_asset router disabled)")
                    return
                r.raise_for_status()
                stream_escrow = r.json()
        except httpx.HTTPError as e:
            print(f"[02] create-stream failed: {e}")
            return

        sh = stream_escrow.get("service_hash") or stream_escrow.get("id")
        print(f"[02] streaming escrow: {sh}  total={args.total_amount} motes over {args.duration_seconds}s")

        # Poll claim_stream a few times to show linear vesting.
        for i, delay in enumerate([2, 5, 10]):
            await asyncio.sleep(delay)
            try:
                claimed = await buyer.claim_stream(sh)
                print(
                    f"[03.{i}] after {delay}s wait: vested_available={claimed.get('vested_available')} "
                    f"remaining={claimed.get('remaining')}"
                )
            except Exception as e:  # noqa: BLE001
                print(f"[03.{i}] claim_stream error: {e}")
                return


if __name__ == "__main__":
    asyncio.run(main())
