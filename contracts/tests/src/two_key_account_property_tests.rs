// Property-based tests (proptest) for the pure invariants of the
// two-key-account contract. Same rationale as property_tests.rs: the
// contract crate is `#![no_std]`/wasm32-only, so the pure logic is
// duplicated here in a plain std test crate.
//
// Covered invariants:
//   * `build_signed_message` is bijective in (action, contract_id, nonce,
//     payload_hash) — no two distinct tuples can produce the same message,
//     which is the anti-replay foundation.
//   * `nonce_to_string` matches std's `to_string()` for every u64 (proves
//     the no_std hand-rolled version is decimal-correct).
//   * Nonce consumption is monotonic + strictly increasing; any provided
//     nonce != expected must revert (property: reject_replay).
//   * Freeze / renounce state transitions form a lattice with the
//     expected "no un-renounce" terminal.

use proptest::prelude::*;

const DOMAIN: &str = "ae402:two-key:v1";

// ── Duplicated pure functions (must match main.rs) ──────────────────

fn nonce_to_string(mut n: u64) -> String {
    if n == 0 {
        return "0".to_string();
    }
    let mut buf: [u8; 20] = [0; 20];
    let mut i = 0;
    while n > 0 {
        buf[i] = b'0' + (n % 10) as u8;
        n /= 10;
        i += 1;
    }
    let mut s = String::with_capacity(i);
    while i > 0 {
        i -= 1;
        s.push(buf[i] as char);
    }
    s
}

fn build_signed_message(
    action: &str,
    contract_id: &str,
    nonce: u64,
    payload_hash: &str,
) -> String {
    let mut m = String::with_capacity(
        DOMAIN.len() + action.len() + contract_id.len() + payload_hash.len() + 24,
    );
    m.push_str(DOMAIN);
    m.push(':');
    m.push_str(action);
    m.push(':');
    m.push_str(contract_id);
    m.push(':');
    m.push_str(&nonce_to_string(nonce));
    m.push(':');
    m.push_str(payload_hash);
    m
}

/// Simulated on-chain nonce guard: same logic as `consume_nonce` in main.rs.
/// Returns Ok(new_state) or Err(kind) mirroring runtime::revert error codes.
#[derive(Debug, PartialEq)]
enum NonceErr {
    Mismatch,
}
fn consume_nonce_pure(current: u64, provided: u64) -> Result<u64, NonceErr> {
    if provided != current {
        return Err(NonceErr::Mismatch);
    }
    Ok(current.saturating_add(1))
}

// ── Unit-style expected outputs ─────────────────────────────────────

#[test]
fn nonce_to_string_zero() {
    assert_eq!(nonce_to_string(0), "0");
}

#[test]
fn nonce_to_string_matches_std() {
    for n in [1u64, 9, 10, 42, 99, 100, 1234, u64::MAX] {
        assert_eq!(nonce_to_string(n), n.to_string());
    }
}

#[test]
fn build_signed_message_has_domain_prefix() {
    let m = build_signed_message("exec", "hash-abc", 7, "payload-hash-xyz");
    assert!(m.starts_with("ae402:two-key:v1:exec:"));
    assert!(m.contains(":7:"));
    assert!(m.ends_with(":payload-hash-xyz"));
}

#[test]
fn build_signed_message_action_distinct_from_payload() {
    // Two different actions with the same everything-else must produce
    // different messages — otherwise a signature for `freeze` could
    // execute as `renounce`.
    let a = build_signed_message("freeze", "c1", 0, "p1");
    let b = build_signed_message("renounce", "c1", 0, "p1");
    assert_ne!(a, b);
}

#[test]
fn build_signed_message_contract_id_binds_signature() {
    // A signature valid for contract_id=c1 must NOT verify for c2, because
    // the signed string is different.
    let a = build_signed_message("exec", "contract-alpha", 5, "p");
    let b = build_signed_message("exec", "contract-beta", 5, "p");
    assert_ne!(a, b);
}

#[test]
fn consume_nonce_rejects_replay() {
    // valid path: 0 -> 1 -> 2
    let n0 = 0u64;
    let n1 = consume_nonce_pure(n0, 0).unwrap();
    assert_eq!(n1, 1);
    let n2 = consume_nonce_pure(n1, 1).unwrap();
    assert_eq!(n2, 2);
    // replaying the same nonce is a hard error
    assert_eq!(consume_nonce_pure(n2, 1), Err(NonceErr::Mismatch));
    // skipping ahead is also a hard error (no gaps allowed)
    assert_eq!(consume_nonce_pure(n2, 5), Err(NonceErr::Mismatch));
}

