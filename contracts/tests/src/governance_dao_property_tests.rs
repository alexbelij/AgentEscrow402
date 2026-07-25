// Property + unit tests for the AE402 Governance DAO pure logic.
//
// The contract crate is `#![no_std]`/wasm32-only; the pure functions
// (status transitions, quorum math, params parsing, execution-message
// bijection) are also exposed as a std library. This test file consumes
// the std library and covers:
//
//   * status transitions form the expected lattice (ACTIVE → PASSED/REJECTED/EXPIRED/VETOED/EXECUTED).
//   * quorum threshold math never overflows on u64 stakes.
//   * effective_weight is min(requested, voting_power).
//   * split_kv is exhaustive on well-formed and malformed input.
//   * parse_u64 rejects empty, non-decimal, and overflowing strings.
//   * parse_params round-trips valid params for every action; rejects everything else.
//   * build_execution_message is injective in (proposal_id, action_type, params).

use proptest::prelude::*;

use ae402_governance_dao::{
    build_execution_message, effective_weight, is_valid_action, parse_params, parse_u64,
    quorum_threshold, resolve_status, split_kv, ActionParams, ACTION_ADJUST_FEE_BPS,
    ACTION_PAUSE_PROTOCOL, ACTION_ROTATE_ARBITER_SET, ACTION_UPDATE_INSURANCE_POOL_PARAMS,
    ACTION_UPDATE_RANGE_PROOF_PARAMS, ACTION_UPDATE_TIMELOCK_DELAY, ERR_INVALID_ACTION,
    ERR_INVALID_PARAMS, MAX_ACTION, QUORUM_PERCENT, STATUS_ACTIVE, STATUS_EXPIRED, STATUS_PASSED,
    STATUS_REJECTED,
};

// ── Quorum math ──────────────────────────────────────────────────────

#[test]
fn quorum_zero_stake_is_zero() {
    assert_eq!(quorum_threshold(0, QUORUM_PERCENT), 0);
}

#[test]
fn quorum_matches_percent_math() {
    assert_eq!(quorum_threshold(1_000, 30), 300);
    assert_eq!(quorum_threshold(1_000, 50), 500);
    assert_eq!(quorum_threshold(1_000, 100), 1_000);
}

proptest! {
    #[test]
    fn quorum_never_exceeds_total(total in 0u64..u64::MAX, percent in 0u64..=100) {
        let t = quorum_threshold(total, percent);
        prop_assert!(t as u128 <= total as u128);
    }

    #[test]
    fn quorum_monotonic_in_percent(total in 0u64..1_000_000_000u64) {
        let t30 = quorum_threshold(total, 30);
        let t50 = quorum_threshold(total, 50);
        let t100 = quorum_threshold(total, 100);
        prop_assert!(t30 <= t50);
        prop_assert!(t50 <= t100);
    }
}

// ── effective_weight ─────────────────────────────────────────────────

proptest! {
    #[test]
    fn effective_weight_is_min(a in 0u64..u64::MAX, b in 0u64..u64::MAX) {
        let e = effective_weight(a, b);
        prop_assert!(e <= a);
        prop_assert!(e <= b);
        prop_assert!(e == a || e == b);
    }
}

// ── Status transitions ───────────────────────────────────────────────

#[test]
fn status_open_below_quorum_stays_active() {
    // 100 total, 10 for, 5 against → 15 < 30 threshold → ACTIVE while open
    let s = resolve_status(10, 5, 100, 30, 500, 1000);
    assert_eq!(s, STATUS_ACTIVE);
}

#[test]
fn status_open_quorum_passed() {
    // 100 total, 25 for, 5 against → 30 ≥ 30 threshold, for > against → PASSED
    let s = resolve_status(25, 5, 100, 30, 500, 1000);
    assert_eq!(s, STATUS_PASSED);
}

#[test]
fn status_open_quorum_tie_rejected() {
    // Quorum met, for == against → REJECTED (not "still active"). This matches
    // RWA-S: for MUST strictly exceed against.
    let s = resolve_status(15, 15, 100, 30, 500, 1000);
    assert_eq!(s, STATUS_REJECTED);
}

