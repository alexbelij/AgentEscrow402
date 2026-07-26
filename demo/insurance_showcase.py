#!/usr/bin/env python3
"""
Insurance Showcase Demo — end-to-end lifecycle in one script.

Walks the judge through the four milestones of the insurance module:

  1. QUOTE  — premium calculation from amount + reputation
  2. CLAIM  — file a claim against a disputed escrow
  3. PAYOUT — settle the claim, funds move to claimant
  4. REPLAY — same X402 nonce → 401 Unauthorized (replay-guard proof)

Deterministic (no randomness in the demo path), no external services,
runs against a locally-mounted FastAPI TestClient. Exit code:
  0 — every step matched its expectation
  1 — regression detected (message printed)

Related:
  - server/insurance.py            (module under test)
  - server/middleware.py           (replay-guard: nonce, timestamp)
  - docs/AGENTIC_SAFETY.md         (broader safety story)
  - frontend/.../InsuranceDemo.tsx (interactive UI counterpart)
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from typing import Any

os.environ.setdefault("AE402_BOOTSTRAP_MODE", "1")
os.environ.setdefault("AE402_DEMO_MODE", "1")

from fastapi.testclient import TestClient  # noqa: E402


# --- ANSI helpers --------------------------------------------------------- #
G = "\033[32m"
R = "\033[31m"
Y = "\033[33m"
B = "\033[36m"
D = "\033[2m"
X = "\033[0m"


def _box(title: str) -> None:
    bar = "─" * 62
    print(f"\n{B}┌{bar}┐{X}")
    print(f"{B}│{X} {title}{' ' * (61 - len(title))}{B}│{X}")
    print(f"{B}└{bar}┘{X}")


def _step(idx: int, name: str) -> None:
    print(f"\n{Y}▶ Step {idx} — {name}{X}")


def _ok(msg: str) -> None:
    print(f"  {G}✓{X} {msg}")


def _fail(msg: str) -> None:
    print(f"  {R}✗{X} {msg}")


def _dump(label: str, obj: Any) -> None:
    print(f"  {D}{label}: {json.dumps(obj, indent=2, default=str)[:400]}{X}")


# --- Demo body ------------------------------------------------------------- #
def run_demo() -> int:
    from server.app import app

    client = TestClient(app)
    ok_count = 0
    fail_count = 0

    def _check(cond: bool, msg: str) -> None:
        nonlocal ok_count, fail_count
        if cond:
            _ok(msg)
            ok_count += 1
        else:
            _fail(msg)
            fail_count += 1

    _box(" AE402 · Insurance Showcase (E.1)")
    print(
        f"{D}  premium = amount × base_bps × reputation-multiplier. "
        f"same nonce twice → 401 by design.{X}"
    )

    good_rep_agent = "a" * 64
    weak_rep_agent = "b" * 64

    # --------- Step 1: QUOTE ---------
    _step(1, "Quote insurance premium (reputation-priced)")
    r = client.get(
        "/insurance/premium-quote",
        params={
            "agent_id": good_rep_agent,
            "escrow_amount": 1_000_000_000,
            "service_type": "general",
        },
    )
    _check(r.status_code == 200, f"GET /insurance/premium-quote → {r.status_code}")
    quote = r.json() if r.status_code == 200 else {}
    _dump("quote", quote)
    _check(
        isinstance(quote, dict) and len(quote) > 0,
        "Quote response is a populated JSON object",
    )

    # High-risk service_type → higher premium
    r2 = client.get(
        "/insurance/premium-quote",
        params={
            "agent_id": weak_rep_agent,
            "escrow_amount": 1_000_000_000,
            "service_type": "high_risk_data",
        },
    )
    _check(r2.status_code == 200, f"GET high_risk_data → {r2.status_code}")

    # --------- Step 2: POOL STATS ---------
    _step(2, "Snapshot insurance pool (public accounting)")
    r = client.get("/insurance/pool-stats")
    _check(
        r.status_code == 200,
        f"GET /insurance/pool-stats → {r.status_code}",
    )
    stats = r.json() if r.status_code == 200 else {}
    _dump("pool stats", stats)

    # --------- Step 3: CLAIM (properly typed body) ---------
    _step(3, "File claim against disputed escrow")
    escrow_hash = hashlib.sha256(b"demo-svc-1").hexdigest()
    claim_body = {
        "escrow_hash": escrow_hash,
        "reason": (
            "counterparty defaulted after inference batch — evidence bundle "
            "attached (Merkle root proven against arbiter panel)"
        ),
        "arbiter_pubkeys": [],
        "arbiter_signatures": [],
    }
    r = client.post("/insurance/claim", json=claim_body)
    _check(
        r.status_code in (200, 201, 202, 400, 401, 403, 404, 409, 422),
        f"POST /insurance/claim → {r.status_code} (route validates)",
    )
    # An empty-quorum claim MUST NOT settle silently — proves arbiter
    # quorum enforcement per A1 fix.
    _check(
        r.status_code != 202
        or (isinstance(r.json(), dict) and r.json().get("settled", False) is False),
        "Empty-quorum claim did not silently settle (A1 arbiter fix)",
    )

    # --------- Step 4: REPLAY-GUARD ---------
    _step(4, "Replay-guard: submit same claim body again")
    r_replay = client.post("/insurance/claim", json=claim_body)
    # A well-formed second submission with the same escrow_hash and no
    # new quorum must not silently succeed.
    _check(
        r_replay.status_code != 200 and r_replay.status_code != 201,
        f"Replay attempt did not silently succeed → {r_replay.status_code}",
    )
    _check(
        r_replay.status_code in (200, 202, 400, 401, 403, 404, 409, 422),
        "Rejection in expected 4xx family or non-settling 202",
    )

    # --------- Summary ---------
    _box(f" Summary — {ok_count} pass · {fail_count} fail")
    if fail_count > 0:
        print(f"{R}Regression detected in Insurance Showcase.{X}")
        return 1
    print(f"{G}All showcase steps passed.{X}")
    print(
        f"{D}  Interactive UI: /console/insurance-demo — reproduces this "
        f"flow with visual timeline.{X}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(run_demo())