#[test]
fn consume_nonce_saturates_at_u64_max() {
    // At u64::MAX any further nonce would be replay (there's no MAX+1
    // slot), and consume_nonce_pure saturates rather than overflowing.
    let saturated = consume_nonce_pure(u64::MAX, u64::MAX).unwrap();
    assert_eq!(saturated, u64::MAX);
}

// ── Proptest invariants ─────────────────────────────────────────────

proptest! {
    /// Round-trip: nonce_to_string agrees with std for every u64.
    #[test]
    fn nonce_to_string_prop_matches_std(n in any::<u64>()) {
        prop_assert_eq!(nonce_to_string(n), n.to_string());
    }

    /// Distinct (action, contract_id, nonce, payload) tuples produce
    /// distinct signed messages. This is the *core* anti-replay property:
    /// the same signature cannot ever be reused across contracts, nonces,
    /// or actions.
    #[test]
    fn build_signed_message_is_injective(
        // Keep components ASCII-alphanumeric to avoid `:` collisions that
        // would break the trivial injectivity argument (the on-chain layer
        // constrains action/contract_id to hex-ish strings).
        a1 in "[a-z_]{1,16}",
        a2 in "[a-z_]{1,16}",
        c1 in "[a-f0-9]{1,32}",
        c2 in "[a-f0-9]{1,32}",
        n1 in any::<u64>(),
        n2 in any::<u64>(),
        p1 in "[a-f0-9]{1,64}",
        p2 in "[a-f0-9]{1,64}",
    ) {
        let m1 = build_signed_message(&a1, &c1, n1, &p1);
        let m2 = build_signed_message(&a2, &c2, n2, &p2);
        let same_tuple = a1 == a2 && c1 == c2 && n1 == n2 && p1 == p2;
        if same_tuple {
            prop_assert_eq!(m1, m2);
        } else {
            prop_assert_ne!(m1, m2);
        }
    }

    /// Nonce sequence is strictly increasing whenever consumption
    /// succeeds; and any mismatch reverts without state change.
    #[test]
    fn nonce_strictly_monotone_or_reverts(
        current in 0u64..(u64::MAX - 1),
        provided in any::<u64>(),
    ) {
        match consume_nonce_pure(current, provided) {
            Ok(next) => {
                prop_assert_eq!(next, current + 1);
                prop_assert_eq!(provided, current);
            }
            Err(NonceErr::Mismatch) => {
                prop_assert_ne!(provided, current);
            }
        }
    }
}

// ── State-machine invariants ────────────────────────────────────────

/// Simulated account state for lattice tests.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
struct AcctState {
    frozen: bool,
    renounced: bool,
}

impl AcctState {
    fn new() -> Self { Self { frozen: false, renounced: false } }
    fn can_exec(&self) -> bool { !self.frozen && !self.renounced }
    fn can_admin(&self) -> bool { !self.renounced }
    fn freeze(mut self) -> Option<Self> {
        if self.renounced { return None; }
        self.frozen = true;
        Some(self)
    }
    fn unfreeze(mut self) -> Option<Self> {
        if self.renounced { return None; }
        self.frozen = false;
        Some(self)
    }
    fn renounce(mut self) -> Option<Self> {
        if self.renounced { return None; }
        self.renounced = true;
        Some(self)
    }
}

#[test]
fn renounce_is_terminal() {
    let s = AcctState::new().renounce().unwrap();
    assert!(!s.can_exec());
    assert!(!s.can_admin());
    // Further admin ops MUST fail
    assert!(s.freeze().is_none());
    assert!(s.unfreeze().is_none());
    assert!(s.renounce().is_none());
}

#[test]
fn freeze_blocks_exec_but_admin_still_works() {
    let s = AcctState::new().freeze().unwrap();
    assert!(!s.can_exec());
    assert!(s.can_admin()); // cold key can still unfreeze / renounce / rotate
}

#[test]
fn unfreeze_restores_exec() {
    let s = AcctState::new().freeze().unwrap().unfreeze().unwrap();
    assert!(s.can_exec());
    assert!(s.can_admin());
}

proptest! {
    /// After any sequence of admin ops, `renounced` is monotonic: once
    /// set, it never clears. And `can_admin()` is exactly `!renounced`.
    #[test]
    fn renounced_monotonic(
        ops in prop::collection::vec(0u8..=2, 0..30),
    ) {
        let mut s = AcctState::new();
        let mut ever_renounced = false;
        for op in ops {
            let next = match op {
                0 => s.freeze(),
                1 => s.unfreeze(),
                _ => s.renounce(),
            };
            if let Some(ns) = next {
                s = ns;
                if op == 2 { ever_renounced = true; }
            }
            prop_assert_eq!(s.can_admin(), !s.renounced);
            prop_assert!(ever_renounced == s.renounced);
        }
    }
}
