#![no_main]
//! C12 fuzz target: `flash_guard::check_hold_period` must
//!   (1) never panic for any (u64, u64) input,
//!   (2) return Ok iff `current_time.saturating_sub(funded_at) >= MIN_HOLD_PERIOD_SECS`.
//!
//! Rationale: the hold-period check runs in the release / refund / dispute
//! hot path; a panic there would DoS the endpoint, and a wrong Ok would let
//! a flash-loan-funded caller pass. Fuzzing the raw u64 space catches both.

use libfuzzer_sys::fuzz_target;
use ae402_stubs::flash_guard;

fuzz_target!(|data: (u64, u64)| {
    let (funded_at, current_time) = data;
    let elapsed = current_time.saturating_sub(funded_at);
    let expected_ok = elapsed >= flash_guard::MIN_HOLD_PERIOD_SECS;
    match flash_guard::check_hold_period(funded_at, current_time) {
        Ok(()) => assert!(expected_ok, "unexpected Ok for elapsed={elapsed}"),
        Err(_) => assert!(!expected_ok, "unexpected Err for elapsed={elapsed}"),
    }
});
