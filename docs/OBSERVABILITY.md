# Observability

> **What this covers.** How to see AgentEscrow402 with the eyes of a
> Prometheus/Grafana operator. What metrics we expose, what labels they
> carry, how to enable structured logs, how to import the Grafana
> dashboard, and how to trace a single request end-to-end via a
> correlation id.
>
> **Audience.** Anyone running the backend outside a laptop demo —
> hackathon judges verifying operational readiness, pilot integrators,
> the eventual production operator.

---

## 1. `/metrics` — Prometheus / OpenMetrics scrape endpoint

**URL:** `GET /metrics` (also `GET /api/v1/metrics/prometheus` — same body).

**Content-type:** `application/openmetrics-text; version=1.0.0; charset=utf-8`.

Response body ends with `# EOF` (OpenMetrics 1.0 conformance). Zero
runtime dependencies: no `prometheus_client`, no separate exporter —
the metric families are hand-rendered to keep the audit surface small.

### Families

Names use the `ae402_` namespace prefix throughout to keep group-by
predictable across a multi-service Prometheus.

| Metric | Type | Labels | Meaning |
|---|---|---|---|
| `ae402_uptime_seconds` | gauge | — | Seconds since the process started. |
| `ae402_db_connected` | gauge | — | `1` if the DB is reachable, else `0`. |
| `ae402_sandbox_mode` | gauge | — | `1` under sandbox (mock chain), `0` for live testnet. |
| `ae402_build_info` | gauge (value=1) | `chain`, `contract_escrow`, `contract_manager`, `contract_insurance`, `contract_vrf` | Label-carrier for chain identity + deployed contract hashes. |
| `ae402_deployed_contracts` | gauge | — | Number of core contracts with a non-empty deploy hash. |
| `ae402_escrow_created_total` | counter | — | Escrow-lifecycle counter (server has created N escrows). |
| `ae402_escrow_released_total` | counter | — | Escrows released (funds sent to worker). |
| `ae402_escrow_refunded_total` | counter | — | Escrows refunded (funds returned to buyer). |
| `ae402_escrow_disputed_total` | counter | — | Escrows moved into disputed state. |
| `ae402_escrow_resolved_total` | counter | — | Disputes resolved by arbiter quorum. |
| `ae402_rpc_fallback_total` | counter | — | RPC-client fallbacks to secondary endpoint. |
| `ae402_arbiter_quorum_met_total` | counter | — | Arbiter-quorum verifications that succeeded. |
| `ae402_arbiter_quorum_missing_total` | counter | — | Arbiter-quorum verifications that failed. |
| **`ae402_http_requests_total`** | counter | `route`, `method`, `status` (2xx/3xx/4xx/5xx) | HTTP requests received. |
| **`ae402_http_request_duration_seconds_bucket`** + `_sum` + `_count` | histogram | `route`, `method`, `status`, `le` | Wall-clock request duration. Buckets: `0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0` seconds. |

**Bold** = added in **C2** (this document).

### Route label hygiene

The middleware collapses variable path slots to templates *before*
recording, so `/escrow/{service_hash}` is one series, not one per hash
value. Hex-heavy segments (`≥32 hex chars`) collapse to `{hash}`;
digit-only segments collapse to `{n}`. If Starlette matched the
request to a `Route`, its `.path` template is used directly.

### Sample scrape

```
# TYPE ae402_http_requests_total counter
ae402_http_requests_total{route="/health",method="GET",status="2xx"} 5
ae402_http_requests_total{route="/stats",method="GET",status="2xx"} 1
ae402_http_request_duration_seconds_bucket{route="/health",method="GET",status="2xx",le="0.005"} 4
ae402_http_request_duration_seconds_bucket{route="/health",method="GET",status="2xx",le="0.01"} 5
ae402_http_request_duration_seconds_bucket{route="/health",method="GET",status="2xx",le="+Inf"} 5
ae402_http_request_duration_seconds_sum{route="/health",method="GET",status="2xx"} 0.041
ae402_http_request_duration_seconds_count{route="/health",method="GET",status="2xx"} 5
```

---

## 2. Correlation ID (X-Request-ID)

Every request enters the observability middleware and:

