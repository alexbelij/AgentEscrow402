#![no_std]
#![no_main]

extern crate alloc;

use alloc::collections::BTreeMap;
use alloc::string::{String, ToString};
use alloc::vec;
use alloc::vec::Vec;

use casper_contract::contract_api::{runtime, storage, system};
use casper_contract::unwrap_or_revert::UnwrapOrRevert;
use casper_types::account::AccountHash;
use casper_types::contracts::NamedKeys;
use casper_types::{
    ApiError, CLType, CLValue, EntryPoint, EntryPointAccess, EntryPointType, EntryPoints, Key,
    Parameter, RuntimeArgs, URef, U512,
};

// ── Error codes ──────────────────────────────────────────────────────

const ERR_ESCROW_NOT_FOUND: u16 = 1;
const ERR_UNAUTHORIZED: u16 = 2;
const ERR_INSUFFICIENT_FUNDS: u16 = 3;
const ERR_ALREADY_DISPUTED: u16 = 4;
const ERR_INVALID_SIGNATURE: u16 = 5;
const ERR_POOL_FROZEN: u16 = 6;
const ERR_FEE_TOO_HIGH: u16 = 7;
const ERR_INVALID_STATUS: u16 = 8;
const ERR_TTL_EXPIRED: u16 = 9;
const ERR_TTL_OUT_OF_RANGE: u16 = 10;
const ERR_DUPLICATE_HASH: u16 = 11;
const ERR_INSUFFICIENT_SIGS: u16 = 12;
const ERR_ZERO_AMOUNT: u16 = 13;

// ── Storage keys ─────────────────────────────────────────────────────

const ESCROWS_DICT: &str = "escrows";
const REPUTATION_DICT: &str = "reputation";
const ARBITER_LIST: &str = "arbiter_list";
const ARBITER_THRESHOLD: &str = "arbiter_threshold";
const FEE_BPS_KEY: &str = "fee_bps";
const POOL_FROZEN_KEY: &str = "pool_frozen";
const INSTALLER_KEY: &str = "installer";
const CONTRACT_PURSE: &str = "contract_purse";
const INSURANCE_PURSE: &str = "insurance_purse";

// ── Constants ────────────────────────────────────────────────────────

const MIN_TTL: u64 = 60;
const MAX_TTL: u64 = 86_400;
const MAX_FEE_BPS: u64 = 1_000;
const DEFAULT_FEE_BPS: u64 = 200;
const DECAY_PERCENT_PER_WEEK: u64 = 5;

// ── Escrow status ────────────────────────────────────────────────────

const STATUS_PENDING: u8 = 0;
const STATUS_RELEASED: u8 = 1;
const STATUS_REFUNDED: u8 = 2;
const STATUS_EXPIRED: u8 = 3;
const STATUS_DISPUTED: u8 = 4;
const STATUS_RESOLVED: u8 = 5;

// ── Helpers ──────────────────────────────────────────────────────────

fn emit_event(event_type: &str, data: &[(&str, &str)]) {
    let mut ev = BTreeMap::new();
    ev.insert("type".to_string(), event_type.to_string());
    for (k, v) in data {
        ev.insert(k.to_string(), v.to_string());
    }
    let cl = CLValue::from_t(ev).unwrap_or_revert();
    runtime::put_key(
        &alloc::format!("event_{}", runtime::get_blocktime().into()),
        Key::from(storage::new_uref(cl)),
    );
}

fn read_installer() -> AccountHash {
    let key = runtime::get_key(INSTALLER_KEY).unwrap_or_revert();
    key.into_account().unwrap_or_revert()
}

fn read_fee_bps() -> u64 {
    let uref = runtime::get_key(FEE_BPS_KEY)
        .unwrap_or_revert()
        .into_uref()
        .unwrap_or_revert();
    storage::read::<u64>(uref)
        .unwrap_or_revert()
        .unwrap_or(DEFAULT_FEE_BPS)
}

