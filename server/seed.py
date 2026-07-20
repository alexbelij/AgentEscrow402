"""Demo seed data for AgentEscrow402.

All ``amount`` values are denominated in **motes** (1 CSPR = 1_000_000_000
motes), consistent with the API/contract unit contract documented in
``docs/CSPR_UNITS.md``. Prior seeds used bare whole-CSPR integers (e.g.
``25000`` meaning 25,000 CSPR) which conflicted with backend/contract
docs that declared motes; the frontend then compensated with identity
conversion functions that silently redefined the unit. This module now
seeds real motes values, and the frontend's ``motesToCspr()`` boundary
retains a bounded heuristic for any legacy row that predates this fix.
"""

from __future__ import annotations

import time

MOTES_PER_CSPR = 1_000_000_000


def _cspr(whole: int) -> int:
    """Return ``whole`` CSPR expressed in motes."""
    return whole * MOTES_PER_CSPR


def generate_seed_escrows() -> list[dict]:
    """Produce realistic demo escrows.

    Amounts below are in motes; each ``_cspr(X)`` reads as *X CSPR* for
    the human reviewer while keeping the on-wire representation honest.
    """
    now = int(time.time())
    demos = [
        {
            "sender": "agent-alpha-7b",
            "receiver": "agent-compute-gpt4",
            "amount": _cspr(25000),
            "service_hash": "5dd33e8e79789d386832a80c39006002383fa44dd76ba677cae3279f3a134451",
            "status": "released",
            "created_at": now - 86400 * 3,
            "ttl": 3600,
        },
        {
            "sender": "agent-rewriter-v2",
            "receiver": "agent-validator-llm",
            "amount": _cspr(12000),
            "service_hash": "a91b2f3c4d5e6f7081929a0b1c2d3e4f5061728394a5b6c7d8e9f0a1b2c3d4e5",
            "status": "pending",
            "created_at": now - 3600,
            "ttl": 7200,
        },
        {
            "sender": "agent-scraper-nx",
            "receiver": "agent-compute-gpt4",
            "amount": _cspr(8500),
            "service_hash": "b72c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f607182a3b4c5d6e7f80192",
            "status": "released",
            "created_at": now - 86400 * 2,
            "ttl": 1800,
        },
        {
            "sender": "agent-data-pipeline",
            "receiver": "agent-ml-trainer",
            "amount": _cspr(45000),
            "service_hash": "c83d4e5f60718293a4b5c6d7e8f9a01b2c3d4e5f6071a293b4c5d6e7f8019283",
            "status": "disputed",
            "created_at": now - 86400,
            "ttl": 3600,
        },
        {
            "sender": "agent-summarizer-v3",
            "receiver": "agent-formatter-md",
            "amount": _cspr(3200),
            "service_hash": "d94e5f607182a3b4c5d6e7f8019283a4b5c6d7e8f9a01b2c3d4e5f6071829384",
            "status": "refunded",
            "created_at": now - 86400 * 4,
            "ttl": 900,
        },
        {
            "sender": "agent-ocr-parser",
            "receiver": "agent-pdf-extract",
            "amount": _cspr(15800),
            "service_hash": "e05f607182a3b4c5d6e7f8019283a4b5c6d7e8f9a01b2c3d4e5f607182a3b4c5",
            "status": "released",
            "created_at": now - 86400 * 5,
            "ttl": 1800,
        },
        {
            "sender": "agent-alpha-7b",
            "receiver": "agent-ml-trainer",
            "amount": _cspr(62000),
            "service_hash": "f16071829a3b4c5d6e7f8019283a4b5c6d7e8f9a01b2c3d4e5f607182a3b4c5d",
            "status": "pending",
            "created_at": now - 600,
            "ttl": 7200,
        },
        {
            "sender": "agent-code-review",
            "receiver": "agent-test-runner",
            "amount": _cspr(9700),
            "service_hash": "0271829a3b4c5d6e7f8019283a4b5c6d7e8f9a01b2c3d4e5f607182a3b4c5d6e",
            "status": "released",
            "created_at": now - 86400 * 1,
            "ttl": 3600,
        },
    ]
    return demos
