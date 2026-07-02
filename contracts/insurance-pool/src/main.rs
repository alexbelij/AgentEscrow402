#![no_std]
#![no_main]

extern crate alloc;

use alloc::format;
use alloc::string::{String, ToString};
use alloc::vec;
use alloc::vec::Vec;

use casper_contract::contract_api::{runtime, storage, system};
use casper_contract::unwrap_or_revert::UnwrapOrRevert;
use casper_types::account::AccountHash;
use casper_types::contracts::NamedKeys;
use casper_types::{EntryPointPayment, 
    ApiError, CLType, CLValue, EntityEntryPoint, EntryPointAccess, EntryPointType, EntryPoints, Key,
    Parameter, URef, U512,
};

// Constants
const CONTRACT_PURSE: &str = "insurance_contract_purse";
const DICT_CLAIMS: &str = "claims";
const KEY_PREMIUM_RATE_BPS: &str = "premium_rate_bps";
const KEY_TOTAL_CLAIMED: &str = "total_claimed";
const KEY_INSTALLER: &str = "installer";

// Error codes
const ERR_NOT_INSTALLER: u16 = 1;
const ERR_INVALID_AMOUNT: u16 = 2;
const ERR_INSUFFICIENT_POOL_FUNDS: u16 = 3;
const ERR_COOLDOWN: u16 = 4;
const ERR_MAX_COVERAGE_EXCEEDED: u16 = 5;
const ERR_CLAIM_AMOUNT_TOO_LARGE: u16 = 6;
const ERR_ACCOUNT_HASH_PARSE: u16 = 7;

const COOLDOWN_SECONDS: u64 = 86400; // 24 hours
const MAX_COVERAGE_BPS: u64 = 8000; // 80% of pool balance

/// Dictionary value type for claims: (last_claim_timestamp, total_claims_count, last_escrow_id)
/// This adheres to the rule of max 3 elements per tuple.
type ClaimsRecord = (u64, u64, String);

// Helper functions (storage access)
fn get_installer() -> AccountHash {
    let key: Key = runtime::get_key(KEY_INSTALLER).unwrap_or_revert();
    match key { Key::Account(hash) => hash, _ => runtime::revert(ApiError::User(ERR_ACCOUNT_HASH_PARSE)) }
}

fn assert_installer() {
    if runtime::get_caller() != get_installer() {
        runtime::revert(ApiError::User(ERR_NOT_INSTALLER));
    }
}

fn get_uref(name: &str) -> URef {
    runtime::get_key(name)
        .unwrap_or_revert()
        .into_uref()
        .unwrap_or_revert()
}

fn get_dict_uref(name: &str) -> URef {
    runtime::get_key(name)
        .unwrap_or_revert()
        .into_uref()
        .unwrap_or_revert()
}

// Entry points

#[no_mangle]
pub extern "C" fn deposit() {
    let source_purse: URef = runtime::get_named_arg("source_purse");
    let amount: U512 = runtime::get_named_arg("amount");

    if amount == U512::zero() {
        runtime::revert(ApiError::User(ERR_INVALID_AMOUNT));
    }

    let contract_purse = get_uref(CONTRACT_PURSE);
    system::transfer_from_purse_to_purse(source_purse, contract_purse, amount, None).unwrap_or_revert();
}

#[no_mangle]
pub extern "C" fn withdraw() {
    assert_installer();
    let amount: U512 = runtime::get_named_arg("amount");

    if amount == U512::zero() {
        runtime::revert(ApiError::User(ERR_INVALID_AMOUNT));
    }

    let contract_purse = get_uref(CONTRACT_PURSE);
    let pool_balance = system::get_purse_balance(contract_purse).unwrap_or_revert();

    if amount > pool_balance {
        runtime::revert(ApiError::User(ERR_INSUFFICIENT_POOL_FUNDS));
    }

    let installer_account = get_installer();
    system::transfer_from_purse_to_account(contract_purse, installer_account, amount, None).unwrap_or_revert();
}

#[no_mangle]
pub extern "C" fn claim() {
    let escrow_id: String = runtime::get_named_arg("escrow_id");
    let amount: U512 = runtime::get_named_arg("amount");
    let _evidence: String = runtime::get_named_arg("evidence"); // Evidence is received but not stored/processed in this contract version

    let caller = runtime::get_caller();
    let caller_str = caller.to_string();

    let claims_dict = get_dict_uref(DICT_CLAIMS);
    let mut claims_record: ClaimsRecord = storage::dictionary_get(claims_dict, &caller_str)
        .unwrap_or_revert()
        .unwrap_or((0, 0, String::new())); // Default if no previous claims

    let now: u64 = runtime::get_blocktime().into();

    // Check cooldown period
    if now < claims_record.0.saturating_add(COOLDOWN_SECONDS) {
        runtime::revert(ApiError::User(ERR_COOLDOWN));
    }

    let contract_purse = get_uref(CONTRACT_PURSE);
    let pool_balance = system::get_purse_balance(contract_purse).unwrap_or_revert();

    // Check if claim amount exceeds maximum coverage (percentage of pool)
    let max_coverage = (pool_balance.saturating_mul(U512::from(MAX_COVERAGE_BPS))) / U512::from(10000);
    if amount > max_coverage {
        runtime::revert(ApiError::User(ERR_MAX_COVERAGE_EXCEEDED));
    }

    // Check if claim amount exceeds current pool balance
    if amount > pool_balance {
        runtime::revert(ApiError::User(ERR_CLAIM_AMOUNT_TOO_LARGE));
    }

    // Transfer funds from contract purse to caller's main purse
    system::transfer_from_purse_to_account(contract_purse, caller, amount, None).unwrap_or_revert();

    // Update total claimed amount
    let total_claimed_uref = get_uref(KEY_TOTAL_CLAIMED);
    let current_total_claimed: U512 = storage::read(total_claimed_uref)
        .unwrap_or_revert()
        .unwrap_or(U512::zero());
    storage::write(total_claimed_uref, current_total_claimed.saturating_add(amount));

    // Update claims record for the caller
    claims_record.0 = now; // last_claim_timestamp
    claims_record.1 = claims_record.1.saturating_add(1); // total_claims_count
    claims_record.2 = escrow_id; // last_escrow_id
    storage::dictionary_put(claims_dict, &caller_str, claims_record);
}

