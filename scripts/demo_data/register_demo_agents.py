#!/usr/bin/env python3
"""Register 5 demo agents on the hosted AE402 identity registry.

The identity registry (`server/identity_registry_api.py`) is an in-memory,
process-lifetime store — it is wiped on every deploy/restart. Run this any
time before a demo/judging session if the Marketplace/Identity Registry
console pages look empty.

Usage:
    python3 scripts/demo_data/register_demo_agents.py
    python3 scripts/demo_data/register_demo_agents.py --base-url http://localhost:8000
"""

from __future__ import annotations

import argparse

import httpx

DEFAULT_BASE_URL = "https://agentescrow402-api-ywm8.onrender.com"

AGENTS = [
    {
        "account_hash": "account-hash-9f1a3c2e0000000000000000000000000000000000000000000000000000",
        "display_name": "DataMiner-7 (research agent)",
        "capabilities": [
            {
                "name": "data-extraction",
                "version": "2.1",
                "description": "Structured web data extraction",
                "verified": True,
            },
            {
                "name": "report-writing",
                "version": "1.0",
                "description": "Long-form research report generation",
                "verified": False,
            },
        ],
        "verify_level": "ENHANCED",
        "reputation": {"completed": 14, "disputed": 1},
    },
    {
        "account_hash": "account-hash-b7d2e40100000000000000000000000000000000000000000000000000",
        "display_name": "CodeReview-Prime",
        "capabilities": [
            {
                "name": "code-review",
                "version": "3.0",
                "description": "Automated PR review + static analysis",
                "verified": True,
            },
        ],
        "verify_level": "FULL",
        "reputation": {"completed": 28, "disputed": 0},
    },
    {
        "account_hash": "account-hash-4e6f9a2200000000000000000000000000000000000000000000000000",
        "display_name": "TranslateBot-EU",
        "capabilities": [
            {
                "name": "translation",
                "version": "1.4",
                "description": "Multi-language document translation",
                "verified": True,
            },
            {
                "name": "localization-qa",
                "version": "1.0",
                "description": "Localization quality assurance",
                "verified": False,
            },
        ],
        "verify_level": "BASIC",
        "reputation": {"completed": 6, "disputed": 2},
    },
    {
        "account_hash": "account-hash-1c8b5d3300000000000000000000000000000000000000000000000000",
        "display_name": "ImageGen-Atelier",
        "capabilities": [
            {
                "name": "image-generation",
                "version": "2.0",
                "description": "Diffusion-based image generation",
                "verified": True,
            },
        ],
        "verify_level": "ENHANCED",
        "reputation": {"completed": 9, "disputed": 0},
    },
    {
        "account_hash": "account-hash-af03e75400000000000000000000000000000000000000000000000000",
        "display_name": "AuditChain-Sentinel",
        "capabilities": [
            {
                "name": "smart-contract-audit",
                "version": "1.2",
                "description": "Automated smart contract vulnerability scanning",
                "verified": True,
            },
            {
                "name": "compliance-check",
                "version": "1.0",
                "description": "Jurisdiction/KYC compliance screening",
                "verified": True,
            },
        ],
        "verify_level": "FULL",
        "reputation": {"completed": 22, "disputed": 1},
    },
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    args = parser.parse_args()

    with httpx.Client(timeout=30, base_url=args.base_url) as client:
        for agent in AGENTS:
            body = {
                "account_hash": agent["account_hash"],
                "display_name": agent["display_name"],
                "capabilities": agent["capabilities"],
            }
            r = client.post("/identity-registry/register", json=body)
            if r.status_code not in (200, 201, 409):
                print(f"FAIL register {agent['display_name']}: {r.status_code} {r.text}")
                continue
            did = f"did:casper:{agent['account_hash']}" if r.status_code != 200 else r.json().get("did")
            if r.status_code == 201:
                did = r.json()["did"]
            r1 = client.post(f"/identity-registry/{did}/verify", json={"level": agent["verify_level"]})
            r2 = client.post(f"/identity-registry/{did}/reputation", json=agent["reputation"])
            print(agent["display_name"], "register", r.status_code, "verify", r1.status_code, "rep", r2.status_code)

        r = client.get("/identity-registry/search/agents")
        print(f"\nTotal agents now in registry: {len(r.json())}")


if __name__ == "__main__":
    main()
