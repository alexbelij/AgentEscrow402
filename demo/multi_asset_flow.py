#!/usr/bin/env python3
"""Multi-asset escrow demo — happy-path lifecycle over the /escrow/multi-asset router.

Runs entirely in-process against the sandbox backend (no on-chain calls,
no external network). Demonstrates the same lifecycle a real agent runs
on the live contract, minus the Casper deploy latency.

Lifecycle:
    1. Buyer + Seller each have a deterministic Ed25519 keypair.
    2. Buyer creates a multi-asset escrow via POST /escrow/multi-asset.
    3. The backend accepts the create call and stores the escrow in
       SandboxStore (same store the main /escrow lifecycle uses).
    4. Buyer either releases (happy path) or refunds (abort path).
    5. Escrow record transitions pending -> released / refunded.

Usage:
    python -m demo.multi_asset_flow                # default: CSPR, amount=1000000000 (=1 CSPR)
    python -m demo.multi_asset_flow --token-type cep18   # CEP-18 (requires live-mode contract; see below)
    python -m demo.multi_asset_flow --refund       # trigger refund path instead
    python -m demo.multi_asset_flow --json         # emit final receipt as JSON

WHY CSPR IS THE DEFAULT: the CEP-18 code path calls
`CasperClient.cep18_transfer`, which requires the live deployed CEP-18
contract at `cep18_aetusd_contract_hash` (see TX_MANIFEST.md). The sandbox
Casper stub cannot fulfil that call. For a real CEP-18 lifecycle demo,
point the demo at a live backend with `AE402_API_URL=https://ae402...`
(a variant that uses `sdk.EscrowClient` against the live endpoint is left
as an exercise — the wire format is identical, only the auth changes).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

# The sandbox backend runs entirely in-process via TestClient.
os.environ.setdefault("SANDBOX", "true")
# Enable hosted-demo x402 identity so we can exercise the multi-asset
# endpoint without producing a real Ed25519 signature (the sandbox
# still validates header shape, but accepts the demo signature).
os.environ.setdefault("ALLOW_HOSTED_DEMO_IDENTITY", "true")


def _hex64(seed: bytes) -> str:
    """32-byte hex — used for account hashes / service hashes."""
    return hashlib.sha256(seed).hexdigest()


# The x402 header uses a hosted-demo-identity path when the backend has
# ALLOW_HOSTED_DEMO_IDENTITY=true (bench + sandbox demo). This lets us
# skip real signing while still exercising the same code paths.
HOSTED_DEMO_SENDER = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
HOSTED_DEMO_SIGNATURE = "a" * 128
X402_VERSION = "x402-v1"


def _serialise_x402(escrow_hash: str, amount: int, sender: str, nonce: str) -> str:
    """Build the x402 header string:

    Format: x402-v1;<escrow_hash>;<amount>;<sender>;<timestamp>;<nonce>;<signature>
    (see server/middleware.py::parse_x402_header for the canonical grammar)
    """
    import time

    ts = str(int(time.time()))
    # Signature is fixed for the hosted-demo path; the backend only checks
    # that it matches the constant when X-AE402-Demo-Identity is set.
    parts = [X402_VERSION, escrow_hash, str(amount), sender, ts, nonce, HOSTED_DEMO_SIGNATURE]
    return ";".join(parts)


def run(token_type: str = "cspr", amount: int = 1_000_000_000, refund: bool = False) -> dict:
    """Execute one full multi-asset escrow lifecycle. Returns a receipt dict."""
    # Lazy import — avoids the FastAPI startup cost on `python -m demo.multi_asset_flow --help`.
    from fastapi.testclient import TestClient

    # Neutralise the in-process 60/min rate limiter for the demo so a
    # user running this back-to-back doesn't hit 429 on the third try.
    try:
        from server import app as _sapp
        _sapp._rate_limits = type("_NL", (dict,), {"__setitem__": lambda self, k, v: None, "get": lambda self, k, d=None: None})()
    except Exception:
        pass

    # Belt-and-braces: also flip the flag on the in-process Config in
    # case it was already cached at module-load time.
    try:
        from server.config import get_config
        cfg = get_config()
        cfg.allow_hosted_demo_identity = True
    except Exception:
        pass

    # server/multi_asset.py's _build_token_adapter requires a truthy casper
    # client even in sandbox mode. Provide a stub so the token adapter can
    # be constructed — the sandbox path never actually calls it.
    class _StubCasper:
        async def close(self) -> None:  # for lifespan shutdown
            return None

    try:
        from server import app as _sapp3
        if getattr(_sapp3, "_casper", None) is None:
            _sapp3._casper = _StubCasper()
    except Exception:
        pass

    from server.app import app  # noqa: E402

    with TestClient(app) as client:
        # 1. Warm-up: the sandbox exposes a health endpoint.
        health = client.get("/health").json()
        assert health["status"] == "ok", f"backend unhealthy: {health}"

        # 2. Deterministic buyer/seller identities for reproducibility.
        # Buyer must be one of the hosted-demo identities (see server/app.py
        # DEMO_CONSOLE_IDENTITIES); seller can be any valid account hash.
        buyer_hex = HOSTED_DEMO_SENDER
        seller_hex = _hex64(b"demo-multi-asset-seller")

        # 3. service_hash is unique per escrow — bind it to a random nonce.
        nonce = secrets.token_hex(16)  # 32 hex chars, well within 8..128
        svc_hash = _hex64(f"{buyer_hex}|{seller_hex}|{amount}|{nonce}".encode())

        token = {"token_type": token_type}
        if token_type == "cep18":
            # Use the AETUSD test-token contract hash the backend advertises.
            # In sandbox this is not enforced; we pass a valid-length placeholder.
            token["contract_hash"] = "aa" * 32

        body = {
            "receiver": seller_hex,
            "amount_motes": amount,
            "token": token,
            "service_hash": svc_hash,
            "ttl": 300,
        }
        header_str = _serialise_x402(svc_hash, amount, buyer_hex, nonce)

        # 4. Create the multi-asset escrow.
        r = client.post(
            "/escrow/multi-asset",
            json=body,
            headers={
                "X-Payment": header_str,
                "X-AE402-Demo-Identity": "hosted-console",
            },
        )
        if r.status_code not in (200, 201):
            raise RuntimeError(f"POST /escrow/multi-asset failed: {r.status_code} {r.text[:200]}")
        escrow = r.json()
        assert escrow["service_hash"] == svc_hash, "service_hash mismatch on response"

        # 5. Terminal transition — release or refund.
        # POST /release + POST /refund take {service_hash, ...} in the body.
        # The route reuses the hosted-demo x402 identity to prove the caller
        # is the escrow's own sender (same identity we used to create it).
        terminal_nonce = secrets.token_hex(16)
        terminal_header = _serialise_x402(svc_hash, amount, buyer_hex, terminal_nonce)
        terminal_headers = {
            "X-Payment": terminal_header,
            "X-AE402-Demo-Identity": "hosted-console",
        }

        if refund:
            terminal = client.post(
                "/refund",
                json={"service_hash": svc_hash},
                headers=terminal_headers,
            )
        else:
            terminal = client.post(
                "/release",
                json={
                    "service_hash": svc_hash,
                    "arbiter_pubkeys": [],
                    "arbiter_signatures": [],
                },
                headers=terminal_headers,
            )

        if terminal.status_code not in (200, 201):
            # In sandbox, some paths return 400 if the release requires a
            # signature we didn't attach. That's still a valid outcome for
            # the demo — the escrow was created; we just log and continue.
            pass

        # 6. Fetch final state.
        state = client.get(f"/escrow/{svc_hash}").json()

    return {
        "buyer": buyer_hex,
        "seller": seller_hex,
        "token_type": token_type,
        "amount": amount,
        "service_hash": svc_hash,
        "created_status": escrow.get("status"),
        "final_status": state.get("status"),
        "terminal_http": terminal.status_code,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--token-type", choices=["cspr", "cep18"], default="cspr")
    ap.add_argument("--amount", type=int, default=1_000_000_000)
    ap.add_argument("--refund", action="store_true", help="Refund path instead of release")
    ap.add_argument("--json", dest="as_json", action="store_true", help="Emit receipt as JSON")
    args = ap.parse_args()

    receipt = run(token_type=args.token_type, amount=args.amount, refund=args.refund)

    if args.as_json:
        print(json.dumps(receipt, indent=2))
    else:
        print("AE402 multi-asset escrow demo")
        print(f"  token_type      = {receipt['token_type']}")
        print(f"  amount          = {receipt['amount']}")
        print(f"  service_hash    = {receipt['service_hash']}")
        print(f"  created_status  = {receipt['created_status']}")
        print(f"  final_status    = {receipt['final_status']}")
        print(f"  terminal_http   = {receipt['terminal_http']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
