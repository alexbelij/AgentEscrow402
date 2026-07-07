//! MultiAssetEscrow — real on-chain contract-custody escrow for CEP-18
//! fungible tokens on Casper. Mirrors the state machine of the native
//! CSPR escrow (`contracts/escrow`) -- create/release/refund/dispute/
//! resolve, same arbiter-quorum-above-cap guard -- but instead of moving
//! CSPR through `system::transfer_from_purse_to_purse`, it moves an
//! arbitrary CEP-18-compatible token in and out of *this contract's own*
//! balance slot inside that token's `balances` dictionary via real
//! cross-contract calls (`transfer_from` on create, `transfer` on
//! release/refund/resolve). This is not a copy-paste of the escrow
//! crate -- it's an independent contract that reuses the same reasoning.
//!
//! Custody identity: Casper's `runtime::get_caller()` always returns an
//! `AccountHash` -- by construction it can never represent a contract, so
//! it resolves to the transaction's originating account even many
//! call-stack hops deep. A CEP-18 token whose `transfer`/`transfer_from`/
//! `approve` derive the acting identity from `get_caller()` alone can
//! therefore never let a contract be a spender or a token holder in its
//! own right -- there is no way for a contract to "be" the caller. This
//! contract's custody model requires the token it calls to instead use
//! `runtime::get_immediate_caller()` (which *can* represent a calling
//! smart contract via `Caller::SmartContract`) to compute the acting
//! identity for those three entry points -- see
//! `contracts/test-token/src/main.rs`'s `caller_key()`, upgraded for
//! this. Escrow flow with that token: the depositor calls
//! `token.approve(spender=<this contract's own package hash as Key>,
//! amount)` once (a normal account-signed call, so
//! `get_immediate_caller()` reports `Caller::Initiator` there), then
//! calls `create_escrow(...)`; this contract pulls the funds in via
//! `transfer_from(owner=depositor, recipient=<this contract's own
//! package hash as Key>, amount)`. On the payout side this contract
//! calls `token.transfer(recipient=<receiver or sender>, amount)`
//! itself, so `get_immediate_caller()` inside the token reports
//! `Caller::SmartContract{contract_package_hash: <this contract's
//! package hash>, ..}` -- the same identity that received the funds at
//! creation -- and the token debits exactly that custody balance.

#![no_std]
#![no_main]

extern crate alloc;

mod logic;

use alloc::collections::BTreeMap;
use alloc::string::{String, ToString};
use alloc::vec;
use alloc::vec::Vec;

use casper_contract::contract_api::{runtime, storage};
use casper_contract::unwrap_or_revert::UnwrapOrRevert;
use casper_types::account::AccountHash;
use casper_types::contracts::{ContractHash, ContractPackageHash, NamedKeys};
use casper_types::{
    ApiError, CLType, CLValue, EntityEntryPoint, EntryPointAccess, EntryPointPayment,
    EntryPointType, EntryPoints, Key, Parameter, RuntimeArgs, URef, U256,
};

use logic::{
    build_cap_approval_message, build_resolve_message, can_dispute, can_refund, can_release,
    can_resolve, checked_deduct_fee, compute_fee, hex_decode_32, is_expired, is_fee_bps_valid,
    is_ttl_valid, resolve_winner_is_sender, verify_arbiter_quorum, DEFAULT_RELEASE_CAP,
    STATUS_DISPUTED, STATUS_EXPIRED, STATUS_PENDING, STATUS_REFUNDED, STATUS_RELEASED,
    STATUS_RESOLVED,
};

// ── Error codes ──────────────────────────────────────────────────────

const ERR_ESCROW_NOT_FOUND: u16 = 1;
const ERR_UNAUTHORIZED: u16 = 2;
const ERR_ALREADY_DISPUTED: u16 = 4;
const ERR_INVALID_SIGNATURE: u16 = 5;
const ERR_INVALID_STATUS: u16 = 8;
const ERR_TTL_OUT_OF_RANGE: u16 = 10;
const ERR_DUPLICATE_HASH: u16 = 11;
const ERR_INSUFFICIENT_SIGS: u16 = 12;
const ERR_ZERO_AMOUNT: u16 = 13;
const ERR_POOL_FROZEN: u16 = 14;
const ERR_CAP_EXCEEDED: u16 = 19;
const ERR_FEE_EXCEEDS_AMOUNT: u16 = 20;
const ERR_FEE_TOO_HIGH: u16 = 21;

