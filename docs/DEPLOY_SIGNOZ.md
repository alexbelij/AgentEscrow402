# AE402 SigNoz Deploy Runbook

**Task**: T23 — production deploy of the observability stack (T22 branch).
**Branch to merge**: `feat/ae402-signoz-otel` → `main`.
**Audience**: the deploy agent (or human) that owns Render + main merges.
**Author**: Pancake, 2026-07-23.

---

## TL;DR — what this runbook does

The T22 branch (`feat/ae402-signoz-otel`) added OpenTelemetry instrumentation to `server/app.py` and `server/telemetry.py`. It is **zero-config graceful**: without `SIGNOZ_OTEL_ENDPOINT` the server starts clean and the escrow hot path never touches OTel. To make telemetry actually flow, five environment variables must be set on the Render service. That is the whole T23.

**Do all three steps in one deploy cycle:**

1. Merge `feat/ae402-signoz-otel` into `main`.
2. Set the 5 env vars on the Render service (values live in the pod vault at `team.signoz_ae402` — see *§2 Env vars*).
3. Trigger a Render deploy of `main`, then run the smoke verification in *§4*.

Nothing else in the branch requires Render config changes — the `Dockerfile` and dependencies are self-contained.

---

## §1 Merge

**Branch**: `feat/ae402-signoz-otel` @ `f66133a`
**Commit author**: `alexbelij <aliaksandr.khrol@gmail.com>` (owner of `alexbelij/AgentEscrow402` — the required convention).
**PR link**: https://github.com/alexbelij/AgentEscrow402/pull/new/feat/ae402-signoz-otel

The branch is 1 commit, 6 files, 499 LOC:

- `server/telemetry.py` (new, 256 LOC) — `setup_telemetry(app)`, `escrow_lifecycle_span()`, `record_escrow_metric()`, `shutdown_telemetry()`. TraceIdRatioBased sampler, BatchSpanProcessor, PeriodicExportingMetricReader, 5s export timeouts.
- `server/app.py` — telemetry setup/shutdown inside the FastAPI `lifespan`; `_broadcast_event` now emits a span + a counter increment for `escrow_created`, `escrow_released`, `arbitration_complete`, `escrow_resolved`. All telemetry errors are swallowed — they never break the hot path.
- `tests/test_telemetry_smoke.py` (new, 125 LOC) — 6 smoke tests: no-op path, disabled path, active path with `InMemorySpanExporter` (force-flush proves the span reaches the exporter), idempotent setup, app import without endpoint, `_broadcast_event` never raises.
- `requirements.txt` — pinned:
  - `opentelemetry-api==1.28.*`
  - `opentelemetry-sdk==1.28.*`
  - `opentelemetry-exporter-otlp==1.28.*`
  - `opentelemetry-instrumentation-fastapi==0.49b2`
- `README.md` — new *📈 Observability (SigNoz / OpenTelemetry)* section.
- `.gitignore` — added `.venv-ae2/`.

**Full test suite on the branch**: `598 passed in 4.89s`, zero regressions.

Merge strategy: whatever `main` normally uses (squash or merge commit). No conflicts expected — the branch is 1 commit ahead of `main`, no divergence.

---

## §2 Env vars to set on Render

