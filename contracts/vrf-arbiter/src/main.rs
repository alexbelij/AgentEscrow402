#![no_std]
#![no_main]
extern crate alloc;

use alloc::string::String;
use alloc::vec::Vec;
use alloc::vec;
use casper_contract::contract_api::{runtime, storage, system};
use casper_types::{ApiError, CLType, CLValue, EntityEntryPoint, EntryPointAccess, EntryPointType, EntryPoints, Parameter, URef, U512, Key};
use casper_types::account::AccountHash;
use casper_types::contracts::NamedKeys;
use casper_types::EntryPointPayment;
use casper_contract::unwrap_or_revert::UnwrapOrRevert;

const ARBITERS_DICT: &str = "arbiters_dict";
const ELECTIONS_DICT: &str = "elections_dict";
const ARBITER_IDS_DICT: &str = "arbiter_ids_dict";
const NONCE_KEY: &str = "nonce";
const INSTALLER_KEY: &str = "installer";

const ERR_NOT_INSTALLER: u16 = 1;
const ERR_ARBITER_EXISTS: u16 = 2;
const ERR_ARBITER_NOT_FOUND: u16 = 3;
const ERR_INVALID_STAKE: u16 = 4;
const ERR_ELECTION_EXISTS: u16 = 5;
const ERR_ELECTION_NOT_FOUND: u16 = 6;
const ERR_NOT_SELECTED: u16 = 7;
const ERR_ALREADY_VERDICT: u16 = 8;
const ERR_INSUFFICIENT_STAKE: u16 = 9;

fn get_installer() -> AccountHash {
    let key: Key = runtime::get_key(INSTALLER_KEY).unwrap_or_revert();
    key.into_account().unwrap_or_revert()
}

fn assert_installer() {
    if runtime::get_caller() != get_installer() {
        runtime::revert(ApiError::User(ERR_NOT_INSTALLER));
    }
}

fn get_dict_uref(name: &str) -> URef {
    runtime::get_key(name).unwrap_or_revert().into_uref().unwrap_or_revert()
}

#[no_mangle]
pub extern "C" fn register_arbiter() {
    let arbiter_id: String = runtime::get_named_arg("arbiter_id");
    let stake: U512 = runtime::get_named_arg("stake");
    
    if stake == U512::zero() {
        runtime::revert(ApiError::User(ERR_INVALID_STAKE));
    }
    
    let caller = runtime::get_caller();
    let arbiters_uref = get_dict_uref(ARBITERS_DICT);
    let ids_uref = get_dict_uref(ARBITER_IDS_DICT);
    
    if storage::dictionary_get::<()>(arbiters_uref, &arbiter_id).unwrap_or_revert().is_some() {
        runtime::revert(ApiError::User(ERR_ARBITER_EXISTS));
    }
    
    let owner_str = caller.to_string();
    let stake_u64: u64 = stake.as_u64();
    let block_time = runtime::get_blocktime().into();
    
    let record = (
        (arbiter_id.clone(), owner_str, stake_u64),
        (0u64, 0u64, block_time),
        (1u64, 100u64, 0u64)
    );
    
    storage::dictionary_put(arbiters_uref, &arbiter_id, record);
    storage::dictionary_put(ids_uref, &caller.to_string(), arbiter_id);
}

