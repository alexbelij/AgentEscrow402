"""PostgreSQL persistence layer for AgentEscrow402."""

from __future__ import annotations

import logging
import os
import time
from typing import Any

from server.models import EscrowRecord, EscrowStatus

logger = logging.getLogger(__name__)

_pool = None


def _get_pool():
    global _pool
    if _pool is not None:
        return _pool
    try:
        import psycopg_pool  # noqa: F401

        db_url = os.getenv("DATABASE_URL", "")
        if not db_url:
            return None
        _pool = psycopg_pool.ConnectionPool(db_url, min_size=1, max_size=5)
        logger.info("PostgreSQL pool opened")
        return _pool
    except Exception as exc:
        logger.warning("PostgreSQL unavailable: %s", exc)
        return None


def is_connected() -> bool:
    pool = _get_pool()
    if pool is None:
        return False
    try:
        with pool.connection() as conn:
            conn.execute("SELECT 1")
        return True
    except Exception:
        return False


def save_escrow(record: EscrowRecord) -> bool:
    pool = _get_pool()
    if pool is None:
        return False
    try:
        with pool.connection() as conn:
            conn.execute(
                """INSERT INTO escrows (service_hash, sender, receiver, amount, status, ttl, created_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (service_hash) DO UPDATE SET
                     status = EXCLUDED.status,
                     amount = EXCLUDED.amount""",
                (
                    record.service_hash,
                    record.sender,
                    record.receiver,
                    record.amount,
                    record.status.value if isinstance(record.status, EscrowStatus) else record.status,
                    record.ttl,
                    record.created_at,
                ),
            )
        return True
    except Exception as exc:
        logger.warning("save_escrow failed: %s", exc)
        return False


def update_escrow_status(service_hash: str, status: str, deploy_hash: str = "") -> bool:
    pool = _get_pool()
    if pool is None:
        return False
    try:
        with pool.connection() as conn:
            if deploy_hash:
                conn.execute(
                    "UPDATE escrows SET status = %s, deploy_hash = %s WHERE service_hash = %s",
                    (status, deploy_hash, service_hash),
                )
            else:
                conn.execute(
                    "UPDATE escrows SET status = %s WHERE service_hash = %s",
                    (status, service_hash),
                )
        return True
    except Exception as exc:
        logger.warning("update_escrow failed: %s", exc)
        return False


def load_escrows() -> list[dict[str, Any]]:
    pool = _get_pool()
    if pool is None:
        return []
    try:
        with pool.connection() as conn:
            rows = conn.execute(
                "SELECT service_hash, sender, receiver, amount, status, ttl, created_at, deploy_hash FROM escrows"
            ).fetchall()
        result = []
        for r in rows:
            result.append(
                {
                    "service_hash": r[0],
                    "sender": r[1],
                    "receiver": r[2],
                    "amount": r[3],
                    "status": r[4],
                    "ttl": r[5],
                    "created_at": r[6],
                    "deploy_hash": r[7],
                }
            )
        return result
    except Exception as exc:
        logger.warning("load_escrows failed: %s", exc)
        return []


def get_stats() -> dict[str, Any]:
    pool = _get_pool()
    if pool is None:
        return {"total": 0, "pending": 0, "released": 0, "disputed": 0, "db": "disconnected"}
    try:
        with pool.connection() as conn:
            total = conn.execute("SELECT COUNT(*) FROM escrows").fetchone()[0]
            pending = conn.execute("SELECT COUNT(*) FROM escrows WHERE status='pending'").fetchone()[0]
            released = conn.execute("SELECT COUNT(*) FROM escrows WHERE status='released'").fetchone()[0]
            disputed = conn.execute("SELECT COUNT(*) FROM escrows WHERE status='disputed'").fetchone()[0]
            total_vol = conn.execute("SELECT COALESCE(SUM(amount),0) FROM escrows").fetchone()[0]
        return {
            "total": total,
            "pending": pending,
            "released": released,
            "disputed": disputed,
            "volume": total_vol,
            "db": "connected",
        }
    except Exception as exc:
        logger.warning("get_stats failed: %s", exc)
        return {"total": 0, "db": "error", "detail": str(exc)}


def bump_reputation(agent: str, completed: int = 0, disputed: int = 0) -> bool:
    pool = _get_pool()
    if pool is None:
        return False
    try:
        now = int(time.time())
        with pool.connection() as conn:
            conn.execute(
                """INSERT INTO reputation (agent, completed, disputed, last_active, score)
                   VALUES (%s, %s, %s, %s, %s)
                   ON CONFLICT (agent) DO UPDATE SET
                     completed = reputation.completed + EXCLUDED.completed,
                     disputed = reputation.disputed + EXCLUDED.disputed,
                     last_active = EXCLUDED.last_active,
                     score = GREATEST(0, LEAST(100,
                       50 + (reputation.completed + EXCLUDED.completed) * 5
                       - (reputation.disputed + EXCLUDED.disputed) * 10))""",
                (agent, completed, disputed, now, max(0, min(100, 50 + completed * 5 - disputed * 10))),
            )
        return True
    except Exception as exc:
        logger.warning("bump_reputation failed: %s", exc)
        return False


def record_insurance_fee(service_hash: str, fee_amount: int) -> bool:
    """Record insurance fee deducted from an escrow."""
    pool = _get_pool()
    if pool is None:
        return False
    try:
        with pool.connection() as conn:
            conn.execute(
                """INSERT INTO insurance_pool (service_hash, fee_amount, collected_at)
                   VALUES (%s, %s, %s)
                   ON CONFLICT (service_hash) DO NOTHING""",
                (service_hash, fee_amount, int(time.time())),
            )
        return True
    except Exception as exc:
        logger.warning("record_insurance_fee failed: %s", exc)
        return False


def get_reputation_db(agent: str) -> dict[str, Any] | None:
    pool = _get_pool()
    if pool is None:
        return None
    try:
        with pool.connection() as conn:
            row = conn.execute(
                "SELECT completed, disputed, slashed, last_active, score FROM reputation WHERE agent = %s",
                (agent,),
            ).fetchone()
        if row is None:
            return None
        return {
            "completed": row[0],
            "disputed": row[1],
            "slashed": row[2],
            "last_active": row[3],
            "score": row[4],
        }
    except Exception:
        return None
