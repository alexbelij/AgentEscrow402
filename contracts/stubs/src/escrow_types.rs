//! Extensible escrow type enumeration.
//!
//! Different escrow types have different settlement logic,
//! fee structures, and timeout behaviors.

/// Categories of escrow with distinct business logic.
#[derive(Clone, Debug, PartialEq)]
pub enum EscrowType {
    /// Standard buyer-seller escrow with single delivery confirmation.
    Standard,
    /// Time-locked escrow that auto-releases after deadline.
    Timed { release_after_secs: u64 },
    /// Conditional escrow requiring external oracle confirmation.
    Conditional { oracle_key: [u8; 32] },
    /// Gaming reward escrow with Merkle proof of game results.
    Gaming { game_id: u64, result_merkle_root: Option<[u8; 32]> },
    /// Streaming payment released incrementally over time.
    Streaming { interval_secs: u64, installments: u32 },
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn streaming_timeout_saturates_on_overflow() {
        // Regression: fuzz target `escrow_types_status` found the naive
        // `interval_secs * installments as u64` panicked with attempt-to-
        // multiply-with-overflow. The fix uses saturating_mul; verify.
        let et = EscrowType::Streaming {
            interval_secs: u64::MAX,
            installments: u32::MAX,
        };
        assert_eq!(et.default_timeout_secs(), u64::MAX);
    }

    #[test]
    fn streaming_timeout_normal_multiplies() {
        let et = EscrowType::Streaming {
            interval_secs: 100,
            installments: 5,
        };
        assert_eq!(et.default_timeout_secs(), 500);
    }
}

impl EscrowType {
    pub fn default_timeout_secs(&self) -> u64 {
        match self {
            EscrowType::Standard => 86400 * 7,       // 7 days
            EscrowType::Timed { release_after_secs } => *release_after_secs,
            EscrowType::Conditional { .. } => 86400 * 14, // 14 days
            EscrowType::Gaming { .. } => 86400 * 3,   // 3 days
            EscrowType::Streaming { interval_secs, installments } => {
                // C12: `interval_secs * installments` panics in debug builds
                // (attempt to multiply with overflow) for large enough pairs
                // — discovered by the escrow_types_status fuzz target. Use
                // saturating_mul so the timeout maxes out at u64::MAX rather
                // than aborting the whole enclosing contract call.
                interval_secs.saturating_mul(*installments as u64)
            }
        }
    }
}
