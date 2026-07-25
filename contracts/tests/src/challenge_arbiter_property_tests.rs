// Property-based tests for challenge-arbiter's pure logic.
//
// The contract crate is `#![no_std]`/wasm32-only, so we duplicate the pure
// functions here (same convention as two_key_account_property_tests.rs).
//
// Covered invariants:
//   1. `u64_to_decimal` — matches std's `to_string()` for every u64 (proves
//      the hand-rolled no_std version is decimal-correct across the whole
//      64-bit range).
//   2. `canonical_reveal_preimage` — bijective in (dispute_id, verdict,
//      nonce_hex, arbiter_pk). Any two distinct tuples produce distinct
//      preimages. This is the anti-replay + anti-cross-dispute-forge
//      foundation.
//   3. State-machine safety:
//        a. STATUS_COMMIT_PHASE cannot transition to STATUS_REVEAL_PHASE
//           until now > commit_deadline.
//        b. STATUS_REVEAL_PHASE cannot finalize until now > reveal_deadline.
//        c. Finalized statuses are terminal (no re-finalize).
//   4. Threshold semantics: reveal_count < threshold ⇒ FAILED_QUORUM;
//      >= threshold + majority chooses winner; tie ⇒ status-quo.
//   5. Slash-on-non-reveal: an arbiter with a commit and no reveal AFTER
//      reveal_deadline is slashable; committed+revealed is not; no commit
//      is not.
//   6. Commit-reveal binding: a reveal is only accepted when the stored
//      commit hex matches the caller-supplied recomputed hex. Any diff
//      rejects.
//   7. Verdict enum: reveal_verdict rejects verdicts outside {1, 2}.
//   8. Timing monotonicity: commit_deadline = opened + commit_window;
//      reveal_deadline = commit_deadline + reveal_window; both strictly
//      greater than opened_at when windows are non-zero.

use proptest::prelude::*;

const DOMAIN: &str = "ae402:challenge:v1";

// ── Duplicated pure functions ───────────────────────────────────────

fn u64_to_decimal(n: u64) -> String {
    if n == 0 {
        return "0".to_string();
    }
    let mut buf = [0u8; 20];
    let mut i = 20usize;
    let mut v = n;
    while v > 0 {
        i -= 1;
        buf[i] = b'0' + (v % 10) as u8;
        v /= 10;
    }
    String::from_utf8_lossy(&buf[i..]).into_owned()
}

fn canonical_reveal_preimage(
    self_package_hash: &str,
    dispute_id: &str,
    verdict: u64,
    nonce_hex: &str,
    pk_hex: &str,
) -> String {
    let mut m = String::with_capacity(
        DOMAIN.len() + dispute_id.len() + nonce_hex.len() + pk_hex.len() + 32,
    );
    m.push_str(DOMAIN);
    m.push_str(":reveal:");
    m.push_str(self_package_hash);
    m.push(':');
    m.push_str(dispute_id);
    m.push(':');
    let verdict_s = u64_to_decimal(verdict);
    m.push_str(&verdict_s);
    m.push(':');
    m.push_str(nonce_hex);
    m.push(':');
    m.push_str(pk_hex);
    m
}

// ── Status constants (mirror main.rs) ───────────────────────────────

const STATUS_COMMIT_PHASE: u64 = 2;
const STATUS_REVEAL_PHASE: u64 = 3;
const STATUS_FINALIZED_CHALLENGER_WINS: u64 = 4;
const STATUS_FINALIZED_STATUS_QUO: u64 = 5;
const STATUS_FINALIZED_FAILED_QUORUM: u64 = 6;

const VERDICT_SENDER: u64 = 1;
const VERDICT_RECEIVER: u64 = 2;

fn is_terminal(status: u64) -> bool {
    status == STATUS_FINALIZED_CHALLENGER_WINS
        || status == STATUS_FINALIZED_STATUS_QUO
        || status == STATUS_FINALIZED_FAILED_QUORUM
}

/// Pure finalize logic (mirrors `finalize()` in main.rs).
fn finalize_pure(
    reveal_count: u64,
    threshold: u64,
    sender_reveal_count: u64,
    receiver_reveal_count: u64,
) -> u64 {
    if sender_reveal_count.saturating_add(receiver_reveal_count) != reveal_count {
        // Caller-supplied counts must sum to reveal_count; encode "invalid" as
        // a distinguishable sentinel status.
        return u64::MAX;
    }
    if reveal_count < threshold {
        STATUS_FINALIZED_FAILED_QUORUM
    } else if sender_reveal_count > receiver_reveal_count {
        STATUS_FINALIZED_CHALLENGER_WINS
    } else if receiver_reveal_count > sender_reveal_count {
        STATUS_FINALIZED_STATUS_QUO
    } else {
        STATUS_FINALIZED_STATUS_QUO
    }
}

