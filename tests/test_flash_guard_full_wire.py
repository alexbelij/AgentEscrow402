"""C11 — flash_guard full wire tests.

Covers the wiring added on top of the T2.12 baseline:

* `/refund` now runs flash_guard when enabled (unless the escrow has
  already expired past its TTL, in which case the guard is bypassed so
  legitimate refunds of stale escrows are never blocked).
* `/dispute` now runs flash_guard when enabled.
* The block-delay half of flash_guard fires when both `funded_block`
  and the process-global chain-tip are known and the delta is under
  MIN_BLOCK_DELAY, in addition to (or instead of) the hold-period half.
* funded_block=0 or chain-tip=0 skips the block-delay half so unknown
  block contexts never produce a false rejection.
"""

from __future__ import annotations

import hashlib

import pytest
from fastapi.testclient import TestClient

from server import event_monitor, flash_guard
from server.app import app, get_config, get_sandbox
from server.config import Config
from server.sandbox import SandboxStore


RECEIVER_HEX = "a" * 64


def _hash(seed: str) -> str:
    return hashlib.sha256(seed.encode()).hexdigest()


@pytest.fixture
def sandbox_store() -> SandboxStore:
    return SandboxStore()


@pytest.fixture(autouse=True)
def _reset_block_height():
    # Ensure a clean chain-tip between tests. Some tests set it, others
    # rely on 0 (unknown). Reset before AND after so a mid-test failure
    # cannot leak state into the next test.
    event_monitor._LAST_KNOWN_BLOCK_HEIGHT = 0
    yield
    event_monitor._LAST_KNOWN_BLOCK_HEIGHT = 0


@pytest.fixture
def guarded_client(sandbox_store: SandboxStore):
    cfg = Config(sandbox=True, flash_guard_enabled=True)
    app.dependency_overrides[get_config] = lambda: cfg
    app.dependency_overrides[get_sandbox] = lambda: sandbox_store
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


class TestRefundGuard:
    def test_refund_blocked_during_hold_window(self, guarded_client, sandbox_store):
        # A fund-then-immediately-refund cycle is the flash-loan attack we
        # care about: the guard must reject even before TTL expiry.
        h = _hash("refund-guard-block")
        guarded_client.post(
            "/escrow",
            json={"receiver": RECEIVER_HEX, "amount": 100, "service_hash": h},
            params={"sender": "alice"},
        )
        resp = guarded_client.post(
            "/refund", json={"service_hash": h}, params={"sender": "alice"}
        )
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert "flash guard (refund)" in detail
        assert "hold period not met" in detail

    def test_refund_allowed_after_hold_period(self, guarded_client, sandbox_store):
        # Age past hold window → the flash guard must let the refund through.
        # TTL is set generously so the escrow does not concurrently expire
        # (which would otherwise legitimately transition it to "expired").
        h = _hash("refund-guard-pass")
        guarded_client.post(
            "/escrow",
            json={
                "receiver": RECEIVER_HEX,
                "amount": 100,
                "service_hash": h,
                "ttl": 86400,
            },
            params={"sender": "alice"},
        )
        rec = sandbox_store._escrows[h]
        rec["created_at"] -= flash_guard.MIN_HOLD_PERIOD_SECS + 1
        resp = guarded_client.post(
            "/refund", json={"service_hash": h}, params={"sender": "alice"}
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "refunded"

    def test_refund_of_expired_escrow_bypasses_guard(self, guarded_client, sandbox_store):
        # Refunding an escrow whose TTL has already elapsed is a legitimate,
        # non-flash-loan operation (funds are stuck otherwise). The guard
        # must NOT block this even inside the flash window.
        h = _hash("refund-guard-expired")
        guarded_client.post(
            "/escrow",
            json={"receiver": RECEIVER_HEX, "amount": 100, "service_hash": h, "ttl": 60},
            params={"sender": "alice"},
        )
        rec = sandbox_store._escrows[h]
        # Push both created_at and ttl so the escrow is expired but still
        # inside the flash-guard's hold-period window from "now".
        rec["created_at"] -= 120  # 2 min old
        rec["ttl"] = 60  # ttl already elapsed
        resp = guarded_client.post(
            "/refund", json={"service_hash": h}, params={"sender": "alice"}
        )
        # Expired refund path may resolve to refunded OR expired (both are
        # acceptable per the FSM); the point is the guard did not block.
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] in {"refunded", "expired"}


def _dispute_body(service_hash: str) -> dict:
    # /dispute requires reason_hash — use a stable sha256 placeholder.
    return {
        "service_hash": service_hash,
        "reason_hash": hashlib.sha256(b"unit-test-reason").hexdigest(),
    }