fn is_pool_frozen() -> bool {
    let uref = runtime::get_key(POOL_FROZEN_KEY)
        .unwrap_or_revert()
        .into_uref()
        .unwrap_or_revert();
    storage::read::<bool>(uref)
        .unwrap_or_revert()
        .unwrap_or(false)
}

fn get_dict_uref(name: &str) -> URef {
    runtime::get_key(name)
        .unwrap_or_revert()
        .into_uref()
        .unwrap_or_revert()
}

fn reputation_score(completed: u64, disputed: u64, weeks_inactive: u64) -> u8 {
    if completed == 0 {
        return 50;
    }
    let base = 100u64.saturating_sub(disputed.saturating_mul(10).min(50));
    let decay = DECAY_PERCENT_PER_WEEK
        .saturating_mul(weeks_inactive)
        .min(50);
    let score = base.saturating_sub(base.saturating_mul(decay) / 100);
    score.min(100) as u8
}

// ── Entry points ─────────────────────────────────────────────────────

/// Lock CSPR in escrow until service completes or TTL expires.
#[no_mangle]
pub extern "C" fn escrow() {
    let sender = runtime::get_caller();
    let receiver: AccountHash = runtime::get_named_arg("receiver");
    let amount: U512 = runtime::get_named_arg("amount");
    let service_hash: String = runtime::get_named_arg("service_hash");
    let ttl: u64 = runtime::get_named_arg("ttl");

    if amount.is_zero() {
        runtime::revert(ApiError::User(ERR_ZERO_AMOUNT));
    }
    if ttl < MIN_TTL || ttl > MAX_TTL {
        runtime::revert(ApiError::User(ERR_TTL_OUT_OF_RANGE));
    }

    let dict = get_dict_uref(ESCROWS_DICT);
    let existing: Option<Vec<u8>> = storage::dictionary_get(dict, &service_hash).unwrap_or_revert();
    if existing.is_some() {
        runtime::revert(ApiError::User(ERR_DUPLICATE_HASH));
    }

    let fee_bps = read_fee_bps();
    let insurance_fee = amount * U512::from(fee_bps) / U512::from(10_000u64);
    let escrow_amount = amount - insurance_fee;

    let contract_purse = get_dict_uref(CONTRACT_PURSE);
    system::transfer_from_purse_to_purse(
        runtime::get_caller().value().into(),
        contract_purse,
        escrow_amount,
        None,
    )
    .unwrap_or_revert();

    if !insurance_fee.is_zero() {
        let ins_purse = get_dict_uref(INSURANCE_PURSE);
        system::transfer_from_purse_to_purse(
            runtime::get_caller().value().into(),
            ins_purse,
            insurance_fee,
            None,
        )
        .unwrap_or_revert();
    }

    let created_at: u64 = runtime::get_blocktime().into();
    let record = (
        sender.to_string(),
        receiver.to_string(),
        amount.to_string(),
        service_hash.clone(),
        STATUS_PENDING,
        created_at,
        ttl,
    );
    let encoded = CLValue::from_t(record).unwrap_or_revert();
    storage::dictionary_put(dict, &service_hash, encoded);

    emit_event(
        "EscrowCreated",
        &[
            ("service_hash", &service_hash),
            ("amount", &amount.to_string()),
            ("sender", &sender.to_string()),
            ("receiver", &receiver.to_string()),
            ("ttl", &ttl.to_string()),
        ],
    );
}

