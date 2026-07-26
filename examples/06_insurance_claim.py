"""Insurance-claim scenario: how an escrow falls back to the insurance pool
when the arbiter quorum cannot resolve a dispute within the cooldown window.

Storyline:
    1. Buyer creates an escrow with `insurance=True` (adds insurance fee).
    2. Buyer disputes on delivery failure.
    3. Arbiter quorum returns ABSTAIN / low-confidence (simulated).
    4. VRF escalation panel is auto-invoked; if quorum still not met, the
       escrow becomes eligible for insurance claim after the cooldown.
    5. Buyer claims from the insurance pool — a one-shot payout gated by
       the on-chain claim tombstone.

This example exercises three surfaces beyond the happy-path SDK:
    * `POST /escrow/create` with `insurance=True`
    * `POST /escrow/{id}/dispute` + `GET /escrow/{id}/status` polling
    * `POST /insurance/{escrow_id}/claim` (the pool endpoint)

Prerequisites:
    uvicorn server.app:app --reload

Run:
    python examples/06_insurance_claim.py
    python examples/06_insurance_claim.py --api-url http://localhost:8000

For the underlying on-chain contract semantics (tombstone, cooldown,
quorum requirements), see docs/INSURANCE_POOL.md and the E2E test
contracts/tests/src/insurance_cooldown_replay_e2e_tests.rs.
"""

from __future__ import annotations

import argparse
import asyncio
import time

from sdk.client import EscrowClient

COOLDOWN_POLL_INTERVAL_S = 3
COOLDOWN_MAX_WAIT_S = 90  # sandbox cooldown is short; production is much longer


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-url", default="http://localhost:8000")
    parser.add_argument("--amount", type=int, default=1_000_000, help="escrow amount in motes")
    parser.add_argument("--service-hash", default="insurance-demo/v1")
    args = parser.parse_args()

    buyer = EscrowClient.generate(api_url=args.api_url)
    seller = EscrowClient.generate(api_url=args.api_url)

    print(f"[1/6] Buyer creates escrow with insurance (amount={args.amount} motes)")
    escrow = await buyer.create(
        service_hash=args.service_hash,
        receiver=seller.address,
        amount_motes=args.amount,
        insurance=True,
    )
    escrow_id = escrow["id"]
    print(f"      → escrow_id={escrow_id} insurance_fee_motes={escrow.get('insurance_fee_motes')}")

    print("[2/6] Buyer disputes on delivery failure")
    dispute = await buyer.dispute(escrow_id, reason="content_never_delivered")
    print(f"      → dispute_id={dispute.get('dispute_id')} status={dispute.get('status')}")

    print("[3/6] Poll dispute status until arbitration terminal state")
    deadline = time.time() + COOLDOWN_MAX_WAIT_S
    terminal_status = None
    while time.time() < deadline:
        status = await buyer.get_status(escrow_id)
        state = status.get("state") or status.get("status")
        arbitration = status.get("arbitration_outcome")
        print(f"      state={state} arbitration={arbitration}")
        if state in {"insurance_eligible", "resolved", "released", "refunded"}:
            terminal_status = state
            break
        if arbitration in {"abstain", "quorum_missing", "escalated"}:
            print(f"      → arbitration inconclusive ({arbitration}); waiting for cooldown")
        await asyncio.sleep(COOLDOWN_POLL_INTERVAL_S)

    if terminal_status is None:
        print("      → timed out waiting for terminal state; check server logs")
        return

    print(f"[4/6] Terminal state: {terminal_status}")

    if terminal_status != "insurance_eligible":
        print("      escrow resolved without insurance path — nothing to claim")
        return

    print("[5/6] Claiming from insurance pool")
    try:
        claim = await buyer.claim_insurance(escrow_id)
        print(f"      → claim_tx={claim.get('deploy_hash')} amount={claim.get('amount_motes')}")
    except AttributeError:
        # SDK may not expose claim_insurance directly; fall back to raw HTTP
        import httpx

        async with httpx.AsyncClient(base_url=args.api_url) as http:
            r = await http.post(f"/insurance/{escrow_id}/claim", json={"claimant": buyer.address})
            r.raise_for_status()
            claim = r.json()
            print(f"      → claim_tx={claim.get('deploy_hash')} amount={claim.get('amount_motes')}")

    print("[6/6] Verify tombstone: second claim must be rejected")
    try:
        import httpx

        async with httpx.AsyncClient(base_url=args.api_url) as http:
            r = await http.post(f"/insurance/{escrow_id}/claim", json={"claimant": buyer.address})
            if r.status_code >= 400:
                print(f"      → replay correctly rejected ({r.status_code}): {r.json().get('detail', r.text[:100])}")
            else:
                print("      ⚠ WARNING: replay was NOT rejected — on-chain tombstone may not be wired")
    except Exception as exc:
        print(f"      → replay attempt raised: {exc.__class__.__name__}")

    print("\nDone. See docs/INSURANCE_POOL.md for the on-chain tombstone contract.")


if __name__ == "__main__":
    asyncio.run(main())
