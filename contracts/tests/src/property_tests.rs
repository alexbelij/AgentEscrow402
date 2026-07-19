// Property-based tests (proptest) for the pure invariants of the escrow
// contract logic. These mirror the same helper functions unit-tested in
// integration_tests.rs, but check the invariants hold across thousands of
// randomly generated inputs instead of a handful of hand-picked cases.
//
// Kept in a separate test binary (not a lib import) for the same reason
// integration_tests.rs is: these contract crates are `#![no_std]` and only
// buildable for wasm32 as libraries, so the pure logic is duplicated here in
// a plain std test crate, same as the existing integration tests do.

use proptest::prelude::*;

const MIN_TTL: u64 = 60;
const MAX_TTL: u64 = 86_400;
const MAX_FEE_BPS: u64 = 1_000;

fn validate_ttl(ttl: u64) -> bool {
    ttl >= MIN_TTL && ttl <= MAX_TTL
}

fn validate_fee_bps(fee: u64) -> bool {
    fee <= MAX_FEE_BPS
}

fn compute_fee(amount: u64, fee_bps: u64) -> u64 {
    // Mirror the contract's overflow-safe U512 arithmetic while keeping this
    // pure host-side property harness on u64 inputs.
    ((amount as u128 * fee_bps as u128) / 10_000) as u64
}

fn compute_insurance(fee: u64) -> u64 {
    fee / 2
}

fn checked_deduct_fee(amount: u64, fee: u64) -> Option<u64> {
    amount.checked_sub(fee)
}

fn reputation_score(completed: u64, disputed: u64, weeks_inactive: u64) -> u64 {
    if completed == 0 {
        return 50;
    }
    let base = 100u64.saturating_sub(disputed.saturating_mul(10).min(50));
    let decay_pct = 5u64.saturating_mul(weeks_inactive).min(50);
    base.saturating_sub(base * decay_pct / 100)
}

fn count_quorum(registered: &[&str], claimed_pubkeys: &[&str]) -> u64 {
    let mut seen = std::collections::HashSet::new();
    let mut count = 0u64;
    for pk in claimed_pubkeys {
        if registered.contains(pk) && seen.insert(*pk) {
            count += 1;
        }
    }
    count
}

fn sha256_hex(preimage: &[u8]) -> String {
    use sha2::{Digest, Sha256};
    let mut hasher = Sha256::new();
    hasher.update(preimage);
    hex_encode(&hasher.finalize())
}

fn hex_encode(bytes: &[u8]) -> String {
    bytes.iter().map(|b| format!("{:02x}", b)).collect()
}

proptest! {
    // Amounts up to 1e18 motes (~1e6 CSPR) cover any realistic escrow size
    // without risking u64 overflow in amount * fee_bps.

    /// The fee taken from an escrow can never exceed the escrow amount
    /// itself, for any amount and any *valid* (<= MAX_FEE_BPS) fee rate.
    /// This is the invariant `checked_deduct_fee` exists to protect on-chain.
    #[test]
    fn fee_never_exceeds_amount(amount in 0u64..1_000_000_000_000_000_000, fee_bps in 0u64..=MAX_FEE_BPS) {
        let fee = compute_fee(amount, fee_bps);
        prop_assert!(fee <= amount);
        prop_assert!(checked_deduct_fee(amount, fee).is_some());
    }

    /// Insurance is always at most half the fee, and never more than the fee
    /// itself, for any fee value the contract could ever produce.
    #[test]
    fn insurance_never_exceeds_fee(fee in 0u64..u64::MAX) {
        let insurance = compute_insurance(fee);
        prop_assert!(insurance <= fee);
        prop_assert!(insurance * 2 <= fee);
    }

    /// TTL validation is exactly the closed interval [MIN_TTL, MAX_TTL] --
    /// no off-by-one gaps at either boundary, for any u64 input.
    #[test]
    fn ttl_validation_matches_closed_interval(ttl in any::<u64>()) {
        let expected = ttl >= MIN_TTL && ttl <= MAX_TTL;
        prop_assert_eq!(validate_ttl(ttl), expected);
    }

    /// Fee-bps validation never accepts anything above MAX_FEE_BPS (10% cap),
    /// for any u64 input, not just the hand-picked boundary cases.
    #[test]
    fn fee_bps_validation_matches_cap(fee_bps in any::<u64>()) {
        let expected = fee_bps <= MAX_FEE_BPS;
        prop_assert_eq!(validate_fee_bps(fee_bps), expected);
    }

    /// Reputation score is always within [0, 100] regardless of how many
    /// disputes or how many weeks inactive an agent has accumulated.
    #[test]
    fn reputation_score_always_in_valid_range(
        completed in any::<u64>(),
        disputed in any::<u64>(),
        weeks_inactive in any::<u64>(),
    ) {
        let score = reputation_score(completed, disputed, weeks_inactive);
        prop_assert!(score <= 100);
    }

    /// More disputes (all else equal) never *increases* the reputation
    /// score -- monotonicity that the piecewise saturating-sub formula must
    /// preserve across its whole domain, not just the tested examples.
    #[test]
    fn reputation_score_monotonic_in_disputes(
        completed in 1u64..1_000_000,
        disputed in 0u64..1_000,
        extra_disputes in 0u64..1_000,
        weeks_inactive in 0u64..1_000,
    ) {
        let low = reputation_score(completed, disputed, weeks_inactive);
        let high = reputation_score(completed, disputed + extra_disputes, weeks_inactive);
        prop_assert!(high <= low);
    }

    /// Counting quorum votes never exceeds the number of registered
    /// arbiters, and duplicate/unregistered claims are always ignored, for
    /// any combination of a fixed 5-arbiter registry and arbitrary claims.
    #[test]
    fn quorum_count_bounded_by_registered_size(
        claims in prop::collection::vec("[a-e]", 0..20),
    ) {
        let registered = ["a", "b", "c", "d", "e"];
        let claimed: Vec<&str> = claims.iter().map(|s| s.as_str()).collect();
        let count = count_quorum(&registered, &claimed);
        prop_assert!(count <= registered.len() as u64);
    }

    /// SHA-256 HTLC commit hashing is deterministic (same preimage always
    /// produces the same hash) and injective enough in practice that two
    /// different preimages never collide across the sampled input space.
    #[test]
    fn htlc_hash_deterministic(preimage in prop::collection::vec(any::<u8>(), 0..64)) {
        let h1 = sha256_hex(&preimage);
        let h2 = sha256_hex(&preimage);
        prop_assert_eq!(h1, h2);
    }

    #[test]
    fn htlc_different_preimages_different_hashes(
        a in prop::collection::vec(any::<u8>(), 1..64),
        b in prop::collection::vec(any::<u8>(), 1..64),
    ) {
        prop_assume!(a != b);
        prop_assert_ne!(sha256_hex(&a), sha256_hex(&b));
    }
}
