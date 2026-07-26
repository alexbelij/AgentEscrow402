"""Observability foundation for AgentEscrow402 (C2).

Two independent bits of infrastructure that historically lived in
server/app.py and server/metrics.py but grew out of scope for those
modules:

1. JSON structured logging — a stdlib-only `logging.Formatter` subclass
   that emits one JSON object per log record on stdout. Compatible with
   Loki/Fluent Bit/CloudWatch/any log shipper that reads JSON lines.
   Includes correlation_id from `contextvars` when set by the request
   middleware, so a scraper can trace one request across all log lines.

2. Request-observability middleware — measures per-route wall-clock
   latency, records it into a hand-rolled histogram (Prometheus native
   bucketing), and increments an http-request counter labelled by
   route + method + status class. Exposed via /metrics.

Design constraints:

- Zero new runtime dependency (no structlog, no prometheus_client) — we
  extend the same hand-rolled MetricFamily pattern already used in
  server/metrics.py to keep the observability contract minimal for the
  hackathon submission.
- Purely additive. No changes to existing endpoints, request semantics,
  or config schema. If AE402_JSON_LOGS is unset, logging behaves
  exactly like before (unformatted).
- Middleware is a FastAPI/ASGI-compatible plain-Python callable, so it
  works both under uvicorn and under the test client.
"""

from __future__ import annotations

import contextvars
import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

# -- Correlation-id context ------------------------------------------------

# A per-request UUID (or client-supplied X-Request-ID). Any log record
# emitted during a request handler will include this via JsonFormatter.
_correlation_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "correlation_id", default=None
)


def get_correlation_id() -> str | None:
    return _correlation_id.get()


def set_correlation_id(value: str | None) -> contextvars.Token:
    return _correlation_id.set(value)


# -- JSON log formatter ----------------------------------------------------


class JsonFormatter(logging.Formatter):
    """One-line JSON logs suited to Loki/CloudWatch/Fluent Bit ingest.

    Keys included in every record:
    - ts       : ISO-8601 UTC timestamp with millisecond precision.
    - level    : uppercase log level ("INFO", "ERROR", ...).
    - logger   : logger name.
    - msg      : the formatted message (with % args interpolated).
    - correlation_id : from contextvars, if the request middleware set one.
    - exc_info : formatted traceback when present.

    Any `record.__dict__` extras (e.g. `logger.info(..., extra={"route": ...})`)
    that aren't stdlib LogRecord internals are also included.
    """

    _RESERVED_ATTRS: frozenset[str] = frozenset(
        {
            "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
            "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
            "created", "msecs", "relativeCreated", "thread", "threadName",
            "processName", "process", "message", "asctime", "taskName",
        }
    )

    def format(self, record: logging.LogRecord) -> str:  # noqa: A003
        # Time in UTC with millisecond precision (Loki-friendly).
        ct = time.gmtime(record.created)
        ts = time.strftime("%Y-%m-%dT%H:%M:%S", ct) + f".{int(record.msecs):03d}Z"

        payload: dict[str, Any] = {
            "ts": ts,
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }

        cid = _correlation_id.get()
        if cid:
            payload["correlation_id"] = cid

        # Include any user-supplied extras (from logger.info(..., extra={...})).
        for k, v in record.__dict__.items():
            if k in self._RESERVED_ATTRS or k.startswith("_"):
                continue
            if k in payload:
                continue
            try:
                json.dumps(v)  # ensure serializable; if not, coerce to repr()
                payload[k] = v
            except (TypeError, ValueError):
                payload[k] = repr(v)

        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)

        return json.dumps(payload, separators=(",", ":"), sort_keys=False)


def configure_json_logging(level: int = logging.INFO) -> None:
    """Idempotent: install JsonFormatter on the root logger's stream handler.

    Callers: server/app.py at startup when AE402_JSON_LOGS=1. Under the
    default (unset) env, this function is not called and Python logging
    behaves normally.
    """
    root = logging.getLogger()
    root.setLevel(level)

    # Replace the formatter on any existing StreamHandler; add one if none.
    handlers = [h for h in root.handlers if isinstance(h, logging.StreamHandler)]
    if not handlers:
        h = logging.StreamHandler()
        root.addHandler(h)
        handlers = [h]

    formatter = JsonFormatter()
    for h in handlers:
        h.setFormatter(formatter)


# -- Latency histogram + request counter -----------------------------------