// ── Storage keys ─────────────────────────────────────────────────────

const ESCROWS_DICT: &str = "escrows";
const ARBITER_LIST: &str = "arbiter_list";
const ARBITER_THRESHOLD: &str = "arbiter_threshold";
const POOL_FROZEN_KEY: &str = "pool_frozen";
const INSTALLER_KEY: &str = "installer";
const RELEASE_CAP_KEY: &str = "release_cap";
const SELF_PACKAGE_KEY: &str = "self_package_hash";

const PACKAGE_KEY: &str = "multi_asset_escrow_package_hash";
const ACCESS_KEY: &str = "multi_asset_escrow_access_uref";
const CONTRACT_KEY: &str = "multi_asset_escrow_contract";

// ── Escrow record layout ─────────────────────────────────────────────
// Nested 3-tuples (same trick as contracts/escrow) to stay within the
// tuple arities casper-types implements ToBytes/FromBytes for.
type EscrowCore = (String, String, String); // sender_hex, receiver_hex, amount_str
type EscrowMeta = (String, u64, u64); // service_hash, status, created_at
type EscrowExtra = (u64, u64, String); // ttl, fee_bps, token_contract_hash_hex
type EscrowRecord = (EscrowCore, EscrowMeta, EscrowExtra);

// ── Helpers ──────────────────────────────────────────────────────────

fn read_installer() -> AccountHash {
    runtime::get_key(INSTALLER_KEY)
        .unwrap_or_revert()
        .into_account()
        .unwrap_or_revert()
}

fn get_dict_uref(name: &str) -> URef {
    // Casper 2.2.x: new_dictionary is disallowed in install/session
    // context -- create lazily on first entry-point ("Called") call.
    match runtime::get_key(name) {
        Some(key) => key.into_uref().unwrap_or_revert(),
        None => storage::new_dictionary(name).unwrap_or_revert(),
    }
}

fn require_not_frozen() {
    let uref = runtime::get_key(POOL_FROZEN_KEY)
        .unwrap_or_revert()
        .into_uref()
        .unwrap_or_revert();
    let frozen: bool = storage::read(uref).unwrap_or_revert().unwrap_or(false);
    if frozen {
        runtime::revert(ApiError::User(ERR_POOL_FROZEN));
    }
}

fn parse_u256(s: &str) -> U256 {
    match U256::from_dec_str(s) {
        Ok(v) => v,
        Err(_) => runtime::revert(ApiError::User(ERR_ESCROW_NOT_FOUND)),
    }
}

fn parse_account(s: &str) -> AccountHash {
    match AccountHash::from_formatted_str(s) {
        Ok(v) => v,
        Err(_) => AccountHash::new(hex_decode_32(s)),
    }
}

/// Parses a 64-hex-char (optionally `contract-`-prefixed) string into a
/// `ContractHash`, mirroring `parse_account`'s two-format tolerance.
fn parse_contract_hash(s: &str) -> ContractHash {
    match ContractHash::from_formatted_str(s) {
        Ok(v) => v,
        Err(_) => ContractHash::new(hex_decode_32(s)),
    }
}

/// This contract's own package hash, embedded as a named key at install
/// time (see `call()`). Used as the custody identity for cross-contract
/// calls into the token contract -- both the `recipient` of `transfer_from`
/// on create and the implicit sender of `transfer` on payout resolve to
/// this same identity inside a token whose `caller_key()` uses
/// `get_immediate_caller()` (see module doc comment).
fn read_self_package_hash() -> ContractPackageHash {
    let key = runtime::get_key(SELF_PACKAGE_KEY).unwrap_or_revert();
    let addr = key.into_hash_addr().unwrap_or_revert();
    addr.into()
}

fn self_key() -> Key {
    Key::from(read_self_package_hash())
}

fn read_escrow(dict: URef, key: &str) -> EscrowRecord {
    storage::dictionary_get::<EscrowRecord>(dict, key)
        .unwrap_or_revert()
        .unwrap_or_revert_with(ApiError::User(ERR_ESCROW_NOT_FOUND))
}

fn write_escrow(dict: URef, key: &str, record: EscrowRecord) {
    storage::dictionary_put(dict, key, record);
}

