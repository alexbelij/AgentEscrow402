#![no_main]
//! C12 fuzz target: `ThresholdConfig::new` and `is_quorum`.
//!
//! Invariants under test:
//!   - new(min, total) succeeds  ⇔  1 <= min <= total  (i.e. never Ok when
//!     min == 0 or min > total, and never Err otherwise).
//!   - When Ok, `is_quorum(c)` returns true iff `c >= min_signers` for every
//!     u32 `c`. This is the exact predicate a Shamir-Secret-Sharing (SSS)
//!     coordinator will consult before releasing funds, so any drift is a
//!     safety bug.

use libfuzzer_sys::fuzz_target;
use ae402_stubs::threshold_config::ThresholdConfig;

fuzz_target!(|data: (u32, u32, u32)| {
    let (min, total, collected) = data;
    let result = ThresholdConfig::new(min, total);
    let should_be_ok = min > 0 && min <= total;

    match result {
        Ok(cfg) => {
            assert!(should_be_ok, "unexpected Ok for min={min} total={total}");
            assert_eq!(cfg.min_signers, min);
            assert_eq!(cfg.total_signers, total);
            assert!(!cfg.setup_complete, "new config must not be setup_complete");
            // Quorum predicate must be exact.
            let expected = collected >= min;
            assert_eq!(cfg.is_quorum(collected), expected);
        }
        Err(_) => {
            assert!(!should_be_ok, "unexpected Err for min={min} total={total}");
        }
    }
});
