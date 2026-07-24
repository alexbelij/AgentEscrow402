"""
Smoke tests for OpenTelemetry setup.

Two scenarios:
  1. SIGNOZ_OTEL_ENDPOINT unset — telemetry is a graceful no-op.
  2. SIGNOZ_OTEL_ENDPOINT set — code path is exercised end-to-end via
     a stubbed exporter to prove wiring works without spawning real
     network threads that would leak into pytest.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI

from server import telemetry


@pytest.fixture(autouse=True)
def _reset_module():
    """Wipe module-level OTel state before AND after every test — we do
    not want a leaked BatchSpanProcessor thread from one test to bleed
    into the next."""
    try:
        telemetry.shutdown_telemetry()
    except Exception:  # noqa: BLE001
        pass
    telemetry._ENABLED = False
    telemetry._tracer = None
    telemetry._meter = None
    telemetry._metric_counters.clear()
    telemetry._metric_histograms.clear()
    yield
    try:
        telemetry.shutdown_telemetry()
    except Exception:  # noqa: BLE001
        pass
    telemetry._ENABLED = False
    telemetry._tracer = None
    telemetry._meter = None
    telemetry._metric_counters.clear()
    telemetry._metric_histograms.clear()


def test_setup_is_noop_when_endpoint_unset(monkeypatch):
    monkeypatch.delenv("SIGNOZ_OTEL_ENDPOINT", raising=False)
    app = FastAPI()
    activated = telemetry.setup_telemetry(app)
    assert activated is False
    assert telemetry.is_enabled() is False


def test_metric_and_span_are_noop_when_disabled(monkeypatch):
    monkeypatch.delenv("SIGNOZ_OTEL_ENDPOINT", raising=False)
    telemetry.record_escrow_metric("escrow.opened", 1.0)
    telemetry.record_escrow_metric("agent.claim_ms", 250.5, tenant="tenant-a")
    with telemetry.escrow_lifecycle_span("test", "sh-abc"):
        pass
    telemetry.shutdown_telemetry()


def test_setup_activates_with_mocked_exporters(monkeypatch):
    """End-to-end wiring: setup returns True and metric/span calls run
    when OTLP exporters are stubbed to in-memory no-ops. This exercises
    the full setup_telemetry path (resource, provider, sampler,
    instrumentor, counters, histograms) without spawning any real
    export threads that would keep the process alive at shutdown.
    """
    try:
        import opentelemetry.sdk.trace  # noqa: F401
    except ImportError:  # pragma: no cover
        pytest.skip("opentelemetry SDK not installed")

    from opentelemetry.sdk.metrics.export import InMemoryMetricReader
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    monkeypatch.setenv("SIGNOZ_OTEL_ENDPOINT", "http://127.0.0.1:14317")
    monkeypatch.setenv("SIGNOZ_SERVICE_NAME", "ae402-test")

    # Swap the OTLP gRPC exporters for in-memory ones — same interface,
    # zero network, instant shutdown. We patch inside the SDK module
    # so setup_telemetry's `from ... import OTLPSpanExporter` picks them up.
    span_exporter = InMemorySpanExporter()
    monkeypatch.setattr(
        "opentelemetry.exporter.otlp.proto.grpc.trace_exporter.OTLPSpanExporter",
        lambda **_: span_exporter,
    )

    # For metrics, PeriodicExportingMetricReader wraps the exporter and
    # spins a background thread; swap the reader itself for an in-memory
    # reader by patching PeriodicExportingMetricReader.
    in_mem_reader = InMemoryMetricReader()
    monkeypatch.setattr(
        "opentelemetry.sdk.metrics.export.PeriodicExportingMetricReader",
        lambda *a, **kw: in_mem_reader,
    )

    app = FastAPI()
    activated = telemetry.setup_telemetry(app)
    assert activated is True
    assert telemetry.is_enabled() is True

    telemetry.record_escrow_metric("escrow.opened", 1.0)
    telemetry.record_escrow_metric("escrow.paid_out", 1.0, sender="s1")
    telemetry.record_escrow_metric("arbiter.approved", 1.0)
    telemetry.record_escrow_metric("agent.claim_ms", 42.0, agent="agent-a")

    with telemetry.escrow_lifecycle_span("opened", "sh-abc123"):
        pass

    # Force-flush BatchSpanProcessor into the in-memory exporter
    # so we can assert what was recorded.
    from opentelemetry import trace as _trace

    _trace.get_tracer_provider().force_flush(timeout_millis=1000)

    span_names = [s.name for s in span_exporter.get_finished_spans()]
    assert "escrow.opened" in span_names


def test_idempotent_setup_unit_level():
    """Unit-level check: once _ENABLED is True, setup returns True
    immediately without touching the OTel SDK. Faster and safer than
    spinning a second real provider."""
    telemetry._ENABLED = True
    app = FastAPI()
    assert telemetry.setup_telemetry(app) is True


def test_lifespan_imports_without_endpoint(monkeypatch):
    """The FastAPI app module must import cleanly with no OTel endpoint."""
    monkeypatch.delenv("SIGNOZ_OTEL_ENDPOINT", raising=False)
    from server import app as server_app

    assert server_app.app is not None
    assert hasattr(server_app.app, "router")


def test_broadcast_event_never_raises_on_lifecycle_events(monkeypatch):
    """_broadcast_event must swallow all OTel errors — it's on the hot
    event path and cannot fail even if telemetry is broken."""
    monkeypatch.delenv("SIGNOZ_OTEL_ENDPOINT", raising=False)
    from server import app as server_app

    server_app._broadcast_event({"type": "escrow_created", "service_hash": "sh-" + ("aa" * 30), "ts": 1234})
    server_app._broadcast_event({"type": "escrow_released", "service_hash": "sh-" + ("bb" * 30), "ts": 1234})
    server_app._broadcast_event({"type": "unknown_event", "service_hash": "sh-x", "ts": 1234})
    server_app._broadcast_event({"type": "arbitration_complete", "service_hash": "sh-z", "ts": 1})
    server_app._broadcast_event({"type": "escrow_resolved", "service_hash": "sh-q", "ts": 1})