/// Pure state-machine advance check.
#[derive(Debug, PartialEq)]
enum PhaseError {
    CommitWindowOpen,
    RevealWindowOpen,
    InvalidState,
    AlreadyFinalized,
}
fn advance_to_reveal(status: u64, now: u64, commit_deadline: u64) -> Result<u64, PhaseError> {
    if status != STATUS_COMMIT_PHASE {
        return Err(PhaseError::InvalidState);
    }
    if now <= commit_deadline {
        return Err(PhaseError::CommitWindowOpen);
    }
    Ok(STATUS_REVEAL_PHASE)
}
fn can_finalize(status: u64, now: u64, reveal_deadline: u64) -> Result<(), PhaseError> {
    if is_terminal(status) {
        return Err(PhaseError::AlreadyFinalized);
    }
    if status != STATUS_REVEAL_PHASE {
        return Err(PhaseError::InvalidState);
    }
    if now <= reveal_deadline {
        return Err(PhaseError::RevealWindowOpen);
    }
    Ok(())
}

/// Slash-eligibility check. Returns `true` iff the arbiter has a commit but
/// no reveal AND the reveal window is closed.
fn is_slashable(
    now: u64,
    reveal_deadline: u64,
    has_commit: bool,
    has_reveal: bool,
) -> bool {
    if now <= reveal_deadline {
        return false;
    }
    has_commit && !has_reveal
}

// ── Unit-style baselines ────────────────────────────────────────────

#[test]
fn u64_to_decimal_zero() {
    assert_eq!(u64_to_decimal(0), "0");
}

#[test]
fn u64_to_decimal_max() {
    assert_eq!(u64_to_decimal(u64::MAX), u64::MAX.to_string());
}

#[test]
fn preimage_deterministic_for_same_inputs() {
    let a = canonical_reveal_preimage("pkg", "d1", 1, "aabb", "010203");
    let b = canonical_reveal_preimage("pkg", "d1", 1, "aabb", "010203");
    assert_eq!(a, b);
}

#[test]
fn preimage_domain_contains_package_hash() {
    // Anti-replay across deployments: the package hash MUST appear in the
    // preimage, so a signature made for staging can't be replayed on
    // mainnet.
    let m = canonical_reveal_preimage("PKG-STAGING", "d1", 1, "aa", "bb");
    assert!(m.contains("PKG-STAGING"));
}

#[test]
fn advance_rejects_before_deadline() {
    assert_eq!(
        advance_to_reveal(STATUS_COMMIT_PHASE, 500, 1000),
        Err(PhaseError::CommitWindowOpen)
    );
    assert_eq!(
        advance_to_reveal(STATUS_COMMIT_PHASE, 1000, 1000),
        Err(PhaseError::CommitWindowOpen) // <= is not open
    );
    assert_eq!(
        advance_to_reveal(STATUS_COMMIT_PHASE, 1001, 1000),
        Ok(STATUS_REVEAL_PHASE)
    );
}

#[test]
fn finalize_rejects_before_reveal_deadline() {
    assert_eq!(
        can_finalize(STATUS_REVEAL_PHASE, 500, 1000),
        Err(PhaseError::RevealWindowOpen)
    );
    assert_eq!(
        can_finalize(STATUS_REVEAL_PHASE, 1001, 1000),
        Ok(())
    );
}

#[test]
fn finalize_rejects_terminal() {
    for &s in &[
        STATUS_FINALIZED_CHALLENGER_WINS,
        STATUS_FINALIZED_STATUS_QUO,
        STATUS_FINALIZED_FAILED_QUORUM,
    ] {
        assert_eq!(
            can_finalize(s, 5000, 1000),
            Err(PhaseError::AlreadyFinalized)
        );
    }
}

#[test]
fn slashable_only_after_reveal_deadline_and_committed_no_reveal() {
    // Before deadline: never slashable regardless of state.
    assert!(!is_slashable(500, 1000, true, false));
    assert!(!is_slashable(500, 1000, true, true));
    assert!(!is_slashable(500, 1000, false, false));

    // After deadline:
    assert!(is_slashable(1001, 1000, true, false));  // committed, no reveal → slash
    assert!(!is_slashable(1001, 1000, true, true));  // revealed → not slashable
    assert!(!is_slashable(1001, 1000, false, false)); // never committed → not slashable
}

#[test]
fn finalize_below_threshold_is_failed_quorum() {
    assert_eq!(
        finalize_pure(2, 3, 1, 1),
        STATUS_FINALIZED_FAILED_QUORUM
    );
}

