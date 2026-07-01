#![no_std]
#![no_main]
extern crate alloc;

use alloc::string::String;
use alloc::vec::Vec;
use alloc::vec;

use casper_contract::contract_api::{runtime, storage, system};
use casper_contract::unwrap_or_revert::UnwrapOrRevert;

use casper_types::{
    ApiError, CLType, CLValue, EntityEntryPoint, EntryPointAccess, EntryPointType,
    EntryPoints, Parameter, URef, U512, Key,
};
use casper_types::account::AccountHash;
use casper_types::contracts::NamedKeys;
use casper_types::EntryPointPayment;

const CONTRACT_HASH_KEY: &str = "contract_hash";
const DICT_POLICIES: &str = "policies";
const DICT_CLAIMS: &str = "claims";
const KEY_BASE_RATE: &str = "base_rate_bps";
const KEY_POOL_BALANCE: &str = "pool_balance";
const KEY_TOTAL_CLAIMED: &str = "total_claimed";
const KEY_TOTAL_BURNED: &str = "total_burned";
const KEY_INSTALLER: &str = "installer";

const ERR_NOT_INSTALLER: u16 = 1;
const ERR_INVALID_AMOUNT: u16 = 2;
const ERR_INSUFFICIENT_POOL: u16 = 3;
const ERR_COOLDOWN: u16 = 4;
const ERR_POLICY_EXISTS: u16 = 5;
const ERR_POLICY_NOT_FOUND: u16 = 6;
const ERR_MAX_COVERAGE: u16 = 7;
const ERR_CLAIM_TOO_LARGE: u16 = 8;

const COOLDOWN_SECONDS: u64 = 86400;
const MAX_COVERAGE_BPS: u64 = 8000;

fn get_installer() -> AccountHash {
    let key: Key = runtime::get_key(KEY_INSTALLER).unwrap_or_revert();
    key.into_account_hash().unwrap_or_revert()
}

fn assert_installer() {
    if runtime::get_caller() != get_installer() {
        runtime::revert(ApiError::User(ERR_NOT_INSTALLER));
    }
}

fn get_uref(name: &str) -> URef {
    runtime::get_key(name).unwrap_or_revert().into_uref().unwrap_or_revert()
}

fn get_dict(name: &str) -> URef {
    runtime::get_key(name).unwrap_or_revert().into_uref().unwrap_or_revert()
}

fn policy_key(policy_id: &str) -> String {
    policy_id.to_string()
}

#[no_mangle]
pub extern "C" fn deposit() {
    let amount: U512 = runtime::get_named_arg("amount");
    if amount == U512::zero() {
        runtime::revert(ApiError::User(ERR_INVALID_AMOUNT));
    }

    let purse = system::get_main_purse();
    system::transfer_from_purse_to_purse(purse, purse, amount, None).unwrap_or_revert();

    let balance_key = get_uref(KEY_POOL_BALANCE);
    let current: U512 = storage::read(balance_key).unwrap_or_default().unwrap_or(U512::zero());
    storage::write(balance_key, current + amount);
}

#[no_mangle]
pub extern "C" fn claim() {
    let escrow_id: String = runtime::get_named_arg("escrow_id");
    let amount: U512 = runtime::get_named_arg("amount");
    let _evidence: String = runtime::get_named_arg("evidence");

    let caller = runtime::get_caller();
    let caller_str = caller.to_string();

    let claims_dict = get_dict(DICT_CLAIMS);
    let last_claim: Option<u64> = storage::dictionary_get(claims_dict, &caller_str).unwrap_or_default();
    let now: u64 = runtime::get_blocktime().into();

    if let Some(last) = last_claim {
        if now < last + COOLDOWN_SECONDS {
            runtime::revert(ApiError::User(ERR_COOLDOWN));
        }
    }

    let pool_balance_key = get_uref(KEY_POOL_BALANCE);
    let pool_balance: U512 = storage::read(pool_balance_key).unwrap_or_default().unwrap_or(U512::zero());

    let max_coverage = (pool_balance * U512::from(MAX_COVERAGE_BPS)) / U512::from(10000);
    if amount > max_coverage {
        runtime::revert(ApiError::User(ERR_MAX_COVERAGE));
    }

    let total_claimed_key = get_uref(KEY_TOTAL_CLAIMED);
    let total_claimed: U512 = storage::read(total_claimed_key).unwrap_or_default().unwrap_or(U512::zero());

    if amount > pool_balance {
        runtime::revert(ApiError::User(ERR_CLAIM_TOO_LARGE));
    }

    let purse = system::get_main_purse();
    system::transfer_from_purse_to_account(purse, caller, amount, None).unwrap_or_revert();

    storage::write(pool_balance_key, pool_balance - amount);
    storage::write(total_claimed_key, total_claimed + amount);
    storage::dictionary_put(claims_dict, &caller_str, now);
}

#[no_mangle]
pub extern "C" fn set_premium_rate() {
    assert_installer();
    let rate_bps: u64 = runtime::get_named_arg("rate_bps");
    let rate_uref = get_uref(KEY_BASE_RATE);
    storage::write(rate_uref, rate_bps);
}