#[no_mangle]
pub extern "C" fn elect_arbiter() {
    let dispute_id: String = runtime::get_named_arg("dispute_id");
    let count: u64 = runtime::get_named_arg("count");
    
    let elections_uref = get_dict_uref(ELECTIONS_DICT);
    
    if storage::dictionary_get::<()>(elections_uref, &dispute_id).unwrap_or_revert().is_some() {
        runtime::revert(ApiError::User(ERR_ELECTION_EXISTS));
    }
    
    let arbiters_uref = get_dict_uref(ARBITERS_DICT);
    let all_ids_uref = get_dict_uref(ARBITER_IDS_DICT);
    
    let block_time: u64 = runtime::get_blocktime().into();
    let nonce_key = runtime::get_key(NONCE_KEY).unwrap_or_revert().into_uref().unwrap_or_revert();
    let nonce: u64 = storage::read(nonce_key).unwrap_or_revert().unwrap_or(0u64);
    
    let seed_input = format!("{}{}{}", block_time, dispute_id, nonce);
    let hash = runtime::blake2b(seed_input.as_bytes());
    let seed = hex::encode(&hash[..16]);
    
    let mut selected = String::new();
    let ids_uref = get_dict_uref(ARBITER_IDS_DICT);
    let ids_count: u64 = storage::dictionary_get(ids_uref, "count").unwrap_or_revert().unwrap_or(0u64);
    
    if ids_count > 0 {
        let hash_val = u64::from_le_bytes([
            hash[0], hash[1], hash[2], hash[3],
            hash[4], hash[5], hash[6], hash[7]
        ]);
        let idx = hash_val % ids_count;
        let id_key = format!("id_{}", idx);
        if let Some(id) = storage::dictionary_get::<String>(ids_uref, &id_key).unwrap_or_revert() {
            selected = id;
        }
    }
    
    let record = (
        (dispute_id.clone(), seed.clone(), count),
        (selected.clone(), String::new(), 0u64),
    );
    
    storage::dictionary_put(elections_uref, &dispute_id, record);
    storage::write(nonce_key, nonce + 1);
}

#[no_mangle]
pub extern "C" fn submit_verdict() {
    let dispute_id: String = runtime::get_named_arg("dispute_id");
    let verdict: u64 = runtime::get_named_arg("verdict");
    let evidence: String = runtime::get_named_arg("evidence");
    
    let caller = runtime::get_caller();
    let elections_uref = get_dict_uref(ELECTIONS_DICT);
    
    let election: ((String, String, u64), (String, String, u64)) = 
        storage::dictionary_get(elections_uref, &dispute_id).unwrap_or_revert()
            .unwrap_or_else(|| runtime::revert(ApiError::User(ERR_ELECTION_NOT_FOUND)));
    
    let arbiters_uref = get_dict_uref(ARBITERS_DICT);
    let ids_uref = get_dict_uref(ARBITER_IDS_DICT);
    let caller_id: String = storage::dictionary_get(ids_uref, &caller.to_string())
        .unwrap_or_revert()
        .unwrap_or_else(|| runtime::revert(ApiError::User(ERR_ARBITER_NOT_FOUND)));
    
    let selected = (election.1).0;
    if caller_id != selected {
        runtime::revert(ApiError::User(ERR_NOT_SELECTED));
    }
    
    let verdict_str = format!("{}:{}", verdict, evidence);
    let updated = (
        (dispute_id.clone(), (election.0).1, (election.0).2),
        (selected, verdict_str, 1u64),
    );
    
    storage::dictionary_put(elections_uref, &dispute_id, updated);
}

#[no_mangle]
pub extern "C" fn slash_arbiter() {
    assert_installer();
    
    let arbiter_id: String = runtime::get_named_arg("arbiter_id");
    let amount: U512 = runtime::get_named_arg("amount");
    
    let arbiters_uref = get_dict_uref(ARBITERS_DICT);
    
    let record: ((String, String, u64), (u64, u64, u64), (u64, u64, u64)) = 
        storage::dictionary_get(arbiters_uref, &arbiter_id).unwrap_or_revert()
            .unwrap_or_else(|| runtime::revert(ApiError::User(ERR_ARBITER_NOT_FOUND)));
    
    let amount_u64: u64 = amount.as_u64();
    let updated = (
        (record.0).0,
        (record.0).1,
        (record.0).2,
        ((record.1).0, (record.1).1 + amount_u64, (record.1).2),
        ((record.2).0, if (record.2).1 > amount_u64 { (record.2).1 - amount_u64 } else { 0 }, (record.2).2)
    );
    
    let flat = (
        ((record.0).0, (record.0).1, (record.0).2),
        ((record.1).0, (record.1).1 + amount_u64, (record.1).2),
        ((record.2).0, if (record.2).1 > amount_u64 { (record.2).1 - amount_u64 } else { 0 }, (record.2).2)
    );
    
    storage::dictionary_put(arbiters_uref, &arbiter_id, flat);
}