/// Release escrowed funds to the service provider.
#[no_mangle]
pub extern "C" fn release() {
    let service_hash: String = runtime::get_named_arg("service_hash");
    let caller = runtime::get_caller();

    let dict = get_dict_uref(ESCROWS_DICT);
    let record: (String, String, String, String, u8, u64, u64) =
        storage::dictionary_get(dict, &service_hash)
            .unwrap_or_revert()
            .unwrap_or_revert_with(ApiError::User(ERR_ESCROW_NOT_FOUND));

    let (sender_str, receiver_str, amount_str, _, status, _, _) = record;
    if status != STATUS_PENDING {
        runtime::revert(ApiError::User(ERR_INVALID_STATUS));
    }
    if caller.to_string() != sender_str {
        runtime::revert(ApiError::User(ERR_UNAUTHORIZED));
    }

    let amount = U512::from_dec_str(&amount_str).unwrap_or_revert();
    let fee_bps = read_fee_bps();
    let insurance_fee = amount * U512::from(fee_bps) / U512::from(10_000u64);
    let net_amount = amount - insurance_fee;

    let receiver = AccountHash::from_formatted_str(&receiver_str).unwrap_or_revert();
    let contract_purse = get_dict_uref(CONTRACT_PURSE);
    system::transfer_from_purse_to_account(contract_purse, receiver, net_amount, None)
        .unwrap_or_revert();

    let updated = (
        sender_str,
        receiver_str,
        amount_str,
        service_hash.clone(),
        STATUS_RELEASED,
        0u64,
        0u64,
    );
    storage::dictionary_put(dict, &service_hash, CLValue::from_t(updated).unwrap_or_revert());

    let rep_dict = get_dict_uref(REPUTATION_DICT);
    let rep: (u64, u64, u64, u64, u8) = storage::dictionary_get(rep_dict, &receiver.to_string())
        .unwrap_or_revert()
        .unwrap_or((0, 0, 0, runtime::get_blocktime().into(), 50));
    let (completed, disputed, slashed, _, _) = rep;
    let new_completed = completed + 1;
    let now: u64 = runtime::get_blocktime().into();
    let score = reputation_score(new_completed, disputed, 0);
    storage::dictionary_put(
        rep_dict,
        &receiver.to_string(),
        CLValue::from_t((new_completed, disputed, slashed, now, score)).unwrap_or_revert(),
    );

    emit_event(
        "EscrowReleased",
        &[
            ("service_hash", &service_hash),
            ("amount", &net_amount.to_string()),
        ],
    );
}

/// Refund escrowed funds to the sender when TTL expires.
#[no_mangle]
pub extern "C" fn refund() {
    let service_hash: String = runtime::get_named_arg("service_hash");
    let caller = runtime::get_caller();

    let dict = get_dict_uref(ESCROWS_DICT);
    let record: (String, String, String, String, u8, u64, u64) =
        storage::dictionary_get(dict, &service_hash)
            .unwrap_or_revert()
            .unwrap_or_revert_with(ApiError::User(ERR_ESCROW_NOT_FOUND));

    let (sender_str, _, amount_str, _, status, created_at, ttl) = record;
    if status != STATUS_PENDING {
        runtime::revert(ApiError::User(ERR_INVALID_STATUS));
    }

    let now: u64 = runtime::get_blocktime().into();
    let is_expired = now > created_at + ttl;
    let is_sender = caller.to_string() == sender_str;

    if !is_expired && !is_sender {
        runtime::revert(ApiError::User(ERR_UNAUTHORIZED));
    }

    let amount = U512::from_dec_str(&amount_str).unwrap_or_revert();
    let fee_bps = read_fee_bps();
    let insurance_fee = amount * U512::from(fee_bps) / U512::from(10_000u64);
    let refund_amount = amount - insurance_fee;

    let sender = AccountHash::from_formatted_str(&sender_str).unwrap_or_revert();
    let contract_purse = get_dict_uref(CONTRACT_PURSE);
    system::transfer_from_purse_to_account(contract_purse, sender, refund_amount, None)
        .unwrap_or_revert();

    let reason = if is_expired { "ttl_expired" } else { "sender_request" };
    let new_status = if is_expired {
        STATUS_EXPIRED
    } else {
        STATUS_REFUNDED
    };

    let updated = (
        sender_str,
        String::new(),
        amount_str,
        service_hash.clone(),
        new_status,
        created_at,
        ttl,
    );
    storage::dictionary_put(dict, &service_hash, CLValue::from_t(updated).unwrap_or_revert());

    emit_event(
        "EscrowRefunded",
        &[("service_hash", &service_hash), ("reason", reason)],
    );
}

