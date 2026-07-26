"""Tests for server/observability.py (C2).

Covers three units:
1. JsonFormatter — one-line JSON emission with correlation_id + extras.
2. RequestObservability — thread-safe histogram + counter recording.
3. Middleware + /metrics — end-to-end via TestClient: a request flows
   through the middleware, gets recorded, shows up on /metrics.
"""

from __future__ import annotations

import json
import logging
import re

import pytest
from fastapi.testclient import TestClient


def _reset_obs():
    from server.observability import REQUEST_OBS

    REQUEST_OBS.reset()


# ---------------------------------------------------------------------------
# JsonFormatter
# ---------------------------------------------------------------------------


class TestJsonFormatter:
    def _make_record(self, level: int = logging.INFO, msg: str = "hello", **extra) -> logging.LogRecord:
        rec = logging.LogRecord(
            name="test.logger",
            level=level,
            pathname="/x/y.py",
            lineno=1,
            msg=msg,
            args=(),
            exc_info=None,
        )
        for k, v in extra.items():
            setattr(rec, k, v)
        return rec

    def test_basic_fields_present(self) -> None:
        from server.observability import JsonFormatter

        fmt = JsonFormatter()
        line = fmt.format(self._make_record(msg="hi"))
        obj = json.loads(line)
        assert obj["level"] == "INFO"
        assert obj["logger"] == "test.logger"
        assert obj["msg"] == "hi"
        # Timestamp must be ISO-8601 UTC with millisecond precision.
        assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$", obj["ts"])

    def test_correlation_id_from_contextvar(self) -> None:
        from server.observability import JsonFormatter, set_correlation_id

        fmt = JsonFormatter()
        tok = set_correlation_id("test-rid-42")
        try:
            line = fmt.format(self._make_record())
        finally:
            from server.observability import _correlation_id  # noqa

            _correlation_id.reset(tok)
        obj = json.loads(line)
        assert obj["correlation_id"] == "test-rid-42"

    def test_extras_serialized(self) -> None:
        from server.observability import JsonFormatter

        fmt = JsonFormatter()
        line = fmt.format(self._make_record(route="/escrow/{h}", duration_ms=42))
        obj = json.loads(line)
        assert obj["route"] == "/escrow/{h}"
        assert obj["duration_ms"] == 42

    def test_non_serializable_extras_coerced(self) -> None:
        from server.observability import JsonFormatter

        class Weird:
            def __repr__(self) -> str:
                return "<Weird>"

        fmt = JsonFormatter()
        line = fmt.format(self._make_record(obj=Weird()))
        obj = json.loads(line)
        assert obj["obj"] == "<Weird>"

    def test_exc_info_formatted(self) -> None:
        from server.observability import JsonFormatter

        fmt = JsonFormatter()
        try:
            raise ValueError("boom")
        except ValueError:
            import sys

            rec = self._make_record(level=logging.ERROR, msg="failure")
            rec.exc_info = sys.exc_info()
        line = fmt.format(rec)
        obj = json.loads(line)
        assert "exc_info" in obj
        assert "ValueError: boom" in obj["exc_info"]


# ---------------------------------------------------------------------------
# RequestObservability recorder
# ---------------------------------------------------------------------------


class TestRequestObservability:
    def test_observe_updates_count_and_sum(self) -> None:
        from server.observability import RequestObservability

        obs = RequestObservability(buckets=(0.1, 0.5, 1.0))
        obs.observe("/x", "GET", "2xx", 0.05)
        obs.observe("/x", "GET", "2xx", 0.3)

        hist, counter = obs.snapshot()
        key = ("/x", "GET", "2xx")
        assert counter[key] == 2
        s = hist[key]
        assert s.count == 2
        assert s.sum_seconds == pytest.approx(0.35, rel=1e-6)

    def test_buckets_populate_below_boundary(self) -> None:
        from server.observability import RequestObservability

        obs = RequestObservability(buckets=(0.1, 0.5, 1.0))
        obs.observe("/x", "GET", "2xx", 0.05)  # ≤ 0.1, 0.5, 1.0
        obs.observe("/x", "GET", "2xx", 0.7)   # ≤ 1.0 only

        hist, _ = obs.snapshot()
        s = hist[("/x", "GET", "2xx")]
        assert s.buckets[0.1] == 1   # 0.05
        assert s.buckets[0.5] == 1   # 0.05
        assert s.buckets[1.0] == 2   # 0.05, 0.7

    def test_multiple_keys_kept_separate(self) -> None:
        from server.observability import RequestObservability

        obs = RequestObservability(buckets=(1.0,))
        obs.observe("/a", "GET", "2xx", 0.1)
        obs.observe("/b", "POST", "5xx", 0.1)

        _, counter = obs.snapshot()
        assert counter[("/a", "GET", "2xx")] == 1
        assert counter[("/b", "POST", "5xx")] == 1


class TestNormalizeRoute:
    def test_hex_slot_collapsed(self) -> None:
        from server.observability import normalize_route

        assert normalize_route("/escrow/" + "ab" * 32) == "/escrow/{hash}"
        assert normalize_route("/escrow/" + "ab" * 32 + "/history") == "/escrow/{hash}/history"

    def test_digit_slot_collapsed(self) -> None:
        from server.observability import normalize_route

        assert normalize_route("/user/12345/profile") == "/user/{n}/profile"

    def test_static_paths_untouched(self) -> None:
        from server.observability import normalize_route

        assert normalize_route("/health") == "/health"
        assert normalize_route("/mcp/tools") == "/mcp/tools"


# ---------------------------------------------------------------------------
# Middleware + /metrics end-to-end
# ---------------------------------------------------------------------------


class TestMiddlewareEndToEnd:
    def setup_method(self) -> None:
        _reset_obs()

    def test_request_id_echoed(self) -> None:
        from server.app import app

        c = TestClient(app)
        r = c.get("/health")
        assert r.status_code == 200
        rid = r.headers.get("X-Request-ID")
        assert rid and len(rid) >= 8

    def test_request_id_propagated_when_client_supplied(self) -> None:
        from server.app import app

        c = TestClient(app)
        r = c.get("/health", headers={"X-Request-ID": "client-rid-xyz"})
        assert r.status_code == 200
        assert r.headers.get("X-Request-ID") == "client-rid-xyz"

    def test_metrics_endpoint_includes_new_families(self) -> None:
        from server.app import app

        c = TestClient(app)
        c.get("/health")
        c.get("/stats")
        r = c.get("/metrics")
        assert r.status_code == 200
        body = r.text
        assert "ae402_http_requests_total" in body
        assert "ae402_http_request_duration_seconds_bucket" in body
        assert 'route="/health"' in body
        assert 'method="GET"' in body
        assert 'status="2xx"' in body
        # OpenMetrics 1.0 conformance
        assert body.endswith("# EOF\n")

    def test_histogram_bucket_cumulative_semantics(self) -> None:
        from server.app import app

        c = TestClient(app)
        # Hit /health a few times to accumulate a real histogram.
        for _ in range(5):
            c.get("/health")
        r = c.get("/metrics")
        body = r.text

        # +Inf bucket must equal _count.
        route_lines = [l for l in body.splitlines() if 'route="/health"' in l and 'duration_seconds' in l]
        inf_line = next(l for l in route_lines if 'le="+Inf"' in l)
        count_line = next(l for l in route_lines if l.startswith("ae402_http_request_duration_seconds_count"))

        inf_val = int(inf_line.split()[-1])
        count_val = int(count_line.split()[-1])
        assert inf_val == count_val
        assert count_val >= 5  # at least our 5 hits (metrics itself is not counted for /metrics)