#[no_mangle]
pub extern "C" fn get_arbiter() {
    let arbiter_id: String = runtime::get_named_arg("arbiter_id");
    let arbiters_uref = get_dict_uref(ARBITERS_DICT);
    
    let record: ((String, String, u64), (u64, u64, u64), (u64, u64, u64)) = 
        storage::dictionary_get(arbiters_uref, &arbiter_id).unwrap_or_revert()
            .unwrap_or_else(|| runtime::revert(ApiError::User(ERR_ARBITER_NOT_FOUND)));
    
    runtime::ret(CLValue::from_t(record).unwrap_or_revert());
}

#[no_mangle]
pub extern "C" fn get_election() {
    let dispute_id: String = runtime::get_named_arg("dispute_id");
    let elections_uref = get_dict_uref(ELECTIONS_DICT);
    
    let record: ((String, String, u64), (String, String, u64)) = 
        storage::dictionary_get(elections_uref, &dispute_id).unwrap_or_revert()
            .unwrap_or_else(|| runtime::revert(ApiError::User(ERR_ELECTION_NOT_FOUND)));
    
    runtime::ret(CLValue::from_t(record).unwrap_or_revert());
}

#[no_mangle]
pub extern "C" fn call() {
    let mut entry_points = EntryPoints::new();
    
    entry_points.add_entrypoint(
        EntityEntryPoint::new(
            "register_arbiter",
            vec![
                Parameter::new("arbiter_id", CLType::String),
                Parameter::new("stake", CLType::U512),
            ],
            CLType::Unit,
            EntryPointAccess::Public,
            EntryPointType::Called,
            EntryPointPayment::Caller,
        )
    );
    
    entry_points.add_entrypoint(
        EntityEntryPoint::new(
            "elect_arbiter",
            vec![
                Parameter::new("dispute_id", CLType::String),
                Parameter::new("count", CLType::U64),
            ],
            CLType::Unit,
            EntryPointAccess::Public,
            EntryPointType::Called,
            EntryPointPayment::Caller,
        )
    );
    
    entry_points.add_entrypoint(
        EntityEntryPoint::new(
            "submit_verdict",
            vec![
                Parameter::new("dispute_id", CLType::String),
                Parameter::new("verdict", CLType::U64),
                Parameter::new("evidence", CLType::String),
            ],
            CLType::Unit,
            EntryPointAccess::Public,
            EntryPointType::Called,
            EntryPointPayment::Caller,
        )
    );
    
    entry_points.add_entrypoint(
        EntityEntryPoint::new(
            "slash_arbiter",
            vec![
                Parameter::new("arbiter_id", CLType::String),
                Parameter::new("amount", CLType::U512),
            ],
            CLType::Unit,
            EntryPointAccess::Public,
            EntryPointType::Called,
            EntryPointPayment::Caller,
        )
    );
    
    entry_points.add_entrypoint(
        EntityEntryPoint::new(
            "get_arbiter",
            vec![Parameter::new("arbiter_id", CLType::String)],
            CLType::Any,
            EntryPointAccess::Public,
            EntryPointType::Called,
            EntryPointPayment::Caller,
        )
    );
    
    entry_points.add_entrypoint(
        EntityEntryPoint::new(
            "get_election",
            vec![Parameter::new("dispute_id", CLType::String)],
            CLType::Any,
            EntryPointAccess::Public,
            EntryPointType::Called,
            EntryPointPayment::Caller,
        )
    );
    
    let mut named_keys = NamedKeys::new();
    
    let arbiters_uref = storage::new_dictionary(ARBITERS_DICT).unwrap_or_revert();
    let elections_uref = storage::new_dictionary(ELECTIONS_DICT).unwrap_or_revert();
    let ids_uref = storage::new_dictionary(ARBITER_IDS_DICT).unwrap_or_revert();
    let nonce_uref = storage::new_uref(0u64);
    
    named_keys.insert(String::from(ARBITERS_DICT), arbiters_uref.into());
    named_keys.insert(String::from(ELECTIONS_DICT), elections_uref.into());
    named_keys.insert(String::from(ARBITER_IDS_DICT), ids_uref.into());
    named_keys.insert(String::from(NONCE_KEY), nonce_uref.into());
    named_keys.insert(String::from(INSTALLER_KEY), runtime::get_caller().into());
    
    storage::new_contract(entry_points, Some(named_keys), None, None);
}