fn read_release_cap() -> U256 {
    let cap = match runtime::get_key(RELEASE_CAP_KEY) {
        Some(key) => {
            let uref = key.into_uref().unwrap_or_revert();
            match storage::read::<u64>(uref) {
                Ok(Some(v)) => v,
                _ => DEFAULT_RELEASE_CAP,
            }
        }
        None => DEFAULT_RELEASE_CAP,
    };
    U256::from(cap)
}

fn require_arbiter_cap_approval(
    action: &str,
    service_hash: &str,
    arbiter_pubkeys: &[String],
    arbiter_signatures: &[String],
) {
    let threshold_uref = runtime::get_key(ARBITER_THRESHOLD)
        .unwrap_or_revert()
        .into_uref()
        .unwrap_or_revert();
    let threshold: u64 = storage::read(threshold_uref).unwrap_or_revert().unwrap_or(3);

    let arb_uref = runtime::get_key(ARBITER_LIST)
        .unwrap_or_revert()
        .into_uref()
        .unwrap_or_revert();
    let registered: Vec<String> = storage::read(arb_uref).unwrap_or_revert().unwrap_or_default();

    let message = build_cap_approval_message(action, service_hash);
    let valid_count = verify_arbiter_quorum(&message, &registered, arbiter_pubkeys, arbiter_signatures);
    if valid_count < threshold {
        runtime::revert(ApiError::User(ERR_CAP_EXCEEDED));
    }
}

/// Cross-contract call into the token's `transfer_from` entry point,
/// pulling `amount` from `owner` into `recipient` (this contract's own
/// custody identity). Reverts (propagating the token's own ApiError) if
/// the allowance/balance is insufficient.
fn token_transfer_from(token: ContractHash, owner: Key, recipient: Key, amount: U256) {
    let mut args = RuntimeArgs::new();
    args.insert("owner", owner).unwrap_or_revert();
    args.insert("recipient", recipient).unwrap_or_revert();
    args.insert("amount", amount).unwrap_or_revert();
    runtime::call_contract::<()>(token, "transfer_from", args);
}

/// Cross-contract call into the token's `transfer` entry point, pushing
/// `amount` out of *this contract's own* balance (the token derives the
/// sender from the immediate caller, which is this contract) to
/// `recipient`.
fn token_transfer(token: ContractHash, recipient: Key, amount: U256) {
    let mut args = RuntimeArgs::new();
    args.insert("recipient", recipient).unwrap_or_revert();
    args.insert("amount", amount).unwrap_or_revert();
    runtime::call_contract::<()>(token, "transfer", args);
}

// ── Entry points ─────────────────────────────────────────────────────

/// Lock a CEP-18 token amount in escrow by pulling it into this
/// contract's own custody balance via `transfer_from`, until the service
/// completes (`release`) or the TTL expires (`refund`).
#[no_mangle]
pub extern "C" fn create_escrow() {
    require_not_frozen();

    let sender = runtime::get_caller();
    let receiver: AccountHash = runtime::get_named_arg("receiver");
    let amount: U256 = runtime::get_named_arg("amount");
    let service_hash: String = runtime::get_named_arg("service_hash");
    let ttl: u64 = runtime::get_named_arg("ttl");
    let token_contract_hash: String = runtime::get_named_arg("token_contract_hash");
    let fee_bps: u64 = runtime::get_named_arg("fee_bps");

    if amount.is_zero() {
        runtime::revert(ApiError::User(ERR_ZERO_AMOUNT));
    }
    if !is_ttl_valid(ttl) {
        runtime::revert(ApiError::User(ERR_TTL_OUT_OF_RANGE));
    }
    if !is_fee_bps_valid(fee_bps) {
        runtime::revert(ApiError::User(ERR_FEE_TOO_HIGH));
    }

    let dict = get_dict_uref(ESCROWS_DICT);
    let existing: Option<EscrowRecord> = storage::dictionary_get(dict, &service_hash).unwrap_or_revert();
    if existing.is_some() {
        runtime::revert(ApiError::User(ERR_DUPLICATE_HASH));
    }

    let token = parse_contract_hash(&token_contract_hash);

    // Pull the full amount into this contract's own custody balance.
    // Checks-effects-interactions would normally write state first, but
    // here the escrow record's existence *is* gated on this call
    // succeeding (a reverted transfer_from aborts the whole deploy, so
    // there's no partial-state risk either way).
    token_transfer_from(token, Key::Account(sender), self_key(), amount);

    let created_at: u64 = runtime::get_blocktime().into();
    let record: EscrowRecord = (
        (sender.to_string(), receiver.to_string(), amount.to_string()),
        (service_hash.clone(), STATUS_PENDING as u64, created_at),
        (ttl, fee_bps, token_contract_hash),
    );
    write_escrow(dict, &service_hash, record);
}