#[no_mangle]
pub extern "C" fn set_premium_rate() {
    assert_installer();
    let rate_bps: u64 = runtime::get_named_arg("rate_bps");
    let rate_uref = get_uref(KEY_PREMIUM_RATE_BPS);
    storage::write(rate_uref, rate_bps);
}

#[no_mangle]
pub extern "C" fn calculate_premium() {
    let amount: u64 = runtime::get_named_arg("amount");
    let risk_score: u64 = runtime::get_named_arg("risk_score");

    let rate_uref = get_uref(KEY_PREMIUM_RATE_BPS);
    let base_rate: u64 = storage::read(rate_uref)
        .unwrap_or_revert()
        .unwrap_or(0);

    // Simple premium calculation: base_rate * amount * (100 + risk_score) / (10000 * 100)
    // risk_score is assumed to be a percentage modifier, e.g., 0-100.
    // 10000 for BPS (base_rate), 100 for risk_score percentage.
    let multiplier = 100u64.saturating_add(risk_score);
    let premium = (base_rate.saturating_mul(amount).saturating_mul(multiplier)) / (10000u64.saturating_mul(100));

    runtime::ret(CLValue::from_t(premium).unwrap_or_revert());
}

#[no_mangle]
pub extern "C" fn get_pool_stats() {
    let contract_purse = get_uref(CONTRACT_PURSE);
    let pool_balance: U512 = system::get_purse_balance(contract_purse).unwrap_or_revert();
    
    let total_claimed: U512 = storage::read(get_uref(KEY_TOTAL_CLAIMED))
        .unwrap_or_revert()
        .unwrap_or(U512::zero());
    
    let premium_rate_bps: u64 = storage::read(get_uref(KEY_PREMIUM_RATE_BPS))
        .unwrap_or_revert()
        .unwrap_or(0);

    let stats = (
        pool_balance,
        total_claimed,
        premium_rate_bps,
    );

    runtime::ret(CLValue::from_t(stats).unwrap_or_revert());
}

#[no_mangle]
pub extern "C" fn call() {
    let installer = runtime::get_caller();

    let contract_purse = system::create_purse();
    let claims_dict = storage::new_dictionary(DICT_CLAIMS).unwrap_or_revert();
    let premium_rate_uref = storage::new_uref(0u64); // Default premium rate
    let total_claimed_uref = storage::new_uref(U512::zero());

    let mut named_keys = NamedKeys::new();
    named_keys.insert(CONTRACT_PURSE.into(), contract_purse.into());
    named_keys.insert(DICT_CLAIMS.into(), claims_dict.into());
    named_keys.insert(KEY_PREMIUM_RATE_BPS.into(), premium_rate_uref.into());
    named_keys.insert(KEY_TOTAL_CLAIMED.into(), total_claimed_uref.into());
    named_keys.insert(KEY_INSTALLER.into(), Key::Account(installer));

    let mut entry_points = EntryPoints::new();

    entry_points.add_entry_point(EntityEntryPoint::new(
        "deposit",
        vec![
            Parameter::new("source_purse", CLType::URef),
            Parameter::new("amount", CLType::U512),
        ],
        CLType::Unit,
        EntryPointAccess::Public,
        EntryPointType::Called,
        EntryPointPayment::Caller,
    ));

    entry_points.add_entry_point(EntityEntryPoint::new(
        "withdraw",
        vec![Parameter::new("amount", CLType::U512)],
        CLType::Unit,
        EntryPointAccess::Public,
        EntryPointType::Called,
        EntryPointPayment::Caller,
    ));

    entry_points.add_entry_point(EntityEntryPoint::new(
        "claim",
        vec![
            Parameter::new("escrow_id", CLType::String),
            Parameter::new("amount", CLType::U512),
            Parameter::new("evidence", CLType::String),
        ],
        CLType::Unit,
        EntryPointAccess::Public,
        EntryPointType::Called,
        EntryPointPayment::Caller,
    ));

    entry_points.add_entry_point(EntityEntryPoint::new(
        "set_premium_rate",
        vec![Parameter::new("rate_bps", CLType::U64)],
        CLType::Unit,
        EntryPointAccess::Public,
        EntryPointType::Called,
        EntryPointPayment::Caller,
    ));

    entry_points.add_entry_point(EntityEntryPoint::new(
        "calculate_premium",
        vec![
            Parameter::new("amount", CLType::U64),
            Parameter::new("risk_score", CLType::U64),
        ],
        CLType::U64,
        EntryPointAccess::Public,
        EntryPointType::Called,
        EntryPointPayment::Caller,
    ));

    entry_points.add_entry_point(EntityEntryPoint::new(
        "get_pool_stats",
        Vec::new(),
        CLType::Any,
        EntryPointAccess::Public,
        EntryPointType::Called,
        EntryPointPayment::Caller,
    ));

    let (contract_hash, _version) = storage::new_contract(
        entry_points,
        Some(named_keys),
        Some("insurance_pool_package_hash".into()),
        Some("insurance_pool_access_uref".into()),
        None, // No initial entry point
    );

    runtime::put_key("insurance_pool_contract", contract_hash.into());
}