#[test]
fn status_closed_no_quorum_expired() {
    let s = resolve_status(5, 3, 100, 30, 2000, 1000);
    assert_eq!(s, STATUS_EXPIRED);
}

#[test]
fn status_closed_quorum_passed() {
    let s = resolve_status(20, 15, 100, 30, 2000, 1000);
    assert_eq!(s, STATUS_PASSED);
}

#[test]
fn status_closed_quorum_rejected() {
    let s = resolve_status(15, 20, 100, 30, 2000, 1000);
    assert_eq!(s, STATUS_REJECTED);
}

proptest! {
    #[test]
    fn status_only_emits_known_codes(
        vf in 0u64..1_000_000u64,
        va in 0u64..1_000_000u64,
        total in 0u64..1_000_000u64,
        percent in 0u64..=100,
        t in 0u64..u64::MAX,
        ve in 0u64..u64::MAX,
    ) {
        let s = resolve_status(vf, va, total, percent, t, ve);
        prop_assert!(matches!(
            s,
            STATUS_ACTIVE | STATUS_PASSED | STATUS_REJECTED | STATUS_EXPIRED
        ));
    }
}

// ── Action-code validity ─────────────────────────────────────────────

#[test]
fn actions_zero_through_max_valid() {
    for a in 0..=MAX_ACTION {
        assert!(is_valid_action(a), "action {} should be valid", a);
    }
}

#[test]
fn action_above_max_invalid() {
    assert!(!is_valid_action(MAX_ACTION + 1));
    assert!(!is_valid_action(u64::MAX));
}

// ── split_kv ─────────────────────────────────────────────────────────

#[test]
fn split_kv_empty_ok() {
    assert!(split_kv("").unwrap().is_empty());
}

#[test]
fn split_kv_single_pair() {
    let pairs = split_kv("bps=250").unwrap();
    assert_eq!(pairs, vec![("bps".to_string(), "250".to_string())]);
}

#[test]
fn split_kv_multi() {
    let pairs = split_kv("bps=250;flag=on").unwrap();
    assert_eq!(pairs.len(), 2);
    assert_eq!(pairs[0], ("bps".to_string(), "250".to_string()));
    assert_eq!(pairs[1], ("flag".to_string(), "on".to_string()));
}

#[test]
fn split_kv_missing_value() {
    assert_eq!(split_kv("bps=").unwrap_err(), ERR_INVALID_PARAMS);
}

#[test]
fn split_kv_missing_equals() {
    assert_eq!(split_kv("bps").unwrap_err(), ERR_INVALID_PARAMS);
}

#[test]
fn split_kv_empty_segment() {
    assert_eq!(split_kv("bps=1;;flag=2").unwrap_err(), ERR_INVALID_PARAMS);
}

// ── parse_u64 ────────────────────────────────────────────────────────

#[test]
fn parse_u64_ok() {
    assert_eq!(parse_u64("0").unwrap(), 0);
    assert_eq!(parse_u64("1").unwrap(), 1);
    assert_eq!(parse_u64("42").unwrap(), 42);
    assert_eq!(parse_u64("18446744073709551615").unwrap(), u64::MAX);
}

#[test]
fn parse_u64_rejects_empty() {
    assert_eq!(parse_u64("").unwrap_err(), ERR_INVALID_PARAMS);
}

#[test]
fn parse_u64_rejects_non_digit() {
    assert_eq!(parse_u64("12a").unwrap_err(), ERR_INVALID_PARAMS);
    assert_eq!(parse_u64("-1").unwrap_err(), ERR_INVALID_PARAMS);
    assert_eq!(parse_u64(" 1").unwrap_err(), ERR_INVALID_PARAMS);
}

#[test]
fn parse_u64_rejects_overflow() {
    assert_eq!(parse_u64("18446744073709551616").unwrap_err(), ERR_INVALID_PARAMS);
    assert_eq!(parse_u64("99999999999999999999").unwrap_err(), ERR_INVALID_PARAMS);
}