/// Release escrowed tokens to the receiver. Same A1 guard as the native
/// escrow: above the release cap, a quorum of registered-arbiter
/// signatures over `build_cap_approval_message("release", service_hash)`
/// is required in addition to sender authorization.
#[no_mangle]
pub extern "C" fn release() {
    require_not_frozen();

    let service_hash: String = runtime::get_named_arg("service_hash");
    let arbiter_pubkeys: Vec<String> = runtime::get_named_arg("arbiter_pubkeys");
    let arbiter_signatures: Vec<String> = runtime::get_named_arg("arbiter_signatures");
    let caller = runtime::get_caller();

    let dict = get_dict_uref(ESCROWS_DICT);
    let ((sender_str, receiver_str, amount_str), (_, status, created_at), (ttl, fee_bps, token_hash_str)) =
        read_escrow(dict, &service_hash);

    if !can_release(status as u8) {
        runtime::revert(ApiError::User(ERR_INVALID_STATUS));
    }
    if caller.to_string() != sender_str {
        runtime::revert(ApiError::User(ERR_UNAUTHORIZED));
    }

    let amount = parse_u256(&amount_str);
    if amount > read_release_cap() {
        require_arbiter_cap_approval("release", &service_hash, &arbiter_pubkeys, &arbiter_signatures);
    }

    let fee = compute_fee(amount, fee_bps);
    let net_amount = checked_deduct_fee(amount, fee)
        .unwrap_or_revert_with(ApiError::User(ERR_FEE_EXCEEDS_AMOUNT));

    // Checks-effects-interactions: write terminal status before the
    // outbound cross-contract transfer.
    let updated: EscrowRecord = (
        (sender_str, receiver_str.clone(), amount_str),
        (service_hash.clone(), STATUS_RELEASED as u64, created_at),
        (ttl, fee_bps, token_hash_str.clone()),
    );
    write_escrow(dict, &service_hash, updated);

    let token = parse_contract_hash(&token_hash_str);
    let receiver = parse_account(&receiver_str);
    if !fee.is_zero() {
        let installer = read_installer();
        token_transfer(token, Key::Account(installer), fee);
    }
    token_transfer(token, Key::Account(receiver), net_amount);
}

/// Refund escrowed tokens to the sender once the TTL has expired (or at
/// any time if the sender itself calls it, mirroring the native escrow).
#[no_mangle]
pub extern "C" fn refund() {
    require_not_frozen();

    let service_hash: String = runtime::get_named_arg("service_hash");
    let caller = runtime::get_caller();

    let dict = get_dict_uref(ESCROWS_DICT);
    let ((sender_str, receiver_str, amount_str), (_, status, created_at), (ttl, fee_bps, token_hash_str)) =
        read_escrow(dict, &service_hash);

    if !can_refund(status as u8) {
        runtime::revert(ApiError::User(ERR_INVALID_STATUS));
    }

    let now: u64 = runtime::get_blocktime().into();
    let expired = is_expired(now, created_at, ttl);
    let is_sender = caller.to_string() == sender_str;
    if !expired && !is_sender {
        runtime::revert(ApiError::User(ERR_UNAUTHORIZED));
    }

    let amount = parse_u256(&amount_str);
    let fee = compute_fee(amount, fee_bps);
    let refund_amount = checked_deduct_fee(amount, fee)
        .unwrap_or_revert_with(ApiError::User(ERR_FEE_EXCEEDS_AMOUNT));

    let new_status = if expired { STATUS_EXPIRED } else { STATUS_REFUNDED };
    let updated: EscrowRecord = (
        (sender_str.clone(), receiver_str, amount_str),
        (service_hash.clone(), new_status as u64, created_at),
        (ttl, fee_bps, token_hash_str.clone()),
    );
    write_escrow(dict, &service_hash, updated);

    let token = parse_contract_hash(&token_hash_str);
    let sender = parse_account(&sender_str);
    if !fee.is_zero() {
        let installer = read_installer();
        token_transfer(token, Key::Account(installer), fee);
    }
    token_transfer(token, Key::Account(sender), refund_amount);
}