# Standard Prometheus latency buckets, in seconds. Covers 1 ms → 10 s
# with a shape suited to REST APIs; adjust if the profile of AE402
# requests shifts significantly.
_DEFAULT_BUCKETS_SECONDS: tuple[float, ...] = (
    0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0,
)


@dataclass
class _HistogramSeries:
    """A single labelled series (route, method, status_class)."""

    buckets: dict[float, int] = field(default_factory=dict)
    count: int = 0
    sum_seconds: float = 0.0


class RequestObservability:
    """Thread-safe recorder for HTTP request duration + counter.

    A single instance lives at module scope (see `REQUEST_OBS` below).
    Middleware records into it; /metrics reads a snapshot.
    """

    def __init__(self, buckets: tuple[float, ...] = _DEFAULT_BUCKETS_SECONDS) -> None:
        self._buckets = buckets
        self._lock = threading.Lock()
        self._series: dict[tuple[str, str, str], _HistogramSeries] = {}
        self._counter: dict[tuple[str, str, str], int] = {}

    def observe(self, route: str, method: str, status_class: str, duration_s: float) -> None:
        key = (route, method, status_class)
        with self._lock:
            s = self._series.setdefault(key, _HistogramSeries())
            for b in self._buckets:
                if duration_s <= b:
                    s.buckets[b] = s.buckets.get(b, 0) + 1
            s.count += 1
            s.sum_seconds += duration_s
            self._counter[key] = self._counter.get(key, 0) + 1

    def snapshot(self) -> tuple[dict[tuple[str, str, str], _HistogramSeries], dict[tuple[str, str, str], int]]:
        with self._lock:
            hist_copy: dict[tuple[str, str, str], _HistogramSeries] = {}
            for k, v in self._series.items():
                hist_copy[k] = _HistogramSeries(
                    buckets=dict(v.buckets),
                    count=v.count,
                    sum_seconds=v.sum_seconds,
                )
            counter_copy = dict(self._counter)
        return hist_copy, counter_copy

    @property
    def buckets(self) -> tuple[float, ...]:
        return self._buckets

    def reset(self) -> None:
        """Test-only. Clear all recorded series."""
        with self._lock:
            self._series.clear()
            self._counter.clear()


# Module-level singleton — same pattern as server/metrics.py::COUNTERS.
REQUEST_OBS = RequestObservability()


def status_class_of(status_code: int) -> str:
    """Group HTTP status codes into "2xx"/"3xx"/"4xx"/"5xx" for cardinality control."""
    if 200 <= status_code < 300:
        return "2xx"
    if 300 <= status_code < 400:
        return "3xx"
    if 400 <= status_code < 500:
        return "4xx"
    if 500 <= status_code < 600:
        return "5xx"
    return "other"


def normalize_route(path: str) -> str:
    """Best-effort route templating so /metrics doesn't blow up cardinality.

    The FastAPI request handler has a `request.scope["route"].path` attribute
    that already carries the template (e.g. "/escrow/{service_hash}"). The
    middleware prefers that; this helper is the fallback when no route match
    is available (404 handlers, static assets, etc.).
    """
    # Hex-heavy paths are almost always {service_hash}/{account_hash} slots.
    parts = path.split("/")
    out = []
    for p in parts:
        if len(p) >= 32 and all(c in "0123456789abcdefABCDEF" for c in p):
            out.append("{hash}")
        elif p.isdigit():
            out.append("{n}")
        else:
            out.append(p)
    return "/".join(out) or "/"


# -- Middleware ------------------------------------------------------------


async def observability_middleware(request, call_next):  # type: ignore[no-untyped-def]
    """FastAPI/Starlette-compatible middleware.

    - Assigns/propagates X-Request-ID as correlation_id.
    - Measures wall-clock request duration.
    - Records into REQUEST_OBS.
    - Returns the response unchanged, with X-Request-ID header echoed.
    """
    # Correlation id: prefer client-supplied header, else generate.
    client_rid = request.headers.get("X-Request-ID") or request.headers.get("X-Correlation-ID")
    rid = client_rid or uuid.uuid4().hex
    token = set_correlation_id(rid)

    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:  # noqa: BLE001
        elapsed = time.perf_counter() - started
        route_tpl = _resolve_route_template(request)
        REQUEST_OBS.observe(
            route=route_tpl,
            method=request.method,
            status_class="5xx",
            duration_s=elapsed,
        )
        _correlation_id.reset(token)
        raise

    elapsed = time.perf_counter() - started
    route_tpl = _resolve_route_template(request)
    REQUEST_OBS.observe(
        route=route_tpl,
        method=request.method,
        status_class=status_class_of(response.status_code),
        duration_s=elapsed,
    )
    response.headers["X-Request-ID"] = rid
    _correlation_id.reset(token)
    return response