/// Open a dispute for a pending escrow.
#[no_mangle]
pub extern "C" fn dispute() {
    let service_hash: String = runtime::get_named_arg("service_hash");
    let reason_hash: String = runtime::get_named_arg("reason_hash");
    let caller = runtime::get_caller();

    let dict = get_dict_uref(ESCROWS_DICT);
    let record: (String, String, String, String, u8, u64, u64) =
        storage::dictionary_get(dict, &service_hash)
            .unwrap_or_revert()
            .unwrap_or_revert_with(ApiError::User(ERR_ESCROW_NOT_FOUND));

    let (sender_str, receiver_str, amount_str, _, status, created_at, ttl) = record;
    if status != STATUS_PENDING {
        runtime::revert(ApiError::User(ERR_INVALID_STATUS));
    }

    let updated = (
        sender_str.clone(),
        receiver_str,
        amount_str,
        service_hash.clone(),
        STATUS_DISPUTED,
        created_at,
        ttl,
    );
    storage::dictionary_put(dict, &service_hash, CLValue::from_t(updated).unwrap_or_revert());

    let rep_dict = get_dict_uref(REPUTATION_DICT);
    let rep: (u64, u64, u64, u64, u8) = storage::dictionary_get(rep_dict, &sender_str)
        .unwrap_or_revert()
        .unwrap_or((0, 0, 0, 0, 50));
    let (completed, disputed, slashed, last_active, _) = rep;
    let new_disputed = disputed + 1;
    let score = reputation_score(completed, new_disputed, 0);
    storage::dictionary_put(
        rep_dict,
        &sender_str,
        CLValue::from_t((completed, new_disputed, slashed, last_active, score)).unwrap_or_revert(),
    );

    emit_event(
        "DisputeOpened",
        &[
            ("service_hash", &service_hash),
            ("reason_hash", &reason_hash),
            ("caller", &caller.to_string()),
        ],
    );
}

/// Resolve dispute via 3-of-5 multisig arbitration.
#[no_mangle]
pub extern "C" fn resolve() {
    let service_hash: String = runtime::get_named_arg("service_hash");
    let in_favor_of: String = runtime::get_named_arg("in_favor_of");
    let arbiter_accounts: Vec<String> = runtime::get_named_arg("arbiter_accounts");

    let dict = get_dict_uref(ESCROWS_DICT);
    let record: (String, String, String, String, u8, u64, u64) =
        storage::dictionary_get(dict, &service_hash)
            .unwrap_or_revert()
            .unwrap_or_revert_with(ApiError::User(ERR_ESCROW_NOT_FOUND));

    let (sender_str, receiver_str, amount_str, _, status, created_at, ttl) = record;
    if status != STATUS_DISPUTED {
        runtime::revert(ApiError::User(ERR_ALREADY_DISPUTED));
    }

    let threshold_uref = runtime::get_key(ARBITER_THRESHOLD)
        .unwrap_or_revert()
        .into_uref()
        .unwrap_or_revert();
    let threshold: u8 = storage::read(threshold_uref)
        .unwrap_or_revert()
        .unwrap_or(3);

    if arbiter_accounts.len() < threshold as usize {
        runtime::revert(ApiError::User(ERR_INSUFFICIENT_SIGS));
    }

    let arb_uref = runtime::get_key(ARBITER_LIST)
        .unwrap_or_revert()
        .into_uref()
        .unwrap_or_revert();
    let registered: Vec<String> = storage::read(arb_uref).unwrap_or_revert().unwrap_or_default();

    let mut valid_count = 0u8;
    for acct in &arbiter_accounts {
        if registered.contains(acct) {
            valid_count += 1;
        }
    }
    if valid_count < threshold {
        runtime::revert(ApiError::User(ERR_INVALID_SIGNATURE));
    }

    let amount = U512::from_dec_str(&amount_str).unwrap_or_revert();
    let fee_bps = read_fee_bps();
    let insurance_fee = amount * U512::from(fee_bps) / U512::from(10_000u64);
    let net_amount = amount - insurance_fee;

    let contract_purse = get_dict_uref(CONTRACT_PURSE);
    let winner = if in_favor_of == "sender" {
        AccountHash::from_formatted_str(&sender_str).unwrap_or_revert()
    } else {
        AccountHash::from_formatted_str(&receiver_str).unwrap_or_revert()
    };

    system::transfer_from_purse_to_account(contract_purse, winner, net_amount, None)
        .unwrap_or_revert();

    let updated = (
        sender_str,
        receiver_str,
        amount_str,
        service_hash.clone(),
        STATUS_RESOLVED,
        created_at,
        ttl,
    );
    storage::dictionary_put(dict, &service_hash, CLValue::from_t(updated).unwrap_or_revert());

    emit_event(
        "DisputeResolved",
        &[
            ("service_hash", &service_hash),
            ("winner", &in_favor_of),
            ("arbiter_count", &valid_count.to_string()),
        ],
    );
}

