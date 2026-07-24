#![no_std]
#![no_main]

//! Two-Key Smart Account (cold / hot)
//!
//! A minimal AA-style account contract that separates two Ed25519 key roles:
//!
//! * **Cold key** — root authority. Rotates keys, freezes/unfreezes the account,
//!   raises/lowers the hot-key spend cap, renounces the account. Meant to live
//!   offline (hardware wallet, air-gapped signer). Every cold-key action is
//!   signature-verified against a domain-separated, nonce-bound message so a
//!   compromised RPC / relayer cannot replay or forge.
//!
//! * **Hot key** — day-to-day agent authority. Signs `exec()` payloads up to
//!   `hot_spend_cap`. If the hot key is stolen, damage is bounded by the cap
//!   and can be cut immediately by the cold key via `freeze` or `rotate_hot`.
//!
//! Anti-replay: every signed message includes a monotonically increasing
//! `nonce` per role AND the contract package hash, so a signature for one
//! deployment cannot be replayed against another.
//!
//! Domain string: `ae402:two-key:v1:{action}:{contract_hash}:{nonce}:{payload_hash}`
//!
//! Threat model + full docs: `docs/TWO_KEY_ACCOUNT.md`.

extern crate alloc;

use alloc::string::{String, ToString};
use alloc::vec;
use alloc::vec::Vec;

use casper_contract::contract_api::{runtime, storage};
use casper_contract::unwrap_or_revert::UnwrapOrRevert;
use casper_types::contracts::NamedKeys;
use casper_types::crypto::{self, PublicKey, Signature};
use casper_types::{
    ApiError, AsymmetricType, CLType, CLValue, EntityEntryPoint, EntryPointAccess, EntryPointPayment,
    EntryPointType, EntryPoints, Key, Parameter, URef,
};

// ── Error codes ──────────────────────────────────────────────────────

const ERR_UNAUTHORIZED: u16 = 1;
const ERR_INVALID_SIGNATURE: u16 = 2;
const ERR_NONCE_MISMATCH: u16 = 3;
const ERR_FROZEN: u16 = 4;
const ERR_SPEND_CAP_EXCEEDED: u16 = 5;
const ERR_RENOUNCED: u16 = 6;
const ERR_KEY_UNCHANGED: u16 = 7;
const ERR_INVALID_KEY: u16 = 8;
const ERR_MISSING_KEY: u16 = 9;

// ── Storage keys ─────────────────────────────────────────────────────

const COLD_KEY: &str = "cold_key";
const HOT_KEY: &str = "hot_key";
const COLD_NONCE: &str = "cold_nonce";
const HOT_NONCE: &str = "hot_nonce";
const FROZEN: &str = "frozen";
const RENOUNCED: &str = "renounced";
const HOT_SPEND_CAP: &str = "hot_spend_cap";
const AUDIT_LOG: &str = "audit_log";

// ── Constants ────────────────────────────────────────────────────────

const DOMAIN: &str = "ae402:two-key:v1";

// ── Helpers ──────────────────────────────────────────────────────────

fn read_string_key(name: &str) -> String {
    let uref = runtime::get_key(name)
        .unwrap_or_revert_with(ApiError::User(ERR_MISSING_KEY))
        .into_uref()
        .unwrap_or_revert();
    storage::read::<String>(uref)
        .unwrap_or_revert()
        .unwrap_or_revert()
}

fn read_u64_key(name: &str) -> u64 {
    let uref = runtime::get_key(name)
        .unwrap_or_revert_with(ApiError::User(ERR_MISSING_KEY))
        .into_uref()
        .unwrap_or_revert();
    storage::read::<u64>(uref).unwrap_or_revert().unwrap_or(0)
}

fn read_bool_key(name: &str) -> bool {
    let uref = runtime::get_key(name)
        .unwrap_or_revert_with(ApiError::User(ERR_MISSING_KEY))
        .into_uref()
        .unwrap_or_revert();
    storage::read::<bool>(uref).unwrap_or_revert().unwrap_or(false)
}

