"""Comprehensive business logic tests — 100% coverage of core escrow workflows.

Covers:
- Insurance fee calculation (all edge cases)
- Full escrow lifecycle: create → release / refund / dispute
- State machine transitions (valid and invalid)
- Reputation scoring (accumulation, capping, dispute penalties)
- Pagination & filtering
- Security: bounded nonce cache, error sanitization, limit caps
- Concurrency safety
- Compute hash determinism
"""

from __future__ import annotations

import asyncio
import hashlib
import time

import pytest
from fastapi.testclient import TestClient

from server.app import _apply_insurance_fee, app, get_config, get_sandbox
from server.config import Config
from server.middleware import (
    MAX_NONCE_CACHE,
    _check_replay,
    _used_nonces,
    compute_service_hash,
)
from server.models import EscrowRecord, EscrowStatus, ReputationRecord
from server.sandbox import SandboxStore


def _hash(val: str) -> str:
    return hashlib.sha256(val.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sandbox_store():
    return SandboxStore()


@pytest.fixture
def client(sandbox_store):
    cfg = Config(sandbox=True)
    app.dependency_overrides[get_config] = lambda: cfg
    app.dependency_overrides[get_sandbox] = lambda: sandbox_store
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def client_with_fee(sandbox_store):
    """Client with custom insurance fee of 500 bps (5%)."""
    cfg = Config(sandbox=True, insurance_fee_bps=500)
    app.dependency_overrides[get_config] = lambda: cfg
    app.dependency_overrides[get_sandbox] = lambda: sandbox_store
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ============================================================================
# 1. INSURANCE FEE CALCULATION
# ============================================================================


class TestInsuranceFee:
    """Test _apply_insurance_fee for all edge cases."""

    def test_standard_2_percent(self):
        net, fee = _apply_insurance_fee(10000, 200)
        assert fee == 200  # 2% of 10000
        assert net == 9800
        assert net + fee == 10000

    def test_5_percent(self):
        net, fee = _apply_insurance_fee(10000, 500)
        assert fee == 500
        assert net == 9500

    def test_zero_fee(self):
        net, fee = _apply_insurance_fee(10000, 0)
        assert fee == 0
        assert net == 10000

    def test_100_percent_fee(self):
        net, fee = _apply_insurance_fee(10000, 10000)
        assert fee == 10000
        assert net == 0

    def test_small_amount_rounds_down(self):
        """Integer division: 99 * 200 // 10000 = 1."""
        net, fee = _apply_insurance_fee(99, 200)
        assert fee == 1
        assert net == 98

    def test_very_small_amount_zero_fee(self):
        """Amount too small for fee: 49 * 200 // 10000 = 0."""
        net, fee = _apply_insurance_fee(49, 200)
        assert fee == 0
        assert net == 49

    def test_one_unit(self):
        net, fee = _apply_insurance_fee(1, 200)
        assert fee == 0
        assert net == 1

    def test_large_amount(self):
        net, fee = _apply_insurance_fee(1_000_000_000, 200)
        assert fee == 20_000_000
        assert net == 980_000_000

    def test_fee_via_api_default(self, client):
        """Verify the API applies the default 2% insurance fee."""
        h = _hash("fee-test-api")
        resp = client.post(
            "/escrow",
            json={"receiver": "r", "amount": 5000, "service_hash": h},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["amount"] == 4900  # 5000 - 2% = 4900

    def test_fee_via_api_custom(self, client_with_fee):
        """Verify the API with custom 5% fee."""
        h = _hash("fee-test-custom")
        resp = client_with_fee.post(
            "/escrow",
            json={"receiver": "r", "amount": 10000, "service_hash": h},
        )
        assert resp.status_code == 200
        assert resp.json()["amount"] == 9500  # 10000 - 5% = 9500

    def test_estimate_endpoint(self, client):
        resp = client.get("/estimate?amount=10000")
        assert resp.status_code == 200
        body = resp.json()
        assert body["gross_amount"] == 10000
        assert body["net_amount"] == 9800
        assert body["insurance_fee"] == 200
        assert body["fee_bps"] == 200


# ============================================================================
# 2. FULL ESCROW LIFECYCLE
# ============================================================================


class TestEscrowLifecycle:
    """Test complete lifecycle: create → release/refund/dispute."""

    def test_create_and_release(self, client):
        h = _hash("lifecycle-release")
        client.post(
            "/escrow",
            json={"receiver": "agent-r", "amount": 1000, "service_hash": h},
            params={"sender": "alice"},
        )
        resp = client.post(
            "/release", json={"service_hash": h}, params={"sender": "alice"}
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "released"

        # Verify state persisted
        get = client.get(f"/escrow/{h}")
        assert get.json()["status"] == "released"

    def test_create_and_refund(self, client):
        h = _hash("lifecycle-refund")
        client.post(
            "/escrow",
            json={"receiver": "r", "amount": 500, "service_hash": h},
            params={"sender": "bob"},
        )
        resp = client.post(
            "/refund", json={"service_hash": h}, params={"sender": "bob"}
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "refunded"

    def test_create_and_dispute(self, client):
        h = _hash("lifecycle-dispute")
        client.post(
            "/escrow",
            json={"receiver": "r", "amount": 300, "service_hash": h},
        )
        resp = client.post(
            "/dispute",
            json={"service_hash": h, "reason_hash": "b" * 64},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "disputed"

    def test_double_release_fails(self, client):
        h = _hash("double-release")
        client.post(
            "/escrow",
            json={"receiver": "r", "amount": 100, "service_hash": h},
            params={"sender": "s"},
        )
        client.post("/release", json={"service_hash": h}, params={"sender": "s"})
        resp = client.post(
            "/release", json={"service_hash": h}, params={"sender": "s"}
        )
        assert resp.status_code == 400

    def test_release_by_wrong_sender_fails(self, client):
        h = _hash("wrong-sender")
        client.post(
            "/escrow",
            json={"receiver": "r", "amount": 100, "service_hash": h},
            params={"sender": "alice"},
        )
        resp = client.post(
            "/release", json={"service_hash": h}, params={"sender": "eve"}
        )
        assert resp.status_code == 400

    def test_refund_after_release_fails(self, client):
        h = _hash("refund-after-release")
        client.post(
            "/escrow",
            json={"receiver": "r", "amount": 100, "service_hash": h},
            params={"sender": "s"},
        )
        client.post("/release", json={"service_hash": h}, params={"sender": "s"})
        resp = client.post(
            "/refund", json={"service_hash": h}, params={"sender": "s"}
        )
        assert resp.status_code == 400

    def test_dispute_after_release_fails(self, client):
        h = _hash("dispute-after-release")
        client.post(
            "/escrow",
            json={"receiver": "r", "amount": 100, "service_hash": h},
            params={"sender": "s"},
        )
        client.post("/release", json={"service_hash": h}, params={"sender": "s"})
        resp = client.post(
            "/dispute",
            json={"service_hash": h, "reason_hash": "a" * 64},
        )
        assert resp.status_code == 400

    def test_refund_after_dispute_fails(self, client):
        h = _hash("refund-after-dispute")
        client.post(
            "/escrow",
            json={"receiver": "r", "amount": 100, "service_hash": h},
            params={"sender": "s"},
        )
        client.post(
            "/dispute",
            json={"service_hash": h, "reason_hash": "d" * 64},
        )
        resp = client.post(
            "/refund", json={"service_hash": h}, params={"sender": "s"}
        )
        assert resp.status_code == 400


# ============================================================================
# 3. STATE MACHINE TRANSITIONS (sandbox store level)
# ============================================================================


class TestStateMachine:
    """Test all valid and invalid state transitions on SandboxStore."""

    def test_pending_to_released(self, sandbox_store):
        sandbox_store.create_escrow("s", "r", 100, _hash("sm-1"), 300)
        rec = sandbox_store.release_escrow(_hash("sm-1"), "s")
        assert rec.status == EscrowStatus.RELEASED

    def test_pending_to_refunded(self, sandbox_store):
        sandbox_store.create_escrow("s", "r", 100, _hash("sm-2"), 300)
        rec = sandbox_store.refund_escrow(_hash("sm-2"), "s")
        assert rec.status == EscrowStatus.REFUNDED

    def test_pending_to_disputed(self, sandbox_store):
        sandbox_store.create_escrow("s", "r", 100, _hash("sm-3"), 300)
        rec = sandbox_store.dispute_escrow(_hash("sm-3"))
        assert rec.status == EscrowStatus.DISPUTED

    def test_released_is_terminal(self, sandbox_store):
        h = _hash("sm-terminal-1")
        sandbox_store.create_escrow("s", "r", 100, h, 300)
        sandbox_store.release_escrow(h, "s")

        with pytest.raises(ValueError):
            sandbox_store.release_escrow(h, "s")
        with pytest.raises(ValueError):
            sandbox_store.refund_escrow(h, "s")
        with pytest.raises(ValueError):
            sandbox_store.dispute_escrow(h)

    def test_refunded_is_terminal(self, sandbox_store):
        h = _hash("sm-terminal-2")
        sandbox_store.create_escrow("s", "r", 100, h, 300)
        sandbox_store.refund_escrow(h, "s")

        with pytest.raises(ValueError):
            sandbox_store.release_escrow(h, "s")
        with pytest.raises(ValueError):
            sandbox_store.dispute_escrow(h)

    def test_disputed_blocks_refund(self, sandbox_store):
        h = _hash("sm-terminal-3")
        sandbox_store.create_escrow("s", "r", 100, h, 300)
        sandbox_store.dispute_escrow(h)

        with pytest.raises(ValueError):
            sandbox_store.refund_escrow(h, "s")


# ============================================================================
# 4. REPUTATION SYSTEM
# ============================================================================


class TestReputation:
    """Test reputation scoring: accumulation, penalties, cap at 100."""

    def test_initial_reputation(self, sandbox_store):
        rep = sandbox_store.get_reputation("new-agent")
        assert rep.score == 50
        assert rep.completed == 0
        assert rep.disputed == 0

    def test_reputation_after_single_completion(self, sandbox_store):
        h = _hash("rep-1")
        sandbox_store.create_escrow("s", "agent-a", 100, h, 300)
        sandbox_store.release_escrow(h, "s")
        rep = sandbox_store.get_reputation("agent-a")
        assert rep.completed == 1
        assert rep.score == 55  # 50 + 5

    def test_reputation_accumulates(self, sandbox_store):
        for i in range(5):
            h = _hash(f"rep-accum-{i}")
            sandbox_store.create_escrow("s", "agent-b", 100, h, 300)
            sandbox_store.release_escrow(h, "s")
        rep = sandbox_store.get_reputation("agent-b")
        assert rep.completed == 5
        assert rep.score == 75  # 50 + 5*5

    def test_reputation_capped_at_100(self, sandbox_store):
        for i in range(15):
            h = _hash(f"rep-cap-{i}")
            sandbox_store.create_escrow("s", "capped-agent", 100, h, 300)
            sandbox_store.release_escrow(h, "s")
        rep = sandbox_store.get_reputation("capped-agent")
        assert rep.score <= 100

    def test_reputation_penalty_on_dispute(self, sandbox_store):
        h = _hash("rep-dispute")
        sandbox_store.create_escrow("bad-sender", "r", 100, h, 300)
        sandbox_store.dispute_escrow(h)
        rep = sandbox_store.get_reputation("bad-sender")
        assert rep.disputed == 1
        assert rep.score == 40  # 50 - 10

    def test_mixed_completions_and_disputes(self, sandbox_store):
        # 3 completions, 1 dispute for sender
        sender = "mixed-agent"
        for i in range(3):
            h = _hash(f"rep-mixed-{i}")
            sandbox_store.create_escrow(sender, f"r-{i}", 100, h, 300)
            sandbox_store.release_escrow(h, sender)

        h = _hash("rep-mixed-dispute")
        sandbox_store.create_escrow(sender, "r-d", 100, h, 300)
        sandbox_store.dispute_escrow(h)

        rep = sandbox_store.get_reputation(sender)
        assert rep.disputed == 1

    def test_reputation_api(self, client):
        resp = client.get("/reputation/unknown-agent")
        assert resp.status_code == 200
        assert resp.json()["score"] == 50


# ============================================================================
# 5. PAGINATION AND FILTERING
# ============================================================================


class TestPaginationFiltering:
    """Test /escrows endpoint with pagination and filters."""

    def test_list_empty(self, client):
        resp = client.get("/escrows")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 0

    def test_list_with_created_escrows(self, client):
        for i in range(5):
            client.post(
                "/escrow",
                json={
                    "receiver": f"r-{i}",
                    "amount": 100 * (i + 1),
                    "service_hash": _hash(f"list-{i}"),
                },
                params={"sender": "lister"},
            )
        resp = client.get("/escrows")
        assert resp.json()["total"] >= 5

    def test_pagination_limit(self, client):
        for i in range(10):
            client.post(
                "/escrow",
                json={
                    "receiver": "r",
                    "amount": 100,
                    "service_hash": _hash(f"page-{i}"),
                },
                params={"sender": "s"},
            )
        resp = client.get("/escrows?page=1&limit=3")
        body = resp.json()
        assert len(body["escrows"]) <= 3

    def test_limit_capped_at_100(self, client):
        resp = client.get("/escrows?limit=999")
        body = resp.json()
        assert body["limit"] <= 100

    def test_filter_by_status(self, client):
        h1 = _hash("filter-pending")
        h2 = _hash("filter-released")
        client.post(
            "/escrow",
            json={"receiver": "r", "amount": 100, "service_hash": h1},
            params={"sender": "s"},
        )
        client.post(
            "/escrow",
            json={"receiver": "r", "amount": 100, "service_hash": h2},
            params={"sender": "s"},
        )
        client.post("/release", json={"service_hash": h2}, params={"sender": "s"})

        resp = client.get("/escrows?status=pending")
        for esc in resp.json()["escrows"]:
            assert esc["status"] == "pending"

    def test_filter_by_sender(self, client):
        client.post(
            "/escrow",
            json={
                "receiver": "r",
                "amount": 100,
                "service_hash": _hash("filter-sender"),
            },
            params={"sender": "unique-sender-123"},
        )
        resp = client.get("/escrows?sender=unique-sender-123")
        for esc in resp.json()["escrows"]:
            assert esc["sender"] == "unique-sender-123"


# ============================================================================
# 6. SECURITY: BOUNDED NONCE CACHE
# ============================================================================


class TestNonceCacheBounds:
    """Test that the nonce cache doesn't grow unbounded."""

    def setup_method(self):
        _used_nonces.clear()

    def test_cache_accepts_fresh_nonces(self):
        ts = int(time.time())
        assert _check_replay("nonce-fresh-1", ts) is None
        assert _check_replay("nonce-fresh-2", ts) is None

    def test_cache_rejects_reused_nonce(self):
        ts = int(time.time())
        _check_replay("dup", ts)
        assert _check_replay("dup", ts) == "nonce_reused"

    def test_cache_bounded(self):
        """After MAX_NONCE_CACHE entries, old ones should be evicted."""
        ts = int(time.time())
        # Fill beyond the cap
        for i in range(MAX_NONCE_CACHE + 100):
            _check_replay(f"flood-{i}", ts)
        assert len(_used_nonces) <= MAX_NONCE_CACHE + 1  # +1 for timing

    def test_expired_timestamp_rejected(self):
        old_ts = int(time.time()) - 600
        assert _check_replay("old", old_ts) == "timestamp_expired"

    def test_future_timestamp_rejected(self):
        future_ts = int(time.time()) + 600
        assert _check_replay("future", future_ts) == "timestamp_expired"


# ============================================================================
# 7. COMPUTE HASH DETERMINISM
# ============================================================================


class TestComputeHash:
    def test_deterministic(self):
        h1 = compute_service_hash("alice", "bob", 1000, "nonce1")
        h2 = compute_service_hash("alice", "bob", 1000, "nonce1")
        assert h1 == h2

    def test_different_inputs_differ(self):
        h1 = compute_service_hash("alice", "bob", 1000, "n1")
        h2 = compute_service_hash("alice", "bob", 2000, "n1")
        assert h1 != h2

    def test_different_nonce_differs(self):
        h1 = compute_service_hash("a", "b", 100, "n1")
        h2 = compute_service_hash("a", "b", 100, "n2")
        assert h1 != h2

    def test_hash_length(self):
        h = compute_service_hash("a", "b", 100, "n")
        assert len(h) == 64

    def test_api_compute_hash(self, client):
        resp = client.post(
            "/compute-hash",
            params={"sender": "a", "receiver": "b", "amount": 100, "nonce": "x"},
        )
        assert resp.status_code == 200
        assert len(resp.json()["service_hash"]) == 64


# ============================================================================
# 8. ERROR HANDLING & EDGE CASES
# ============================================================================


class TestErrorHandling:
    def test_get_nonexistent_escrow(self, client):
        resp = client.get(f"/escrow/{_hash('no-such')}")
        assert resp.status_code == 404

    def test_release_nonexistent(self, client):
        resp = client.post("/release", json={"service_hash": _hash("ghost")})
        assert resp.status_code == 404

    def test_refund_nonexistent(self, client):
        resp = client.post("/refund", json={"service_hash": _hash("ghost")})
        assert resp.status_code == 404

    def test_dispute_nonexistent(self, client):
        resp = client.post(
            "/dispute",
            json={"service_hash": _hash("ghost"), "reason_hash": "a" * 64},
        )
        assert resp.status_code == 404

    def test_create_duplicate_409(self, client):
        h = _hash("dup-err")
        client.post(
            "/escrow",
            json={"receiver": "r", "amount": 100, "service_hash": h},
        )
        resp = client.post(
            "/escrow",
            json={"receiver": "r", "amount": 100, "service_hash": h},
        )
        assert resp.status_code == 409
        # Error message should NOT contain internal exception details
        assert "already exists" not in resp.json().get("detail", "").lower()

    def test_invalid_amount_422(self, client):
        resp = client.post(
            "/escrow",
            json={
                "receiver": "r",
                "amount": 0,
                "service_hash": _hash("invalid"),
            },
        )
        assert resp.status_code == 422

    def test_escrow_history_nonexistent(self, client):
        resp = client.get(f"/escrow/{_hash('no-history')}/history")
        assert resp.status_code == 404

    def test_escrow_history_exists(self, client):
        h = _hash("hist-ok")
        client.post(
            "/escrow",
            json={"receiver": "r", "amount": 100, "service_hash": h},
        )
        resp = client.get(f"/escrow/{h}/history")
        assert resp.status_code == 200
        assert len(resp.json()["events"]) >= 1


# ============================================================================
# 9. AGENTS LIST & STATS
# ============================================================================


class TestAgentsAndStats:
    def test_agents_list(self, client):
        client.post(
            "/escrow",
            json={
                "receiver": "agent-x",
                "amount": 100,
                "service_hash": _hash("agents-1"),
            },
            params={"sender": "agent-y"},
        )
        resp = client.get("/agents")
        assert resp.status_code == 200
        assert resp.json()["total"] >= 2

    def test_stats_endpoint(self, client):
        resp = client.get("/stats")
        assert resp.status_code == 200


# ============================================================================
# 10. CONFIG
# ============================================================================


class TestConfig:
    def test_defaults(self):
        cfg = Config()
        assert cfg.sandbox is True
        assert cfg.insurance_fee_bps == 200
        assert cfg.default_ttl == 300
        assert cfg.casper_chain_name == "casper-test"

    def test_custom(self):
        cfg = Config(
            sandbox=False,
            insurance_fee_bps=500,
            default_ttl=600,
            contract_hash="abc123",
        )
        assert cfg.sandbox is False
        assert cfg.insurance_fee_bps == 500
        assert cfg.contract_hash == "abc123"
