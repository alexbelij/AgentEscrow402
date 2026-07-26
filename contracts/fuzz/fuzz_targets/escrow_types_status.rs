#![no_main]
//! C12 fuzz target: `EscrowType::default_timeout_secs` must never panic.
//!
//! The Streaming variant multiplies `interval_secs * (installments as u64)`
//! without a checked_mul — a large enough pair could overflow. This target
//! feeds arbitrary values into each variant and asserts the call returns
//! (or gracefully saturates) instead of panicking.

use libfuzzer_sys::fuzz_target;
use arbitrary::{Arbitrary, Unstructured};
use ae402_stubs::escrow_types::EscrowType;

#[derive(Debug, Arbitrary)]
enum FuzzVariant {
    Standard,
    Timed(u64),
    Conditional([u8; 32]),
    Gaming(u64, Option<[u8; 32]>),
    Streaming(u64, u32),
}

impl FuzzVariant {
    fn to_escrow_type(self) -> EscrowType {
        match self {
            FuzzVariant::Standard => EscrowType::Standard,
            FuzzVariant::Timed(s) => EscrowType::Timed { release_after_secs: s },
            FuzzVariant::Conditional(k) => EscrowType::Conditional { oracle_key: k },
            FuzzVariant::Gaming(g, m) => EscrowType::Gaming {
                game_id: g,
                result_merkle_root: m,
            },
            FuzzVariant::Streaming(i, n) => EscrowType::Streaming {
                interval_secs: i,
                installments: n,
            },
        }
    }
}

fuzz_target!(|data: &[u8]| {
    let mut u = Unstructured::new(data);
    if let Ok(v) = FuzzVariant::arbitrary(&mut u) {
        let et = v.to_escrow_type();
        // Property: default_timeout_secs must return a u64 without panicking.
        // We don't assert a specific value because the Streaming variant can
        // legitimately saturate/wrap on overflow — the invariant is only
        // "no panic, no unwind".
        let _timeout: u64 = et.default_timeout_secs();
    }
});