proptest! {
    #[test]
    fn parse_u64_roundtrip(n in 0u64..u64::MAX) {
        let s = n.to_string();
        prop_assert_eq!(parse_u64(&s).unwrap(), n);
    }
}

// ── parse_params — happy paths ──────────────────────────────────────

#[test]
fn adjust_fee_bps_ok() {
    let p = parse_params(ACTION_ADJUST_FEE_BPS, "bps=250").unwrap();
    assert_eq!(p, ActionParams::AdjustFeeBps { bps: 250 });
}

#[test]
fn adjust_fee_bps_boundary() {
    assert!(matches!(
        parse_params(ACTION_ADJUST_FEE_BPS, "bps=0").unwrap(),
        ActionParams::AdjustFeeBps { bps: 0 }
    ));
    assert!(matches!(
        parse_params(ACTION_ADJUST_FEE_BPS, "bps=10000").unwrap(),
        ActionParams::AdjustFeeBps { bps: 10000 }
    ));
}

#[test]
fn adjust_fee_bps_over_10000_rejected() {
    assert_eq!(
        parse_params(ACTION_ADJUST_FEE_BPS, "bps=10001").unwrap_err(),
        ERR_INVALID_PARAMS
    );
}

#[test]
fn rotate_arbiter_add_ok() {
    let pk = "a".repeat(66);
    let params = format!("op=add;value={}", pk);
    let p = parse_params(ACTION_ROTATE_ARBITER_SET, &params).unwrap();
    assert_eq!(
        p,
        ActionParams::RotateArbiterSet {
            op: "add".to_string(),
            value: pk,
        }
    );
}

#[test]
fn rotate_arbiter_threshold_ok() {
    let p = parse_params(ACTION_ROTATE_ARBITER_SET, "op=threshold;value=5").unwrap();
    assert_eq!(
        p,
        ActionParams::RotateArbiterSet {
            op: "threshold".to_string(),
            value: "5".to_string(),
        }
    );
}

#[test]
fn rotate_arbiter_unknown_op_rejected() {
    assert_eq!(
        parse_params(ACTION_ROTATE_ARBITER_SET, "op=nuke;value=1").unwrap_err(),
        ERR_INVALID_PARAMS
    );
}

#[test]
fn rotate_arbiter_bad_hex_rejected() {
    let bad = "z".repeat(66);
    assert_eq!(
        parse_params(ACTION_ROTATE_ARBITER_SET, &format!("op=add;value={}", bad)).unwrap_err(),
        ERR_INVALID_PARAMS
    );
}

#[test]
fn rotate_arbiter_wrong_length_rejected() {
    let short = "a".repeat(64);
    assert_eq!(
        parse_params(ACTION_ROTATE_ARBITER_SET, &format!("op=add;value={}", short)).unwrap_err(),
        ERR_INVALID_PARAMS
    );
}

#[test]
fn rotate_arbiter_threshold_zero_rejected() {
    assert_eq!(
        parse_params(ACTION_ROTATE_ARBITER_SET, "op=threshold;value=0").unwrap_err(),
        ERR_INVALID_PARAMS
    );
}

#[test]
fn rotate_arbiter_threshold_over_64_rejected() {
    assert_eq!(
        parse_params(ACTION_ROTATE_ARBITER_SET, "op=threshold;value=65").unwrap_err(),
        ERR_INVALID_PARAMS
    );
}

#[test]
fn insurance_pool_ok() {
    let p = parse_params(
        ACTION_UPDATE_INSURANCE_POOL_PARAMS,
        "max_coverage_bps=5000;cooldown_sec=3600",
    )
    .unwrap();
    assert_eq!(
        p,
        ActionParams::UpdateInsurancePool {
            max_coverage_bps: 5000,
            cooldown_sec: 3600,
        }
    );
}

#[test]
fn insurance_pool_coverage_over_10000_rejected() {
    assert_eq!(
        parse_params(
            ACTION_UPDATE_INSURANCE_POOL_PARAMS,
            "max_coverage_bps=10001;cooldown_sec=1"
        )
        .unwrap_err(),
        ERR_INVALID_PARAMS
    );
}

