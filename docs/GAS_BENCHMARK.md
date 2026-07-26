# Gas Benchmark Report

Real testnet gas costs for `escrow-manager` entry points, measured against the live v9
contract (`612cead2226329fafec492042fd96a999df06d1e88c476913a167f44d3ddd9ec`). All numbers
come from actual confirmed deploys already recorded in
[`docs/evidence/bulk_escrow_tx_log.jsonl`](evidence/bulk_escrow_tx_log.jsonl) — no synthetic
or local-node estimates.

## Methodology

- Sampled a subset of confirmed deploy hashes per entry point from the 359-entry bulk-tx log
  (`create`: 12 of 178, `release`: 12 of 171, `refund`: all 4, `dispute`: all 3, `resolve`:
  all 3 — the last three groups only have that many real on-chain occurrences so far).
- Pulled each deploy's execution result from `GET /deploys/{hash}` on the CSPR.cloud testnet
  API (`consumed_gas`, `cost` = configured payment cap, `refund_amount`).
- `consumed_gas` is denominated in gas units, which map 1:1 to motes at gas price 1
  (Casper testnet default); divided by 1e9 to express in CSPR.

## Results (mean of sampled deploys, in CSPR)

| Entry point | Gas consumed | Payment cap (funded) | Refund | Notes |
|---|---|---|---|---|
| `create_escrow` | 3.625 | 12.0 | 6.281 | Deterministic — identical gas across all 12 samples (fixed-size args, no branching cost). |
| `release` | 3.176 | 5.0 | 1.368 | Deterministic — identical gas across all 12 samples. Cheaper than `create` (no new dictionary-item allocation). |
| `refund` | 2.970 | 5.0 | 1.522 | Deterministic across the 4 real occurrences. Cheapest of the fund-moving paths. |
| `dispute` | 0.648 | 5.0 | 3.264 | Cheapest entry point overall — only flips a status flag, no fund movement. |
| `resolve` (3-of-5 arbiter multisig) | 7.537 (range 7.473–7.628) | 10.0 | 1.847 | Most expensive — verifies 3 ed25519 signatures on-chain plus moves funds. Only entry point with measurable variance across runs (signature-verification cost is not perfectly constant call-to-call). |

## Practical takeaways

- **Configured payment caps are comfortably oversized** — refunds recover a meaningful
  fraction of every cap, confirming the caps in `server/casper_tx/*.mjs` are safe-but-generous
  rather than tightly tuned. There's headroom to reduce caps (e.g. `release`/`refund`/`dispute`
  caps could likely drop from 5.0 to ~4.0 CSPR) if minimizing locked-up gas float matters for a
  production deployment — not changed here since it's a caller-side convenience knob, not a
  contract change, and reducing it risks "out of gas" if network gas prices rise.
- **Arbiter-quorum `resolve` is ~2x the cost of a plain `release`**, which is the expected and
  acceptable price of the 3-of-5 signature-verification security guarantee.
- **`dispute` is nearly free** relative to the other paths since it only writes a status flag.

Full per-deploy raw numbers for this sample are reproducible via
[`docs/evidence/bulk_escrow_tx_log.jsonl`](evidence/bulk_escrow_tx_log.jsonl) (deploy hashes)
and `GET https://api.testnet.cspr.cloud/deploys/{hash}`.
