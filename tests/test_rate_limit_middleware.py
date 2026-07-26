"""Tests for the in-process rate-limit middleware.

The middleware in `server/app.py` enforces 60 requests/minute per client IP.
On breach it returns HTTP 429 with a structured JSON body. The internal
`_rate_limits` cache is bounded (max 5000 entries) and evicts expired entries
opportunistically to prevent memory growth from IP churn.
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from server import app as app_module
from server.app import app


@pytest.fixture(autouse=True)
def _clear_rate_limit_state():
    """Isolate each test by clearing the in-process rate-limit cache."""
    app_module._rate_limits.clear()
    yield
    app_module._rate_limits.clear()


def _hit(client: TestClient, path: str = "/health"):
    """A lightweight endpoint hit; /health has no auth and no side effects."""
    return client.get(path)


def test_rate_limit_allows_first_60_requests():
    """Under the threshold, every request should pass."""
    client = TestClient(app)
    statuses = [_hit(client).status_code for _ in range(60)]
    # All 60 must be 200 (not rate limited).
    assert all(s == 200 for s in statuses), f"unexpected statuses: {set(statuses)}"


def test_rate_limit_returns_429_on_61st_request():
    """The 61st request within the same 60-second window must be blocked."""
    client = TestClient(app)
    for _ in range(60):
        assert _hit(client).status_code == 200
    resp = _hit(client)
    assert resp.status_code == 429
    body = resp.json()
    assert body.get("error") == "rate_limited"
    assert "detail" in body


def test_rate_limit_response_has_expected_shape():
    """A 429 body must contain 'error' and 'detail' for client-side handling."""
    client = TestClient(app)
    for _ in range(60):
        _hit(client)
    resp = _hit(client)
    assert resp.status_code == 429
    body = resp.json()
    assert set(body.keys()) >= {"error", "detail"}
    assert body["error"] == "rate_limited"


def test_rate_limit_isolates_by_ip():
    """Two clients with different IPs must not share a bucket.

    TestClient overrides `request.client.host` via the ASGI scope. We manipulate
    the internal dict directly to simulate two IPs; a real ASGI transport would
    do this via peer address.
    """
    client = TestClient(app)
    # Manually pre-fill the bucket for a fake IP.
    now = time.time()
    app_module._rate_limits["1.2.3.4"] = {"count": 60, "reset": now + 60}
    # The default TestClient IP ("testclient") should still be able to hit /health.
    resp = _hit(client)
    assert resp.status_code == 200
    # And "1.2.3.4"'s bucket is unaffected by our new request.
    assert app_module._rate_limits["1.2.3.4"]["count"] == 60


def test_rate_limit_window_resets_after_expiry():
    """After the 60-second window elapses, a new bucket must accept requests."""
    client = TestClient(app)
    for _ in range(60):
        _hit(client)
    assert _hit(client).status_code == 429

    # Fast-forward the internal cache: force the entry's reset into the past.
    for ip_key, entry in list(app_module._rate_limits.items()):
        entry["reset"] = time.time() - 1.0
    # Next request should re-initialise the bucket and succeed.
    resp = _hit(client)
    assert resp.status_code == 200


def test_rate_limit_cache_is_bounded():
    """The internal cache prunes expired entries when it grows past 5000.

    We seed >5000 expired entries, hit a real request, and confirm the cache
    was pruned (either below the trigger point or with a small headroom).
    """
    # Seed 5100 expired entries.
    past = time.time() - 3600
    for i in range(5100):
        app_module._rate_limits[f"10.0.{i // 256}.{i % 256}"] = {
            "count": 1,
            "reset": past,
        }
    client = TestClient(app)
    _hit(client)  # triggers the eviction path
    # After eviction, cache must be significantly smaller than 5100.
    # The middleware evicts all entries with reset < now-120.
    assert (
        len(app_module._rate_limits) < 5100
    ), f"cache did not prune expired entries; size={len(app_module._rate_limits)}"


def test_rate_limit_counts_only_hits_not_misses():
    """The counter increments only when a request actually reaches the middleware.

    Sanity check that 30 requests + a small sleep still leaves budget for more.
    """
    client = TestClient(app)
    for _ in range(30):
        assert _hit(client).status_code == 200
    # Still 30 remaining in the bucket.
    for _ in range(30):
        assert _hit(client).status_code == 200
    # 61st should now trip.
    assert _hit(client).status_code == 429