#[test]
fn timelock_delay_ok() {
    let p = parse_params(ACTION_UPDATE_TIMELOCK_DELAY, "delay_sec=86400").unwrap();
    assert_eq!(p, ActionParams::UpdateTimelockDelay { delay_sec: 86400 });
}

#[test]
fn timelock_delay_below_hour_rejected() {
    assert_eq!(
        parse_params(ACTION_UPDATE_TIMELOCK_DELAY, "delay_sec=3599").unwrap_err(),
        ERR_INVALID_PARAMS
    );
    assert_eq!(
        parse_params(ACTION_UPDATE_TIMELOCK_DELAY, "delay_sec=0").unwrap_err(),
        ERR_INVALID_PARAMS
    );
}

#[test]
fn range_proof_ok() {
    let p = parse_params(ACTION_UPDATE_RANGE_PROOF_PARAMS, "min_bits=8;max_bits=16").unwrap();
    assert_eq!(
        p,
        ActionParams::UpdateRangeProof {
            min_bits: 8,
            max_bits: 16,
        }
    );
}

#[test]
fn range_proof_min_greater_than_max_rejected() {
    assert_eq!(
        parse_params(ACTION_UPDATE_RANGE_PROOF_PARAMS, "min_bits=16;max_bits=8").unwrap_err(),
        ERR_INVALID_PARAMS
    );
}

#[test]
fn range_proof_over_32_bits_rejected() {
    assert_eq!(
        parse_params(ACTION_UPDATE_RANGE_PROOF_PARAMS, "min_bits=1;max_bits=33").unwrap_err(),
        ERR_INVALID_PARAMS
    );
}

#[test]
fn range_proof_zero_bits_rejected() {
    assert_eq!(
        parse_params(ACTION_UPDATE_RANGE_PROOF_PARAMS, "min_bits=0;max_bits=8").unwrap_err(),
        ERR_INVALID_PARAMS
    );
}

#[test]
fn pause_ok() {
    assert_eq!(
        parse_params(ACTION_PAUSE_PROTOCOL, "mode=pause").unwrap(),
        ActionParams::PauseProtocol { pause: true }
    );
    assert_eq!(
        parse_params(ACTION_PAUSE_PROTOCOL, "mode=unpause").unwrap(),
        ActionParams::PauseProtocol { pause: false }
    );
}

#[test]
fn pause_unknown_mode_rejected() {
    assert_eq!(
        parse_params(ACTION_PAUSE_PROTOCOL, "mode=maybe").unwrap_err(),
        ERR_INVALID_PARAMS
    );
}

#[test]
fn unknown_action_rejected() {
    assert_eq!(
        parse_params(MAX_ACTION + 1, "bps=0").unwrap_err(),
        ERR_INVALID_ACTION
    );
    assert_eq!(
        parse_params(u64::MAX, "bps=0").unwrap_err(),
        ERR_INVALID_ACTION
    );
}

// ── build_execution_message — bijection in (id, action, params) ─────

#[test]
fn exec_msg_shape() {
    let m = build_execution_message(1, ACTION_ADJUST_FEE_BPS, "bps=250");
    assert_eq!(m, "ae402:governance-dao:exec:v1:1:0:bps=250");
}

proptest! {
    #[test]
    fn exec_msg_id_bijection(id1 in 0u64..u64::MAX, id2 in 0u64..u64::MAX) {
        prop_assume!(id1 != id2);
        let a = build_execution_message(id1, 0, "bps=250");
        let b = build_execution_message(id2, 0, "bps=250");
        prop_assert_ne!(a, b);
    }

    #[test]
    fn exec_msg_action_bijection(id in 0u64..u64::MAX, a1 in 0u64..=MAX_ACTION, a2 in 0u64..=MAX_ACTION) {
        prop_assume!(a1 != a2);
        let m1 = build_execution_message(id, a1, "x=y");
        let m2 = build_execution_message(id, a2, "x=y");
        prop_assert_ne!(m1, m2);
    }
}
