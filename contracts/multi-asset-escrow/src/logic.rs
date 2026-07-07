//! Pure state-machine logic for MultiAssetEscrow, kept free of any Casper
//! host-function calls (`runtime::*`, `storage::*`, `system::*`) so it can
//! be exercised by plain `cargo test` on the host target as well as
//! compiled into the `no_std` wasm contract binary. Mirrors the
//! release-cap / arbiter-quorum / status-transition logic in
//! `contracts/escrow/src/main.rs` -- this is not a copy-paste import of
//! that crate (this is an independent contract), but the same reasoning.

extern crate alloc;

use alloc::string::String;
use alloc::vec::Vec;

use casper_types::crypto::{self, PublicKey, Signature};
use casper_types::{AsymmetricType, U256};

// ── Escrow status codes (mirrors contracts/escrow) ──────────────────────

pub const STATUS_PENDING: u8 = 0;
pub const STATUS_RELEASED: u8 = 1;
pub const STATUS_REFUNDED: u8 = 2;
pub const STATUS_EXPIRED: u8 = 3;
pub const STATUS_DISPUTED: u8 = 4;
pub const STATUS_RESOLVED: u8 = 5;

// ── Constants ────────────────────────────────────────────────────────

pub const MIN_TTL: u64 = 60;
pub const MAX_TTL: u64 = 86_400;
pub const MAX_FEE_BPS: u64 = 1_000;
// Denominated in the token's smallest unit (not motes -- this contract
// never touches CSPR/purses). Above this amount, release()/resolve()
// require an arbiter-quorum cap-approval on top of normal authorization,
// same A1 "no unilateral withdraw above cap" guard as the native escrow.
pub const DEFAULT_RELEASE_CAP: u64 = 1_000_000_000_000;

// ── TTL / expiry ─────────────────────────────────────────────────────

pub fn is_ttl_valid(ttl: u64) -> bool {
    ttl >= MIN_TTL && ttl <= MAX_TTL
}

pub fn is_expired(now: u64, created_at: u64, ttl: u64) -> bool {
    now > created_at.saturating_add(ttl)
}

// ── Fee math ─────────────────────────────────────────────────────────

pub fn is_fee_bps_valid(fee_bps: u64) -> bool {
    fee_bps <= MAX_FEE_BPS
}

pub fn compute_fee(amount: U256, bps: u64) -> U256 {
    amount * U256::from(bps) / U256::from(10_000u64)
}

/// `None` on underflow (fee > amount) -- defensive, should be
/// unreachable given `is_fee_bps_valid`, but never silently wrap.
pub fn checked_deduct_fee(amount: U256, fee: U256) -> Option<U256> {
    amount.checked_sub(fee)
}

// ── Status-transition guards ─────────────────────────────────────────

pub fn can_release(status: u8) -> bool {
    status == STATUS_PENDING
}

pub fn can_refund(status: u8) -> bool {
    status == STATUS_PENDING
}

pub fn can_dispute(status: u8) -> bool {
    status == STATUS_PENDING
}

pub fn can_resolve(status: u8) -> bool {
    status == STATUS_DISPUTED
}

pub fn resolve_winner_is_sender(in_favor_of: &str) -> bool {
    in_favor_of == "sender"
}

// ── Arbiter-quorum signed messages ───────────────────────────────────

pub fn build_resolve_message(service_hash: &str, in_favor_of: &str) -> String {
    let mut msg = String::from("resolve:");
    msg.push_str(service_hash);
    msg.push(':');
    msg.push_str(in_favor_of);
    msg
}

pub fn build_cap_approval_message(action: &str, service_hash: &str) -> String {
    let mut msg = String::from(action);
    msg.push(':');
    msg.push_str(service_hash);
    msg.push_str(":cap_approval");
    msg
}

/// Shared arbiter-quorum verification: at least `threshold` *distinct*,
/// *registered* arbiters must produce a valid Ed25519 signature over
/// `message`. Returns the number of valid, deduplicated votes. Identical
/// logic to `contracts/escrow::verify_arbiter_quorum`.
pub fn verify_arbiter_quorum(
    message: &str,
    registered: &[String],
    pubkeys: &[String],
    signatures: &[String],
) -> u64 {
    if pubkeys.len() != signatures.len() {
        return 0;
    }
    let mut seen = Vec::<String>::new();
    let mut valid_count: u64 = 0;
    for (pubkey_hex, sig_hex) in pubkeys.iter().zip(signatures.iter()) {
        if seen.contains(pubkey_hex) || !registered.contains(pubkey_hex) {
            continue;
        }
        let Ok(public_key) = PublicKey::from_hex(pubkey_hex.as_bytes()) else {
            continue;
        };
        let Ok(signature) = Signature::from_hex(sig_hex.as_bytes()) else {
            continue;
        };
        if crypto::verify(message.as_bytes(), &signature, &public_key).is_ok() {
            valid_count += 1;
            seen.push(pubkey_hex.clone());
        }
    }
    valid_count
}