def _resolve_route_template(request) -> str:  # type: ignore[no-untyped-def]
    """Prefer request.scope['route'].path when Starlette matched a route.

    Falls back to normalize_route(request.url.path) for un-matched paths.
    """
    route = request.scope.get("route")
    if route is not None and getattr(route, "path", None):
        return route.path  # already templated (e.g. "/escrow/{service_hash}")
    return normalize_route(request.url.path)


# -- Prometheus text rendering (histogram + request counter) ---------------


def render_request_families() -> list[str]:
    """Render the extra Prometheus families this module owns.

    Returned as a list of rendered `MetricFamily`-shaped strings so
    server/metrics.py can concat them into its body without importing us
    at module init time (circular-import defence).
    """
    from server.metrics import MetricFamily  # local import

    hist, counter = REQUEST_OBS.snapshot()
    buckets = REQUEST_OBS.buckets

    counter_family = MetricFamily(
        name="ae402_http_requests_total",
        kind="counter",
        help_text="HTTP requests received, labelled by route template, method, and status class.",
        samples=[
            (
                _labels({"route": route, "method": method, "status": sc}),
                float(value),
            )
            for (route, method, sc), value in sorted(counter.items())
        ],
    )

    duration_samples: list[tuple[str, float]] = []
    for (route, method, sc), series in sorted(hist.items()):
        labels_base = {"route": route, "method": method, "status": sc}
        cumulative = 0
        for b in buckets:
            cumulative = series.buckets.get(b, cumulative)
            # Prometheus expects cumulative bucket counts. We ensured that
            # in observe() by iterating buckets in order.
            duration_samples.append(
                (_labels({**labels_base, "le": _fmt_bucket(b)}), float(series.buckets.get(b, 0))),
            )
        duration_samples.append(
            (_labels({**labels_base, "le": "+Inf"}), float(series.count)),
        )
        duration_samples.append(
            (_labels({**labels_base}), float(series.sum_seconds), "_sum"),
        )
        duration_samples.append(
            (_labels({**labels_base}), float(series.count), "_count"),
        )

    # We can't render `_sum`/`_count` as separate metric names via one
    # MetricFamily. Emit them as raw strings below.
    counter_body = counter_family.render()

    hist_lines: list[str] = []
    if hist:
        hist_lines.append("# HELP ae402_http_request_duration_seconds HTTP request wall-clock duration in seconds.")
        hist_lines.append("# TYPE ae402_http_request_duration_seconds histogram")
    for (route, method, sc), series in sorted(hist.items()):
        labels_base = {"route": route, "method": method, "status": sc}
        cumulative = 0
        for b in buckets:
            cumulative += series.buckets.get(b, 0) - (0)  # already-incremented per observe
        # We re-render bucket lines from series.buckets, which stores cumulative-by-observe counts.
        for b in buckets:
            labelset = _labels({**labels_base, "le": _fmt_bucket(b)})
            hist_lines.append(f"ae402_http_request_duration_seconds_bucket{labelset} {series.buckets.get(b, 0)}")
        labelset = _labels({**labels_base, "le": "+Inf"})
        hist_lines.append(f"ae402_http_request_duration_seconds_bucket{labelset} {series.count}")
        base_labels = _labels(labels_base)
        hist_lines.append(f"ae402_http_request_duration_seconds_sum{base_labels} {series.sum_seconds}")
        hist_lines.append(f"ae402_http_request_duration_seconds_count{base_labels} {series.count}")

    return [counter_body, "\n".join(hist_lines)]


def _labels(d: dict[str, str]) -> str:
    if not d:
        return ""
    parts = [f'{k}="{_escape(v)}"' for k, v in d.items()]
    return "{" + ",".join(parts) + "}"


def _escape(v: str) -> str:
    return v.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _fmt_bucket(b: float) -> str:
    # Prometheus canonical bucket labels: 0.005, 0.01, ... use minimal repr.
    if b >= 1:
        return f"{b:.3f}".rstrip("0").rstrip(".")
    return f"{b}"