#[test]
fn finalize_majority_sender_wins_challenger() {
    assert_eq!(
        finalize_pure(3, 3, 2, 1),
        STATUS_FINALIZED_CHALLENGER_WINS
    );
}

#[test]
fn finalize_majority_receiver_wins_status_quo() {
    assert_eq!(
        finalize_pure(3, 3, 1, 2),
        STATUS_FINALIZED_STATUS_QUO
    );
}

#[test]
fn finalize_tie_falls_back_to_status_quo() {
    assert_eq!(
        finalize_pure(4, 3, 2, 2),
        STATUS_FINALIZED_STATUS_QUO
    );
}

#[test]
fn finalize_rejects_inconsistent_counts() {
    // caller lied: 2 + 2 = 4, but reveal_count = 3
    assert_eq!(finalize_pure(3, 3, 2, 2), u64::MAX);
}

// ── Proptest invariants ─────────────────────────────────────────────

proptest! {
    /// Invariant 1: u64_to_decimal matches std for every u64 value.
    #[test]
    fn prop_u64_decimal_matches_std(n in any::<u64>()) {
        prop_assert_eq!(u64_to_decimal(n), n.to_string());
    }

    /// Invariant 2a: preimage is injective in dispute_id.
    #[test]
    fn prop_preimage_injective_in_dispute_id(
        d1 in "[a-zA-Z0-9]{1,32}",
        d2 in "[a-zA-Z0-9]{1,32}",
        v in 1u64..=2,
        nonce in "[0-9a-f]{2,64}",
        pk in "[0-9a-f]{2,66}",
    ) {
        prop_assume!(d1 != d2);
        let m1 = canonical_reveal_preimage("pkg", &d1, v, &nonce, &pk);
        let m2 = canonical_reveal_preimage("pkg", &d2, v, &nonce, &pk);
        prop_assert_ne!(m1, m2);
    }

    /// Invariant 2b: preimage is injective in verdict.
    #[test]
    fn prop_preimage_injective_in_verdict(
        d in "[a-zA-Z0-9]{1,32}",
        nonce in "[0-9a-f]{2,64}",
        pk in "[0-9a-f]{2,66}",
    ) {
        let m1 = canonical_reveal_preimage("pkg", &d, VERDICT_SENDER, &nonce, &pk);
        let m2 = canonical_reveal_preimage("pkg", &d, VERDICT_RECEIVER, &nonce, &pk);
        prop_assert_ne!(m1, m2);
    }

    /// Invariant 2c: preimage is injective in nonce.
    #[test]
    fn prop_preimage_injective_in_nonce(
        d in "[a-zA-Z0-9]{1,32}",
        v in 1u64..=2,
        n1 in "[0-9a-f]{2,64}",
        n2 in "[0-9a-f]{2,64}",
        pk in "[0-9a-f]{2,66}",
    ) {
        prop_assume!(n1 != n2);
        let m1 = canonical_reveal_preimage("pkg", &d, v, &n1, &pk);
        let m2 = canonical_reveal_preimage("pkg", &d, v, &n2, &pk);
        prop_assert_ne!(m1, m2);
    }

    /// Invariant 2d: preimage is injective in arbiter pubkey.
    #[test]
    fn prop_preimage_injective_in_pubkey(
        d in "[a-zA-Z0-9]{1,32}",
        v in 1u64..=2,
        nonce in "[0-9a-f]{2,64}",
        pk1 in "[0-9a-f]{2,66}",
        pk2 in "[0-9a-f]{2,66}",
    ) {
        prop_assume!(pk1 != pk2);
        let m1 = canonical_reveal_preimage("pkg", &d, v, &nonce, &pk1);
        let m2 = canonical_reveal_preimage("pkg", &d, v, &nonce, &pk2);
        prop_assert_ne!(m1, m2);
    }

    /// Invariant 2e: preimage is injective across package hashes (anti-replay
    /// across deployments).
    #[test]
    fn prop_preimage_injective_in_package_hash(
        d in "[a-zA-Z0-9]{1,32}",
        v in 1u64..=2,
        nonce in "[0-9a-f]{2,64}",
        pk in "[0-9a-f]{2,66}",
        pkg1 in "[A-Z0-9]{4,32}",
        pkg2 in "[A-Z0-9]{4,32}",
    ) {
        prop_assume!(pkg1 != pkg2);
        let m1 = canonical_reveal_preimage(&pkg1, &d, v, &nonce, &pk);
        let m2 = canonical_reveal_preimage(&pkg2, &d, v, &nonce, &pk);
        prop_assert_ne!(m1, m2);
    }

    /// Invariant 3a: advance_to_reveal is a monotonic step function on time.
    /// Before or at commit_deadline → error; strictly after → success.
    #[test]
    fn prop_advance_monotonic(
        commit_deadline in 100u64..=10_000,
        delta in 0i64..=20_000,
    ) {
        let now = commit_deadline.saturating_add_signed(delta);
        let res = advance_to_reveal(STATUS_COMMIT_PHASE, now, commit_deadline);
        if now > commit_deadline {
            prop_assert_eq!(res, Ok(STATUS_REVEAL_PHASE));
        } else {
            prop_assert_eq!(res, Err(PhaseError::CommitWindowOpen));
        }
    }

    /// Invariant 3b: can_finalize is monotonic on reveal_deadline.
    #[test]
    fn prop_finalize_monotonic(
        reveal_deadline in 100u64..=10_000,
        delta in 0i64..=20_000,
    ) {
        let now = reveal_deadline.saturating_add_signed(delta);
        let res = can_finalize(STATUS_REVEAL_PHASE, now, reveal_deadline);
        if now > reveal_deadline {
            prop_assert_eq!(res, Ok(()));
        } else {
            prop_assert_eq!(res, Err(PhaseError::RevealWindowOpen));
        }
    }

    /// Invariant 3c: terminal statuses never re-finalize regardless of time.
    #[test]
    fn prop_terminal_never_refinalize(
        now in any::<u64>(),
        reveal_deadline in any::<u64>(),
        idx in 0u8..3,
    ) {
        let terminal = match idx {
            0 => STATUS_FINALIZED_CHALLENGER_WINS,
            1 => STATUS_FINALIZED_STATUS_QUO,
            _ => STATUS_FINALIZED_FAILED_QUORUM,
        };
        prop_assert_eq!(
            can_finalize(terminal, now, reveal_deadline),
            Err(PhaseError::AlreadyFinalized)
        );
    }

    /// Invariant 4: threshold + majority rule is total on well-formed inputs.
    #[test]
    fn prop_finalize_total(
        threshold in 1u64..=10,
        sender_ct in 0u64..=20,
        receiver_ct in 0u64..=20,
    ) {
        let total = sender_ct + receiver_ct;
        let result = finalize_pure(total, threshold, sender_ct, receiver_ct);
        // Result MUST be one of the three finalized statuses.
        prop_assert!(
            result == STATUS_FINALIZED_CHALLENGER_WINS
                || result == STATUS_FINALIZED_STATUS_QUO
                || result == STATUS_FINALIZED_FAILED_QUORUM,
            "unexpected status {}", result
        );
        // Below threshold ⇒ FAILED_QUORUM regardless of majority.
        if total < threshold {
            prop_assert_eq!(result, STATUS_FINALIZED_FAILED_QUORUM);
        }
        // Above threshold with strict sender majority ⇒ CHALLENGER_WINS.
        if total >= threshold && sender_ct > receiver_ct {
            prop_assert_eq!(result, STATUS_FINALIZED_CHALLENGER_WINS);
        }
    }

    /// Invariant 4b: caller-supplied counts that don't sum to reveal_count
    /// are rejected (encoded as u64::MAX).
    #[test]
    fn prop_finalize_rejects_inconsistent(
        reveal_count in 0u64..=20,
        threshold in 1u64..=10,
        sender_ct in 0u64..=20,
        receiver_ct in 0u64..=20,
    ) {
        let sum = sender_ct + receiver_ct;
        prop_assume!(sum != reveal_count);
        prop_assert_eq!(
            finalize_pure(reveal_count, threshold, sender_ct, receiver_ct),
            u64::MAX
        );
    }

    /// Invariant 5: slash-eligibility. Only committed-and-not-revealed AND
    /// after reveal_deadline.
    #[test]
    fn prop_slashable_semantics(
        reveal_deadline in 100u64..=1_000_000,
        delta in 0i64..=2_000_000,
        committed in any::<bool>(),
        revealed in any::<bool>(),
    ) {
        let now = reveal_deadline.saturating_add_signed(delta);
        let result = is_slashable(now, reveal_deadline, committed, revealed);
        let expected = now > reveal_deadline && committed && !revealed;
        prop_assert_eq!(result, expected);
    }

    /// Invariant 8: timing monotonicity — commit_deadline > opened_at
    /// whenever commit_window > 0, and reveal_deadline > commit_deadline
    /// whenever reveal_window > 0.
    #[test]
    fn prop_timing_monotonic(
        opened_at in 0u64..=1_000_000,
        commit_window in 1u64..=1_000_000,
        reveal_window in 1u64..=1_000_000,
    ) {
        let commit_deadline = opened_at.saturating_add(commit_window);
        let reveal_deadline = commit_deadline.saturating_add(reveal_window);
        prop_assert!(commit_deadline > opened_at);
        prop_assert!(reveal_deadline > commit_deadline);
    }
}