/// Open a dispute for a pending escrow. Only sender or receiver may
/// call it, same as the native escrow.
#[no_mangle]
pub extern "C" fn dispute() {
    require_not_frozen();

    let service_hash: String = runtime::get_named_arg("service_hash");
    let caller = runtime::get_caller();

    let dict = get_dict_uref(ESCROWS_DICT);
    let ((sender_str, receiver_str, amount_str), (_, status, created_at), (ttl, fee_bps, token_hash_str)) =
        read_escrow(dict, &service_hash);

    if !can_dispute(status as u8) {
        runtime::revert(ApiError::User(ERR_INVALID_STATUS));
    }
    let caller_str = caller.to_string();
    if caller_str != sender_str && caller_str != receiver_str {
        runtime::revert(ApiError::User(ERR_UNAUTHORIZED));
    }

    let updated: EscrowRecord = (
        (sender_str, receiver_str, amount_str),
        (service_hash.clone(), STATUS_DISPUTED as u64, created_at),
        (ttl, fee_bps, token_hash_str),
    );
    write_escrow(dict, &service_hash, updated);
}

/// Resolve a disputed escrow via arbiter-quorum vote. Mirrors the native
/// escrow's `resolve()` quorum check verbatim (same message format, same
/// dedupe-by-pubkey, same registered-arbiter/threshold source).
#[no_mangle]
pub extern "C" fn resolve() {
    require_not_frozen();

    let service_hash: String = runtime::get_named_arg("service_hash");
    let in_favor_of: String = runtime::get_named_arg("in_favor_of");
    let arbiter_pubkeys: Vec<String> = runtime::get_named_arg("arbiter_pubkeys");
    let arbiter_signatures: Vec<String> = runtime::get_named_arg("arbiter_signatures");

    let dict = get_dict_uref(ESCROWS_DICT);
    let ((sender_str, receiver_str, amount_str), (_, status, created_at), (ttl, fee_bps, token_hash_str)) =
        read_escrow(dict, &service_hash);

    if !can_resolve(status as u8) {
        runtime::revert(ApiError::User(ERR_ALREADY_DISPUTED));
    }

    let threshold_uref = runtime::get_key(ARBITER_THRESHOLD)
        .unwrap_or_revert()
        .into_uref()
        .unwrap_or_revert();
    let threshold: u64 = storage::read(threshold_uref).unwrap_or_revert().unwrap_or(3);

    if arbiter_pubkeys.len() != arbiter_signatures.len() {
        runtime::revert(ApiError::User(ERR_INVALID_SIGNATURE));
    }
    if (arbiter_pubkeys.len() as u64) < threshold {
        runtime::revert(ApiError::User(ERR_INSUFFICIENT_SIGS));
    }

    let arb_uref = runtime::get_key(ARBITER_LIST)
        .unwrap_or_revert()
        .into_uref()
        .unwrap_or_revert();
    let registered: Vec<String> = storage::read(arb_uref).unwrap_or_revert().unwrap_or_default();

    let vote_message = build_resolve_message(&service_hash, &in_favor_of);
    let valid_count = verify_arbiter_quorum(&vote_message, &registered, &arbiter_pubkeys, &arbiter_signatures);
    if valid_count < threshold {
        runtime::revert(ApiError::User(ERR_INVALID_SIGNATURE));
    }

    let amount = parse_u256(&amount_str);
    let fee = compute_fee(amount, fee_bps);
    let net_amount = checked_deduct_fee(amount, fee)
        .unwrap_or_revert_with(ApiError::User(ERR_FEE_EXCEEDS_AMOUNT));

    let winner_str = if resolve_winner_is_sender(&in_favor_of) {
        sender_str.clone()
    } else {
        receiver_str.clone()
    };
    let winner = parse_account(&winner_str);

    let updated: EscrowRecord = (
        (sender_str, receiver_str, amount_str),
        (service_hash.clone(), STATUS_RESOLVED as u64, created_at),
        (ttl, fee_bps, token_hash_str.clone()),
    );
    write_escrow(dict, &service_hash, updated);

    let token = parse_contract_hash(&token_hash_str);
    if !fee.is_zero() {
        let installer = read_installer();
        token_transfer(token, Key::Account(installer), fee);
    }
    token_transfer(token, Key::Account(winner), net_amount);
}