class TestDisputeGuard:
    def test_dispute_blocked_during_hold_window(self, guarded_client, sandbox_store):
        h = _hash("dispute-guard-block")
        guarded_client.post(
            "/escrow",
            json={"receiver": RECEIVER_HEX, "amount": 100, "service_hash": h},
            params={"sender": "alice"},
        )
        resp = guarded_client.post(
            "/dispute", json=_dispute_body(h), params={"sender": "alice"}
        )
        assert resp.status_code == 422
        assert "flash guard (dispute)" in resp.json()["detail"]

    def test_dispute_allowed_after_hold_period(self, guarded_client, sandbox_store):
        h = _hash("dispute-guard-pass")
        guarded_client.post(
            "/escrow",
            json={
                "receiver": RECEIVER_HEX,
                "amount": 100,
                "service_hash": h,
                "ttl": 86400,
            },
            params={"sender": "alice"},
        )
        rec = sandbox_store._escrows[h]
        rec["created_at"] -= flash_guard.MIN_HOLD_PERIOD_SECS + 1
        resp = guarded_client.post(
            "/dispute", json=_dispute_body(h), params={"sender": "alice"}
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "disputed"


class TestBlockDelayHalf:
    def test_block_delay_blocks_release_when_hold_period_ok(
        self, guarded_client, sandbox_store
    ):
        # Hold period satisfied but funded_block=100, current=101 →
        # block-delay half must still block the release.
        h = _hash("block-delay-block")
        guarded_client.post(
            "/escrow",
            json={
                "receiver": RECEIVER_HEX,
                "amount": 100,
                "service_hash": h,
                "ttl": 86400,
            },
            params={"sender": "alice"},
        )
        rec = sandbox_store._escrows[h]
        rec["created_at"] -= flash_guard.MIN_HOLD_PERIOD_SECS + 1  # hold OK
        rec["funded_block"] = 100
        event_monitor._LAST_KNOWN_BLOCK_HEIGHT = 101  # only 1 block later
        resp = guarded_client.post(
            "/release", json={"service_hash": h}, params={"sender": "alice"}
        )
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert "block delay not met" in detail
        assert "flash guard (release)" in detail

    def test_block_delay_passes_after_min_blocks(self, guarded_client, sandbox_store):
        h = _hash("block-delay-pass")
        guarded_client.post(
            "/escrow",
            json={
                "receiver": RECEIVER_HEX,
                "amount": 100,
                "service_hash": h,
                "ttl": 86400,
            },
            params={"sender": "alice"},
        )
        rec = sandbox_store._escrows[h]
        rec["created_at"] -= flash_guard.MIN_HOLD_PERIOD_SECS + 1
        rec["funded_block"] = 100
        event_monitor._LAST_KNOWN_BLOCK_HEIGHT = 100 + flash_guard.MIN_BLOCK_DELAY
        resp = guarded_client.post(
            "/release", json={"service_hash": h}, params={"sender": "alice"}
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "released"

    def test_unknown_block_context_skips_block_delay_half(
        self, guarded_client, sandbox_store
    ):
        # funded_block=0 (unknown) → block-delay half is skipped, so hold
        # period alone controls the outcome. This preserves the sandbox
        # happy-path for anyone who never populated funded_block.
        h = _hash("block-delay-unknown")
        guarded_client.post(
            "/escrow",
            json={
                "receiver": RECEIVER_HEX,
                "amount": 100,
                "service_hash": h,
                "ttl": 86400,
            },
            params={"sender": "alice"},
        )
        rec = sandbox_store._escrows[h]
        rec["created_at"] -= flash_guard.MIN_HOLD_PERIOD_SECS + 1
        rec["funded_block"] = 0  # unknown
        event_monitor._LAST_KNOWN_BLOCK_HEIGHT = 999999  # anything
        resp = guarded_client.post(
            "/release", json={"service_hash": h}, params={"sender": "alice"}
        )
        assert resp.status_code == 200


class TestGuardDisabledByDefault:
    def test_all_lifecycle_paths_unmodified_when_guard_off(self, sandbox_store):
        # Sanity: with the default Config (guard OFF), create → refund
        # happy-path still works instantly. This is the compat guarantee
        # for existing sandbox demos and SDK samples.
        app.dependency_overrides[get_sandbox] = lambda: sandbox_store
        with TestClient(app) as c:
            h = _hash("guard-off-refund")
            c.post(
                "/escrow",
                json={"receiver": RECEIVER_HEX, "amount": 100, "service_hash": h},
                params={"sender": "alice"},
            )
            resp = c.post("/refund", json={"service_hash": h}, params={"sender": "alice"})
            assert resp.status_code == 200
        app.dependency_overrides.clear()
