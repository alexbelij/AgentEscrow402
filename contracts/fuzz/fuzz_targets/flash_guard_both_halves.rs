#![no_main]
//! C12 fuzz target: correlated invariants across both flash_guard halves.
//!
//! Property: an escrow can only leave the guard alive if BOTH the
//! hold-period and the block-delay halves say Ok. Fuzzes the 4-tuple
//! `(funded_at, current_time, funded_block, current_block)` and checks
//! that the AND of the two halves matches the ground-truth predicate.

use libfuzzer_sys::fuzz_target;
use ae402_stubs::flash_guard;

fuzz_target!(|data: (u64, u64, u64, u64)| {
    let (funded_at, current_time, funded_block, current_block) = data;

    let hold_ok = flash_guard::check_hold_period(funded_at, current_time).is_ok();
    let delay_ok = flash_guard::check_block_delay(funded_block, current_block).is_ok();

    let elapsed = current_time.saturating_sub(funded_at);
    let blocks = current_block.saturating_sub(funded_block);
    let expected_hold = elapsed >= flash_guard::MIN_HOLD_PERIOD_SECS;
    let expected_delay = blocks >= flash_guard::MIN_BLOCK_DELAY;

    assert_eq!(hold_ok, expected_hold, "hold-period mismatch");
    assert_eq!(delay_ok, expected_delay, "block-delay mismatch");

    // Composite ("release passes" iff both halves are Ok) — the invariant
    // that server/app.py `_enforce_flash_guard` embodies.
    let both_ok = hold_ok && delay_ok;
    let expected_both = expected_hold && expected_delay;
    assert_eq!(both_ok, expected_both, "composite guard mismatch");
});
