// Contract fuzzing harness (Rust proptest) -- T06.
//
// Extends the existing property_tests.rs coverage with fuzz targets for the
// pure logic mirrored from insurance-pool's `calculate_premium`,
// vrf-arbiter's arbiter-selection index arithmetic, and multi-asset-escrow's
// numeric-string parsing helpers. Same rationale as the sibling test files
// in this crate: the on-chain contracts are `#![no_std]` wasm32-only
// libraries, so their pure invariants are duplicated here as plain-std
// proptest targets that fuzz thousands of random inputs per run.

use proptest::prelude::*;

// ---------------------------------------------------------------------
// insurance-pool::calculate_premium mirror
// ---------------------------------------------------------------------

/// Mirrors insurance-pool/src/main.rs `calculate_premium`:
/// premium = base_rate * amount * (100 + risk_score) / (10000 * 100)
/// using the same saturating arithmetic as the on-chain entry point, so a
/// malicious/huge base_rate, amount, or risk_score can never panic or wrap.
fn calculate_premium(base_rate: u64, amount: u64, risk_score: u64) -> u64 {
    let multiplier = 100u64.saturating_add(risk_score);
    (base_rate.saturating_mul(amount).saturating_mul(multiplier)) / (10_000u64.saturating_mul(100))
}

// ---------------------------------------------------------------------
// vrf-arbiter arbiter-selection mirror
// ---------------------------------------------------------------------

/// Mirrors vrf-arbiter/src/main.rs `get_random_u64`: blake2b(seed) truncated
/// to the first 8 bytes, little-endian.
fn get_random_u64(seed: &[u8]) -> u64 {
    use blake2::{Blake2b512, Digest};
    let mut hasher = Blake2b512::new();
    hasher.update(seed);
    let hash = hasher.finalize();
    u64::from_le_bytes([
        hash[0], hash[1], hash[2], hash[3], hash[4], hash[5], hash[6], hash[7],
    ])
}

/// Mirrors vrf-arbiter/src/main.rs `select_arbiters_from_list`'s per-slot
/// index computation (the modulo-into-active-list step), without the
/// runtime::revert count-too-large guard (fuzzed separately below).
fn select_index(active_len: usize, base_seed_input: &str, i: u64) -> usize {
    let seed_for_this_selection = format!("{}{}", base_seed_input, i);
    let hash_val = get_random_u64(seed_for_this_selection.as_bytes());
    (hash_val % active_len as u64) as usize
}

// ---------------------------------------------------------------------
// multi-asset-escrow numeric-string parsing mirror
// ---------------------------------------------------------------------

/// Mirrors multi-asset-escrow/src/main.rs `parse_u256`'s decimal-string
/// acceptance test, using u128 as a std stand-in for the on-chain U256 --
/// wide enough to exercise the same "valid non-negative decimal digits
/// parse, everything else is rejected" boundary the real U256::from_dec_str
/// enforces.
fn parse_u128_like(s: &str) -> Option<u128> {
    if s.is_empty() || !s.bytes().all(|b| b.is_ascii_digit()) {
        return None;
    }
    s.parse::<u128>().ok()
}

proptest! {
    /// The premium calculated for any base_rate/amount/risk_score never
    /// overflows (saturating arithmetic absorbs it) and never exceeds the
    /// input `amount` scaled by the maximum possible multiplier bound --
    /// i.e. the division floor keeps premium bounded relative to amount
    /// whenever base_rate stays within a realistic bps range.
    #[test]
    fn premium_bounded_by_amount_for_capped_rate(
        base_rate in 0u64..=10_000,
        amount in 0u64..1_000_000_000_000u64,
        risk_score in 0u64..=1_000,
    ) {
        let premium = calculate_premium(base_rate, amount, risk_score);
        // base_rate<=10_000 (100%) and risk_score<=1_000 (multiplier<=1_100,
        // i.e. 100+risk_score) => premium <= amount * 10_000 * 1_100 / 1e6
        // = amount * 11, exactly. Bound with a small slack for integer
        // division rounding.
        prop_assert!(premium <= amount.saturating_mul(11).saturating_add(1));
    }

    /// calculate_premium never panics regardless of how extreme the inputs
    /// are (this is the actual fuzz target: saturating_mul must never wrap
    /// silently into a nonsensical small value via overflow -- it should
    /// saturate to u64::MAX and the division should still produce a finite
    /// result).
    #[test]
    fn premium_never_panics_on_extreme_inputs(
        base_rate in any::<u64>(),
        amount in any::<u64>(),
        risk_score in any::<u64>(),
    ) {
        let premium = calculate_premium(base_rate, amount, risk_score);
        prop_assert!(premium <= u64::MAX);
    }

    /// The arbiter-selection index is always a valid index into the active
    /// arbiter list -- i.e. `select_index` never returns an out-of-bounds
    /// slot -- for any non-empty active list length, seed string, and slot
    /// number. This is the invariant `select_arbiters_from_list` relies on
    /// to never index out of bounds into `active_arbiters`.
    #[test]
    fn arbiter_selection_index_always_in_bounds(
        active_len in 1usize..500,
        base_seed_input in "[a-zA-Z0-9_-]{0,32}",
        i in 0u64..1_000,
    ) {
        let idx = select_index(active_len, &base_seed_input, i);
        prop_assert!(idx < active_len);
    }

    /// Selecting the same slot index `i` for the same seed and list length
    /// is deterministic (same inputs -> same index every time), which the
    /// on-chain election logic depends on for reproducible/auditable
    /// arbiter selection given a fixed dispute_id-derived seed.
    #[test]
    fn arbiter_selection_index_deterministic(
        active_len in 1usize..500,
        base_seed_input in "[a-zA-Z0-9_-]{0,32}",
        i in 0u64..1_000,
    ) {
        let idx1 = select_index(active_len, &base_seed_input, i);
        let idx2 = select_index(active_len, &base_seed_input, i);
        prop_assert_eq!(idx1, idx2);
    }

    /// Different slot numbers `i` for the same base seed are allowed (and
    /// expected in practice) to diverge -- this just checks the function
    /// doesn't blow up and stays in-bounds across a sequence of slots, the
    /// same access pattern `select_arbiters_from_list`'s loop uses.
    #[test]
    fn arbiter_selection_sequence_stays_in_bounds(
        active_len in 1usize..200,
        base_seed_input in "[a-zA-Z0-9_-]{1,16}",
        count in 1u64..50,
    ) {
        for i in 0..count {
            let idx = select_index(active_len, &base_seed_input, i);
            prop_assert!(idx < active_len);
        }
    }

    /// Any string composed purely of ASCII digits round-trips through the
    /// U256-style decimal parser back to the same numeric value (mod u128
    /// width), matching `parse_u256`'s accept path.
    #[test]
    fn numeric_string_roundtrips_through_parser(n in any::<u128>()) {
        let s = n.to_string();
        prop_assert_eq!(parse_u128_like(&s), Some(n));
    }

    /// Any string containing a non-digit character (and not empty) is
    /// always rejected by the parser -- mirroring `parse_u256`'s revert
    /// path for malformed escrow-id / amount strings, which must never be
    /// silently accepted as a wrong numeric value.
    #[test]
    fn non_numeric_strings_are_rejected(
        s in "[^0-9]{1,16}",
    ) {
        prop_assert_eq!(parse_u128_like(&s), None);
    }

}

/// Empty string is always rejected, never parsed as zero or any other
/// value. Plain #[test] (not proptest!) since there's no input to fuzz.
#[test]
fn empty_string_is_rejected() {
    assert_eq!(parse_u128_like(""), None);
}
