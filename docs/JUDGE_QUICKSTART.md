# Judge Quickstart — 60 seconds from clone to “released”

> **Audience:** hackathon judge / auditor / anyone who wants to confirm the
> AE402 backend and CLI actually work, without spinning up Docker, NCTL, or
> paying for testnet gas.
>
> **Time budget:** ≤60 seconds from a fresh `git clone`.
> **Requirements:** Python 3.11+ and a free TCP port. That's it.

---

## TL;DR

```bash
git clone https://github.com/alexbelij/AgentEscrow402
cd AgentEscrow402
pip install -r requirements.txt         # ~10 s on a warm cache
make judge-lite                         # boots sandbox, runs 5 CLI checks, tears down
```

Expected output (last two lines):

```
✔ 5/5 CLI checks passed against sandbox backend.
✔ Backend stopped, log at /tmp/ae402-judge-lite.*.log (safe to delete).
```

Exit code `0` means every check on the [checklist](#what-judge-lite-verifies)
below passed.

If you want more than 60 seconds and you're OK with Docker + a local
Casper 2.0 NCTL network, run `make judge-demo` instead. That path
actually deploys the WASM contracts and exercises them on-chain
(~5 minutes). This document is about the *lite* path.

---

## What `judge-lite` verifies

1. **`ae402 health`** — sandbox backend answers `{status:"ok", sandbox:true, db:"disconnected"}`. Proves the FastAPI app boots and its liveness probe is wired correctly.
2. **`ae402 stats`** — `/stats` endpoint returns aggregate escrow counters. Proves the SDK's `_request()` signature actually accepts a read-only route (the P0.2 regression we closed in this repo).
3. **`ae402 list-escrows --limit 5`** — `/escrows` list endpoint returns the recent-escrows window. Proves query-string forwarding (`params=`) works end-to-end through the SDK.
4. **`ae402 mcp-tools`** — `/mcp/tools` returns the advertised MCP tool catalogue. Proves the MCP tool surface is discoverable exactly as documented.
5. **`ae402 compute-hash …`** — offline determinism check. Proves the SDK computes the canonical `service_hash` locally with **no** network call. Should be byte-identical across machines given the same `(receiver, amount, nonce)` input.

If any single check fails the script exits `1` with:

- the failing check name in red,
- the last 20 lines of that check's stderr,
- the last 40 lines of the uvicorn log path.

That's everything you need to file a bug — no additional debugging on your side.

---

## Options

```bash
make judge-lite         # full pass (default)
make judge-lite-keep    # same, but leave uvicorn running on 127.0.0.1:<port> for inspection
make judge-lite-check   # preflight only: Python + requirements, no boot
```

If the auto-picked port collides with something on your machine, override:

```bash
AE402_JUDGE_LITE_PORT=8125 make judge-lite
```

---

## Behind the scenes

`scripts/judge_lite.sh` performs a hermetic self-check:

- Refuses to run under Python < 3.11.
- If `server.app` or `sdk.cli` are not importable, runs `pip install -r requirements.txt` and retries once.
- Chooses a free TCP port via `socket.bind(("127.0.0.1", 0))`.
- Boots `uvicorn server.app:app` in the background under `SANDBOX=true` (default) at `--log-level warning`. Log goes to a temp file.
- Waits up to 15 seconds for `/health` to return `200`, giving up with a red banner otherwise.
- Runs each CLI check via `ae402 --base-url http://127.0.0.1:$PORT --sandbox <cmd>` (or `python -m sdk.cli …` if the `ae402` entrypoint isn't installed).
- On exit, kills uvicorn unless `--keep` was passed. Deletes nothing else — the log file is a breadcrumb for any post-mortem.

---

## What `judge-lite` **does not** cover

By design, this path skips everything that needs a real Casper node:

- Contract deployment (see `make judge-demo`).
- On-chain state reads (see `scripts/query_multi_asset_state.py`).
- Real signature verification against a deployed contract (see `tests/test_bridge_evm_sepolia_integration.py` for the EVM-side counterpart).
- Docker-based smoke test (see `.github/workflows/docker-compose-smoke.yml`).

If a full on-chain reproduction is what you need, `make judge-demo` is the right tool. This lite path is intentionally the cheapest, fastest possible proof-of-life for the Python surface — small enough to run on every CI push, portable enough to run on a fresh laptop with no admin rights.

---

## Related

- `scripts/judge_demo.sh` — full ~5-minute on-chain flow (Docker + NCTL + WASM).
- `docs/CLI.md` — full command reference for the `ae402` binary.
- `docs/API.md` — REST API surface the backend serves.
- `docs/defence/README_STATIC_AUDIT.md` — static audit + live-verify pass we ran against `main`.
