// Integration-level tests for the AgentEscrow402 smart contract.
//
// These tests validate entry-point logic, error codes, and state
// transitions without requiring a full Casper execution engine.

#[cfg(test)]
mod tests {
    // ── Error code constants (mirror the contract) ──────────────
    const ERR_ESCROW_NOT_FOUND: u16 = 1;
    const ERR_UNAUTHORIZED: u16 = 2;
    const ERR_ALREADY_DISPUTED: u16 = 4;
    const ERR_INVALID_SIGNATURE: u16 = 5;
    const ERR_FEE_TOO_HIGH: u16 = 7;
    const ERR_INVALID_STATUS: u16 = 8;
    const ERR_TTL_OUT_OF_RANGE: u16 = 10;
    const ERR_DUPLICATE_HASH: u16 = 11;
    const ERR_INSUFFICIENT_SIGS: u16 = 12;
    const ERR_ZERO_AMOUNT: u16 = 13;
    const ERR_POOL_FROZEN: u16 = 14;
    const ERR_ALREADY_COMMITTED: u16 = 15;
    const ERR_NO_COMMIT: u16 = 16;
    const ERR_INVALID_PREIMAGE: u16 = 17;
    const ERR_ALREADY_REVEALED: u16 = 18;
    const ERR_CAP_EXCEEDED: u16 = 19;
    const ERR_FEE_EXCEEDS_AMOUNT: u16 = 20;

    const STATUS_PENDING: u8 = 0;
    const STATUS_RELEASED: u8 = 1;
    const STATUS_REFUNDED: u8 = 2;
    const STATUS_EXPIRED: u8 = 3;
    const STATUS_DISPUTED: u8 = 4;
    const STATUS_RESOLVED: u8 = 5;

    const MIN_TTL: u64 = 60;
    const MAX_TTL: u64 = 86_400;
    const MAX_FEE_BPS: u64 = 1_000;
    const DEFAULT_FEE_BPS: u64 = 200;

    // ── Reputation score logic tests ────────────────────────────
    fn reputation_score(completed: u64, disputed: u64, weeks_inactive: u64) -> u64 {
        if completed == 0 {
            return 50;
        }
        let base = 100u64.saturating_sub(disputed.saturating_mul(10).min(50));
        let decay_pct = 5u64.saturating_mul(weeks_inactive).min(50);
        let score = base.saturating_sub(base.saturating_mul(decay_pct) / 100);
        score.min(100)
    }

    #[test]
    fn reputation_new_agent_starts_at_50() {
        assert_eq!(reputation_score(0, 0, 0), 50);
    }

    #[test]
    fn reputation_active_agent() {
        let s = reputation_score(10, 0, 0);
        assert_eq!(s, 100);
    }

    #[test]
    fn reputation_with_disputes() {
        let s = reputation_score(10, 3, 0);
        assert_eq!(s, 70);
    }

    #[test]
    fn reputation_max_disputes_capped() {
        let s = reputation_score(10, 10, 0);
        // disputed*10 capped at 50, so base=50
        assert_eq!(s, 50);
    }

    #[test]
    fn reputation_decay_applied() {
        // 5% per week, 4 weeks = 20% decay
        let s = reputation_score(10, 0, 4);
        assert_eq!(s, 80);
    }

    #[test]
    fn reputation_max_decay_capped() {
        // 5% * 20 weeks = 100% but capped at 50%
        let s = reputation_score(10, 0, 20);
        assert_eq!(s, 50);
    }

    #[test]
    fn reputation_combined_dispute_and_decay() {
        let s = reputation_score(10, 2, 2);
        // base = 100 - 20 = 80
        // decay = 10%
        // score = 80 - 8 = 72
        assert_eq!(s, 72);
    }

    // ── Status transition validation ────────────────────────────

    fn can_release(status: u8) -> bool {
        status == STATUS_PENDING
    }

    fn can_refund(status: u8) -> bool {
        status == STATUS_PENDING
    }

    fn can_dispute(status: u8) -> bool {
        status == STATUS_PENDING
    }

    #[test]
    fn release_only_from_pending() {
        assert!(can_release(STATUS_PENDING));
        assert!(!can_release(STATUS_RELEASED));
        assert!(!can_release(STATUS_REFUNDED));
        assert!(!can_release(STATUS_DISPUTED));
        assert!(!can_release(STATUS_RESOLVED));
    }

    #[test]
    fn refund_only_from_pending() {
        assert!(can_refund(STATUS_PENDING));
        assert!(!can_refund(STATUS_RELEASED));
        assert!(!can_refund(STATUS_DISPUTED));
    }