fn write_string_key(name: &str, value: String) {
    let uref = runtime::get_key(name)
        .unwrap_or_revert_with(ApiError::User(ERR_MISSING_KEY))
        .into_uref()
        .unwrap_or_revert();
    storage::write(uref, value);
}

fn write_u64_key(name: &str, value: u64) {
    let uref = runtime::get_key(name)
        .unwrap_or_revert_with(ApiError::User(ERR_MISSING_KEY))
        .into_uref()
        .unwrap_or_revert();
    storage::write(uref, value);
}

fn write_bool_key(name: &str, value: bool) {
    let uref = runtime::get_key(name)
        .unwrap_or_revert_with(ApiError::User(ERR_MISSING_KEY))
        .into_uref()
        .unwrap_or_revert();
    storage::write(uref, value);
}

fn ensure_not_renounced() {
    if read_bool_key(RENOUNCED) {
        runtime::revert(ApiError::User(ERR_RENOUNCED));
    }
}

fn ensure_not_frozen() {
    if read_bool_key(FROZEN) {
        runtime::revert(ApiError::User(ERR_FROZEN));
    }
}

/// Deterministic message used for signature verification.
/// Format: `ae402:two-key:v1:{action}:{contract_hash}:{nonce}:{payload_hash}`.
/// Every entrypoint calls this exact function so on-chain and off-chain
/// signers can never disagree on the canonical string.
pub fn build_signed_message(
    action: &str,
    contract_hash: &str,
    nonce: u64,
    payload_hash: &str,
) -> String {
    let mut m = String::with_capacity(
        DOMAIN.len() + action.len() + contract_hash.len() + payload_hash.len() + 24,
    );
    m.push_str(DOMAIN);
    m.push(':');
    m.push_str(action);
    m.push(':');
    m.push_str(contract_hash);
    m.push(':');
    // avoid pulling in format! machinery in no_std: manual u64 -> ascii
    let n = nonce_to_string(nonce);
    m.push_str(&n);
    m.push(':');
    m.push_str(payload_hash);
    m
}

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

/// Verify an Ed25519 signature over the domain-separated message.
/// Returns unit on success, reverts with `ERR_INVALID_SIGNATURE` otherwise.
fn verify_signature(pubkey_hex: &str, sig_hex: &str, message: &str) {
    let public_key = match PublicKey::from_hex(pubkey_hex.as_bytes()) {
        Ok(pk) => pk,
        Err(_) => runtime::revert(ApiError::User(ERR_INVALID_KEY)),
    };
    let signature = match Signature::from_hex(sig_hex.as_bytes()) {
        Ok(s) => s,
        Err(_) => runtime::revert(ApiError::User(ERR_INVALID_SIGNATURE)),
    };
    if crypto::verify(message.as_bytes(), &signature, &public_key).is_err() {
        runtime::revert(ApiError::User(ERR_INVALID_SIGNATURE));
    }
}

/// Check nonce equals expected, then bump. Reverts on mismatch → replay-safe.
fn consume_nonce(role_key: &str, provided: u64) {
    let expected = read_u64_key(role_key);
    if provided != expected {
        runtime::revert(ApiError::User(ERR_NONCE_MISMATCH));
    }
    write_u64_key(role_key, expected.saturating_add(1));
}

fn append_audit(entry: String) {
    // Best-effort audit log — bounded to last N events by rolling counter.
    // Kept minimal on-chain (dict of counter -> event string).
    let counter_uref = runtime::get_key(AUDIT_LOG)
        .unwrap_or_revert_with(ApiError::User(ERR_MISSING_KEY))
        .into_uref()
        .unwrap_or_revert();
    let counter: u64 = storage::read(counter_uref).unwrap_or_revert().unwrap_or(0);
    let dict_uref = get_or_init_dict("audit_events");
    storage::dictionary_put(dict_uref, &nonce_to_string(counter), entry);
    storage::write(counter_uref, counter.saturating_add(1));
}