- If the client supplied `X-Request-ID` (or `X-Correlation-ID`), we
  reuse it. Otherwise we generate a fresh `uuid4().hex` (32 hex chars).
- The value is echoed on the response header `X-Request-ID`.
- Inside the handler, `server.observability.get_correlation_id()`
  returns it — and the JSON log formatter automatically includes it in
  every log line emitted during the request scope (via `contextvars`).

**Practical use.** A user reports a broken escrow. You ask for the
`X-Request-ID` shown in the browser devtools, then in Loki:
`{app="ae402"} |= "correlation_id=<rid>"` returns every log line the
request touched — even across background tasks that inherit the same
context.

---

## 3. Structured JSON logs (opt-in)

Off by default. Enable by setting `AE402_JSON_LOGS=1` before starting
the server:

```bash
AE402_JSON_LOGS=1 uvicorn server.app:app --host 0.0.0.0 --port 8000
```

Every log record becomes one JSON line on stdout, ready for Loki /
Fluent Bit / CloudWatch Logs Insights. Shape:

```json
{
  "ts":"2026-07-26T09:31:07.418Z",
  "level":"INFO",
  "logger":"server.agent_identity",
  "msg":"Registering agent identity for ab12cd34",
  "correlation_id":"a7ac06fc9c0f4c96b58f2ba9d0f2fdb8"
}
```

Extras attached via `logger.info(..., extra={"route": "/escrow/{h}"})`
are merged into the top-level JSON object (never nested under `extra`),
so LogQL filters remain first-class:

```logql
{app="ae402"} | json | route="/escrow/{h}" | level="ERROR"
```

Existing plain-text logging behaviour is preserved when the env var is
unset. This is a **zero-risk toggle** — no dependency changes, no
schema migration.

---

## 4. Grafana dashboard

`deploy/grafana/ae402-overview.json` is a self-contained Grafana
dashboard JSON. Import from the Grafana UI:

`Dashboards → New → Import → Upload JSON → pick the file`.

Panels included:

- **Row 0 (stat panels):** backend up, DB connected, sandbox mode, deployed contracts count.
- **Row 1 (time series):** escrow lifecycle counters (rate/min), HTTP request rate by route.
- **Row 2 (time series):** p50/p95/p99 latency across all routes, p95 broken down by route.
- **Row 3 (time series):** HTTP error rate (4xx+5xx) per route, arbiter quorum success vs miss.

Datasource: pick your Prometheus data source at import time (Grafana
prompts).

Recommended companion queries (paste into a Grafana Explore panel to
verify wiring):

- Requests per second by route: `sum by (route) (rate(ae402_http_requests_total[5m]))`
- p95 latency of the create-escrow route: `histogram_quantile(0.95, sum by (le) (rate(ae402_http_request_duration_seconds_bucket{route="/escrow"}[5m])))`
- Error-rate by status class: `sum by (status) (rate(ae402_http_requests_total{status=~"4xx|5xx"}[5m]))`

---

## 5. Scraping (Prometheus config)

Minimal Prometheus scrape:

```yaml
scrape_configs:
  - job_name: ae402
    metrics_path: /metrics
    scrape_interval: 15s
    static_configs:
      - targets: ["ae402-backend.internal:8000"]
```

Or via Grafana Agent / vmagent — same OpenMetrics endpoint works for
all of them.

---

## 6. Verifying the wiring locally

```bash
# In terminal A: boot the sandbox backend.
make judge-lite-keep

# In terminal B: send a couple of requests.
curl -s http://127.0.0.1:$PORT/health > /dev/null
curl -s http://127.0.0.1:$PORT/stats  > /dev/null

# Then scrape:
curl -s http://127.0.0.1:$PORT/metrics | grep -E "^ae402_http"
```

You should see request counters + duration histograms populated for
`/health` and `/stats`, with `route`, `method`, `status` labels.

---

## 7. Related

- `server/observability.py` — implementation.
- `server/metrics.py` — the pre-existing Prometheus text renderer this
  extends.
- `docs/JUDGE_QUICKSTART.md` — 60-second reproducibility path (uses the
  same sandbox backend).
- `docs/API.md` — full REST surface.