    #[test]
    fn dispute_only_from_pending() {
        assert!(can_dispute(STATUS_PENDING));
        assert!(!can_dispute(STATUS_RELEASED));
        assert!(!can_dispute(STATUS_REFUNDED));
    }

    // ── TTL range validation ────────────────────────────────────

    fn validate_ttl(ttl: u64) -> bool {
        ttl >= MIN_TTL && ttl <= MAX_TTL
    }

    #[test]
    fn ttl_within_range() {
        assert!(validate_ttl(300));
        assert!(validate_ttl(60));
        assert!(validate_ttl(86_400));
    }

    #[test]
    fn ttl_below_min_rejected() {
        assert!(!validate_ttl(59));
        assert!(!validate_ttl(0));
    }

    #[test]
    fn ttl_above_max_rejected() {
        assert!(!validate_ttl(86_401));
    }

    // ── Fee validation ──────────────────────────────────────────

    fn validate_fee_bps(fee: u64) -> bool {
        fee <= MAX_FEE_BPS
    }

    fn compute_fee(amount: u64, fee_bps: u64) -> u64 {
        amount * fee_bps / 10_000
    }

    fn compute_insurance(fee: u64) -> u64 {
        fee / 2
    }

    #[test]
    fn fee_within_range() {
        assert!(validate_fee_bps(200));
        assert!(validate_fee_bps(0));
        assert!(validate_fee_bps(1000));
    }

    #[test]
    fn fee_over_max_rejected() {
        assert!(!validate_fee_bps(1001));
        assert!(!validate_fee_bps(10_000));
    }

    #[test]
    fn fee_computation_correct() {
        assert_eq!(compute_fee(10_000, 200), 200);
        assert_eq!(compute_fee(100, 200), 2);
        assert_eq!(compute_fee(0, 200), 0);
    }

    #[test]
    fn insurance_split_correct() {
        assert_eq!(compute_insurance(200), 100);
        assert_eq!(compute_insurance(1), 0);
    }

    // ── Fee deduction underflow guard (hardening pass) ────────────

    /// Mirrors `checked_deduct_fee` in contracts/escrow/src/main.rs: must
    /// revert (return None here) instead of silently wrapping when the fee
    /// would exceed the amount, rather than the raw `amount - fee`
    /// subtraction this replaced.
    fn checked_deduct_fee(amount: u64, fee: u64) -> Option<u64> {
        amount.checked_sub(fee)
    }

    #[test]
    fn fee_deduction_normal_case_succeeds() {
        // Real-world case: bps <= MAX_FEE_BPS always keeps fee <= amount.
        let fee = compute_fee(10_000, MAX_FEE_BPS);
        assert_eq!(checked_deduct_fee(10_000, fee), Some(9_000));
    }

    #[test]
    fn fee_deduction_underflow_is_rejected_not_wrapped() {
        // Defense-in-depth: if `fee` ever exceeded `amount` (should be
        // unreachable given MAX_FEE_BPS, but a future bug/upgrade
        // shouldn't silently wrap to a huge value), the guard must reject
        // it instead of computing a corrupted balance.
        assert_eq!(checked_deduct_fee(100, 150), None);
    }

    // ── Error code distinctness ─────────────────────────────────

    #[test]
    fn error_codes_unique() {
        let codes = [
            ERR_ESCROW_NOT_FOUND,
            ERR_UNAUTHORIZED,
            ERR_ALREADY_DISPUTED,
            ERR_INVALID_SIGNATURE,
            ERR_FEE_TOO_HIGH,
            ERR_INVALID_STATUS,
            ERR_TTL_OUT_OF_RANGE,
            ERR_DUPLICATE_HASH,
            ERR_INSUFFICIENT_SIGS,
            ERR_ZERO_AMOUNT,
            ERR_POOL_FROZEN,
            ERR_ALREADY_COMMITTED,
            ERR_NO_COMMIT,
            ERR_INVALID_PREIMAGE,
            ERR_ALREADY_REVEALED,
            ERR_CAP_EXCEEDED,
            ERR_FEE_EXCEEDS_AMOUNT,
        ];
        let mut sorted = codes.to_vec();
        sorted.sort();
        sorted.dedup();
        assert_eq!(sorted.len(), codes.len(), "duplicate error codes detected");
    }

    // ── A1 release cap / arbiter cap-approval tests ──────────────
    // Mirrors the contract's cap-check + quorum-counting logic (see
    // read_release_cap / verify_arbiter_quorum in main.rs) at the pure
    // math/logic level, matching the existing test style in this file
    // (no full CasperVM execution engine here).
    const DEFAULT_RELEASE_CAP_MOTES: u64 = 1_000_000_000_000;

