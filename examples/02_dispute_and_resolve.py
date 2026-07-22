"""Cookbook 02 — dispute and arbiter resolution.

Extends 01_quickstart_happy_path by taking the buyer down the dispute
path instead of a clean release: buyer opens a dispute, the AI arbiter
is invoked for a recommendation, and (against a sandbox / test
deployment) an arbiter-quorum resolve settles the funds.

Run:
    python examples/02_dispute_and_resolve.py \\
        --api-url http://localhost:8000

Notes:
- Against the live testnet deployment the arbitration/resolve calls
  require registered arbiter keys and are outside the scope of the
  example — the example will stop after the dispute is opened and
  print what the next call would look like.
- Amounts are in motes (1 CSPR = 1e9 motes) — see docs/CSPR_UNITS.md.
"""

from __future__ import annotations

import argparse
import asyncio
from hashlib import sha256

from sdk.client import EscrowClient


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-url", default="http://localhost:8000")
    parser.add_argument("--amount", type=int, default=500_000)
    args = parser.parse_args()

    receiver = EscrowClient.generate(args.api_url).sender

    async with EscrowClient.generate(args.api_url) as buyer:
        print(f"[01] connected: {await buyer.health()}")
        escrow = await buyer.create_escrow(receiver=receiver, amount=args.amount)
        sh = escrow["service_hash"]
        print(f"[02] escrow created: {sh}")

        # The dispute reason is captured off-chain and only its sha256
        # is committed on-chain — verifiable without leaking payload.
        reason = b"worker delivered malformed JSON on the /predict endpoint"
        reason_hash = sha256(reason).hexdigest()

        disputed = await buyer.dispute(sh, reason_hash=reason_hash, amount=args.amount)
        print(f"[03] escrow disputed: status={disputed['status']} reason_hash={reason_hash[:16]}…")

        # AI arbitration recommendation (does NOT settle funds — arbiter
        # quorum still needs to co-sign a resolve() call). Fine to skip
        # against a stripped sandbox; error path is caught cleanly.
        try:
            recommendation = await buyer.arbitrate(
                service_hash=sh,
                buyer_evidence=reason.decode(),
                seller_evidence="worker delivered exactly what was requested",
            )
            print(
                f"[04] AI arbitration: verdict={recommendation.get('verdict')} "
                f"confidence={recommendation.get('confidence')}"
            )
        except Exception as e:  # noqa: BLE001
            print(f"[04] AI arbitration unavailable ({type(e).__name__}: {e}) — expected on stripped sandbox")

        print(
            "[05] next step (not automated here): 3-of-5 registered arbiters would sign the "
            "resolve payload and call client.resolve(...) with pubkeys+signatures. "
            "See sdk/arbiter_signing.py for the canonical message format."
        )


if __name__ == "__main__":
    asyncio.run(main())