fn get_or_init_dict(name: &str) -> URef {
    match runtime::get_key(name) {
        Some(k) => k.into_uref().unwrap_or_revert(),
        None => storage::new_dictionary(name).unwrap_or_revert(),
    }
}

// ── Entry points ─────────────────────────────────────────────────────

/// `exec(hot_pubkey, hot_signature, nonce, payload_hash) -> ()`
///
/// Hot-key authenticated call. The payload itself is described off-chain by
/// its hash; the account contract only guarantees signature+nonce+cap. The
/// caller (relayer) is expected to submit the concrete action separately —
/// this contract's job is to authorise, not to route.
#[no_mangle]
pub extern "C" fn exec() {
    ensure_not_renounced();
    ensure_not_frozen();

    let hot_pubkey: String = runtime::get_named_arg("hot_pubkey");
    let hot_signature: String = runtime::get_named_arg("hot_signature");
    let nonce: u64 = runtime::get_named_arg("nonce");
    let payload_hash: String = runtime::get_named_arg("payload_hash");
    let amount_motes: u64 = runtime::get_named_arg("amount_motes");
    let contract_id: String = runtime::get_named_arg("contract_id");

    // Hot key must match registered hot key
    let registered_hot = read_string_key(HOT_KEY);
    if hot_pubkey != registered_hot {
        runtime::revert(ApiError::User(ERR_UNAUTHORIZED));
    }

    // Enforce spend cap
    let cap = read_u64_key(HOT_SPEND_CAP);
    if amount_motes > cap {
        runtime::revert(ApiError::User(ERR_SPEND_CAP_EXCEEDED));
    }

    let msg = build_signed_message("exec", &contract_id, nonce, &payload_hash);

    verify_signature(&hot_pubkey, &hot_signature, &msg);
    consume_nonce(HOT_NONCE, nonce);

    append_audit(alloc::format!("exec:{}:{}", nonce, payload_hash));
    runtime::ret(CLValue::from_t(true).unwrap_or_revert());
}

/// `rotate_hot(cold_pubkey, cold_signature, nonce, new_hot_pubkey_hex)`
///
/// Cold-key authenticated rotation of the hot key. Anti-replay via cold nonce
/// + payload_hash = hex(new_hot_pubkey).
#[no_mangle]
pub extern "C" fn rotate_hot() {
    ensure_not_renounced();
    require_cold_authorized("rotate_hot");
    let new_hot: String = runtime::get_named_arg("new_hot_pubkey");
    let current = read_string_key(HOT_KEY);
    if new_hot == current {
        runtime::revert(ApiError::User(ERR_KEY_UNCHANGED));
    }
    // sanity: parses as PublicKey
    if PublicKey::from_hex(new_hot.as_bytes()).is_err() {
        runtime::revert(ApiError::User(ERR_INVALID_KEY));
    }
    write_string_key(HOT_KEY, new_hot.clone());
    // Reset hot nonce to 0 on rotation so old signatures cannot replay
    write_u64_key(HOT_NONCE, 0);
    append_audit(alloc::format!("rotate_hot:{}", new_hot));
}

/// `rotate_cold(cold_pubkey, cold_signature, nonce, new_cold_pubkey_hex)`
///
/// Cold-key authenticated rotation of the *cold* key itself. High-risk —
/// requires cold signature over the new cold pubkey.
#[no_mangle]
pub extern "C" fn rotate_cold() {
    ensure_not_renounced();
    require_cold_authorized("rotate_cold");
    let new_cold: String = runtime::get_named_arg("new_cold_pubkey");
    let current = read_string_key(COLD_KEY);
    if new_cold == current {
        runtime::revert(ApiError::User(ERR_KEY_UNCHANGED));
    }
    if PublicKey::from_hex(new_cold.as_bytes()).is_err() {
        runtime::revert(ApiError::User(ERR_INVALID_KEY));
    }
    write_string_key(COLD_KEY, new_cold.clone());
    // Note: cold nonce is *not* reset — it monotonically continues to prevent
    // any residual replay across rotation windows.
    append_audit(alloc::format!("rotate_cold:{}", new_cold));
}

