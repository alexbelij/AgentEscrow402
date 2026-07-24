//! Host-independent half of the insurance-pool claim() preconditions, split
//! out purely so `cargo test` can run the state-machine decision logic on
//! the host target (mirrors the `multi-asset-escrow` lib.rs/logic.rs split).
//! The wasm contract (`src/main.rs`) calls straight into this module so
//! there is exactly one place the tombstone/cooldown/coverage decision is
//! made -- these tests exercise the real decision path, not a hand-copied
//! mirror of it.
//!
//! Order matters and is the actual security property under test: the
//! escrow-id tombstone (`already_claimed`) is checked *before* the
//! claimant-scoped cooldown. A claimant cannot defeat the tombstone by
//! simply waiting out the cooldown window and replaying the same signed
//! claim message for the same `escrow_id` -- see `replay_after_cooldown_...`
//! below.

use casper_types::U512;

#[derive(Debug, PartialEq, Eq)]
pub enum ClaimRejection {
    /// escrow_id already has a tombstone recorded (ERR_ESCROW_ALREADY_CLAIMED = 9).
    AlreadyClaimed,
    /// caller is still inside COOLDOWN_SECONDS of their last claim (ERR_COOLDOWN = 4).
    Cooldown,
    /// amount exceeds MAX_COVERAGE_BPS of current pool balance (ERR_MAX_COVERAGE_EXCEEDED = 5).
    MaxCoverageExceeded,
    /// amount exceeds current pool balance outright (ERR_CLAIM_AMOUNT_TOO_LARGE = 6).
    ClaimAmountTooLarge,
}

pub const COOLDOWN_SECONDS: u64 = 86_400; // 24 hours
pub const MAX_COVERAGE_BPS: u64 = 8_000; // 80% of pool balance

/// Pure re-implementation of the exact check order in `claim()`:
/// tombstone -> (quorum, verified separately by the caller) -> cooldown ->
/// max-coverage cap -> absolute balance cap. Quorum verification itself
/// needs real Ed25519 host crypto and stays in `main.rs`; everything else
/// is plain arithmetic/state and is fully exercised here.
pub fn check_claim_preconditions(
    already_claimed: bool,
    last_claim_timestamp: u64,
    now: u64,
    requested_amount: U512,
    pool_balance: U512,
) -> Result<(), ClaimRejection> {
    if already_claimed {
        return Err(ClaimRejection::AlreadyClaimed);
    }

    if now < last_claim_timestamp.saturating_add(COOLDOWN_SECONDS) {
        return Err(ClaimRejection::Cooldown);
    }

    let max_coverage = (pool_balance.saturating_mul(U512::from(MAX_COVERAGE_BPS))) / U512::from(10_000u64);
    if requested_amount > max_coverage {
        return Err(ClaimRejection::MaxCoverageExceeded);
    }

    if requested_amount > pool_balance {
        return Err(ClaimRejection::ClaimAmountTooLarge);
    }

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn u(x: u64) -> U512 {
        U512::from(x)
    }

    #[test]
    fn first_claim_within_limits_is_accepted() {
        // never claimed, no prior record (timestamp 0), well past any cooldown,
        // amount within both the 80% coverage cap and the pool balance.
        assert_eq!(
            check_claim_preconditions(false, 0, 1_000_000, u(700), u(1_000)),
            Ok(())
        );
    }

    #[test]
    fn tombstoned_escrow_id_is_rejected_even_with_amount_and_cooldown_satisfied() {
        assert_eq!(
            check_claim_preconditions(true, 0, 1_000_000, u(1), u(1_000)),
            Err(ClaimRejection::AlreadyClaimed)
        );
    }

    /// The concrete negative-integration property the P0 task list calls
    /// out explicitly: "the same signature after cooldown must not produce
    /// a second payout". Simulate a claimant whose cooldown window from
    /// their *first* claim has fully elapsed, but who is replaying a claim
    /// for an escrow_id that was already tombstoned by that first claim.
    /// The tombstone must win regardless of how much time has passed.
    #[test]
    fn replay_after_cooldown_elapsed_still_rejected_by_tombstone() {
        let last_claim_timestamp = 1_000u64;
        let now_far_past_cooldown = last_claim_timestamp + COOLDOWN_SECONDS + 999_999;
        assert_eq!(
            check_claim_preconditions(
                true, // escrow_id was tombstoned by the original claim
                last_claim_timestamp,
                now_far_past_cooldown,
                u(1),
                u(1_000),
            ),
            Err(ClaimRejection::AlreadyClaimed)
        );
    }

    #[test]
    fn within_cooldown_window_is_rejected_regardless_of_amount() {
        let last_claim_timestamp = 1_000u64;
        assert_eq!(
            check_claim_preconditions(
                false,
                last_claim_timestamp,
                last_claim_timestamp + COOLDOWN_SECONDS - 1,
                u(1),
                u(1_000),
            ),
            Err(ClaimRejection::Cooldown)
        );
    }

    #[test]
    fn exactly_at_cooldown_boundary_is_accepted() {
        let last_claim_timestamp = 1_000u64;
        assert_eq!(
            check_claim_preconditions(
                false,
                last_claim_timestamp,
                last_claim_timestamp + COOLDOWN_SECONDS,
                u(1),
                u(1_000),
            ),
            Ok(())
        );
    }

    #[test]
    fn amount_above_80pct_coverage_cap_is_rejected() {
        // pool_balance = 1_000 -> max_coverage = 800; 801 must fail even
        // though it is still within the raw pool balance.
        assert_eq!(
            check_claim_preconditions(false, 0, 1_000_000, u(801), u(1_000)),
            Err(ClaimRejection::MaxCoverageExceeded)
        );
        assert_eq!(
            check_claim_preconditions(false, 0, 1_000_000, u(800), u(1_000)),
            Ok(())
        );
    }

    #[test]
    fn max_coverage_bps_invariant_makes_claim_amount_too_large_unreachable_today() {
        // MAX_COVERAGE_BPS (8000) is <= 10_000, so max_coverage = pool_balance
        // * bps / 10_000 can never exceed pool_balance -- any amount that
        // clears the balance also clears the coverage cap first, so
        // ClaimRejection::ClaimAmountTooLarge is dead code under today's
        // constants. The check in check_claim_preconditions is kept as
        // defense-in-depth for if MAX_COVERAGE_BPS is ever misconfigured
        // above 10_000; this test pins that invariant so a future bump of
        // the constant doesn't silently make the pool over-pay without
        // anyone noticing this branch became reachable (and needing its
        // own dedicated test at that point).
        assert!(MAX_COVERAGE_BPS <= 10_000);
        assert_eq!(
            check_claim_preconditions(false, 0, 1_000_000, u(1_001), u(1_000)),
            Err(ClaimRejection::MaxCoverageExceeded)
        );
    }

    #[test]
    fn zero_pool_balance_rejects_any_positive_claim() {
        assert_eq!(
            check_claim_preconditions(false, 0, 1_000_000, u(1), u(0)),
            Err(ClaimRejection::MaxCoverageExceeded)
        );
    }
}
