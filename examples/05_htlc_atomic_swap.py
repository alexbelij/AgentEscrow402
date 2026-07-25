"""Cookbook 05 — HTLC atomic swap.

Demonstrates a Hash Time-Locked Contract escrow: the sender locks funds
against a sha256(preimage) commitment and a timeout. The receiver claims
by revealing the preimage before the timeout; if the receiver never
claims, the sender can refund after the timeout expires.

Run:
    python examples/05_htlc_atomic_swap.py --api-url http://localhost:8000

Notes:
- The HTLC swap route lives on the multi_asset router (POST /swaps/htlc).
- The preimage is a raw byte string; the server verifies sha256(preimage)
  == commitment_hash on claim.
"""

from __future__ import annotations

import argparse
import asyncio
import secrets
from hashlib import sha256

import httpx

from sdk.client import EscrowClient


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-url", default="http://localhost:8000")
    parser.add_argument("--amount", type=int, default=500_000)
    parser.add_argument("--timeout-seconds", type=int, default=3600)
    args = parser.parse_args()

    # Generate a random preimage; commit to its sha256.
    preimage = secrets.token_bytes(32)
    commitment = sha256(preimage).hexdigest()

    receiver_client = EscrowClient.generate(args.api_url)
    receiver = receiver_client.sender

    async with EscrowClient.generate(args.api_url) as sender:
        print(f"[01] connected: {await sender.health()}")
        print(f"[02] preimage:   {preimage.hex()}")
        print(f"     commitment: {commitment}")

        try:
            async with httpx.AsyncClient(base_url=args.api_url, timeout=30.0) as raw:
                r = await raw.post(
                    "/swaps/htlc",
                    json={
                        "sender": sender.sender,
                        "receiver": receiver,
                        "amount": args.amount,
                        "commitment_hash": commitment,
                        "timeout_seconds": args.timeout_seconds,
                    },
                )
                if r.status_code == 404:
                    print("[03] /swaps/htlc not available (multi_asset router disabled)")
                    return
                r.raise_for_status()
                swap = r.json()
        except httpx.HTTPError as e:
            print(f"[03] create HTLC failed: {e}")
            return

        swap_id = swap.get("swap_id") or swap.get("service_hash")
        print(f"[03] HTLC swap created: {swap_id}")

        # Receiver claims by revealing the preimage.
        try:
            async with httpx.AsyncClient(base_url=args.api_url, timeout=30.0) as raw:
                r = await raw.post(
                    "/swaps/htlc/claim",
                    json={"swap_id": swap_id, "preimage": preimage.hex()},
                )
                r.raise_for_status()
                claim = r.json()
                print(f"[04] receiver claimed: status={claim.get('status')} deploy={claim.get('deploy_hash')}")
        except httpx.HTTPError as e:
            print(f"[04] claim failed: {e}")


if __name__ == "__main__":
    asyncio.run(main())