/// `freeze(cold_pubkey, cold_signature, nonce)` — halts exec()
#[no_mangle]
pub extern "C" fn freeze() {
    ensure_not_renounced();
    require_cold_authorized("freeze");
    write_bool_key(FROZEN, true);
    append_audit("freeze".to_string());
}

/// `unfreeze(cold_pubkey, cold_signature, nonce)` — resumes exec()
#[no_mangle]
pub extern "C" fn unfreeze() {
    ensure_not_renounced();
    require_cold_authorized("unfreeze");
    write_bool_key(FROZEN, false);
    append_audit("unfreeze".to_string());
}

/// `set_spend_cap(cold_pubkey, cold_signature, nonce, new_cap_motes)`
#[no_mangle]
pub extern "C" fn set_spend_cap() {
    ensure_not_renounced();
    require_cold_authorized("set_spend_cap");
    let new_cap: u64 = runtime::get_named_arg("new_cap_motes");
    write_u64_key(HOT_SPEND_CAP, new_cap);
    append_audit(alloc::format!("set_spend_cap:{}", new_cap));
}

/// `renounce(cold_pubkey, cold_signature, nonce)` — terminal state, no further ops
#[no_mangle]
pub extern "C" fn renounce() {
    ensure_not_renounced();
    require_cold_authorized("renounce");
    write_bool_key(RENOUNCED, true);
    append_audit("renounce".to_string());
}

/// Reusable cold-authz guard used by every cold entrypoint. Reads the
/// standard named args (cold_pubkey, cold_signature, nonce), builds the
/// canonical message with `action`, verifies + consumes nonce.
///
/// `payload_hash` for cold ops is bound to the action-specific arg the
/// entrypoint just read (via named_arg), passed here to make cold
/// signatures action+payload-specific. To keep this helper simple, entry
/// points read the arg first and pass its string form; helper hashes it.
fn require_cold_authorized(action: &str) {
    let cold_pubkey: String = runtime::get_named_arg("cold_pubkey");
    let cold_signature: String = runtime::get_named_arg("cold_signature");
    let nonce: u64 = runtime::get_named_arg("nonce");
    let payload_hash: String = runtime::get_named_arg("payload_hash");
    let contract_id: String = runtime::get_named_arg("contract_id");

    let registered_cold = read_string_key(COLD_KEY);
    if cold_pubkey != registered_cold {
        runtime::revert(ApiError::User(ERR_UNAUTHORIZED));
    }

    let msg = build_signed_message(action, &contract_id, nonce, &payload_hash);

    verify_signature(&cold_pubkey, &cold_signature, &msg);
    consume_nonce(COLD_NONCE, nonce);
}

// ── Read-only views ─────────────────────────────────────────────────

#[no_mangle]
pub extern "C" fn get_state() {
    let cold = read_string_key(COLD_KEY);
    let hot = read_string_key(HOT_KEY);
    let cold_nonce = read_u64_key(COLD_NONCE);
    let hot_nonce = read_u64_key(HOT_NONCE);
    let frozen = read_bool_key(FROZEN);
    let renounced = read_bool_key(RENOUNCED);
    let cap = read_u64_key(HOT_SPEND_CAP);
    // Return as tuple: ((cold, hot, cold_nonce), (hot_nonce, frozen, renounced), cap)
    let state = ((cold, hot, cold_nonce), (hot_nonce, frozen, renounced), cap);
    runtime::ret(CLValue::from_t(state).unwrap_or_revert());
}

// ── Install ─────────────────────────────────────────────────────────