    fn requires_cap_approval(amount_motes: u64, cap_motes: u64) -> bool {
        amount_motes > cap_motes
    }

    #[test]
    fn amount_at_or_below_cap_needs_no_approval() {
        assert!(!requires_cap_approval(DEFAULT_RELEASE_CAP_MOTES, DEFAULT_RELEASE_CAP_MOTES));
        assert!(!requires_cap_approval(1, DEFAULT_RELEASE_CAP_MOTES));
    }

    #[test]
    fn amount_above_cap_needs_approval() {
        assert!(requires_cap_approval(DEFAULT_RELEASE_CAP_MOTES + 1, DEFAULT_RELEASE_CAP_MOTES));
    }

    // Dedup + threshold counting logic, mirroring verify_arbiter_quorum
    // (a registered arbiter can't have their vote counted twice, and an
    // unregistered "arbiter" contributes nothing even with a valid sig).
    fn count_quorum(registered: &[&str], claimed_pubkeys: &[&str]) -> u64 {
        let mut seen: Vec<&str> = Vec::new();
        let mut count = 0u64;
        for pk in claimed_pubkeys {
            if seen.contains(pk) || !registered.contains(pk) {
                continue;
            }
            seen.push(pk);
            count += 1;
        }
        count
    }

    #[test]
    fn quorum_counts_distinct_registered_votes() {
        let registered = ["a1", "a2", "a3", "a4", "a5"];
        assert_eq!(count_quorum(&registered, &["a1", "a2", "a3"]), 3);
    }

    #[test]
    fn quorum_ignores_duplicate_votes_from_same_arbiter() {
        let registered = ["a1", "a2", "a3", "a4", "a5"];
        assert_eq!(count_quorum(&registered, &["a1", "a1", "a1"]), 1);
    }

    #[test]
    fn quorum_ignores_unregistered_pubkeys() {
        let registered = ["a1", "a2", "a3", "a4", "a5"];
        assert_eq!(count_quorum(&registered, &["a1", "not-an-arbiter", "a2"]), 2);
    }

    #[test]
    fn quorum_below_threshold_is_insufficient() {
        let registered = ["a1", "a2", "a3", "a4", "a5"];
        let threshold = 3u64;
        assert!(count_quorum(&registered, &["a1", "a2"]) < threshold);
    }

    #[test]
    fn quorum_at_threshold_is_sufficient() {
        let registered = ["a1", "a2", "a3", "a4", "a5"];
        let threshold = 3u64;
        assert!(count_quorum(&registered, &["a1", "a2", "a3"]) >= threshold);
    }

    // ── Atomic-swap hash-lock (HTLC) tests ───────────────────────
    // Mirrors the contract's sha256_hex commit/reveal check: a receiver
    // can only trigger release by presenting the exact preimage that
    // hashes to the sender's committed hash.
    fn sha256_hex(preimage: &[u8]) -> String {
        use sha2::{Digest, Sha256};
        let digest = Sha256::digest(preimage);
        digest.iter().map(|b| format!("{:02x}", b)).collect()
    }

    #[test]
    fn htlc_correct_preimage_matches_commit() {
        let preimage = b"super-secret-swap-condition";
        let commit_hash = sha256_hex(preimage);
        // Receiver reveals the same preimage -> must match.
        assert_eq!(sha256_hex(preimage), commit_hash);
    }

    #[test]
    fn htlc_wrong_preimage_rejected() {
        let preimage = b"super-secret-swap-condition";
        let commit_hash = sha256_hex(preimage);
        let wrong_guess = b"wrong-guess";
        assert_ne!(sha256_hex(wrong_guess), commit_hash, "wrong preimage must not match commit hash");
    }

    #[test]
    fn htlc_hash_is_deterministic_and_hex_lowercase() {
        let preimage = b"deterministic-check";
        let h1 = sha256_hex(preimage);
        let h2 = sha256_hex(preimage);
        assert_eq!(h1, h2);
        assert_eq!(h1.len(), 64, "sha256 hex digest must be 64 chars");
        assert!(h1.chars().all(|c| c.is_ascii_hexdigit() && !c.is_ascii_uppercase()));
    }

    #[test]
    fn htlc_empty_preimage_still_hashes_deterministically() {
        // Contract does not special-case empty string; document current
        // behavior explicitly rather than leaving it untested.
        let h1 = sha256_hex(b"");
        let h2 = sha256_hex(b"");
        assert_eq!(h1, h2);
    }
}
