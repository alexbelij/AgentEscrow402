"""Prometheus / OpenMetrics 1.0.0 endpoint tests (Q1-#4).

Exercises server/metrics.py and the /metrics route wired in server/app.py.
No new runtime dependencies — validation is pure string parsing against
the OpenMetrics text spec:
https://github.com/OpenObservability/OpenMetrics/blob/main/specification/OpenMetrics.md
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from server import metrics as metrics_mod
from server.app import app


@pytest.fixture(autouse=True)
def _reset_counters():
    """Every test starts with a clean counter store."""
    metrics_mod.COUNTERS.reset()
    yield
    metrics_mod.COUNTERS.reset()


# ---------------------------------------------------------------------------
# Direct unit tests on the renderer
# ---------------------------------------------------------------------------


class TestRenderer:
    def test_produces_help_and_type_lines(self):
        body = metrics_mod.build_metrics_text(
            started_at=time.time() - 60,
            db_connected=True,
            chain_name="casper-test",
            contract_hashes={"escrow": "abc123"},
            sandbox_mode=False,
        )
        assert "# HELP ae402_uptime_seconds" in body
        assert "# TYPE ae402_uptime_seconds gauge" in body
        assert "# HELP ae402_db_connected" in body
        assert "# TYPE ae402_db_connected gauge" in body

    def test_terminates_with_eof(self):
        body = metrics_mod.build_metrics_text(
            started_at=time.time(),
            db_connected=True,
            chain_name="c",
            contract_hashes={},
            sandbox_mode=False,
        )
        assert body.rstrip("\n").endswith("# EOF")

    def test_db_connected_flag(self):
        body_up = metrics_mod.build_metrics_text(
            started_at=time.time(),
            db_connected=True,
            chain_name="c",
            contract_hashes={},
            sandbox_mode=False,
        )
        assert "ae402_db_connected 1.0" in body_up

        body_down = metrics_mod.build_metrics_text(
            started_at=time.time(),
            db_connected=False,
            chain_name="c",
            contract_hashes={},
            sandbox_mode=False,
        )
        assert "ae402_db_connected 0.0" in body_down

    def test_sandbox_mode_flag(self):
        body_sandbox = metrics_mod.build_metrics_text(
            started_at=time.time(),
            db_connected=True,
            chain_name="c",
            contract_hashes={},
            sandbox_mode=True,
        )
        assert "ae402_sandbox_mode 1.0" in body_sandbox

        body_live = metrics_mod.build_metrics_text(
            started_at=time.time(),
            db_connected=True,
            chain_name="c",
            contract_hashes={},
            sandbox_mode=False,
        )
        assert "ae402_sandbox_mode 0.0" in body_live

    def test_uptime_monotonic_non_negative(self):
        body = metrics_mod.build_metrics_text(
            started_at=time.time() - 100,
            db_connected=True,
            chain_name="c",
            contract_hashes={},
            sandbox_mode=False,
        )
        # Find the uptime sample line and parse the value.
        for line in body.splitlines():
            if line.startswith("ae402_uptime_seconds "):
                value = float(line.split()[1])
                assert value >= 100 - 1  # allow 1s of clock jitter
                assert value < 1_000_000
                return
        pytest.fail("uptime sample line missing")

    def test_build_info_labels_include_chain_and_contracts(self):
        body = metrics_mod.build_metrics_text(
            started_at=time.time(),
            db_connected=True,
            chain_name="casper-test",
            contract_hashes={"escrow": "hash-e", "insurance": "hash-i", "vrf": ""},
            sandbox_mode=False,
        )
        # Find the ae402_build_info line
        for line in body.splitlines():
            if line.startswith("ae402_build_info{"):
                assert 'chain="casper-test"' in line
                assert 'contract_escrow="hash-e"' in line
                assert 'contract_insurance="hash-i"' in line
                # Empty vrf hash omitted
                assert "contract_vrf" not in line
                return
        pytest.fail("ae402_build_info sample line missing")

    def test_deployed_contract_count(self):
        body = metrics_mod.build_metrics_text(
            started_at=time.time(),
            db_connected=True,
            chain_name="c",
            contract_hashes={"a": "h1", "b": "h2", "c": "", "d": None},
            sandbox_mode=False,
        )
        assert "ae402_deployed_contracts 2.0" in body

    def test_counters_emit_zero_by_default(self):
        body = metrics_mod.build_metrics_text(
            started_at=time.time(),
            db_connected=True,
            chain_name="c",
            contract_hashes={},
            sandbox_mode=False,
        )
        for counter_name in (
            metrics_mod.COUNTER_ESCROW_CREATED,
            metrics_mod.COUNTER_ESCROW_RELEASED,
            metrics_mod.COUNTER_RPC_FALLBACK,
        ):
            assert f"# TYPE {counter_name} counter" in body
            assert f"{counter_name} 0.0" in body

    def test_counters_increment_visible(self):
        metrics_mod.COUNTERS.inc(metrics_mod.COUNTER_ESCROW_CREATED, 3)
        metrics_mod.COUNTERS.inc(metrics_mod.COUNTER_ESCROW_CREATED, 2)
        metrics_mod.COUNTERS.inc(metrics_mod.COUNTER_RPC_FALLBACK)
        body = metrics_mod.build_metrics_text(
            started_at=time.time(),
            db_connected=True,
            chain_name="c",
            contract_hashes={},
            sandbox_mode=False,
        )
        assert f"{metrics_mod.COUNTER_ESCROW_CREATED} 5.0" in body
        assert f"{metrics_mod.COUNTER_RPC_FALLBACK} 1.0" in body

    def test_label_value_escapes_special_chars(self):
        body = metrics_mod.build_metrics_text(
            started_at=time.time(),
            db_connected=True,
            chain_name='chain-with-"quote"-and-\\backslash',
            contract_hashes={},
            sandbox_mode=False,
        )
        assert 'chain="chain-with-\\"quote\\"-and-\\\\backslash"' in body


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------


class TestCounterConcurrency:
    def test_concurrent_increments_are_atomic(self):
        """Race 8 threads incrementing the same counter 1000 times each."""
        import threading

        def bump():
            for _ in range(1000):
                metrics_mod.COUNTERS.inc(metrics_mod.COUNTER_ESCROW_CREATED)

        threads = [threading.Thread(target=bump) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert metrics_mod.COUNTERS.get(metrics_mod.COUNTER_ESCROW_CREATED) == 8000


# ---------------------------------------------------------------------------
# End-to-end via FastAPI TestClient
# ---------------------------------------------------------------------------


class TestMetricsRoute:
    def test_metrics_route_returns_openmetrics_content_type(self):
        client = TestClient(app)
        r = client.get("/metrics")
        assert r.status_code == 200
        ct = r.headers["content-type"]
        assert ct.startswith("application/openmetrics-text")
        assert "version=1.0.0" in ct

    def test_metrics_body_has_expected_families(self):
        client = TestClient(app)
        r = client.get("/metrics")
        assert r.status_code == 200
        body = r.text
        for expected in (
            "ae402_uptime_seconds",
            "ae402_db_connected",
            "ae402_sandbox_mode",
            "ae402_build_info",
            "ae402_deployed_contracts",
            metrics_mod.COUNTER_ESCROW_CREATED,
            metrics_mod.COUNTER_RPC_FALLBACK,
        ):
            assert expected in body

    def test_metrics_body_ends_with_eof_marker(self):
        client = TestClient(app)
        r = client.get("/metrics")
        assert r.text.rstrip("\n").endswith("# EOF")

    def test_metrics_route_reflects_live_counter_increments(self):
        client = TestClient(app)

        # Baseline
        r0 = client.get("/metrics")
        assert f"{metrics_mod.COUNTER_ESCROW_CREATED} 0.0" in r0.text

        # Bump directly
        metrics_mod.COUNTERS.inc(metrics_mod.COUNTER_ESCROW_CREATED, 7)

        r1 = client.get("/metrics")
        assert f"{metrics_mod.COUNTER_ESCROW_CREATED} 7.0" in r1.text

    def test_metrics_not_in_openapi_schema(self):
        """The /metrics endpoint is operator-facing infrastructure, not
        part of the user-facing API contract — should be hidden from
        OpenAPI/Swagger."""
        client = TestClient(app)
        r = client.get("/openapi.json")
        assert r.status_code == 200
        paths = r.json()["paths"]
        assert "/metrics" not in paths