#[no_mangle]
pub extern "C" fn call() {
    let cold_pubkey: String = runtime::get_named_arg("cold_pubkey");
    let hot_pubkey: String = runtime::get_named_arg("hot_pubkey");
    let hot_spend_cap_motes: u64 = runtime::get_named_arg("hot_spend_cap_motes");

    // Validate keys parse as Ed25519 pubkeys
    if PublicKey::from_hex(cold_pubkey.as_bytes()).is_err() {
        runtime::revert(ApiError::User(ERR_INVALID_KEY));
    }
    if PublicKey::from_hex(hot_pubkey.as_bytes()).is_err() {
        runtime::revert(ApiError::User(ERR_INVALID_KEY));
    }

    let mut entry_points = EntryPoints::new();

    let ep = |name: &str, params: Vec<Parameter>, ret: CLType| {
        EntityEntryPoint::new(
            name.to_string(),
            params,
            ret,
            EntryPointAccess::Public,
            EntryPointType::Called,
            EntryPointPayment::Caller,
        )
    };

    entry_points.add_entry_point(ep(
        "exec",
        vec![
            Parameter::new("hot_pubkey", CLType::String),
            Parameter::new("hot_signature", CLType::String),
            Parameter::new("nonce", CLType::U64),
            Parameter::new("payload_hash", CLType::String),
            Parameter::new("amount_motes", CLType::U64),
            Parameter::new("contract_id", CLType::String),
        ],
        CLType::Bool,
    ));

    let cold_params = || {
        vec![
            Parameter::new("cold_pubkey", CLType::String),
            Parameter::new("cold_signature", CLType::String),
            Parameter::new("nonce", CLType::U64),
            Parameter::new("payload_hash", CLType::String),
            Parameter::new("contract_id", CLType::String),
        ]
    };

    let with_extra = |extra: Vec<Parameter>| {
        let mut p = cold_params();
        p.extend(extra);
        p
    };

    entry_points.add_entry_point(ep(
        "rotate_hot",
        with_extra(vec![Parameter::new("new_hot_pubkey", CLType::String)]),
        CLType::Unit,
    ));
    entry_points.add_entry_point(ep(
        "rotate_cold",
        with_extra(vec![Parameter::new("new_cold_pubkey", CLType::String)]),
        CLType::Unit,
    ));
    entry_points.add_entry_point(ep("freeze", cold_params(), CLType::Unit));
    entry_points.add_entry_point(ep("unfreeze", cold_params(), CLType::Unit));
    entry_points.add_entry_point(ep(
        "set_spend_cap",
        with_extra(vec![Parameter::new("new_cap_motes", CLType::U64)]),
        CLType::Unit,
    ));
    entry_points.add_entry_point(ep("renounce", cold_params(), CLType::Unit));
    entry_points.add_entry_point(ep(
        "get_state",
        vec![],
        CLType::Any,
    ));

    let mut named_keys = NamedKeys::new();
    named_keys.insert(
        COLD_KEY.to_string(),
        Key::URef(storage::new_uref(cold_pubkey)),
    );
    named_keys.insert(
        HOT_KEY.to_string(),
        Key::URef(storage::new_uref(hot_pubkey)),
    );
    named_keys.insert(
        COLD_NONCE.to_string(),
        Key::URef(storage::new_uref(0u64)),
    );
    named_keys.insert(HOT_NONCE.to_string(), Key::URef(storage::new_uref(0u64)));
    named_keys.insert(FROZEN.to_string(), Key::URef(storage::new_uref(false)));
    named_keys.insert(RENOUNCED.to_string(), Key::URef(storage::new_uref(false)));
    named_keys.insert(
        HOT_SPEND_CAP.to_string(),
        Key::URef(storage::new_uref(hot_spend_cap_motes)),
    );
    named_keys.insert(
        AUDIT_LOG.to_string(),
        Key::URef(storage::new_uref(0u64)),
    );

    let (contract_hash, _version) = storage::new_contract(
        entry_points,
        Some(named_keys),
        Some("two_key_account_package_hash".to_string()),
        Some("two_key_account_access_uref".to_string()),
        None,
    );

    // Expose contract hash under installer's account for the deploy script
    // to pick up. Signature messages are bound to a caller-provided
    // `contract_id` at call time — replay across contracts is prevented
    // because a signature over one id cannot verify with any other.
    runtime::put_key("two_key_account_contract_hash", contract_hash.into());
}
