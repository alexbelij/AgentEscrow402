# AE402 fuzz targets (C12)

Off-chain [`cargo-fuzz`](https://rust-fuzz.github.io/book/cargo-fuzz.html)
harness over the pure-Rust modules under `contracts/stubs/`. The on-chain
Casper contracts themselves are `#![no_std]` WASM and cannot host libFuzzer;
these targets fuzz the same _logic_ that server-side helpers mirror
(`server/flash_guard.py`, `server/batch_guard.py`), so a divergence between
oracle and contract shows up here.

## Targets

- `flash_guard_hold_period` — every u64 pair vs the hold-period predicate
- `flash_guard_block_delay` — every u64 pair vs the block-delay predicate
- `flash_guard_both_halves`  — composite predicate (`release` invariant)
- `escrow_types_status`       — `EscrowType::default_timeout_secs` panic-free
- `threshold_config_validate` — `ThresholdConfig::new` + `is_quorum`

## Run

```sh
cd contracts/fuzz
cargo fuzz run flash_guard_hold_period -- -max_total_time=60
cargo fuzz run escrow_types_status -- -max_total_time=60
# etc.
```

Each target is expected to exit with 0 findings on the current tree; a
non-zero exit is a real bug and blocks merge.

## Findings from the initial run

- `EscrowType::Streaming { interval_secs, installments }` panicked on
  `attempt to multiply with overflow` for large enough pairs. Fixed by
  `saturating_mul`, regression covered by
  `contracts/stubs/src/escrow_types.rs::tests::streaming_timeout_saturates_on_overflow`.

## CI

`.github/workflows/fuzz.yml` runs each target for 60 s on every push to
`main` and on `workflow_dispatch`. This is a smoke-fuzz — not a nightly
long run — and is only meant to catch fresh regressions.
