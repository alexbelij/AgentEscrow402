// Property-based tests (proptest) for the pure invariants of the new
// agent-identity-registry contract. Same rationale as property_tests.rs:
// the contract crate is `#![no_std]`/wasm32-only, so the pure logic is
// duplicated here in a plain std test crate.

use proptest::prelude::*;

const MS_PER_WEEK: u64 = 604_800_000;
const REPUTATION_DECAY_PER_WEEK: u64 = 1;
const DEREGISTER_COOLDOWN_MS: u64 = 604_800_000;

fn decay_reputation(reputation: u64, last_active: u64, now: u64) -> u64 {
    let weeks_inactive = now.saturating_sub(last_active) / MS_PER_WEEK;
    let decay = weeks_inactive.saturating_mul(REPUTATION_DECAY_PER_WEEK);
    reputation.saturating_sub(decay)
}

fn cooldown_elapsed(now: u64, deregistered_at: u64) -> bool {
    now >= deregistered_at.saturating_add(DEREGISTER_COOLDOWN_MS)
}

// Note: the U512->u64 stake-truncation guard (`require_fits_u64` in
// main.rs, added after external-AI review flagged silent truncation via
// `.as_u64()`) isn't covered here since it needs the real `U512` type from
// casper_types, which this std test crate deliberately doesn't depend on
// (same reasoning as property_tests.rs). It's exercised instead by the
// on-chain dry-run: registering with an in-range stake succeeds and the
// stored `stake_motes` matches exactly what was transferred.

#[test]
fn decay_reputation_zero_weeks_is_noop() {
    assert_eq!(decay_reputation(50, 1000, 1000), 50);
    assert_eq!(decay_reputation(50, 1000, 1000 + MS_PER_WEEK - 1), 50);
}

#[test]
fn decay_reputation_one_week_decays_by_one() {
    assert_eq!(decay_reputation(50, 0, MS_PER_WEEK), 49);
}

#[test]
fn decay_reputation_never_goes_below_zero() {
    assert_eq!(decay_reputation(5, 0, MS_PER_WEEK * 1000), 0);
}

#[test]
fn cooldown_boundary_is_inclusive() {
    assert!(!cooldown_elapsed(1000 + DEREGISTER_COOLDOWN_MS - 1, 1000));
    assert!(cooldown_elapsed(1000 + DEREGISTER_COOLDOWN_MS, 1000));
}

proptest! {
    /// Decay is always monotonically non-increasing in reputation as time
    /// moves forward -- an agent can never "gain" reputation just by more
    /// time passing.
    #[test]
    fn decay_reputation_monotonic_in_time(
        reputation in any::<u64>(),
        last_active in 0u64..1_000_000_000,
        elapsed_a in 0u64..10_000_000,
        elapsed_b in 0u64..10_000_000,
    ) {
        let (lo, hi) = if elapsed_a <= elapsed_b { (elapsed_a, elapsed_b) } else { (elapsed_b, elapsed_a) };
        let now_lo = last_active + lo;
        let now_hi = last_active + hi;
        let score_lo = decay_reputation(reputation, last_active, now_lo);
        let score_hi = decay_reputation(reputation, last_active, now_hi);
        prop_assert!(score_hi <= score_lo);
    }

    /// Decay never exceeds the starting reputation (saturates at 0, never
    /// wraps/underflows for any u64 input combination).
    #[test]
    fn decay_reputation_bounded_above_by_start(
        reputation in any::<u64>(),
        last_active in any::<u64>(),
        now in any::<u64>(),
    ) {
        let score = decay_reputation(reputation, last_active, now);
        prop_assert!(score <= reputation);
    }

    /// Cooldown check is a pure, saturating function of two u64s -- never
    /// panics regardless of how close deregistered_at is to u64::MAX.
    #[test]
    fn cooldown_elapsed_never_panics(
        now in any::<u64>(),
        deregistered_at in any::<u64>(),
    ) {
        let _ = cooldown_elapsed(now, deregistered_at);
    }
}
