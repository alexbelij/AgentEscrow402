"""
OpenTelemetry instrumentation for AE402.

Public entry points:
  - `setup_telemetry(app)` — wire OTel into a FastAPI app at startup.
    Idempotent; safe to call multiple times.
  - `escrow_lifecycle_span(event, service_hash, **attrs)` — context
    manager producing a custom span for a lifecycle event.
  - `record_escrow_metric(name, value, **attrs)` — record a business
    metric (opened / paid_out / approved / claim_ms).

Zero-config graceful mode:
  - If `SIGNOZ_OTEL_ENDPOINT` is unset (or empty), telemetry is a no-op
    — the server starts cleanly and calls to lifecycle spans / metrics
    do nothing.
  - If the endpoint is set but unreachable, OTel logs warnings but does
    NOT crash the server (BatchSpanProcessor retries + drops).

Env vars honored:
  - SIGNOZ_OTEL_ENDPOINT       — OTLP gRPC endpoint (e.g. http://otel-collector:4317)
  - SIGNOZ_OTEL_HEADERS        — comma-separated k=v (e.g. signoz-access-token=xyz)
  - SIGNOZ_SERVICE_NAME        — defaults to "agentescrow402"
  - SIGNOZ_DEPLOYMENT_ENV      — defaults to "development"
  - SIGNOZ_SAMPLE_RATIO        — TraceIdRatioBased sampler, defaults to "1.0"
"""

from __future__ import annotations

import contextlib
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# Module-level state — populated by setup_telemetry(); no-op accessors
# when OTel is disabled.
_ENABLED = False
_tracer: Any = None
_meter: Any = None
_metric_counters: dict[str, Any] = {}
_metric_histograms: dict[str, Any] = {}


def _endpoint() -> str:
    return (os.getenv("SIGNOZ_OTEL_ENDPOINT") or "").strip()