/// Register (replace) the on-chain arbiter list (installer only).
#[no_mangle]
pub extern "C" fn set_arbiters() {
    let caller = runtime::get_caller();
    if caller != read_installer() {
        runtime::revert(ApiError::User(ERR_UNAUTHORIZED));
    }
    let arbiters: Vec<String> = runtime::get_named_arg("arbiters");
    let uref = runtime::get_key(ARBITER_LIST).unwrap_or_revert().into_uref().unwrap_or_revert();
    storage::write(uref, arbiters);
}

/// Update the A1 release cap, denominated in the token's smallest unit
/// (installer only).
#[no_mangle]
pub extern "C" fn set_release_cap() {
    let caller = runtime::get_caller();
    if caller != read_installer() {
        runtime::revert(ApiError::User(ERR_UNAUTHORIZED));
    }
    let new_cap: u64 = runtime::get_named_arg("new_cap");
    match runtime::get_key(RELEASE_CAP_KEY) {
        Some(key) => storage::write(key.into_uref().unwrap_or_revert(), new_cap),
        None => {
            let uref = storage::new_uref(new_cap);
            runtime::put_key(RELEASE_CAP_KEY, uref.into());
        }
    }
}

/// Freeze all state-changing entry points (installer only).
#[no_mangle]
pub extern "C" fn emergency_freeze() {
    let caller = runtime::get_caller();
    if caller != read_installer() {
        runtime::revert(ApiError::User(ERR_UNAUTHORIZED));
    }
    let uref = runtime::get_key(POOL_FROZEN_KEY).unwrap_or_revert().into_uref().unwrap_or_revert();
    storage::write(uref, true);
}

/// Resume after `emergency_freeze` (installer only).
#[no_mangle]
pub extern "C" fn unfreeze() {
    let caller = runtime::get_caller();
    if caller != read_installer() {
        runtime::revert(ApiError::User(ERR_UNAUTHORIZED));
    }
    let uref = runtime::get_key(POOL_FROZEN_KEY).unwrap_or_revert().into_uref().unwrap_or_revert();
    storage::write(uref, false);
}

/// Read escrow record by service hash.
#[no_mangle]
pub extern "C" fn get_escrow() {
    let service_hash: String = runtime::get_named_arg("service_hash");
    let dict = get_dict_uref(ESCROWS_DICT);
    let record = read_escrow(dict, &service_hash);
    runtime::ret(CLValue::from_t(record).unwrap_or_revert());
}

// ── Contract installation ────────────────────────────────────────────

