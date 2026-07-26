# Fresh-clone verify — Codespaces runbook

**✅ LIVE-VERIFIED on 2026-07-26.** Both defence paths (Docker + Python) now have proof:
- **Docker path** — continuously verified by the CI job [`docker-compose-smoke`](https://github.com/alexbelij/AgentEscrow402/actions/workflows/ci.yml) on every push. Last green: sha `a2387cd`, 2026-07-26T01:23:52Z, healthy after 3s.
- **Python path** — executed manually in-pod on 2026-07-26T08:22Z: fresh clone → venv → `pip install` (10s) → uvicorn (1s) → all 4 README curls HTTP 200. See [`README_STATIC_AUDIT.md`](README_STATIC_AUDIT.md) §9 for full evidence.

This runbook remains useful for reviewers who want to reproduce either path themselves.

## Why

`README.md` has ~11 explicit "runnable / verifiable" claims. Static tree-walking (grep, curl, `python -c`) proves 9 of them. Two require a real Docker daemon: `docker compose up` and `make judge-demo`. The Docker CI job proves the compose path continuously; this runbook lets you re-run either path by hand.

## Prereqs

- GitHub Codespaces (or any Linux VM with Docker Engine 20+, Node ≥18, Python ≥3.11).
- ~10 min of attention.

## Steps

Run each block *from a fresh clone* — do NOT skip the `git clone`. The whole point is "does a judge with a clean laptop hit any errors."

### Step 1 — clone

```sh
git clone https://github.com/alexbelij/AgentEscrow402.git
cd AgentEscrow402
```

Expected: 100% success, no errors.

### Step 2 — Quickstart local dev (no Docker)

The README's "Under 5 minutes for local development" claim:

```sh
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m uvicorn server.app:app --host 0.0.0.0 --port 8000
```

In another terminal:

```sh
curl http://localhost:8000/health
curl http://localhost:8000/stats
curl http://localhost:8000/escrows
```

Expected:

- `/health` → `{"status":"ok","sandbox":true,...}`
- `/stats` → some pending/released counts (in-memory sandbox seed data)
- `/escrows` → non-empty JSON list

*(Earlier note about `Neon unavailable: No module named 'psycopg_pool'` was retracted after the live pass — `psycopg-pool==3.3.1` **is** in `requirements.txt`, so on a properly installed venv the warning does not fire. See [`README_STATIC_AUDIT.md`](README_STATIC_AUDIT.md) §9.6-L3.)*

### Step 3 — Docker compose (fresh-clone claim)

```sh
docker compose up --build
```

Expected outcome: container `api` builds, listens on `0.0.0.0:8000`, `/health` responds with HTTP 200.

**Known gotcha**: if `.env` is missing, compose will fail with `env_file: .env` not found. Static audit already recorded this. Run `cp .env.example .env` first if you did not do Step 2.

### Step 4 — `make judge-demo`

The one-command reproducibility flow:

```sh
make judge-demo-check   # preflight — verify Docker + Node + Python are ready
make judge-demo         # full ~5 min run: NCTL boot → deploy → e2e → summary → teardown
```

Expected: colored final summary block ending with a manifest of deploy hashes (see `scripts/judge_demo.sh` line 210).

If preflight fails, fix the missing tool and re-run. If the full demo fails after preflight, capture the error and file it back on this ticket.

### Step 5 — full test suite

```sh
# Python
uv run --active python -m pytest -q -m "not network"
# Expected: 1628 passed, 1 skipped, 3 deselected (network) — see README_STATIC_AUDIT.md §2

# Rust contracts
cargo test --manifest-path contracts/tests/Cargo.toml
# Expected: 213 passed (property-based + FSM + reentrancy)
# NB: README.md line 714 says `contracts/escrow/Cargo.toml` — that's the *stale* manifest
# with zero tests. The real 213-test suite lives in contracts/tests/. Fix scheduled.
```

### Step 6 — WASM compile

```sh
cd contracts
cargo build --target wasm32-unknown-unknown --release -p escrow-manager
ls -la target/wasm32-unknown-unknown/release/escrow_manager.wasm
# Expected: ~174 KB binary
```

## Report format

Post the outcome of each step (✅ / ⚠️ / ❌) on the P0.1/P0.2 board ticket. If ❌ on any step, attach the error verbatim — a Codespaces terminal supports triple-backtick paste-through, so no screenshots needed.
