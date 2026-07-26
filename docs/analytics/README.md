# Analytics query pack

Portable SQL queries the operator can run against a Casper-indexed data
warehouse (Allium is the reference target; the SQL is standard enough
that Dune / Flipside / a hand-rolled Postgres warehouse also work with
minimal edits).

## Files

| File | Question it answers |
|------|--------------------|
| `allium/escrow_daily_volume.sql`  | How much CSPR flows through AE402 escrows per day? |
| `allium/dispute_lag.sql`          | Time between escrow creation and dispute opening — histogram + p50/p95. |
| `allium/arbiter_participation.sql`| Which arbiters have voted, how often, on which disputes? |
| `allium/insurance_pool_state.sql` | Insurance pool: premiums in vs claims out, per day. |
| `allium/anomaly_flow.sql`         | Escrows whose amount is > 3σ above the rolling 7-day mean per counterparty. |

## Conventions

- Every query is parameterised by a `contract_hash` — the on-chain
  address of the AE402 escrow-manager contract in the target
  deployment. Substitute at run-time.
- Times are UTC and Unix-epoch seconds; the queries do the timezone
  conversion in-warehouse.
- Named result columns are stable — the console dashboards will pick
  the columns up by name.

## Wire-up

The `Risk` page's *Regime-shift detector* consumes the output of
`anomaly_flow.sql` as its `samples[]` stream. Any other consumer just
needs to pass the same rolling-window arithmetic upstream — the CUSUM
math on the server is signal-agnostic.
