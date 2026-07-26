# Performance

This document is the reference for measuring and comparing the runtime
performance of the AE402 HTTP surface. All numbers are reproducible via
the in-repo bench script.

## Running the benchmark

```
python scripts/bench_escrow_flow.py                     # fast profile, ~2s
python scripts/bench_escrow_flow.py --profile normal    # 1000 iters, ~10s
python scripts/bench_escrow_flow.py --profile heavy     # 5000 iters, ~1min
python scripts/bench_escrow_flow.py --iterations 200 --concurrency 4
```

Output is a Markdown summary on stdout plus a JSON report at
`bench/results/latest.json` (unless `--no-write` is passed).

**What the script does:**

- Starts the FastAPI app via `fastapi.testclient.TestClient` — no
  network, no external processes, no OS-level socket work — so the
  numbers reflect pure Python + FastAPI overhead + our own middleware.
- Runs each scenario with the requested concurrency using an
  asyncio semaphore over a thread-pool (TestClient is sync-only).
- Deterministic input (RNG seed is fixed). Two runs on the same
  commit + same box should be within ~5%.

**What the script does NOT measure:**

- Cold-start latency (TestClient stays warm for the whole run).
- Network / TLS overhead (all in-process).
- Casper on-chain call latency (`/escrow/release` in prod calls
  `casper_client` — in sandbox it's a mock).
- DB latency (Neon connection is disconnected in the bench).

For those, you want an end-to-end load test against a live Render +
Neon deploy — that's separate tooling and not in this repo.

## Rate-limit note

`server/app.py` enforces 60 req/min per client IP via an in-memory
middleware. The bench monkey-patches that middleware to a no-op for
the duration of the run — we're measuring the app's own routing
overhead, not the rate limiter. **Do not remove the rate limiter
in prod; the patch only affects the bench-run scope.**

## Baseline

The current on-`main` baseline (committed at
`bench/results/baseline-2026-07-26.json`) — profile `normal`, 1000
iterations at concurrency 16, Python 3.11.2:

| Scenario | ok | RPS | p50 ms | p95 ms | p99 ms | max ms |
|---|---:|---:|---:|---:|---:|---:|
| `GET  /health`  | 1000 | ≈700 | 20 | 40 | 58 | 96 |
| `GET  /stats`   | 1000 | ≈670 | 22 | 36 | 49 | 63 |
| `GET  /metrics` | 1000 | ≈730 | 20 | 36 | 49 | 59 |
| `POST /escrow`  | 1000 | ≈440 | 35 | 52 | 69 | 83 |

**Interpretation:**

- All GET endpoints sit in the same latency band (~20 ms p50 / ~40 ms
  p95), because the middleware stack is the dominant cost on those —
  the endpoint work itself is a hashmap lookup + JSON encode.
- `POST /escrow` is ~1.7× slower at p50: adds Pydantic validation,
  service-hash byte-compare, sandbox-store insert. Still ~440 RPS
  in-process is comfortably above our target (100 concurrent agents
  × 1 escrow / 10 s = 10 RPS).
- p99 spikes on `/health` (95 ms) are the concurrency-16 tail — likely
  Python GIL contention on the thread-pool boundary. Not seen in the
  fast profile at concurrency 8.

## When to re-run

- Any change to `server/app.py` middleware stack.
- Any change to `server/models.py` Pydantic schemas.
- Any change to a hot code path referenced by these endpoints.
- Before every SDK release (post the results in `CHANGELOG.md` under
  the release entry).

Snapshot the new numbers to `bench/results/<YYYY-MM-DD>.json` — do
not overwrite the baseline. The baseline moves only after a
deliberate perf decision.

## CI integration

The bench script is intentionally not wired to the PR CI pipeline —
runner-hardware noise makes per-PR comparisons unreliable. Instead it
runs weekly via `contract-audit-nightly.yml` (see that workflow for
scheduling) on a stable runner and posts the JSON to `bench/results/`
via a PR.

If you want a smoke check locally on every PR that touches
`server/`, run:

```
python scripts/bench_escrow_flow.py --profile fast --no-write
```

and check that no scenario reports errors > 0.

## Related

- `scripts/bench_escrow_flow.py` — the bench itself.
- `tests/test_bench_escrow_flow.py` — smoke tests (schema stability).
- `bench/results/baseline-2026-07-26.json` — current baseline.
- `docs/OBSERVABILITY.md` (from C2) — how latency is measured in prod
  via the histograms in `server/observability.py`.