// ── Hex helpers (no external crate) ──────────────────────────────────

pub fn hex_decode_32(s: &str) -> [u8; 32] {
    let mut out = [0u8; 32];
    let bytes = s.as_bytes();
    for (i, chunk) in bytes.chunks(2).enumerate() {
        if i >= 32 {
            break;
        }
        let hi = (chunk[0] as char).to_digit(16).unwrap_or(0) as u8;
        let lo = chunk
            .get(1)
            .and_then(|&b| (b as char).to_digit(16))
            .unwrap_or(0) as u8;
        out[i] = (hi << 4) | lo;
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use alloc::string::ToString;
    use alloc::vec;

    #[test]
    fn ttl_bounds() {
        assert!(!is_ttl_valid(0));
        assert!(!is_ttl_valid(59));
        assert!(is_ttl_valid(60));
        assert!(is_ttl_valid(86_400));
        assert!(!is_ttl_valid(86_401));
    }

    #[test]
    fn expiry_math() {
        assert!(!is_expired(100, 50, 60)); // 100 <= 110
        assert!(!is_expired(110, 50, 60)); // boundary: not strictly greater
        assert!(is_expired(111, 50, 60));
    }

    #[test]
    fn fee_bps_bounds() {
        assert!(is_fee_bps_valid(0));
        assert!(is_fee_bps_valid(1_000));
        assert!(!is_fee_bps_valid(1_001));
    }

    #[test]
    fn fee_math() {
        let amount = U256::from(1_000_000u64);
        let fee = compute_fee(amount, 200); // 2%
        assert_eq!(fee, U256::from(20_000u64));
        let net = checked_deduct_fee(amount, fee).unwrap();
        assert_eq!(net, U256::from(980_000u64));
    }

    #[test]
    fn fee_deduction_underflow_is_none() {
        let amount = U256::from(100u64);
        let fee = U256::from(200u64);
        assert!(checked_deduct_fee(amount, fee).is_none());
    }

    #[test]
    fn status_transition_guards() {
        assert!(can_release(STATUS_PENDING));
        assert!(!can_release(STATUS_DISPUTED));
        assert!(!can_release(STATUS_RELEASED));

        assert!(can_refund(STATUS_PENDING));
        assert!(!can_refund(STATUS_REFUNDED));

        assert!(can_dispute(STATUS_PENDING));
        assert!(!can_dispute(STATUS_RESOLVED));

        assert!(can_resolve(STATUS_DISPUTED));
        assert!(!can_resolve(STATUS_PENDING));
    }

    #[test]
    fn winner_selection() {
        assert!(resolve_winner_is_sender("sender"));
        assert!(!resolve_winner_is_sender("receiver"));
        assert!(!resolve_winner_is_sender("anything_else"));
    }

    #[test]
    fn resolve_message_binds_hash_and_verdict() {
        let m1 = build_resolve_message("abc123", "sender");
        let m2 = build_resolve_message("abc123", "receiver");
        let m3 = build_resolve_message("def456", "sender");
        assert_ne!(m1, m2, "different verdicts must produce different messages");
        assert_ne!(m1, m3, "different escrows must produce different messages");
        assert_eq!(m1, "resolve:abc123:sender".to_string());
    }

    #[test]
    fn cap_approval_message_binds_action_and_hash() {
        let m1 = build_cap_approval_message("release", "abc123");
        let m2 = build_cap_approval_message("resolve", "abc123");
        assert_ne!(m1, m2, "different actions must not share a signable message");
        assert_eq!(m1, "release:abc123:cap_approval".to_string());
    }

    #[test]
    fn quorum_rejects_mismatched_lengths() {
        let registered = vec!["pk1".to_string()];
        let pubkeys = vec!["pk1".to_string()];
        let sigs: Vec<String> = vec![];
        assert_eq!(
            verify_arbiter_quorum("msg", &registered, &pubkeys, &sigs),
            0
        );
    }

    #[test]
    fn quorum_rejects_unregistered_and_garbage_signatures() {
        let registered = vec!["pk1".to_string(), "pk2".to_string()];
        let pubkeys = vec!["not_registered".to_string(), "pk1".to_string()];
        let sigs = vec!["deadbeef".to_string(), "deadbeef".to_string()];
        // Neither entry produces a valid signature (garbage hex / not
        // registered), so the quorum count must be zero, not panic.
        assert_eq!(
            verify_arbiter_quorum("msg", &registered, &pubkeys, &sigs),
            0
        );
    }

    #[test]
    fn hex_decode_roundtrip_for_zero_and_max() {
        let zero = hex_decode_32(&"00".repeat(32));
        assert_eq!(zero, [0u8; 32]);
        let max = hex_decode_32(&"ff".repeat(32));
        assert_eq!(max, [0xffu8; 32]);
    }
}
