# AgentEscrow402 SDK cookbook

Six runnable examples covering the full escrow lifecycle. Each script is
self-contained — no shared state, no hidden env — and prints numbered
step traces so a judge can copy any of them into a terminal and see
exactly what the SDK does against the running server.

## Prerequisites

```bash
# Local sandbox (recommended for first run)
uvicorn server.app:app --reload
```

Or point at the live testnet deployment with `--api-url https://…`.

## Cookbook

| # | Example | What it demonstrates |
|---|---------|----------------------|
| 01 | `01_quickstart_happy_path.py` | Minimal create → release lifecycle. First read. |
| 02 | `02_dispute_and_resolve.py` | Buyer disputes → AI arbitration recommendation → arbiter-quorum resolve path. |
| 03 | `03_batch_escrows.py` | Create N escrows, bulk release via `batch_release`. |
| 04 | `04_streaming_escrow.py` | Time-vested claims: create a streaming escrow, poll `claim_stream` at intervals. |
| 05 | `05_htlc_atomic_swap.py` | Hash Time-Locked Contract swap: sha256(preimage) commitment, receiver claims by revealing preimage. |
| 06 | `06_insurance_claim.py` | Insurance-pool fallback: dispute → arbitration abstain → cooldown → pool claim → tombstone replay-reject. |
| — | `escrow_agent.py` | Full autonomous buyer + seller agent lifecycle (existing full-scenario demo). |

`quickstart.py` is a symlink to `01_quickstart_happy_path.py` for
backwards compatibility with the previous docs.

## Running

Each script accepts `--api-url` and its own scenario-specific flags:

```bash
python examples/01_quickstart_happy_path.py --amount 500000
python examples/02_dispute_and_resolve.py
python examples/03_batch_escrows.py --count 5
python examples/04_streaming_escrow.py --duration-seconds 60
python examples/05_htlc_atomic_swap.py --timeout-seconds 3600
```

## Amounts

All amounts are in **motes** (1 CSPR = 1e9 motes). See
`docs/CSPR_UNITS.md` for the systemic conversion contract.

## Server-side dependencies

`04_streaming_escrow.py` and `05_htlc_atomic_swap.py` use routes from
the `multi_asset` router; if a stripped-down sandbox has that router
disabled, the scripts detect the 404 and exit cleanly instead of
crashing.