/// Update the insurance fee (installer only, max 10%).
#[no_mangle]
pub extern "C" fn configure_fee() {
    let caller = runtime::get_caller();
    let installer = read_installer();
    if caller != installer {
        runtime::revert(ApiError::User(ERR_UNAUTHORIZED));
    }

    let new_fee_bps: u64 = runtime::get_named_arg("new_fee_bps");
    if new_fee_bps > MAX_FEE_BPS {
        runtime::revert(ApiError::User(ERR_FEE_TOO_HIGH));
    }

    let uref = runtime::get_key(FEE_BPS_KEY)
        .unwrap_or_revert()
        .into_uref()
        .unwrap_or_revert();
    storage::write(uref, new_fee_bps);
}

/// Freeze insurance pool payouts (installer or 3-of-5 arbiters).
#[no_mangle]
pub extern "C" fn emergency_freeze() {
    let caller = runtime::get_caller();
    let installer = read_installer();
    if caller != installer {
        runtime::revert(ApiError::User(ERR_UNAUTHORIZED));
    }

    let uref = runtime::get_key(POOL_FROZEN_KEY)
        .unwrap_or_revert()
        .into_uref()
        .unwrap_or_revert();
    storage::write(uref, true);

    emit_event("InsurancePoolFrozen", &[("by", &caller.to_string())]);
}

/// Read escrow record by service hash.
#[no_mangle]
pub extern "C" fn get_escrow() {
    let service_hash: String = runtime::get_named_arg("service_hash");
    let dict = get_dict_uref(ESCROWS_DICT);
    let record: (String, String, String, String, u8, u64, u64) =
        storage::dictionary_get(dict, &service_hash)
            .unwrap_or_revert()
            .unwrap_or_revert_with(ApiError::User(ERR_ESCROW_NOT_FOUND));
    let result = CLValue::from_t(record).unwrap_or_revert();
    runtime::ret(result);
}

/// Read reputation by agent account hash.
#[no_mangle]
pub extern "C" fn get_reputation() {
    let agent: String = runtime::get_named_arg("agent");
    let dict = get_dict_uref(REPUTATION_DICT);
    let rep: (u64, u64, u64, u64, u8) = storage::dictionary_get(dict, &agent)
        .unwrap_or_revert()
        .unwrap_or((0, 0, 0, 0, 50));
    runtime::ret(CLValue::from_t(rep).unwrap_or_revert());
}

// ── Contract installation ────────────────────────────────────────────