fn build_entry_points() -> EntryPoints {
    let mut entry_points = EntryPoints::new();
    entry_points.add_entry_point(EntityEntryPoint::new(
        "create_escrow",
        vec![
            Parameter::new("receiver", CLType::ByteArray(32)),
            Parameter::new("amount", CLType::U256),
            Parameter::new("service_hash", CLType::String),
            Parameter::new("ttl", CLType::U64),
            Parameter::new("token_contract_hash", CLType::String),
            Parameter::new("fee_bps", CLType::U64),
        ],
        CLType::Unit,
        EntryPointAccess::Public,
        EntryPointType::Called,
        EntryPointPayment::Caller,
    ));
    entry_points.add_entry_point(EntityEntryPoint::new(
        "release",
        vec![
            Parameter::new("service_hash", CLType::String),
            Parameter::new("arbiter_pubkeys", CLType::List(alloc::boxed::Box::new(CLType::String))),
            Parameter::new("arbiter_signatures", CLType::List(alloc::boxed::Box::new(CLType::String))),
        ],
        CLType::Unit,
        EntryPointAccess::Public,
        EntryPointType::Called,
        EntryPointPayment::Caller,
    ));
    entry_points.add_entry_point(EntityEntryPoint::new(
        "refund",
        vec![Parameter::new("service_hash", CLType::String)],
        CLType::Unit,
        EntryPointAccess::Public,
        EntryPointType::Called,
        EntryPointPayment::Caller,
    ));
    entry_points.add_entry_point(EntityEntryPoint::new(
        "dispute",
        vec![Parameter::new("service_hash", CLType::String)],
        CLType::Unit,
        EntryPointAccess::Public,
        EntryPointType::Called,
        EntryPointPayment::Caller,
    ));
    entry_points.add_entry_point(EntityEntryPoint::new(
        "resolve",
        vec![
            Parameter::new("service_hash", CLType::String),
            Parameter::new("in_favor_of", CLType::String),
            Parameter::new("arbiter_pubkeys", CLType::List(alloc::boxed::Box::new(CLType::String))),
            Parameter::new("arbiter_signatures", CLType::List(alloc::boxed::Box::new(CLType::String))),
        ],
        CLType::Unit,
        EntryPointAccess::Public,
        EntryPointType::Called,
        EntryPointPayment::Caller,
    ));
    entry_points.add_entry_point(EntityEntryPoint::new(
        "set_arbiters",
        vec![Parameter::new("arbiters", CLType::List(alloc::boxed::Box::new(CLType::String)))],
        CLType::Unit,
        EntryPointAccess::Public,
        EntryPointType::Called,
        EntryPointPayment::Caller,
    ));
    entry_points.add_entry_point(EntityEntryPoint::new(
        "set_release_cap",
        vec![Parameter::new("new_cap", CLType::U64)],
        CLType::Unit,
        EntryPointAccess::Public,
        EntryPointType::Called,
        EntryPointPayment::Caller,
    ));
    entry_points.add_entry_point(EntityEntryPoint::new(
        "emergency_freeze",
        vec![],
        CLType::Unit,
        EntryPointAccess::Public,
        EntryPointType::Called,
        EntryPointPayment::Caller,
    ));
    entry_points.add_entry_point(EntityEntryPoint::new(
        "unfreeze",
        vec![],
        CLType::Unit,
        EntryPointAccess::Public,
        EntryPointType::Called,
        EntryPointPayment::Caller,
    ));
    entry_points.add_entry_point(EntityEntryPoint::new(
        "get_escrow",
        vec![Parameter::new("service_hash", CLType::String)],
        CLType::Any,
        EntryPointAccess::Public,
        EntryPointType::Called,
        EntryPointPayment::Caller,
    ));
    entry_points
}

#[no_mangle]
pub extern "C" fn call() {
    let installer = runtime::get_caller();
    let entry_points = build_entry_points();

    // Idempotent re-install support: if this account already installed a
    // package (re-running the same session wasm, e.g. after an entry-point
    // fix with no new named keys), add a new version instead of a new
    // package -- preserves escrows/arbiter state. New named keys (like
    // `self_package_hash`, added at genesis only) are NOT retrofitted by
    // this path -- see module-level SKILL.md note on this limitation.
    if let Some(existing_package_key) = runtime::get_key(PACKAGE_KEY) {
        let package_hash_addr = existing_package_key.into_hash_addr().unwrap_or_revert();
        let package_hash: ContractPackageHash = package_hash_addr.into();
        let (contract_hash, _version) = storage::add_contract_version(
            package_hash,
            entry_points,
            NamedKeys::new(),
            BTreeMap::new(),
        );
        runtime::put_key(CONTRACT_KEY, contract_hash.into());
        return;
    }

    let (package_hash, access_uref) = storage::create_contract_package_at_hash();
    runtime::put_key(PACKAGE_KEY, package_hash.into());
    runtime::put_key(ACCESS_KEY, access_uref.into());

    let mut named_keys = NamedKeys::new();
    named_keys.insert(INSTALLER_KEY.into(), Key::Account(installer));
    named_keys.insert(ARBITER_THRESHOLD.into(), storage::new_uref(3u64).into());
    named_keys.insert(ARBITER_LIST.into(), storage::new_uref(Vec::<String>::new()).into());
    named_keys.insert(RELEASE_CAP_KEY.into(), storage::new_uref(DEFAULT_RELEASE_CAP).into());
    named_keys.insert(POOL_FROZEN_KEY.into(), storage::new_uref(false).into());
    // This contract's own package hash, embedded so entry points can read
    // it back as the custody identity for token cross-contract calls --
    // see module doc comment / `self_key()`.
    named_keys.insert(SELF_PACKAGE_KEY.into(), Key::from(package_hash));

    let (contract_hash, _version) =
        storage::add_contract_version(package_hash, entry_points, named_keys, BTreeMap::new());
    runtime::put_key(CONTRACT_KEY, contract_hash.into());
}