def _parse_headers(raw: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for pair in (raw or "").split(","):
        pair = pair.strip()
        if not pair or "=" not in pair:
            continue
        k, _, v = pair.partition("=")
        out[k.strip()] = v.strip()
    return out


def setup_telemetry(app: Any) -> bool:
    """
    Wire OTel into the given FastAPI app. Returns True if telemetry was
    activated, False if it was skipped (endpoint unset or SDK missing).

    Idempotent: subsequent calls after a successful setup are no-ops.
    """
    global _ENABLED, _tracer, _meter

    if _ENABLED:
        return True

    endpoint = _endpoint()
    if not endpoint:
        logger.info("telemetry: SIGNOZ_OTEL_ENDPOINT not set — OTel disabled (no-op)")
        return False

    try:
        from opentelemetry import metrics, trace
        from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import (
            OTLPMetricExporter,
        )
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
        from opentelemetry.sdk.resources import (
            DEPLOYMENT_ENVIRONMENT,
            SERVICE_NAME,
            SERVICE_VERSION,
            Resource,
        )
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.trace.sampling import TraceIdRatioBased
    except ImportError as e:
        logger.warning(
            "telemetry: opentelemetry SDK not installed (%s) — set is skipped."
            " `pip install opentelemetry-sdk opentelemetry-exporter-otlp"
            " opentelemetry-instrumentation-fastapi` to enable.",
            e,
        )
        return False

    service_name = os.getenv("SIGNOZ_SERVICE_NAME", "agentescrow402")
    deployment_env = os.getenv("SIGNOZ_DEPLOYMENT_ENV", "development")
    try:
        sample_ratio = float(os.getenv("SIGNOZ_SAMPLE_RATIO", "1.0"))
    except ValueError:
        sample_ratio = 1.0
    headers = _parse_headers(os.getenv("SIGNOZ_OTEL_HEADERS", ""))

    resource = Resource.create(
        {
            SERVICE_NAME: service_name,
            SERVICE_VERSION: "0.3.0",
            DEPLOYMENT_ENVIRONMENT: deployment_env,
        }
    )

    # ── Tracing ──────────────────────────────────────────────────────
    tracer_provider = TracerProvider(
        resource=resource,
        sampler=TraceIdRatioBased(sample_ratio),
    )
    span_exporter = OTLPSpanExporter(
        endpoint=endpoint,
        headers=headers,
        insecure=True,
        timeout=5,  # short — don't wedge caller if collector is down
    )
    tracer_provider.add_span_processor(
        BatchSpanProcessor(
            span_exporter,
            max_export_batch_size=64,
            schedule_delay_millis=5000,
            export_timeout_millis=5000,
        )
    )
    trace.set_tracer_provider(tracer_provider)
    _tracer = trace.get_tracer("ae402.server", "0.3.0")

    # ── Metrics ──────────────────────────────────────────────────────
    metric_exporter = OTLPMetricExporter(
        endpoint=endpoint,
        headers=headers,
        insecure=True,
        timeout=5,
    )
    metric_reader = PeriodicExportingMetricReader(
        metric_exporter,
        export_interval_millis=15000,
        export_timeout_millis=5000,
    )
    meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
    metrics.set_meter_provider(meter_provider)
    _meter = metrics.get_meter("ae402.server", "0.3.0")

    # ── FastAPI middleware auto-instrumentation ──────────────────────
    try:
        FastAPIInstrumentor.instrument_app(app)
    except Exception as e:  # noqa: BLE001
        logger.warning("telemetry: FastAPI auto-instrumentation failed: %s", e)

    # ── Warm up metric handles ───────────────────────────────────────
    _metric_counters["escrow.opened"] = _meter.create_counter(
        "escrow.opened",
        description="Escrows opened",
        unit="{escrow}",
    )
    _metric_counters["escrow.paid_out"] = _meter.create_counter(
        "escrow.paid_out",
        description="Escrows paid out",
        unit="{escrow}",
    )
    _metric_counters["arbiter.approved"] = _meter.create_counter(
        "arbiter.approved",
        description="Arbiter approvals recorded",
        unit="{vote}",
    )
    _metric_histograms["agent.claim_ms"] = _meter.create_histogram(
        "agent.claim_ms",
        description="End-to-end latency for agent-side claim submission",
        unit="ms",
    )

    _ENABLED = True
    logger.info(
        "telemetry: OTel enabled — endpoint=%s service=%s env=%s sample=%.2f",
        endpoint,
        service_name,
        deployment_env,
        sample_ratio,
    )
    return True


def is_enabled() -> bool:
    return _ENABLED


# ── Public instrumentation API ───────────────────────────────────────


@contextlib.contextmanager
def escrow_lifecycle_span(event: str, service_hash: str, **attrs: Any):
    """
    Context manager producing a span for an escrow-lifecycle event.
    No-op when OTel is disabled.
    """
    if not _ENABLED or _tracer is None:
        yield None
        return

    with _tracer.start_as_current_span(f"escrow.{event}") as span:
        span.set_attribute("escrow.service_hash", service_hash)
        for k, v in attrs.items():
            if v is not None:
                span.set_attribute(f"escrow.{k}", v)
        yield span


def record_escrow_metric(name: str, value: float = 1.0, **attrs: Any) -> None:
    """
    Record a business metric. `name` must be one of the pre-declared
    counters/histograms (escrow.opened, escrow.paid_out, arbiter.approved,
    agent.claim_ms). Unknown names are silently dropped.
    """
    if not _ENABLED:
        return
    labels = {k: v for k, v in attrs.items() if v is not None}
    if name in _metric_counters:
        _metric_counters[name].add(value, attributes=labels)
    elif name in _metric_histograms:
        _metric_histograms[name].record(value, attributes=labels)


def shutdown_telemetry() -> None:
    """Flush remaining spans + metrics. Called from lifespan shutdown."""
    global _ENABLED
    if not _ENABLED:
        return
    try:
        from opentelemetry import metrics, trace

        tp = trace.get_tracer_provider()
        if hasattr(tp, "shutdown"):
            tp.shutdown()
        mp = metrics.get_meter_provider()
        if hasattr(mp, "shutdown"):
            mp.shutdown()
    except Exception as e:  # noqa: BLE001
        logger.warning("telemetry shutdown warning: %s", e)
    finally:
        _ENABLED = False