#[no_mangle]
pub extern "C" fn call() {
    let installer = runtime::get_caller();

    let escrow_dict = storage::new_dictionary(ESCROWS_DICT).unwrap_or_revert();
    let rep_dict = storage::new_dictionary(REPUTATION_DICT).unwrap_or_revert();
    let contract_purse = system::create_purse();
    let insurance_purse = system::create_purse();
    let fee_bps_uref = storage::new_uref(DEFAULT_FEE_BPS);
    let frozen_uref = storage::new_uref(false);
    let threshold_uref = storage::new_uref(3u8);
    let arbiter_uref = storage::new_uref(Vec::<String>::new());

    let mut named_keys = NamedKeys::new();
    named_keys.insert(ESCROWS_DICT.into(), escrow_dict.into());
    named_keys.insert(REPUTATION_DICT.into(), rep_dict.into());
    named_keys.insert(CONTRACT_PURSE.into(), contract_purse.into());
    named_keys.insert(INSURANCE_PURSE.into(), insurance_purse.into());
    named_keys.insert(FEE_BPS_KEY.into(), fee_bps_uref.into());
    named_keys.insert(POOL_FROZEN_KEY.into(), frozen_uref.into());
    named_keys.insert(ARBITER_THRESHOLD.into(), threshold_uref.into());
    named_keys.insert(ARBITER_LIST.into(), arbiter_uref.into());
    named_keys.insert(INSTALLER_KEY.into(), Key::Account(installer));

    let mut entry_points = EntryPoints::new();
    entry_points.add_entry_point(EntryPoint::new(
        "escrow",
        vec![
            Parameter::new("receiver", CLType::ByteArray(32)),
            Parameter::new("amount", CLType::U512),
            Parameter::new("service_hash", CLType::String),
            Parameter::new("ttl", CLType::U64),
        ],
        CLType::Unit,
        EntryPointAccess::Public,
        EntryPointType::Contract,
    ));
    entry_points.add_entry_point(EntryPoint::new(
        "release",
        vec![Parameter::new("service_hash", CLType::String)],
        CLType::Unit,
        EntryPointAccess::Public,
        EntryPointType::Contract,
    ));
    entry_points.add_entry_point(EntryPoint::new(
        "refund",
        vec![Parameter::new("service_hash", CLType::String)],
        CLType::Unit,
        EntryPointAccess::Public,
        EntryPointType::Contract,
    ));
    entry_points.add_entry_point(EntryPoint::new(
        "dispute",
        vec![
            Parameter::new("service_hash", CLType::String),
            Parameter::new("reason_hash", CLType::String),
        ],
        CLType::Unit,
        EntryPointAccess::Public,
        EntryPointType::Contract,
    ));
    entry_points.add_entry_point(EntryPoint::new(
        "resolve",
        vec![
            Parameter::new("service_hash", CLType::String),
            Parameter::new("in_favor_of", CLType::String),
            Parameter::new("arbiter_accounts", CLType::List(Box::new(CLType::String))),
        ],
        CLType::Unit,
        EntryPointAccess::Public,
        EntryPointType::Contract,
    ));
    entry_points.add_entry_point(EntryPoint::new(
        "configure_fee",
        vec![Parameter::new("new_fee_bps", CLType::U64)],
        CLType::Unit,
        EntryPointAccess::Public,
        EntryPointType::Contract,
    ));
    entry_points.add_entry_point(EntryPoint::new(
        "emergency_freeze",
        vec![],
        CLType::Unit,
        EntryPointAccess::Public,
        EntryPointType::Contract,
    ));
    entry_points.add_entry_point(EntryPoint::new(
        "get_escrow",
        vec![Parameter::new("service_hash", CLType::String)],
        CLType::Any,
        EntryPointAccess::Public,
        EntryPointType::Contract,
    ));
    entry_points.add_entry_point(EntryPoint::new(
        "get_reputation",
        vec![Parameter::new("agent", CLType::String)],
        CLType::Any,
        EntryPointAccess::Public,
        EntryPointType::Contract,
    ));

    let (contract_hash, _) = storage::new_contract(
        entry_points,
        Some(named_keys),
        Some("escrow_package_hash".into()),
        Some("escrow_access_uref".into()),
    );
    runtime::put_key("escrow_contract", contract_hash.into());
}