The Render service for `ae402-server` needs **five** new environment variables. The values live in the pod vault at path `team.signoz_ae402`. Retrieve them with `vault_get(store_path="team.signoz_ae402")` and paste the values into the Render dashboard (or use Render's env-group / env-file mechanism — whatever the deploy pipeline standardises on).

| Env var                    | Value source (vault field)      | Example / notes                                                                 |
|----------------------------|---------------------------------|---------------------------------------------------------------------------------|
| `SIGNOZ_OTEL_ENDPOINT`     | vault: `otlp_endpoint` + `:443` | `https://needed-shepherd.eu2.signoz.cloud:443` — see *§2.1* about the port.     |
| `SIGNOZ_OTEL_HEADERS`      | vault: `ingestion_key`          | `signoz-ingestion-key=<ingestion_key from vault>` (comma-separated k=v; one k=v here). |
| `SIGNOZ_SERVICE_NAME`      | literal                         | `ae402-server`                                                                  |
| `SIGNOZ_DEPLOYMENT_ENV`    | literal                         | `production`                                                                    |
| `SIGNOZ_SAMPLE_RATIO`      | literal                         | `1.0` (100% sampling — production traffic on AE402 is low, keep everything).    |

All five env-var **names** are declared in `server/telemetry.py` (lines 20–24). If `SIGNOZ_OTEL_ENDPOINT` is unset/empty, telemetry is a no-op and the server logs `telemetry: SIGNOZ_OTEL_ENDPOINT not set — OTel disabled (no-op)` at startup.

### §2.1 Confirming the exact endpoint

The tenant is **`needed-shepherd.eu2.signoz.cloud`** (EU2 region). The vault stores the endpoint as `otlp_endpoint = https://needed-shepherd.eu2.signoz.cloud` — **without a port**. SigNoz Cloud uses port `443` for both OTLP/HTTP and OTLP/gRPC, so the correct `SIGNOZ_OTEL_ENDPOINT` value is:

```
https://needed-shepherd.eu2.signoz.cloud:443
```

If a per-tenant subdomain endpoint does not accept OTLP directly (some SigNoz Cloud plans route OTLP through a shared regional collector, not the tenant UI host), fall back to the regional collector:

- EU → `ingest.eu.signoz.cloud:443`
- US → `ingest.us.signoz.cloud:443`
- IN → `ingest.in.signoz.cloud:443`

**Authoritative source**: log into `needed-shepherd.eu2.signoz.cloud` → **Settings → Ingestion** — the "Ingestion URL" shown there is the definitive endpoint to use. If it differs from what vault has, update `team.signoz_ae402.otlp_endpoint` too, so it stays in sync.

### §2.2 About `SIGNOZ_OTEL_HEADERS`

The vault stores the raw ingestion key under `team.signoz_ae402.ingestion_key`. The env var value should be **literally**:

```
signoz-ingestion-key=<ingestion_key from vault>
```

(no quotes, no `Bearer`, no comma if it's the only header).

If the SigNoz UI insists this account uses a **legacy access token** instead of an ingestion key, the header name must be `signoz-access-token=` instead. That is a one-line change to `SIGNOZ_OTEL_HEADERS` — the code parses `,`-separated `k=v` and does not care about the specific header name (`server/telemetry.py:112`).

### §2.3 Vault access from the deploy agent

If the deploy agent does not already have `team.*` access:

```
vault_list(prefix="team")  →  team.signoz_ae402 must be listed
vault_get(store_path="team.signoz_ae402")  →  returns { endpoint_hint, key, ... }
```

If access is denied, request it via `vault_request_access(store_path="team.signoz_ae402", reason="deploy T23")` — the pod owner (Quentin) approves in Slack DM.

---

## §3 Trigger the deploy

Trigger a Render deploy of `main` **after** the env vars are set. Standard Render flow:

- If the service is configured for auto-deploy on `main`: the merge itself triggers the deploy, but you must set the env vars *before* pushing `main` (or Render will build without them and OTel stays disabled). Recommended order: set env → merge → auto-deploy fires with env in place.
- If manual deploy: merge first, then set env, then "Manual Deploy → Deploy latest commit" from the Render dashboard.

**Build**: no change from current — same `Dockerfile`, `requirements.txt` pulls the four `opentelemetry-*` packages during `pip install` (adds ~5–8 MB, ~10s to the build).
**Runtime**: no change from current — same start command, same port. The lifespan hook runs `setup_telemetry(app)` on startup and `shutdown_telemetry()` on graceful shutdown.

---

## §4 Verification (smoke, ~2 min)

Run all four in order. If any fails, see *§5 Rollback*.

### §4.1 Startup log check

Render logs, first 30 lines of the new deploy, should contain:

```
telemetry: SigNoz OTel setup complete — endpoint=..., service=ae402-server, sample_ratio=1.0
```

If instead you see `telemetry: SIGNOZ_OTEL_ENDPOINT not set — OTel disabled (no-op)`, the env var didn't land — recheck *§2*.

### §4.2 Health endpoint

```
curl -f https://<ae402-server-render-url>/health
```

Must return 200. Prove that the OTel instrumentation didn't crash the app. If this fails, escalate — the branch was tested locally with the full test suite, so a health failure means something Render-specific (env parsing, network egress, etc.).

### §4.3 One escrow-flow round-trip

Fire one full escrow lifecycle against production to force `_broadcast_event` to emit spans + metrics. The `run_e2e.py` script (or whatever the deploy runbook uses for smoke tests) is the right tool — one create → release cycle is enough. If there's no standard smoke script, curl the `/escrow/create` endpoint with a minimal payload (see `docs/API_SDK_MCP.md` for the shape).

### §4.4 SigNoz UI check

Log into `needed-shepherd.eu2.signoz.cloud`:

- **Services** → an entry `ae402-server` (or `agentescrow402` if the env var got misconfigured — the default in `server/telemetry.py:106` is `agentescrow402`) should appear within ~60 seconds of the first request. Batch export interval is default 5s + processing lag.
- **Traces** → recent traces for `ae402-server` with span names matching `escrow.lifecycle.opened`, `escrow.lifecycle.released`, `escrow.arbitration.complete`, `escrow.resolved`.
- **Metrics** → counter `escrow_lifecycle_events_total` with attributes `event_type={created|released|arbitrated|resolved}`.

If the service appears but no traces show up: `SIGNOZ_SAMPLE_RATIO` might be `0` — should be `1.0` for production launch.

If the service doesn't appear at all: check the header format — a wrong header name (`signoz-access-token=` vs `signoz-ingestion-key=`) is the #1 cause of silent 403/401 from SigNoz Cloud. Render logs will show `OTLP export failed` if the exporter got an HTTP error.

---

## §5 Rollback

The branch is **zero-config graceful** — the safest rollback is not to revert the merge but to **unset `SIGNOZ_OTEL_ENDPOINT`** on Render and redeploy. The app returns to no-op telemetry immediately, escrow hot path is untouched.

Full revert (revert the merge commit) is only needed if the branch itself is at fault (a real regression), which the 598-passing test suite makes unlikely.

---

## §6 What happens after T23

- The SigNoz account (`needed-shepherd.eu2`) is **AE402-only** by explicit user decision (2026-07-23 Quentin, `#pancake-chat`). Keep this tenant scoped to AE402's own OTel instrumentation only.
- A follow-up ticket may add SigNoz dashboards for AE402 (escrow lifecycle rate, arbitration latency p50/p95/p99, error rate). Those are UI-side, no code changes needed.

---

## Appendix — one-glance env var block for Render

Paste-friendly (fill values from vault):

```
SIGNOZ_OTEL_ENDPOINT=https://needed-shepherd.eu2.signoz.cloud:443
SIGNOZ_OTEL_HEADERS=signoz-ingestion-key=<vault: team.signoz_ae402.ingestion_key>
SIGNOZ_SERVICE_NAME=ae402-server
SIGNOZ_DEPLOYMENT_ENV=production
SIGNOZ_SAMPLE_RATIO=1.0
```

_Confirm the endpoint against the SigNoz UI before pasting (see §2.1). If the tenant host rejects OTLP, fall back to `https://ingest.eu.signoz.cloud:443`._