#[no_mangle]
pub extern "C" fn calculate_premium() {
    let amount: u64 = runtime::get_named_arg("amount");
    let risk_score: u64 = runtime::get_named_arg("risk_score");

    let rate_uref = get_uref(KEY_BASE_RATE);
    let base_rate: u64 = storage::read(rate_uref).unwrap_or_default().unwrap_or(0);

    let multiplier = 100 + risk_score;
    let premium = (base_rate * amount * multiplier) / (10000 * 100);

    let cl_value = CLValue::from_t(premium).unwrap_or_revert();
    runtime::ret(cl_value);
}

#[no_mangle]
pub extern "C" fn burn_penalty() {
    assert_installer();
    let amount: U512 = runtime::get_named_arg("amount");
    if amount == U512::zero() {
        runtime::revert(ApiError::User(ERR_INVALID_AMOUNT));
    }

    let purse = system::get_main_purse();
    let burn_purse = system::create_purse();
    system::transfer_from_purse_to_purse(purse, burn_purse, amount, None).unwrap_or_revert();

    let burned_key = get_uref(KEY_TOTAL_BURNED);
    let current: U = storage::read(burned_key).unwrap_or_default().unwrap_or(U512::zero());
    storage::write(burned_key, current + amount);
}

#[no_mangle]
pub extern "C" fn get_pool_stats() {
    let pool_balance: U512 = storage::read(get_uref(KEY_POOL_BALANCE)).unwrap_or_default().unwrap_or(U512::zero());
    let total_claimed: U512 = storage::read(get_uref(KEY_TOTAL_CLAIMED)).unwrap_or_default().unwrap_or(U512::zero());
    let total_burned: U512 = storage::read(get_uref(KEY_TOTAL_BURNED)).unwrap_or_default().unwrap_or(U512::zero());
    let base_rate: u64 = storage::read(get_uref(KEY_BASE_RATE)).unwrap_or_default().unwrap_or(0);

    let stats = (
        pool_balance,
        total_claimed,
        total_burned,
        base_rate,
    );

    let cl_value = CLValue::from_t(stats).unwrap_or_revert();
    runtime::ret(cl_value);
}

#[no_mangle]
pub extern "C" fn call() {
    let mut named_keys = NamedKeys::new();

    let base_rate_uref = storage::new_uref(0u64);
    let pool_balance_uref = storage::new_uref(U512::zero());
    let total_claimed_uref = storage::new_uref(U512::zero());
    let total_burned_uref = storage::new_uref(U512::zero());
    let policies_dict = storage::new_dictionary(DICT_POLICIES).unwrap_or_revert();
    let claims_dict = storage::new_dictionary(DICT_CLAIMS).unwrap_or_revert();

    named_keys.insert(KEY_BASE_RATE.to_string(), base_rate_uref.into());
    named_keys.insert(KEY_POOL_BALANCE.to_string(), pool_balance_uref.into());
    named_keys.insert(KEY_TOTAL_CLAIMED.to_string(), total_claimed_uref.into());
    named_keys.insert(KEY_TOTAL_BURNED.to_string(), total_burned_uref.into());
    named_keys.insert(DICT_POLICIES.to_string(), policies_dict.into());
    named_keys.insert(DICT_CLAIMS.to_string(), claims_dict.into());
    named_keys.insert(KEY_INSTALLER.to_string(), Key::Account(runtime::get_caller()));

    let mut entry_points = EntryPoints::new();

    entry_points.add_entry_point(EntityEntryPoint::new(
        "deposit".to_string(),
        vec![Parameter::new("amount", CLType::U512)],
        CLType::Unit,
        EntryPointAccess::Public,
        EntryPointType::Called,
        EntryPointPayment::Caller,
    ));

    entry_points.add_entry_point(EntityEntryPoint::new(
        "claim".to_string(),
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
        "set_premium_rate".to_string(),
        vec![Parameter::new("rate_bps", CLType::U64)],
        CLType::Unit,
        EntryPointAccess::Public,
        EntryPointType::Called,
        EntryPointPayment::Caller,
    ));

    entry_points.add_entry_point(EntityEntryPoint::new(
        "calculate_premium".to_string(),
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
        "burn_penalty".to_string(),
        vec![Parameter::new("amount", CLType::U512)],
        CLType::Unit,
        EntryPointAccess::Public,
        EntryPointType::Called,
        EntryPointPayment::Caller,
    ));

    entry_points.add_entry_point(EntityEntryPoint::new(
        "get_pool_stats".to_string(),
        Vec::new(),
        CLType::Tuple2(Box::new(CLType::U512), Box::new(CLType::U512)),
        EntryPointAccess::Public,
        EntryPointType::Called,
        EntryPointPayment::Caller,
    ));

    let (contract_hash, _version) = storage::new_contract(
        entry_points,
        Some(named_keys),
        Some("dynamic_insurance_package".to_string()),
        Some("dynamic_insurance_access_uref".to_string()),
    );

    runtime::put_key(CONTRACT_HASH_KEY, contract_hash.into());
}